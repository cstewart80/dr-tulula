#!/usr/bin/env python3
"""Terminal chat client for the Ai2 Playground API (playground.allenai.org).

Standard library only. Auth token comes from the AI2_TOKEN environment
variable (the `authorization: Bearer ...` value from the browser's DevTools).

Usage:
    olmo                          # interactive chat, default model
    olmo -m Olmo-3.1-32B-Think    # pick a model
    olmo --models                 # list available models
    echo "question" | olmo        # one-shot from stdin

In-chat commands:  /model <id>   /models   /new   /quit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterator

API_BASE = "https://prod-api.playground.apps.allenai.org/v5"
ORIGIN = "https://playground.allenai.org"
DEFAULT_MODEL = "Olmo-3.1-32B-Instruct"
TOKEN_ENV = "AI2_TOKEN"

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class ApiError(Exception):
    """Raised with a message that says what failed, where, and why."""


@dataclass
class Session:
    token: str
    model: str
    parent: str | None = None
    thread: str | None = None
    opts: dict[str, str] = field(default_factory=dict)

    def reset(self) -> None:
        self.parent = None
        self.thread = None


# ---------------------------------------------------------------- HTTP ----


def _headers(token: str) -> dict[str, str]:
    return {
        "authorization": f"Bearer {token}",
        "origin": ORIGIN,
        "referer": ORIGIN + "/",
        "accept": "*/*",
    }


def _request(req: urllib.request.Request):
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        raise ApiError(_describe_http_error(req.full_url, err.code, body)) from err
    except urllib.error.URLError as err:
        raise ApiError(f"could not reach {req.full_url}: {err.reason}") from err


def _describe_http_error(url: str, status: int, body: str) -> str:
    if status == 401:
        return (
            f"HTTP 401 from {url}: token rejected. It has probably expired "
            f"(they last 24h). Copy a fresh one from DevTools into ${TOKEN_ENV}."
        )
    try:
        problem = json.loads(body)
    except json.JSONDecodeError:
        return f"HTTP {status} from {url}: {body[:300]}"
    title = problem.get("title") or problem.get("type") or "error"
    detail = problem.get("detail") or ""
    errors = problem.get("errors")
    if errors:
        detail = "; ".join(e.get("msg", "") for e in errors)
    return f"HTTP {status} from {url}: {title}. {detail}".strip()


def get_json(token: str, path: str):
    req = urllib.request.Request(API_BASE + path, headers=_headers(token))
    with _request(req) as resp:
        return json.load(resp)


def post_form_stream(token: str, path: str, fields: dict[str, str]) -> Iterator[dict]:
    data = urllib.parse.urlencode(fields).encode()
    headers = _headers(token) | {"content-type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(API_BASE + path, data=data, headers=headers, method="POST")
    with _request(req) as resp:
        for raw in resp:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                raise ApiError(f"non-JSON line in stream from {path}: {line[:200]!r}")


# ---------------------------------------------------------------- chat ----


def list_models(token: str) -> list[dict]:
    models = get_json(token, "/models/")
    if not isinstance(models, list):
        raise ApiError(f"/models/ returned {type(models).__name__}, expected a list")
    return models


def print_models(token: str) -> None:
    for m in list_models(token):
        flag = "  (deprecated)" if m.get("isDeprecated") else ""
        print(f"  {m['id']:<32} {m.get('name', '')}{flag}")


def send(session: Session, text: str) -> str:
    """Stream one turn to the terminal; return the assistant message id."""
    fields = {"role": "user", "model": session.model, "content": text, **session.opts}
    if session.parent:
        fields["parent"] = session.parent

    assistant_id: str | None = None
    printer = StreamPrinter()
    for chunk in post_form_stream(session.token, "/threads/chat", fields):
        kind = chunk.get("type")
        # The *Part events (chunkType start/delta/final) carry the complete text.
        # The legacy "thinking"/"modelResponse" chunks duplicate the deltas but
        # omit the first token, so they are ignored.
        if kind in ("ThinkingPart", "AssistantPart"):
            printer.part(kind, chunk.get("chunkType"), chunk["content"])
        elif kind == "addMessage":
            assistant_id = chunk["id"]
        elif kind == "startThread":
            session.thread = chunk["id"]
        elif kind == "error":
            printer.finish()
            _raise_or_warn(chunk)

    printer.finish()
    if assistant_id is None:
        raise ApiError("stream ended without an assistant message (no addMessage chunk)")
    return assistant_id


def _raise_or_warn(chunk: dict) -> None:
    text = f"{chunk.get('errorCode')}: {chunk.get('errorDescription')}"
    if chunk.get("errorSeverity", "error") == "error":
        raise ApiError(f"model error {text}")
    print(f"{DIM}warning {text}{RESET}", file=sys.stderr)


class StreamPrinter:
    """Writes thinking in dim text and the answer in normal text as they arrive."""

    def __init__(self) -> None:
        self.mode: str | None = None

    def part(self, kind: str, chunk_type: str | None, content: str) -> None:
        if chunk_type not in ("start", "delta"):
            return
        if kind != self.mode:
            self._switch(kind)
        sys.stdout.write(content)
        sys.stdout.flush()

    def _switch(self, kind: str) -> None:
        if self.mode == "ThinkingPart":
            sys.stdout.write(RESET + "\n\n")
        if kind == "ThinkingPart":
            sys.stdout.write(DIM)
        self.mode = kind

    def finish(self) -> None:
        if self.mode == "ThinkingPart":
            sys.stdout.write(RESET)
        if self.mode is not None:
            sys.stdout.write("\n")
        self.mode = None
        sys.stdout.flush()


# ------------------------------------------------------------- commands ----


def handle_command(session: Session, line: str) -> bool:
    """Return True if the line was a command (and has been handled)."""
    cmd, _, arg = line.partition(" ")
    if cmd in ("/quit", "/exit", "/q"):
        raise EOFError
    if cmd == "/new":
        session.reset()
        print(f"{DIM}new thread{RESET}")
    elif cmd == "/models":
        print_models(session.token)
    elif cmd == "/model":
        if not arg:
            print(f"model: {session.model}")
        else:
            session.model = arg.strip()
            session.reset()
            print(f"{DIM}model -> {session.model} (new thread){RESET}")
    elif cmd.startswith("/"):
        print(f"unknown command {cmd}. Commands: /model <id>  /models  /new  /quit")
    else:
        return False
    return True


def repl(session: Session) -> None:
    print(f"{DIM}{session.model}  |  /model /models /new /quit{RESET}")
    while True:
        try:
            line = input(f"{BOLD}you>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        try:
            if handle_command(session, line):
                continue
            session.parent = send(session, line)
        except EOFError:
            return
        except ApiError as err:
            print(f"\n{BOLD}error:{RESET} {err}", file=sys.stderr)
        except KeyboardInterrupt:
            print(f"\n{DIM}interrupted{RESET}")


# ----------------------------------------------------------------- main ----


def load_token() -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise ApiError(
            f"${TOKEN_ENV} is not set. In the playground tab: DevTools > Network > any "
            f"prod-api request > copy the authorization header value, then\n"
            f"    export {TOKEN_ENV}='eyJ...'"
        )
    return token


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-m", "--model", default=DEFAULT_MODEL)
    p.add_argument("--models", action="store_true", help="list models and exit")
    p.add_argument("--temperature", type=float)
    p.add_argument("--max-tokens", type=int)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        token = load_token()
        if args.models:
            print_models(token)
            return 0
        opts: dict[str, str] = {}
        if args.temperature is not None:
            opts["temperature"] = str(args.temperature)
        if args.max_tokens is not None:
            opts["maxTokens"] = str(args.max_tokens)
        session = Session(token=token, model=args.model, opts=opts)
        if sys.stdin.isatty():
            repl(session)
        else:
            send(session, sys.stdin.read().strip())
        return 0
    except ApiError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
