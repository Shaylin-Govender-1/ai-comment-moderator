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
- **Tests:** `pytest` (90 tests, **100% coverage**, fully offline — the LLM is mocked)
- **CI:** GitHub Actions — lint + tests with a 100% coverage gate on Python 3.11/3.12/3.13

---

> ### 👋 Reviewing this? Two ways to test it
>
> Live moderation is powered by a real LLM, so there are two ways to evaluate it:
>
> **A. See the real AI in action — add your own Anthropic key (~2 min, a few cents).**
> Create a key at [console.anthropic.com](https://console.anthropic.com/), put it
> in `.env`, and run the server. Full instructions in
> [Quick start](#quick-start-under-5-minutes) + [Try it with curl](#try-it-with-curl).
> A key is not shipped in this repo for security reasons. I built and
> verified this end-to-end against the live API using my own Anthropic API key
> (with purchased credits), so the [curl examples](#try-it-with-curl) below are
> real Sonnet 4.6 responses.
>
> **B. Verify all the logic with zero setup and no key — run the tests.**
> ```bash
> pip install -r requirements-dev.txt && pytest
> ```
> The 90 tests mock the LLM and exercise *everything* at **100% coverage**
> (statement + branch, gated in CI): all three decision types, the complete appeal
> flow (overturn, uphold, not-found, double-appeal), every input edge case, rate
> limiting, file persistence, and the graceful-fallback behaviour when the AI errors
> or misbehaves. (CI runs these on every push.)
>
> Either way you can read [How moderation works](#how-moderation-works) and the
> [Write-up](#write-up) for the design reasoning, and the prompt itself lives in
> [`app/services/prompts.py`](app/services/prompts.py).

---

## Contents
- [Reviewing this? Two ways to test it](#-reviewing-this-two-ways-to-test-it)
- [Features](#features)
- [Additional Features (Other than the Bonus Points)](#additional-features-other-than-the-bonus-points)
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
  - [What I would improve or add with more time](#what-i-would-improve-or-add-with-more-time)
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
- ✅ **Unit tests** — 90 deterministic tests at **100% coverage** (statement + branch), no network or API key required.

---

## Additional Features (Other than the Bonus Points)

Features/functionality built beyond the core and bonus requirements — aimed at
robustness, code quality, and making the project easy to run and review.

**API & docs**
- **`GET /health` endpoint** — liveness check that also reports the active model
  and whether an API key is configured.
- **Interactive API docs** — auto-generated Swagger UI at `/docs` and ReDoc at
  `/redoc`, so every endpoint is testable in the browser with no extra tooling.
- **`appealable` flag** on the `/moderate` response so a client knows up-front
  whether a comment can be appealed.
- **Consistent, typed error responses** — domain errors map to the right HTTP
  status codes (`404` / `409` / `422` / `429` / `503`) with a uniform JSON error shape.

**AI robustness**
- **Guaranteed structured output via forced tool use** — the model must return a
  schema-validated decision object, eliminating fragile free-text/JSON parsing.
- **Defensive LLM handling** — per-request timeout, automatic retries with
  exponential backoff, and safe fallbacks (flag-for-review if moderation cannot
  complete; uphold the original rejection if an appeal cannot complete — never
  auto-approve on error). The API never returns a 500 because the model misbehaved.

**Storage**
- **In-memory _and_ file persistence** — the brief allowed either; this does both,
  writing JSON atomically so the log survives restarts and is reloaded on startup.
- **Thread-safe store** — all log reads/writes are lock-guarded for concurrent requests.
- **Concurrency-safe appeals** — appeals are claimed atomically (check-and-mark under
  one lock), so two appeals racing for the same comment cannot both go through; exactly
  one is processed and the other gets a `409`.

**Security & abuse-resistance**
- **Prompt-injection mitigation** — comments and appeal context are passed to the model
  as clearly-delimited, explicitly *untrusted* content, and the system prompt instructs
  the model to judge it, never to obey instructions inside it. Attempts to override
  moderation are treated as a bad-faith signal and never auto-approve. (Mitigation, not
  a guarantee — see the future-work notes.)
- **Input sanitisation** — control, zero-width and null characters are stripped before
  moderation (ordinary whitespace preserved), preventing invisible-character obfuscation
  of banned words.
- **Bounded rate-limiter memory** — per-user counters are swept on expiry so the limiter
  cannot grow unbounded as new users appear.

**Engineering & developer experience**
- **Dependency-injection architecture** — the LLM client, store, notifier and rate
  limiter are injected, giving clean separation of concerns and making the LLM
  trivially mockable (which is how the test suite runs fully offline).
- **Fully configurable via `.env`** — model, comment-length cap, rate limit, LLM
  timeout, webhook URL and log file are all tunable without code changes.
- **Continuous Integration (GitHub Actions)** — linting and the full test suite run
  on every push/PR across Python 3.11, 3.12 and 3.13.
- **Linting with `ruff`**, enforced in CI, to keep the codebase clean and consistent.
- **Secret hygiene** — real keys live only in a gitignored `.env`; a committed
  `.env.example` documents every variable.

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
| Missing `comment` field / non-string comment | `422` validation error                                            |
| Comment longer than `MAX_COMMENT_LENGTH`   | `422` validation error (default limit 10,000 chars)                 |
| Leading/trailing whitespace                | Trimmed before moderation                                          |
| Control / zero-width / null characters     | Stripped before moderation (keeps `\n` `\t` `\r`); a comment that is *only* such chars is rejected as empty (`422`) |
| Comment trying to instruct the moderator (prompt injection) | Passed as untrusted, delimited content; the model is told to judge not obey, so injections are ignored and never auto-approve (typically rejected/flagged) |
| Over-long `user_id`                        | `422` validation error (max 200 chars)                              |
| Borderline / ambiguous content             | `flagged_for_review` with reasoning + webhook notification          |
| Appeal for a non-existent `comment_id`     | `404 comment_not_found`                                             |
| Appeal for a comment that was not rejected  | `409 not_appealable`                                               |
| Appeal for an already-appealed comment     | `409 already_appealed`                                             |
| Two appeals for the same comment at once   | Atomically guarded — exactly one is processed, the other gets `409 already_appealed` |
| Rate limit exceeded for a user             | `429 rate_limit_exceeded`                                          |
| LLM returns malformed / no structured data | Falls back to `flagged_for_review` (never a 500)                    |
| LLM/network error during moderation        | Falls back to `flagged_for_review`                                  |
| LLM/network error during an appeal         | Upholds the original rejection (never auto-approves on error)       |
| `ANTHROPIC_API_KEY` not configured         | `/moderate` & `/appeal` return `503` with a clear message          |

---

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest                                   # 90 tests, fully offline (LLM mocked) — no API key needed
pytest --cov=app --cov-branch           # 100% coverage (statement + branch), gated in CI
ruff check .                             # linting
```

The tests cover: each decision type, the appeal flow (overturn, uphold, not-found,
not-appealable, double-appeal), input validation and sanitisation (empty / over-long /
non-string / control characters), rate limiting (including window reset and bucket
eviction), concurrency-safe appeal claiming, prompt-injection wiring, webhook
notifications, the `503` no-key path, file persistence round-trips, and the moderator's
fallback behaviour when the AI errors or misbehaves.

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
tests/                   # 90 offline tests (100% coverage)
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
   reasoning how it did or did not. Decisions are restricted to approve/reject.
5. **Graceful degradation.** Timeouts and transient errors are retried with
   backoff; if the model still cannot be parsed, moderation falls back to
   `flagged_for_review`, and appeals fall back to upholding the rejection. The API
   never 500s because the model misbehaved.
6. **Logging + notification.** Every decision (and any appeal) is recorded in the
   log; flagged comments trigger the webhook on a background task so the response
   is never blocked.
7. **Treats input as untrusted.** Comments and appeal context are sanitised (control
   /zero-width/null characters stripped) and sent to the model inside delimiters as
   explicitly untrusted content, so prompt-injection attempts are judged rather than
   obeyed. Appeals are also claimed atomically, so concurrent appeals cannot both run.

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
  database later would not touch the routes or services.
- **Model tier — Claude Sonnet 4.6.** Moderation here needs genuine reasoning about
  nuance and context — telling a strong-but-legitimate opinion apart from unlawful
  discrimination, or judging whether an appeal's new context actually changes the
  picture — not keyword matching. Sonnet 4.6 is the strong mid-tier that balances
  that reasoning quality against cost and latency; obvious cases could later be
  routed to a cheaper first-pass model (see future work).
- **Domain-grounded prompt with few-shot examples.** The system prompt encodes the
  Property Tribes context and UK-specific rules (Equality Act "No DSS" discrimination,
  gas-safety / illegal advice, get-rich-quick property spam) with worked examples.
  Generic moderation would both over-block robust debate *and* miss domain-specific
  harms, so grounding the model in the forum's world makes decisions more accurate
  and consistent.
- **Comments treated as untrusted input.** A comment is adversarial user input, so it
  is sanitised (control / zero-width / null characters stripped) and passed to the
  model as clearly-delimited, explicitly-untrusted content, with the system prompt
  instructed to judge it and never obey instructions inside it. Moderation is exactly
  where prompt injection will be attempted.
- **Synchronous endpoints on FastAPI's threadpool.** The endpoints are plain `def`, so
  FastAPI runs them in its worker threadpool and the blocking Anthropic SDK call never
  ties up the event loop — staying responsive without the added complexity of fully
  async I/O.
- **Public repository.** The brief allows public or private-with-access; I chose public
  so reviewers can open the link and read everything immediately, with no access-granting
  step. No secrets live in the repo (the API key is gitignored in `.env`), so there is no
  downside to public visibility.

### What I would improve or add with more time

- **Persistent, concurrent-safe storage** (SQLite/Postgres) and a Redis-backed
  rate limiter so it works across multiple processes/instances.
- **Containerised, independently deployable service** — package the API as a Docker
  image and run it as a standalone container app (e.g. Cloud Run, AWS ECS, or Azure
  Container Apps) with its own CPU/memory and autoscaling. Other applications would
  consume the moderator over HTTP using an issued API key, so it runs in its own
  isolated environment and never competes for the calling app's resources. This
  pairs naturally with the authentication and Redis-backed rate limiting above.
- **Authentication** so `user_id` is trusted from a token rather than supplied in
  the body, and so the log endpoint is protected (admin-only).
- **An evaluation harness**: a labelled set of forum comments to measure
  precision/recall of the moderator and to catch prompt regressions in CI.
- **Deeper prompt-injection hardening** — building on the delimiting + untrusted-content
  instructions already in place, add a dedicated injection/jailbreak classifier and a
  standing adversarial test set run in CI.
- **Pagination/filtering** on `/log`, plus structured request logging and metrics.
- **Streaming/async LLM calls** and caching of identical recent comments.
- **Richer notifications** (Slack/email templates, retry queue) beyond a single webhook.
- **A no-key "demo mode"** — a heuristic stand-in moderator that activates when no
  API key is set, so the live `/moderate` and `/appeal` endpoints can be tried on a
  fresh clone (with real Claude Sonnet 4.6 still the default when a key is present).
  Today the same goal is met by the offline test suite; a demo mode would make the
  live endpoints explorable with zero setup too.
- **Human-in-the-loop feedback loop (active learning)** — a moderator dashboard for
  actioning `flagged_for_review` items, where every human decision and appeal outcome
  is captured as labelled data. That data continuously curates the few-shot example
  bank and, once there is enough of it, fine-tunes a model — so the moderator
  measurably improves from real corrections instead of staying static.
- **Tiered / cascaded model routing** — run a fast, cheap first pass (rules/blocklists
  or a smaller model such as Claude Haiku) to auto-clear obviously clean content, and
  only escalate genuinely ambiguous comments to Sonnet. At forum scale this cuts cost
  and latency substantially while keeping the strongest model on the hard cases.
- **Agentic, tool-using moderation grounded in live policy** — let the moderator call
  tools mid-decision: retrieve the forum's current community guidelines and similar
  past rulings (RAG) so decisions cite the exact rule and stay consistent as policy
  evolves, and check link/domain reputation to catch scam URLs. This turns a single
  LLM call into a context-aware agent rather than a fixed prompt.
- **User-reputation / history-aware decisions** — feed each author's prior record
  (already captured in the log) into moderation, so repeat offenders are automatically
  escalated and consistently trustworthy users are fast-tracked — reducing both false
  positives and reviewer workload.
- **Decision monitoring, drift detection and spam-campaign dedup** — track decision,
  category and confidence distributions over time to detect model/prompt drift and
  emerging abuse patterns and alert on shifts; fingerprint near-duplicate comments via
  embeddings to auto-handle coordinated spam campaigns without re-invoking the LLM for
  each one.
- **Self-consistency / LLM-as-judge for borderline cases** — on low-confidence
  decisions, either sample the model a few times and take the majority vote, or have a
  second model act as an independent verifier. This reduces variance and directly
  improves the decision consistency the task prioritises.

### Assumptions

- A single-instance deployment is acceptable for this exercise, so in-memory state
  + a JSON file is sufficient (the code is structured to swap in a database).
- `user_id` is supplied by the caller and is sufficient for rate limiting in this
  context; production would derive it from authentication.
- "No further appeals" means exactly one appeal per comment.
- Only `rejected` comments are appealable; `flagged_for_review` goes to a human
  queue rather than the automated appeal path, and `approved` needs no appeal.
- A comment length cap (default 10,000 chars) is a reasonable guard against abuse
  and runaway token usage; it is configurable.
- The webhook is "fire-and-forget" best-effort — a flagged decision is still
  recorded even if the webhook is down.
- Reviewers supply their own Anthropic API key to test the live moderation. No key
  is shipped in the repo for security reasons, so the full AI behaviour needs a key
  in `.env` (~2 minutes to create); alternatively, the offline test suite (`pytest`,
  90 tests, no key) verifies all of the logic. See
  [Reviewing this? Two ways to test it](#-reviewing-this-two-ways-to-test-it).
- Moderation considers **only the comment text** (and, for appeals, the appeal
  context) — no surrounding thread, author history, images, or link/URL reputation
  are taken into account.
- The encoded community guidelines **approximate the real forum policy** — they are
  inferred from the public [propertytribes.com](https://www.propertytribes.com/) site
  rather than an official rulebook; a real deployment would encode the actual policy.
- **`flagged_for_review` items are actioned downstream** — the service flags, logs and
  notifies (webhook), but assumes an external human-review process handles them; it has
  no review UI and does not track their resolution.
- **`GET /log` is unauthenticated** for this exercise; in production it would be
  admin-only (see authentication in future work).
- **Confidence is the model's self-reported estimate** — a useful triage signal, not a
  calibrated statistical probability.
- Comments are assumed to be **English-language and UK-context** — the prompt and
  few-shot examples are written for that audience.
- The client **retains the `comment_id`** returned by `/moderate` in order to appeal
  later (there is no lookup-by-content).
- Comments and `user_id` are **stored in the log in plaintext** — acceptable for this
  exercise; production would add data-retention and PII handling.
