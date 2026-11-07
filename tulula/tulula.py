#!/usr/bin/env python3
"""Ask Tulu 3 on the Ai2 Playground a question, with optional tools.

Usage: tulula.py <prompt.md> <tools.json> <transcript.md> [--model ID] [--max-rounds N] [--dry-run]

tools.json is a list of {"name", "description", "parameters", "result"}. The first three
fields go to the model as a tool definition. "result" is the text sent back whenever the
model calls that tool. An empty list sends no tools. Token: AI2_TOKEN or ~/.ai2_token.
"""
from __future__ import annotations

import importlib.machinery
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_OLMO = Path(__file__).with_name("olmo.py")
if not _OLMO.is_file():
    _OLMO = Path.home() / ".local/bin/olmo"
olmo = importlib.machinery.SourceFileLoader("olmo", str(_OLMO)).load_module()

DEFAULT_MODEL = "cs-Llama-3.1-Tulu-3-70B"
OPTS = {"temperature": "0.7", "topP": "1", "maxTokens": "2048"}


def load_tools(path: Path) -> list[dict]:
    tools = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tools, list):
        raise olmo.ApiError(f"{path}: expected a JSON list of tools, got {type(tools).__name__}")
    for i, t in enumerate(tools):
        missing = {"name", "description", "parameters", "result"} - t.keys()
        if missing:
            raise olmo.ApiError(f"{path}: tool #{i} ({t.get('name', '?')}) is missing {sorted(missing)}")
    return tools


def tool_fields(tools: list[dict]) -> list[tuple[str, str]]:
    if not tools:
        return []
    defs = [{k: t[k] for k in ("name", "description", "parameters")} for t in tools]
    fields = [("enableToolCalling", "true"), ("toolDefinitions", json.dumps(defs))]
    return fields + [("selectedTools", t["name"]) for t in tools]


def parse_stream(chunks) -> dict:
    """Collect assistant text, tool calls and the assistant message id from one stream."""
    text, calls, msg_id = [], {}, None
    for c in chunks:
        kind = c.get("type")
        if kind == "AssistantPart" and c.get("chunkType") in ("start", "delta"):
            text.append(c["content"])
        elif kind in ("toolCall", "ToolCallPart"):
            calls[c["toolCallId"]] = {"id": c["toolCallId"], "name": c["toolName"], "args": c.get("args")}
        elif kind == "addMessage":
            msg_id = c["id"]
        elif kind == "error":
            olmo._raise_or_warn(c)
    if msg_id is None:
        raise olmo.ApiError("stream ended without an assistant message (no addMessage chunk)")
    return {"text": "".join(text), "calls": list(calls.values()), "id": msg_id}


def post(token: str, fields: list[tuple[str, str]]) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    headers = olmo._headers(token) | {"content-type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(olmo.API_BASE + "/threads/chat", data=data, headers=headers, method="POST")
    with olmo._request(req) as resp:
        lines = (json.loads(r) for r in (x.strip() for x in resp) if r)
        return parse_stream(lines)


def load_token() -> str:
    try:
        return olmo.load_token()
    except olmo.ApiError:
        path = Path.home() / ".ai2_token"
        if not path.is_file():
            raise
        token = path.read_text().split()[0] if path.read_text().split() else ""
        if not token:
            raise olmo.ApiError(f"{path} is empty; paste a fresh token into it")
        return token


def check_model(token: str, model: str, tools: list[dict]) -> None:
    found = [m for m in olmo.list_models(token) if m.get("id") == model]
    if not found:
        raise olmo.ApiError(f"model {model} is not offered by the Playground right now")
    if tools and not found[0].get("canCallTools"):
        raise olmo.ApiError(f"model {model} has canCallTools=false; it cannot use the tools in the tools file")


def converse(token, model, prompt, tools, max_rounds, log):
    base = [("model", model), *OPTS.items(), *tool_fields(tools)]
    reply = post(token, [("role", "user"), ("content", prompt), *base])
    log.append(("Tulu", reply))
    results = {t["name"]: t["result"] for t in tools}
    for _ in range(max_rounds):
        if not reply["calls"]:
            return
        call = reply["calls"][0]
        answer = results.get(call["name"], f"ERROR: no tool named {call['name']}")
        log.append(("tool", {"call": call, "result": answer}))
        reply = post(token, [("role", "tool_call_result"), ("parent", reply["id"]),
                             ("toolCallId", call["id"]), ("content", answer), *base])
        log.append(("Tulu", reply))
    raise olmo.ApiError(f"stopped after {max_rounds} tool rounds; Tulu was still calling tools")


def render(model, prompt, tools, log) -> str:
    out = [f"# Tulula transcript\n\nModel: `{model}`. Tools offered: {', '.join(t['name'] for t in tools) or 'none'}.\n",
           "## Prompt sent\n", prompt, ""]
    for who, item in log:
        if who == "Tulu":
            out += [f"## Tulu (message `{item['id']}`)\n", item["text"] or "_(no text)_", ""]
            out += [f"- called `{c['name']}` with `{json.dumps(c['args'])}`" for c in item["calls"]]
        else:
            out += [f"## Tool result for `{item['call']['name']}`\n", item["result"], ""]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a: argv[i + 1] for i, a in enumerate(argv) if a in ("--model", "--max-rounds")}
    if len(args) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    prompt_path, tools_path, out_path = map(Path, (args[0], args[1], args[2]))
    if out_path.exists():
        raise olmo.ApiError(f"{out_path} already exists; pick a new transcript name")
    model = flags.get("--model", DEFAULT_MODEL)
    prompt, tools = prompt_path.read_text(encoding="utf-8"), load_tools(tools_path)
    if "--dry-run" in argv:
        print(json.dumps([("role", "user"), ("content", f"<{len(prompt)} chars>"), ("model", model),
                          *OPTS.items(), *tool_fields(tools)], indent=1))
        return 0
    token = load_token()
    check_model(token, model, tools)
    log: list = []
    try:
        converse(token, model, prompt, tools, int(flags.get("--max-rounds", 5)), log)
    finally:
        if log:
            out_path.write_text(render(model, prompt, tools, log), encoding="utf-8")
            print(f"transcript: {out_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except olmo.ApiError as err:
        print(f"tulula: {err}", file=sys.stderr)
        sys.exit(1)
