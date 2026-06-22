# AI Comment Moderator with Appeal System

A backend API that automatically moderates user-submitted forum comments with an
LLM, and lets a rejected user **appeal** with extra context for a genuine
re-evaluation before a final decision. Every decision is written to a moderation
log.

The forum being moderated is modelled on [Property Tribes](https://www.propertytribes.com)
— a UK community for landlords, buy-to-let investors, letting agents and tenants —
so the moderator understands that domain (Section 21/8, HMOs, EPCs, deposits,
discrimination law, property "get-rich-quick" spam, and so on).

- **Stack:** Python · FastAPI · Pydantic v2
- **LLM:** Anthropic Claude **Sonnet 4.6** via the official SDK, using **forced
  tool use** for guaranteed structured output
- **Storage:** in-memory + JSON file (no database required)
- **Tests:** `pytest` (45 tests, fully offline — the LLM is mocked)
- **CI:** GitHub Actions (lint + tests on Python 3.11/3.12/3.13)

---

> ### 👋 Reviewing this? Two ways to test it
>
> Live moderation is powered by a real LLM, so there are two ways to evaluate it:
>
> **A. See the real AI in action — add your own Anthropic key (~2 min, a few cents).**
> Create a key at [console.anthropic.com](https://console.anthropic.com/), put it
> in `.env`, and run the server. Full instructions in
> [Quick start](#quick-start-under-5-minutes) + [Try it with curl](#try-it-with-curl).
> A key isn't shipped in this repo for obvious security reasons.
>
> **B. Verify all the logic with zero setup and no key — run the tests.**
> ```bash
> pip install -r requirements-dev.txt && pytest
> ```
> The 45 tests mock the LLM and exercise *everything*: all three decision types,
> the complete appeal flow (overturn, uphold, not-found, double-appeal), every
> input edge case, rate limiting, file persistence, and the graceful-fallback
> behaviour when the AI errors or misbehaves. (CI runs these on every push.)
>
> Either way you can read [How moderation works](#how-moderation-works) and the
> [Write-up](#write-up) for the design reasoning, and the prompt itself lives in
> [`app/services/prompts.py`](app/services/prompts.py).

---

## Contents
- [Reviewing this? Two ways to test it](#-reviewing-this-two-ways-to-test-it)
- [Features](#features)
- [Quick start (under 5 minutes)](#quick-start-under-5-minutes)
  - [macOS / Linux](#macos--linux)
  - [Windows](#windows)
- [API reference](#api-reference)
- [Try it with curl](#try-it-with-curl)
- [Edge-case behaviour](#edge-case-behaviour)
- [Running the tests](#running-the-tests)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [How moderation works](#how-moderation-works)
- [Write-up](#write-up)
  - [Key decisions and why](#key-decisions-and-why)
  - [What I would improve with more time](#what-i-would-improve-with-more-time)
  - [Assumptions](#assumptions)

---

## Features

**Core**
- `POST /moderate` — moderate a comment → `approved` / `rejected` /
  `flagged_for_review`, with a confidence score and plain-English reasoning.
- `POST /appeal` — re-evaluate a rejected comment **together with** the user's
  appeal context → a final `approved` / `rejected` (one appeal only).
- `GET /log` — the full moderation log (comment, decision, confidence, reasoning,
  timestamp, and whether an appeal was made).

**Bonus (all implemented)**
- ✅ **Rate limiting per user** — fixed-window limiter keyed on `user_id`.
- ✅ **Rejection categorisation** — `spam`, `hate_speech`, `harassment`,
  `misinformation`, `illegal_activity`, `adult_content`, `personal_information`,
  `off_topic`, `other`.
- ✅ **Webhook / notification on flagged content** — POSTs the entry to a
  configurable `WEBHOOK_URL` when a comment is flagged for review.
- ✅ **Unit tests** — 45 deterministic tests, no network or API key required.

Plus: input validation for every edge case, graceful handling of LLM/network
failures, interactive API docs (Swagger UI), and CI.

---

## Quick start (under 5 minutes)

**Prerequisites:** Python 3.11+ and an Anthropic API key
([get one here](https://console.anthropic.com/)).

### macOS / Linux

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd ai-comment-moderator

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
cp .env.example .env
# then open .env and set ANTHROPIC_API_KEY=sk-ant-...

# 5. Run the server
uvicorn app.main:app --reload
```

### Windows

**PowerShell:**

```powershell
# 1. Clone and enter the project
git clone <your-repo-url>
cd ai-comment-moderator

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
copy .env.example .env
# then open .env and set ANTHROPIC_API_KEY=sk-ant-...

# 5. Run the server
uvicorn app.main:app --reload
```

> If PowerShell blocks the activate script, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use
> `cmd.exe` and activate with `.\.venv\Scripts\activate.bat`.

The API is now at **http://127.0.0.1:8000**.

- Interactive docs (Swagger UI): **http://127.0.0.1:8000/docs**
- Health check: **http://127.0.0.1:8000/health**

---

## API reference

| Method | Endpoint    | Description                                  |
|--------|-------------|----------------------------------------------|
| POST   | `/moderate` | Submit a comment for moderation              |
| POST   | `/appeal`   | Submit an appeal for a rejected comment      |
| GET    | `/log`      | Retrieve the full moderation log             |
| GET    | `/health`   | Liveness + whether the LLM key is configured |

### `POST /moderate`

Request:
```json
{ "comment": "Has anyone served a Section 21 recently?", "user_id": "alice" }
```
`user_id` is optional (defaults to `"anonymous"`) and is used for rate limiting.

Response `200`:
```json
{
  "comment_id": "594029f3-37be-41ab-90c2-9171d9b37869",
  "decision": "approved",
  "confidence": 0.98,
  "reasoning": "A genuine, on-topic question about the eviction process ...",
  "category": "none",
  "timestamp": "2026-06-22T18:05:13.241419+00:00",
  "appealable": false
}
```

### `POST /appeal`

Only comments whose decision is `rejected` can be appealed, and only once.

Request:
```json
{ "comment_id": "b4b9c1a7-...", "appeal_context": "I was genuinely asking, not selling." }
```

Response `200`:
```json
{
  "comment_id": "b4b9c1a7-...",
  "final_decision": "rejected",
  "confidence": 0.99,
  "reasoning": "The appeal does not address why this was spam ... The rejection stands.",
  "category": "spam",
  "appeal_timestamp": "2026-06-22T18:05:42.728427+00:00"
}
```

### `GET /log`

Response `200`:
```json
{
  "count": 2,
  "entries": [
    {
      "id": "b4b9c1a7-...",
      "user_id": "bob",
      "comment": "Make 10k/month PASSIVE ...",
      "decision": "rejected",
      "confidence": 0.99,
      "reasoning": "...",
      "category": "spam",
      "timestamp": "2026-06-22T18:05:16+00:00",
      "appealed": true,
      "appeal_context": "...",
      "final_decision": "rejected",
      "final_reasoning": "...",
      "appeal_confidence": 0.99,
      "appeal_category": "spam",
      "appeal_timestamp": "2026-06-22T18:05:42+00:00"
    }
  ]
}
```

---

## Try it with curl

These are real responses from Claude Sonnet 4.6.

**1. A genuine question → approved**
```bash
curl -X POST http://127.0.0.1:8000/moderate \
  -H "Content-Type: application/json" \
  -d '{"comment":"Has anyone served a Section 21 recently? My tenant has stopped paying rent. S21 or S8?","user_id":"alice"}'
```

**2. Get-rich-quick spam → rejected (category: spam), appealable**
```bash
curl -X POST http://127.0.0.1:8000/moderate \
  -H "Content-Type: application/json" \
  -d '{"comment":"Make 10k/month PASSIVE with my property system! Only 5 spots left, DM me RICH now!!!","user_id":"bob"}'
```

**3. Appeal the rejected comment (use the `comment_id` from step 2)**
```bash
curl -X POST http://127.0.0.1:8000/appeal \
  -H "Content-Type: application/json" \
  -d '{"comment_id":"<comment_id>","appeal_context":"Everyone promotes their stuff here, it is harmless."}'
```
The AI genuinely engages with the appeal argument point-by-point and, because the
appeal does not address the actual spam problem, upholds the rejection.

**4. A borderline "No DSS" comment → flagged_for_review (and fires the webhook)**
```bash
curl -X POST http://127.0.0.1:8000/moderate \
  -H "Content-Type: application/json" \
  -d '{"comment":"Honestly DSS tenants are a nightmare and I would never touch them.","user_id":"carol"}'
```
> Real reasoning returned: *"Expressing a blanket 'no DSS' preference is
> controversial and arguably discriminatory under the Equality Act 2010 ... but
> stops short of explicit hate speech ... a human reviewer should assess the
> broader context."*

**5. View the log**
```bash
curl http://127.0.0.1:8000/log
```

---

## Edge-case behaviour

| Input / situation                          | Behaviour                                                            |
|--------------------------------------------|---------------------------------------------------------------------|
| Empty or whitespace-only comment           | `422` validation error (LLM is never called)                        |
| Missing `comment` field                    | `422` validation error                                              |
| Comment longer than `MAX_COMMENT_LENGTH`   | `422` validation error (default limit 10,000 chars)                 |
| Leading/trailing whitespace                | Trimmed before moderation                                          |
| Borderline / ambiguous content             | `flagged_for_review` with reasoning + webhook notification          |
| Appeal for a non-existent `comment_id`     | `404 comment_not_found`                                             |
| Appeal for a comment that wasn't rejected  | `409 not_appealable`                                               |
| Appeal for an already-appealed comment     | `409 already_appealed`                                             |
| Rate limit exceeded for a user             | `429 rate_limit_exceeded`                                          |
| LLM returns malformed / no structured data | Falls back to `flagged_for_review` (never a 500)                    |
| LLM/network error during moderation        | Falls back to `flagged_for_review`                                  |
| LLM/network error during an appeal         | Upholds the original rejection (never auto-approves on error)       |
| `ANTHROPIC_API_KEY` not configured         | `/moderate` & `/appeal` return `503` with a clear message          |

---

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest            # 45 tests, fully offline (LLM mocked) — no API key needed
ruff check .      # linting
```

The tests cover: each decision type, the appeal flow (overturn, uphold,
not-found, not-appealable, double-appeal), input validation, rate limiting,
file persistence round-trips, and the moderator's fallback behaviour when the AI
misbehaves.

---

## Configuration

All configuration is via environment variables (or a `.env` file). See
[`.env.example`](.env.example).

| Variable              | Default              | Description                                              |
|-----------------------|----------------------|----------------------------------------------------------|
| `ANTHROPIC_API_KEY`   | _(required)_         | Your Anthropic API key                                   |
| `MODERATION_MODEL`    | `claude-sonnet-4-6`  | Model used for moderation                                |
| `MAX_COMMENT_LENGTH`  | `10000`              | Max characters per comment/appeal                        |
| `RATE_LIMIT`          | `10/minute`          | Per-user limit, `<count>/<second\|minute\|hour>`          |
| `RATE_LIMIT_ENABLED`  | `true`               | Toggle rate limiting                                     |
| `LOG_FILE`            | `moderation_log.json`| File the log is persisted to (blank = in-memory only)    |
| `WEBHOOK_URL`         | _(empty)_            | If set, flagged comments are POSTed here                 |
| `LLM_TIMEOUT_SECONDS` | `30`                 | Per-request LLM timeout before falling back              |

---

## Project structure

```
app/
  main.py                # app factory, lifespan wiring, exception handlers, /health
  config.py              # settings from env / .env
  dependencies.py        # DI providers (store, moderator, notifier, limiter)
  models/schemas.py      # Pydantic models, enums, validation
  api/routes.py          # /moderate, /appeal, /log
  services/
    moderator.py         # LLMModerator: moderate() + reconsider(), retries, fallbacks
    prompts.py           # system prompt, few-shot examples, tool schemas, appeal prompt
    store.py             # thread-safe in-memory + JSON-file log
    notifier.py          # webhook notifier for flagged content
  core/
    errors.py            # domain exceptions + handler
    rate_limit.py        # per-user fixed-window limiter
tests/                   # 45 offline tests
.github/workflows/ci.yml # lint + tests on 3.11 / 3.12 / 3.13
```

---

## How moderation works

1. **Validation first.** Pydantic rejects empty, whitespace-only, missing, or
   over-long input with a `422` before any LLM call — fast and cheap.
2. **Structured output via forced tool use.** The model must call a
   `submit_moderation_decision` tool whose JSON schema defines `decision`,
   `confidence`, `category`, and `reasoning`. This guarantees a schema-valid
   answer and removes brittle free-text parsing.
3. **Domain-aware prompt.** The system prompt encodes the Property Tribes
   community guidelines (what to approve / reject / flag, including UK-specific
   issues like Equality Act discrimination and gas-safety obligations), plus
   confidence semantics and a handful of grounded few-shot examples.
4. **Appeals genuinely reconsider.** The appeal call gives the model the original
   comment, the original reasoning, **and** the user's new context, and explicitly
   asks it to weigh whether the appeal changes the picture — and to state in its
   reasoning how it did or didn't. Decisions are restricted to approve/reject.
5. **Graceful degradation.** Timeouts and transient errors are retried with
   backoff; if the model still can't be parsed, moderation falls back to
   `flagged_for_review`, and appeals fall back to upholding the rejection. The API
   never 500s because the model misbehaved.
6. **Logging + notification.** Every decision (and any appeal) is recorded in the
   log; flagged comments trigger the webhook on a background task so the response
   is never blocked.

---

## Write-up

### Key decisions and why

- **FastAPI + Pydantic.** Pydantic makes the trickiest edge cases (empty /
  whitespace / over-long input) declarative and rejects them *before* spending an
  LLM call. FastAPI gives clean dependency injection (which makes the LLM
  trivially mockable in tests) and free interactive docs for manual testing.
- **Forced tool use instead of "return JSON" prompting.** Asking a model to
  "respond in JSON" eventually produces malformed output. Defining a tool schema
  and forcing the model to call it means the response is always structurally valid,
  so the parsing code stays small and the failure modes are well-defined.
- **Confidence-driven `flagged_for_review`.** Rather than forcing a binary call on
  ambiguous content, the prompt routes genuine uncertainty to a human via
  `flagged_for_review` (and a webhook). This matches how real moderation queues
  work and avoids confidently wrong auto-decisions.
- **Appeals re-evaluate from the original + new context.** The appeal prompt is
  deliberately structured to make the model reason about whether the new context
  actually addresses the original problem (and say so), rather than rubber-stamping
  or blindly repeating the first decision.
- **Safe-by-default failure handling.** On any LLM failure, moderation degrades to
  *flag for a human* and appeals degrade to *uphold the rejection* — never to a
  silent auto-approve. Errors should fail toward caution.
- **Custom per-user rate limiter.** A small fixed-window limiter keyed on
  `user_id` exactly matches the "per user" requirement (off-the-shelf middleware
  typically keys on IP), and it is fully unit-testable without HTTP.
- **Storage behind one class.** `ModerationStore` is in-memory for speed and
  mirrors to JSON for durability, with a single interface — swapping in a real
  database later wouldn't touch the routes or services.

### What I would improve with more time

- **Persistent, concurrent-safe storage** (SQLite/Postgres) and a Redis-backed
  rate limiter so it works across multiple processes/instances.
- **Authentication** so `user_id` is trusted from a token rather than supplied in
  the body, and so the log endpoint is protected (admin-only).
- **An evaluation harness**: a labelled set of forum comments to measure
  precision/recall of the moderator and to catch prompt regressions in CI.
- **Prompt-injection hardening** and clearer separation of the (untrusted) comment
  from instructions, plus tests with adversarial comments.
- **Pagination/filtering** on `/log`, plus structured request logging and metrics.
- **Streaming/async LLM calls** and caching of identical recent comments.
- **Richer notifications** (Slack/email templates, retry queue) beyond a single webhook.

### Assumptions

- A single-instance deployment is acceptable for this exercise, so in-memory state
  + a JSON file is sufficient (the code is structured to swap in a database).
- `user_id` is supplied by the caller and is sufficient for rate limiting in this
  context; production would derive it from authentication.
- "No further appeals" means exactly one appeal per comment.
- Only `rejected` comments are appealable; `flagged_for_review` goes to a human
  queue rather than the automated appeal path, and `approved` needs no appeal.
- A comment length cap (default 10,000 chars) is a reasonable guard against abuse
  and runaway token usage; it's configurable.
- The webhook is "fire-and-forget" best-effort — a flagged decision is still
  recorded even if the webhook is down.
```
