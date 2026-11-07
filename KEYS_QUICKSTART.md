# API keys quickstart for DR Tulu

Run this on whatever machine will run DR Tulu, including a fresh Brev instance:

```bash
git clone https://github.com/cstewart80/dr-tulula.git && cd dr-tulula
./setup_keys.sh            # writes agent/.env, chmod 600
```

The script opens nothing for you. It prints each signup link, takes each key with hidden input, tests it with one real API call, and only saves keys the API accepts. Press Enter to skip a key or keep the one already saved. `CHECK=0 ./setup_keys.sh` saves without testing.

## The keys

| Key | Needed? | Where to get it | Free tier |
|---|---|---|---|
| `SERPER_API_KEY` | **Yes** | https://serper.dev/ (sign up, copy the key from the dashboard) | 2,500 queries on signup ([serper.dev](https://serper.dev/)) |
| `S2_API_KEY` | No | https://www.semanticscholar.org/product/api#api-key-form (a request form, not instant) | Without a key you share a public pool of 1,000 requests per second with every anonymous user; a key starts at 1 request per second ([Semantic Scholar](https://www.semanticscholar.org/product/api)) |
| `JINA_API_KEY` | Only if browsing with Jina | https://jina.ai/reader/ | 10M free tokens per new key ([jina.ai/reader](https://jina.ai/reader/)) |
| `OPENAI_API_KEY` | Only for the no-GPU debug mode | https://platform.openai.com/api-keys | Paid |

## Skipping Jina

The shipped config browses with Jina (`agent/workflows/auto_search_sft.yaml`, `browse_tool_name: "jina"`). To browse without it, override:

```bash
--config-overrides "browse_tool_name=crawl4ai"   # local, no key
--config-overrides "browse_tool_name=serper"     # reuses your Serper key
```

## Cost of the tests

Testing spends 1 Serper search credit and a few Jina tokens. The Semantic Scholar and OpenAI tests are free.

## Safety

`agent/.env` is gitignored (`.gitignore` line 153). Never commit it, and don't paste keys into chat logs. An existing `.env` is copied to `.env.bak` before any change.
