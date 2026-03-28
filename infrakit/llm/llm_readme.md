# infrakit.llm

Unified LLM client for OpenAI and Gemini with key rotation, quota tracking,
rate limiting, and batch processing. Designed for free-tier API keys where
RPM/daily limits matter.

---

## Installation

```bash
# core
pip install pydantic tqdm

# for OpenAI
pip install openai

# for Gemini
pip install google-generativeai
```

---

## File structure

```
infrakit/llm/
├── __init__.py          Public API surface
├── client.py            LLMClient — main entry point
├── key_manager.py       Key rotation, quota, persistence
├── rate_limiter.py      RPM / TPM async and sync gates
├── batch.py             Async + threaded batch engine
├── models.py            Shared types (Prompt, LLMResponse, etc.)
└── providers/
    ├── __init__.py
    ├── base.py          AbstractProvider + schema validation
    ├── openai.py        OpenAI provider
    └── gemini.py        Gemini provider

infrakit/cli/
└── llm_cmd.py           CLI commands (ik llm status, ik llm quota set)
```

---

## Quick start

```python
from infrakit.llm import LLMClient, Prompt

client = LLMClient(
    keys={
        "openai_keys": ["sk-key1", "sk-key2"],
        "gemini_keys": ["AIza-key1"],
    },
    storage_dir="./logs",   # key state persisted here
)

# simple prompt
response = client.generate(Prompt(user="What is 2 + 2?"), provider="openai")
print(response.content)

# system + user split
response = client.generate(
    Prompt(system="You are a maths tutor.", user="Explain derivatives."),
    provider="gemini",
)
print(response.content)
```

---

## Structured output (Pydantic)

Pass a Pydantic model as `response_model`. The system will try to parse the
model's JSON response and validate it against your schema. If validation fails
after retries, you still get the raw `content` back with `schema_matched=False`.

```python
from pydantic import BaseModel

class Sentiment(BaseModel):
    label: str        # "positive" | "negative" | "neutral"
    confidence: float

# Your prompt must instruct the model to return JSON — infrakit does not
# inject instructions automatically.
response = client.generate(
    Prompt(
        system='Respond ONLY with valid JSON matching: {"label": str, "confidence": float}',
        user="I love this product!",
    ),
    provider="openai",
    response_model=Sentiment,
)

if response.schema_matched:
    print(response.parsed.label)       # "positive"
    print(response.parsed.confidence)  # 0.97
else:
    print("Schema mismatch — raw response:", response.content)
```

---

## Batch processing

```python
from infrakit.llm import Prompt

words = ["cat", "dog", "bird", "fish"]
prompts = [
    Prompt(
        system="Translate to French. Reply with only the translation.",
        user=word,
    )
    for word in words
]

batch = client.batch_generate(prompts, provider="gemini")

# results are in the same order as prompts
for word, result in zip(words, batch.results):
    if result.error:
        print(f"{word}: ERROR — {result.error}")
    else:
        print(f"{word}: {result.content}")

print(f"\nTotal tokens: {batch.total_tokens}")
print(f"Success: {batch.success_count} / Failure: {batch.failure_count}")
```

---

## LLMClient parameters

| Parameter | Default | Description |
|---|---|---|
| `keys` | required | `{"openai_keys": [...], "gemini_keys": [...]}` |
| `storage_dir` | required | Folder for persistent key state |
| `mode` | `"async"` | `"async"` or `"threaded"` |
| `max_concurrent` | `3` | Max simultaneous batch requests |
| `key_retries` | `2` | Retries on same key before rotating |
| `schema_retries` | `2` | JSON parse/validate retries |
| `meta_window` | `50` | Recent request metadata records per key |
| `openai_model` | `"gpt-4o-mini"` | Default OpenAI model |
| `gemini_model` | `"gemini-1.5-flash"` | Default Gemini model |
| `show_progress` | `True` | tqdm progress bar for batch calls |

---

## Quota management

### Set quota for a key

```python
from infrakit.llm import QuotaConfig

client.set_quota(
    provider="openai",
    key_id="sk-abc123",          # first 8 chars of the key
    quota=QuotaConfig(
        rpm_limit=60,            # 60 requests per minute
        tpm_limit=90_000,        # 90k tokens per minute
        daily_token_limit=1_000_000,
        reset_hour_utc=0,        # resets at midnight UTC
    ),
)
```

Only the fields you set are enforced. Unset fields are unconstrained.

### Key lifecycle

- **active** — key is in normal use.
- **inactive** — key hit a quota limit (daily tokens, or a hard 401/429 from the API).
  Automatically reactivates at `reset_hour_utc` the following day.
- Keys are rotated round-robin among all active keys. When a key is deactivated,
  remaining active keys absorb the load.

---

## Check status (Python)

```python
# all keys
client.print_status()

# one provider
client.print_status(provider="openai")

# one key
client.print_status(provider="openai", key_id="sk-abc123")

# raw dict (for programmatic use)
rows = client.status(provider="openai")
```

---

## CLI

Register `llm_cmd` in your main CLI (add to `infrakit/cli/__init__.py`):

```python
from infrakit.cli.llm_cmd import register as register_llm
register_llm(cli)
```

### Commands

```bash
# show all keys
ik llm status --storage-dir ./logs

# filter by provider
ik llm status --provider openai --storage-dir ./logs

# filter by key (first 8 chars)
ik llm status --key sk-abc123 --storage-dir ./logs

# JSON output
ik llm status --json --storage-dir ./logs

# set quota for a key
ik llm quota set \
  --provider openai \
  --key sk-abc123 \
  --rpm 60 \
  --tpm 90000 \
  --daily 1000000 \
  --reset-hour 0 \
  --storage-dir ./logs
```

If your keys are stored in a JSON file:
```bash
ik llm status --keys-file keys.json --storage-dir ./logs
```

`keys.json` format:
```json
{
  "openai_keys": ["sk-key1", "sk-key2"],
  "gemini_keys": ["AIza-key1"]
}
```

---

## Error handling

Every `generate()` call returns an `LLMResponse` — it never raises. Check `.error`:

```python
result = client.generate(Prompt(user="Hello"), provider="openai")
if result.error:
    print(f"Request failed: {result.error}")
else:
    print(result.content)
```

### What infrakit handles automatically

| Situation | Behaviour |
|---|---|
| Transient error (network, 5xx) | Retry same key up to `key_retries` times with backoff |
| Quota / auth error (401, 402, 429+quota) | Deactivate key immediately, rotate to next |
| All keys exhausted | Return `LLMResponse(error="All keys exhausted.")` |
| RPM limit reached | Async/sync sleep until slot opens |
| Daily token limit reached | Deactivate key, auto-reactivate at reset hour |
| Schema validation fails | Return raw content + `schema_matched=False` |

---

## LLMResponse fields

| Field | Type | Description |
|---|---|---|
| `content` | `str` | Raw text from the model |
| `parsed` | `BaseModel \| None` | Validated Pydantic instance (if `response_model` given and matched) |
| `schema_matched` | `bool` | True if structured output validated successfully |
| `provider` | `str` | `"openai"` or `"gemini"` |
| `model` | `str` | Model string used |
| `key_id` | `str` | First 8 chars of the key used |
| `input_tokens` | `int` | Prompt token count |
| `output_tokens` | `int` | Completion token count |
| `total_tokens` | `int` | input + output |
| `latency_ms` | `float` | Wall-clock API call time |
| `error` | `str \| None` | Set on failure |

---

## What is and isn't stored

infrakit stores **no prompt or response content**. Per key, it persists:

- Status (active/inactive), deactivation timestamp
- Quota config (RPM, TPM, daily limit, reset hour)
- Lifetime totals (requests, tokens in/out, errors)
- Daily token total + day start epoch
- RPM window (timestamps of last 60 s of requests)
- TPM window (timestamps + token counts for last 60 s)
- Rolling metadata for last N requests: timestamp, model, token counts, latency, success/error code

All stored in `{storage_dir}/llm_key_state.json`.