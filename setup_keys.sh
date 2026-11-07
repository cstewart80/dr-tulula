#!/usr/bin/env bash
# Collect DR Tulu API keys, test each one against its real API, and write them to a .env file.
# Usage: ./setup_keys.sh [path/to/.env]      (default: agent/.env next to this script)
#        CHECK=0 ./setup_keys.sh             (save keys without testing them)
# Keys are read hidden, never printed (only the last 4 characters), and the file is chmod 600.
set -euo pipefail

ENV_FILE="${1:-$(cd "$(dirname "$0")" && pwd)/agent/.env}"
CHECK="${CHECK:-1}"

# name | required? | signup page | what it is for
KEYS=(
  "SERPER_API_KEY|required|https://serper.dev/|Google search (2,500 free queries on signup)"
  "S2_API_KEY|optional|https://www.semanticscholar.org/product/api#api-key-form|Semantic Scholar paper search (works without a key, on a shared rate limit)"
  "JINA_API_KEY|optional|https://jina.ai/reader/|Jina page reader for browse_tool_name=jina (skip it if you browse with crawl4ai or serper)"
  "OPENAI_API_KEY|optional|https://platform.openai.com/api-keys|Only for the no-GPU debug mode that runs on OpenAI models"
)

die() { echo "setup_keys: $*" >&2; exit 1; }
command -v curl >/dev/null || die "curl is not installed; install it (apt-get install -y curl) and rerun"

current() { [[ -f "$ENV_FILE" ]] && grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

# Prints the HTTP status of one cheap authenticated request. Serper spends 1 search credit; Jina spends a few tokens.
probe() {
  local name=$1 key=$2
  case $name in
    SERPER_API_KEY) curl -sS -m 20 -o /dev/null -w '%{http_code}' -X POST https://google.serper.dev/search \
                      -H "X-API-KEY: $key" -H 'Content-Type: application/json' -d '{"q":"test","num":1}' ;;
    S2_API_KEY)     curl -sS -m 20 -o /dev/null -w '%{http_code}' -H "x-api-key: $key" \
                      'https://api.semanticscholar.org/graph/v1/paper/search?query=phonon&limit=1&fields=title' ;;
    JINA_API_KEY)   curl -sS -m 40 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $key" https://r.jina.ai/https://example.com ;;
    OPENAI_API_KEY) curl -sS -m 20 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $key" https://api.openai.com/v1/models ;;
  esac
}

save() {  # Replace or append NAME=value without touching any other line.
  local name=$1 value=$2 tmp
  tmp=$(mktemp "${ENV_FILE}.XXXX") || die "cannot create a temp file next to $ENV_FILE"
  { [[ -f "$ENV_FILE" ]] && grep -v -E "^$name=" "$ENV_FILE" || true; printf '%s=%s\n' "$name" "$value"; } >"$tmp"
  chmod 600 "$tmp" && mv "$tmp" "$ENV_FILE"
}

mkdir -p "$(dirname "$ENV_FILE")" || die "cannot create directory for $ENV_FILE"
[[ -f "$ENV_FILE" ]] && cp -p "$ENV_FILE" "$ENV_FILE.bak" && echo "Backed up existing file to $ENV_FILE.bak"
echo "Writing keys to $ENV_FILE"

declare -A RESULT
for entry in "${KEYS[@]}"; do
  IFS='|' read -r name need url what <<<"$entry"
  echo; echo "== $name ($need): $what"; echo "   Get one at: $url"
  have=$(current "$name")
  [[ -z "$have" && -n "${!name:-}" ]] && have=${!name}
  [[ -n "$have" ]] && echo "   Already have one ending in ...${have: -4}. Press Enter to keep it."
  read -r -s -p "   Paste key (input hidden, Enter to skip): " key; echo
  key=${key//[$'\r\n\t ']/}
  if [[ -z "$key" ]]; then
    [[ -n "$have" ]] && key=$have
  fi
  if [[ -z "$key" ]]; then
    RESULT[$name]="skipped"; [[ $need == required ]] && echo "   WARNING: $name is required; DR Tulu search will not work without it."
    continue
  fi
  if [[ "$CHECK" == 1 ]]; then
    status=$(probe "$name" "$key" 2>/dev/null) || status="network error"
    case $status in
      200) RESULT[$name]="saved, tested OK (...${key: -4})" ;;
      401|403) RESULT[$name]="REJECTED by the API (HTTP $status), not saved"; echo "   $name was rejected (HTTP $status). Check you copied the whole key."; continue ;;
      429) RESULT[$name]="saved, but rate-limited during the test (HTTP 429)" ;;
      *) RESULT[$name]="saved, test inconclusive ($status)" ;;
    esac
  else
    RESULT[$name]="saved, not tested (...${key: -4})"
  fi
  save "$name" "$key"
done

echo; echo "Summary for $ENV_FILE:"
for entry in "${KEYS[@]}"; do name=${entry%%|*}; printf '  %-15s %s\n' "$name" "${RESULT[$name]}"; done
