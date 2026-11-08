"""MCP server that exposes a running DR Tulu web API as a `deep_research` tool.

Run it on the GPU box next to the DR Tulu web server (default http://localhost:8080):

    .venv/bin/python tulula/dr_tulu_mcp.py            # stdio (for `ssh host python ...`)
    .venv/bin/python tulula/dr_tulu_mcp.py --http      # streamable HTTP on 127.0.0.1:8765

Claude Code, from any machine with SSH access to the box (no tunnel needed):

    claude mcp add dr-tulu -- ssh gwingz ~/dr-tulula/agent/.venv/bin/python ~/dr-tulula/tulula/dr_tulu_mcp.py
"""

import argparse
import json
import os
import urllib.error
import urllib.request

from fastmcp import FastMCP

DR_TULU_URL = os.environ.get("DR_TULU_URL", "http://localhost:8080").rstrip("/")
REQUEST_TIMEOUT = int(os.environ.get("DR_TULU_TIMEOUT", "1200"))

mcp = FastMCP(
    "dr-tulu",
    instructions=(
        "deep_research runs the DR Tulu deep-research agent: it searches the web and "
        "Semantic Scholar, reads sources, and returns a cited answer. Calls take one to "
        "several minutes; ask one complete, specific question per call."
    ),
)


@mcp.tool
def deep_research(question: str, dataset_name: str = "long_form") -> str:
    """Research a question with DR Tulu and return a cited, sourced answer.

    Args:
        question: The full research question, with any constraints (time range, region, sources to prefer).
        dataset_name: DR Tulu answer style. "long_form" (default) for a report with citations,
            "short_form" for a brief direct answer.
    """
    body = json.dumps({"content": question, "dataset_name": dataset_name}).encode()
    req = urllib.request.Request(
        f"{DR_TULU_URL}/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return f"DR Tulu returned HTTP {e.code}: {e.read().decode(errors='replace')[:2000]}"
    except urllib.error.URLError as e:
        return (
            f"Could not reach DR Tulu at {DR_TULU_URL}: {e.reason}. "
            "Check that the web server (port 8080), MCP backend (8000) and vLLM (30001) are running."
        )
    return data.get("response") or json.dumps(data)


@mcp.tool
def dr_tulu_status() -> str:
    """Check whether the DR Tulu web server is reachable."""
    try:
        with urllib.request.urlopen(f"{DR_TULU_URL}/openapi.json", timeout=10) as resp:
            info = json.loads(resp.read().decode()).get("info", {})
        return f"DR Tulu is up at {DR_TULU_URL}: {info.get('title')} {info.get('version')}"
    except Exception as e:  # noqa: BLE001
        return f"DR Tulu is not reachable at {DR_TULU_URL}: {e}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()
