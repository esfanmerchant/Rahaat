# PLAN: Rahat, "The Last Mile: AI on Public Rails"

Coder's Cup '26 AI Hackathon, ACM FAST-NUCES Karachi. Plan written Sat 21 Nov 2026, 11:45 PKT.

> **PROTOTYPE. Not an official service. All identity, payment and data services are simulated.**

This file is the single source of truth. `CLAUDE.md` holds the standing rules every session loads. `docs/KICKOFF.md` holds the step-by-step commands and the prompts to paste.

---

## 0. Situation and the decision this plan makes

| | |
|---|---|
| Build window ends | **Sun 22 Nov 2026, 18:00 PKT**. We submit by 16:30. |
| Time left when written | about 30 hours, repository empty |
| Live evaluation | Mon 23 Nov, FAST-NUCES Karachi library, in person, live demo mandatory |
| Rubric | 100 pts: AI 30, SaaS 20, Real-world 15, Safety 15, Accessibility 10, Innovation 10 |

**The official brief is built in full**: all 8 technical challenges, all 5 roles, all 7 core features, all 10 optional platform features, all 11 AI features, all 4 bonus features. It is built in **score order**, in tiers, and each tier is finished and live before the next begins.

The extra enterprise list from the original master prompt (Kubernetes, PgBouncer, read replicas, ZAP, trivy, semgrep and similar) earns almost nothing on this rubric and cannot be shown in a demo. It moves to Tier 3 and to a written "scale path" in `docs/ARCHITECTURE.md`.

Why, in the organisers' own words:
1. "You are scored on how your system behaves, not on what you claim." A feature that breaks live scores below a feature that is absent.
2. "A deep solution for one task beats a thin solution for many." End-to-end task completion is 7 points on its own.
3. "One bonus feature that really works is worth more than four half-finished ones."

**The rule for the whole build: a feature is either demo-proof or hidden behind a flag.** Nothing half-built is reachable on Monday.

## 1. Ways to lose (read once, remember always)

- **Real personal data is disqualification.** Never photograph or upload a real CNIC, never type a real person's name with an ID or phone number, not even in the live demo. OCR is demonstrated only on our generated specimen cards.
- Mock IDs use the reserved shape `00000-NNNNNNN-C`. Mock phones use `0999-NNNNNNN`. CI fails if anything else that looks like a CNIC or a Pakistani mobile number appears in the repo.
- All code is written inside the build window. Commit early and often so the history proves it.
- The live URL must still be up on Monday. Screenshots and video do not replace a live demo.
- Every screen footer, the API docs and the README carry the prototype label.

## 2. How we win: rubric line to proof

| Rubric line | Pts | What the judge sees working | Tier |
|---|---|---|---|
| Functional AI features | 12 | 11 AI features, each with an entry point in the main flow and a number on the eval dashboard | T0-T2 |
| AI workflow integration | 8 | One pipeline: voice, structured form, OCR/QR/forgery, dedupe, rules, calibrated decision, route, explanation, agent pays after approval | T0-T1 |
| AI output quality and consistency | 6 | Validated outputs, calibrated probabilities with ECE shown, golden tests, replay returns the identical decision | T1 |
| Model and tool selection | 4 | README table: small local models for decisions, Whisper for Urdu, LLM only for wording inside a validated structure, and why | T1 |
| Core SaaS features | 8 | Login/RBAC, dashboards, cases, API keys + Swagger, audit, consent, mock services, tenants, plans, notifications, webhooks | T0-T2 |
| Backend architecture and API | 5 | Modular monolith, an adapter for every external party, `/v1`, RFC 7807 errors, idempotency, OpenAPI | T0 |
| Database design | 4 | RLS on every tenant table, immutable rule versions, hash-chained audit, up/down migrations | T0 |
| Deploy, test, monitor | 3 | Live URL, CI green, `/healthz`, `/metrics`, system health screen | T0 |
| Problem understanding | 5 | Anchor sentence, three personas, Pakistan specifics: feature phones, name spellings, shared phones, relief-payment SMS scams | T0 |
| End-to-end task completion | 7 | The Relief application finishes for all three personas, unhappy paths included | T0 |
| Practical impact | 3 | Impact report (time saved, handoff rate, fraud stopped, cost per claim), USSD/SMS channel | T2 |
| Voice and regional language | 4 | Urdu prompts and Urdu speech input with read-back (the brief asks for Urdu or a regional language) | T1 |
| Low-literacy usability | 3 | One question per screen, pictograms, no typing, symbol tracking code | T0-T1 |
| Weak internet | 3 | Offline PWA, outbox sync, under 100 KB, image compression, resume | T1 |
| Uncertainty and handoff | 5 | Three-way router everywhere, handoff package, silent-guess rate 0 and measured | T0-T1 |
| Privacy and consent | 4 | Consent centre; withdrawal blocks officer, helper and API key at once, inside the database | T1 |
| Explainability and auditability | 3 | Two views per decision, chain verify, replay | T0-T1 |
| Risk and reliability | 3 | Circuit breakers with failure injection, idempotent payments, four-eyes, rate limits | T1-T2 |
| Originality | 4 | Section 3, "what makes us different" | T1-T2 |
| Creative feature implementation | 4 | Digital Twin, Helper Mode, Offline sync, Scam Map, all working | T2 |
| Technical creativity | 2 | Pure decision core, consent inside RLS, zero web-font bytes, Postgres as the queue | T0-T1 |

## 3. Product

**Anchor sentence.** We help a low-literacy widow, a scam-targeted shopkeeper, and a community helper serving 40 families apply for and track a mock Relief Payment even though they cannot read the forms, have weak signal, get fake "relief payment" messages, and have messy or duplicated records.

**Program name in the UI:** Rahat (Prototype Relief Program).

**The one flow.** register, consent, guided application by voice and icons, upload ID, quality + QR + OCR + forgery check, bad-data resolution and dedupe, versioned rules, cost-based decision (auto / ask for proof / human), officer review when needed, mock payment, notification, audit trail and explanation. The scam checker is open to everyone and feeds the Scam Map.

**What makes us different.** Every team will have a checklist of features. These nine are cheap to build on top of ours and are what a judge remembers:

1. **Challenge Lab.** One page, eight cards, one per official technical challenge. Each card runs the real scenario against the live system and shows the evidence: requests, responses, audit rows. The judge ticks the rubric from one screen.
2. **Cost of being wrong, with live sliders.** Move a cost, watch the thresholds, the cost curve and the confusion matrix on 1,000+ labelled cases change, save, and the next decision uses it.
3. **Replay.** Any past decision can be recomputed from its stored snapshot and pinned versions and must match bit for bit. The trace is evidence, not decoration.
4. **Ask the cheapest question.** When unsure, the engine works out which single proof would lower expected cost the most and asks for exactly that.
5. **Verify code on every official message.** Our own SMS carries a short code; anyone can check it in the scam checker or over USSD. Real messages are confirmed by cryptography, so they are never false alarms.
6. **Feature-phone channel.** A USSD/SMS simulator for status check, scam check and consent withdrawal. Most relief beneficiaries do not own a smartphone.
7. **Symbol tracking code.** A case is tracked by three pictograms plus digits, so a person who cannot read can still recognise and say their code.
8. **Mistakes ledger.** A page listing the real people we wrongly flagged or blocked and what that cost. The brief asks for honest false alarms; we make them a screen.
9. **Human voice.** Fixed Urdu prompts can be re-recorded by a native speaker on the team. It works offline and it is trusted more than a synthetic voice.

## 4. Scope, in the order that scores

**T0, the spine (Phase 1, live by Sat 21:00)**
- Staff login (email + password), citizen login (phone + PIN), JWT access + rotating refresh, RBAC policy registry, two tenants with RLS, hash-chained audit log.
- Register person, consent, guided application (icons + Urdu audio), upload mock ID, quality check + QR signature + OCR.
- Versioned rules, cost-based decision, user explanation and auditor trace.
- Officer queue and review with handoff package, mock payment (idempotent), mock SMS in the outbox, tracker.
- Mock identity, registry and payment services behind adapters. Seed data, Swagger, CI, live URL.

**T1, the eight challenges provable (Phase 2, by Sun 03:00)**
- C01 calibrated model, threshold analysis on 1,000+ cases, slider page.
- C02 complete handoff package, silent-guess invariant and metric, golden tests.
- C03 name matching, dedupe bands, duplicate-review case, 200+ messy fixtures.
- C04 rule editor, second-approver publish, instant effect, old decisions keep their version.
- C05 two views, replay, chain verify.
- C06 consent centre, withdrawal enforced in RLS and API, blocked attempts audited.
- C07 voice answers with read-back, offline autosave, outbox, resume, bundle budget.
- C08 scam checker in English, Urdu and Roman Urdu, forgery signals, false-alarm metrics, "this is real, ask a person".
- Challenge Lab. API keys and rate limiting. Helper basics (delegation, switch with PIN).

**T2, bonus features and the rest of the brief (Phase 3, by Sun 09:00), in this order**
1. RAG with citations, agent with approval gate, guardrails with a 50-attack red-team suite.
2. Digital Twin, Scam Map.
3. Eval dashboard, analytics per tenant, mistakes ledger.
4. Offline-first sync with conflict UI, Helper Mode in full.
5. Webhooks, plans and usage limits, notification channels, jobs dashboard.
6. USSD/SMS simulator, verify code, symbol tracking code.
7. Anomaly detection, memory, appeals and complaints.

**T3, stretch (only when T0-T2 are green)**
Jev adapter, MCP server exposing the agent tools, verifiable eligibility credential as a QR, fraud-ring graph, override learning loop with a promotion gate, TOTP for staff, a second program by configuration, schemathesis fuzz run, visual QA, Kubernetes manifests.

**Documented only** (`docs/ARCHITECTURE.md`, one honest paragraph each): PgBouncer, read replicas, table partitioning, swapping the Postgres queue for Redis, autoscaling, BYOK key management, canary release of models, DAST and container scanning, data residency.

**Cut rule.** At each gate, anything not green is cut or hidden. Cuts come from the bottom of the current tier. No tier starts before the previous gate passes on the live URL.

## 5. Architecture

### 5.1 Decisions

| Area | Choice | Why | Change from the original prompt |
|---|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync, psycopg 3), Alembic | One language for API, decision engine and AI. Sync sessions avoid async lazy-load traps. | same |
| Database | PostgreSQL 16 on Neon (free), RLS, pgvector | One system for data, tenancy isolation, vectors, queue and audit | hosted instead of local |
| Jobs | `jobs` table, `SELECT ... FOR UPDATE SKIP LOCKED`, worker in the same image | One fewer service to deploy and debug. `enqueue()` keeps the same interface if Redis is added later. | replaces Redis + Dramatiq |
| Rate limits | In-process token bucket; plan usage counters in Postgres | Single instance in the demo; interface allows Redis later | replaces Redis |
| Frontend | Vite, Preact, TypeScript, Tailwind, PWA (`vite-plugin-pwa`), `idb`, `openapi-fetch` | Next.js App Router ships roughly 90-100 KB of framework JS before our code and the citizen budget is 100 KB in total. Preact is about 5 KB. The static build is served by FastAPI: one origin, one container, simple cookies and service worker. | replaces Next.js |
| Deploy | One Docker image: API, built frontend, worker, mock services on an internal port. Postgres external. | Runs on any host; see 5.4 | replaces Compose + Kubernetes |
| Local dev | Native: `uv` + Python 3.12, Node 24 + npm, and an embedded PostgreSQL 16 with pgvector (`pgserver`) that starts by itself | Dev PCs are Windows without Docker or `make`; nobody needs an account to develop or test | new |
| Delivery order | Vertical slices; frontend starts in Phase 1 | A mandatory live demo cannot wait for "backend complete" | replaces "backend first, Gate B" |
| AI | Local-first provider chains; hosted services optional | Zero-cost core that also runs offline on a laptop | same intent |

### 5.2 Topology

```
Browser PWA (Preact)  --HTTPS-->  FastAPI :8000
  IndexedDB draft + outbox          /v1/*  API        /docs  Swagger       /  static frontend
  service worker (shell + audio)    worker (jobs table)
                                    AI modules: scikit-learn, OpenCV, Tesseract, Whisper*
                                    httpx adapters --> mock services :9001 (identity, registry, payment, SMS)
                                                       internal only, own API keys, failure injection
                                    Postgres (Neon): RLS, pgvector, hash-chained audit
* only when AI_PROFILE=full
```

### 5.3 Repo layout and ownership

```
backend/app/core/          config, db session + RLS context, security, audit, errors, rate limit, jobs   (Track A)
backend/app/contracts/     shared Pydantic contracts (section 6)                                         (lead; change by request)
backend/app/db/models/     all SQLAlchemy models, created in Phase 0                                     (lead)
backend/app/modules/<name>/ router.py, service.py, schemas.py, tests/                                    (one track each, section 7)
backend/app/mocks/         mock identity, registry, payment, SMS                                         (Track A)
backend/app/synth/         deterministic synthetic world generator                                       (Track B)
backend/migrations/        Alembic; single author                                                        (lead)
frontend/src/citizen/      citizen PWA                                                                   (Track D1)
frontend/src/staff/        staff console, lazy-loaded                                                    (Track D2)
frontend/src/shared/       tokens, pictograms, i18n, api client                                          (D1 owns, D2 requests)
data/                      policy corpus, scam templates, fixtures, audio manifest
deploy/                    Dockerfile, start script, host-specific files
docs/                      STATUS, DECISIONS, CONTRACTS, ARCHITECTURE, reports, DEMO
```

Routers are auto-discovered from `modules/*/router.py`, so no track edits `main.py`.

### 5.4 Deployment, ranked. A public URL must serve the Phase-0 skeleton by Sat 15:00.

| # | Host | Cost | Needs | AI profile | Notes |
|---|---|---|---|---|---|
| 1 | Azure for Students VM (2 vCPU, 8 GB) + Docker + Caddy for HTTPS | $0 from the $100 credit | university email, no card | full | Free DNS label `name.region.cloudapp.azure.com`. Most control. About 45 minutes. |
| 2 | Hugging Face Docker Space | $9 (PRO) | card | full (16 GB) | Simplest: git push. The free Docker tier is no longer dependable in 2026. |
| 3 | This PC + tunnel | $0 | PC stays on | full | Tailscale Funnel gives a stable URL. Cloudflare quick tunnel gives a random URL and no SSE. Also Monday's Plan C. |
| 4 | Render free web service | $0 | nothing | lite (512 MB, sleeps after 15 min) | Last resort; ping it to keep it awake. |

Timebox each attempt to 40 minutes, then move down the list. Database is Neon free in every case.

### 5.5 Provider chains and profiles

Every AI capability sits behind an interface with a local implementation that always works, and optional hosted ones in front of it.

| Capability | Always available | Optional |
|---|---|---|
| Scam, complaint, request and document-type classification | char n-gram TF-IDF + logistic regression, calibrated | Jev (`typesafe-ai/jev` through Vercel AI Gateway), LLM second opinion. Disagreement routes to a human. |
| Eligibility evidence | calibrated logistic regression on synthetic labelled cases | none |
| OCR, QR, forgery | Tesseract (`eng` + `urd`), OpenCV `QRCodeDetector`, ELA, Laplacian blur | none |
| Speech to text (Urdu) | browser speech recognition where present; icons always | faster-whisper `small` locally (`AI_PROFILE=full`), Groq `whisper-large-v3` (free key) |
| Text to speech | pre-generated audio files for every fixed prompt, reason code and digit | browser `speechSynthesis` for dynamic text |
| Retrieval | BM25 | fastembed multilingual ONNX embeddings + pgvector (`AI_PROFILE=full`) |
| Wording of answers and explanations | deterministic templates and extractive answers | an LLM, only inside a validated structure. With an Anthropic key use the official `anthropic` SDK, default `claude-opus-5-5` (`claude-haiku-5-5` is the cheap option), structured outputs. |

`AI_PROFILE=full|lite`. Heavy imports are lazy and guarded. `/v1/system/health` lists which providers are active right now, and the System Health screen shows it.

`APP_ENV=demo|prod`. Demo enables `/demo`, the Challenge Lab and mock controls. Prod refuses to start with default secrets.

**Jev.** It is a real model (TypeSafe AI's typed decision model, choice / score / boolean questions with probabilities) reached through Vercel AI Gateway with the AI SDK. It needs a gateway credential and a JavaScript SDK. The brief allows "build the same idea with another tool", so our `TypedDecision` interface and local calibrated classifier are the default, and Jev is a T3 adapter with a 30-minute timebox. Read https://vercel.com/kb/guide/typesafe-jev-and-ai-sdk before writing it.

## 6. Contracts every track depends on

Phase 0 writes these as Pydantic models in `backend/app/contracts/` and exports them to `docs/CONTRACTS.md`. Changing one needs the lead's agreement.

### 6.1 Decision math (Challenge 01)

Per-tenant cost matrix, editable by admin. Defaults in cost units, 1 unit is about Rs 120:

| Cost | Units | Meaning |
|---|---|---|
| `C_wrong_approve` | 100 | the Rs 12,000 mock payment is lost |
| `C_wrong_reject` | 30 | an eligible family is denied; appeal and hardship |
| `C_human_review` | 3 | officer time |
| `C_ask_proof` | 1 | one more step for the citizen |
| `C_delay_per_day` | 0.2 | waiting |

- `p_ok = p_eligible * p_genuine`. Independence is an assumption and is listed as a limitation; the product is conservative.
- Expected cost of each action:
  - approve: `(1 - p_ok) * C_wrong_approve`
  - human: `C_human_review + C_delay_per_day * d_h` where `d_h` is the current expected queue days
  - ask for proof, only when a resolvable field exists: `C_ask_proof + C_delay_per_day * d_p + q * cost_approve(p_ok') + (1 - q) * cost_human`, where `p_ok'` is `p_ok` recomputed with that field verified and `q` is the chance the proof confirms it
  - reject: allowed only when a hard rule fails on **verified** inputs (signed QR or registry), never on a model score or a self-declared value; cost `(1 - p_ineligible) * C_wrong_reject`
- Choose the minimum. **Hard guards override and send the case to a human**: forgery suspicion, identity mismatch, possible duplicate, high anomaly score, guardrail trip, model disagreement.
- Derived thresholds shown in the UI and recomputed on every cost edit: approve when `p_ok >= 1 - cost_human / C_wrong_approve` (0.968 with defaults and one day of queue); reject when a verified hard rule fails and `p_ineligible >= 1 - cost_human / C_wrong_reject` (0.89).
- **Silent guess** means `route = auto` while a required field is below its confidence floor, or the threshold is not met, or a guard is active. The engine asserts this cannot happen and falls back to human; the metric is computed over every decision and must be 0.

### 6.2 TypedDecision (our Jev-equivalent). Every AI component returns it.

```python
class TypedDecision(BaseModel, Generic[T]):
    choice: T | None                    # None when abstained
    probabilities: dict[str, float]
    confidence: float                   # calibrated
    route: Literal["auto", "ask_more", "human"]
    reasons: list[str]                  # reason codes, never free text
    model_version: str
    abstained: bool
```

### 6.3 ApplicationFormV1 (structured output with provenance)

```python
class FieldValue(BaseModel, Generic[T]):
    value: T | None                     # None means unknown; never guessed
    confidence: float                   # 0..1
    provenance: Literal["tapped", "typed", "spoken", "ocr", "qr_signed", "registry"]
    verified: bool                      # true only for qr_signed and registry
```

Fields: `full_name, national_id, dob, gender, district, phone, household_size, income_band, is_widow, has_disability, receives_other_aid, payout_account, language`. Invalid output is repaired once, otherwise handed to a human.

### 6.4 DocumentCheck

`quality: ok | blurry | glare | cropped | not_a_card`, `retake_hint` (reason code with audio), `qr: {found, signature_valid, payload}`, `ocr: {fields, mean_confidence}`, `authenticity: TypedDecision[genuine | suspect]`, `signals: [{code, weight, staff_detail}]`.
Poor quality asks for a retake; it is never a rejection. Glare with a valid signed QR is not blocked. Signals are shown to staff and auditors only; the citizen hears "a person will check".

### 6.5 HandoffPackage (Challenge 02)

`question, understanding, uncertain_fields[{field, value, confidence, why}], rule_fired, hypotheses[top 2 with probabilities], resolving_proof, suggested_question, evidence{ocr, transcript, document_ids}, expected_costs`. Attached to the case and shown at the top of the officer's review screen.

### 6.6 Access: RBAC, RLS, consent (Challenge 06)

- App connects as `rahat_app` (not table owner, no `BYPASSRLS`). Migrations run as the owner role.
- Each transaction sets context with `set_config('app.tenant_id' | 'app.user_id' | 'app.role' | 'app.person_id', value, true)`. Apply it in a SQLAlchemy `after_begin` listener so it survives commits inside one request.
- Every tenant table: `USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)` with the same `WITH CHECK`. Unset context returns no rows.
- Person-data tables (`persons`, `applications`, `documents`, `document_checks`, `memory_items`) add `AND app_can_read_person(person_id)`. That function is `SECURITY DEFINER`, owned by the owner role, and returns true when: the caller is the citizen who owns the row; or a helper with an active, unexpired delegation; or an officer or API client whose tenant holds an active consent covering the purpose. Admins manage configuration and do not read case data. Auditors read audit, consent and decision records with redacted snapshots.
- Every route declares a policy. A test fails the build when a route has none.
- Withdrawal sets the consent to `withdrawn` in one transaction. From the next request the function returns false, so officer, helper and API-key reads return 403 or empty. Side effects: pause the application, cancel queued jobs for the person, purge memory items, emit a `consent.withdrawn` webhook.
- A denied read writes `access.denied` to the audit log in its own committed transaction.

### 6.7 Audit chain (Challenge 05)

`audit_log(id, tenant_id, ts, actor_type, actor_id, acting_for_person_id, action, object_type, object_id, reason, input_hash, model_version, rule_version_id, result, request_id, prev_hash, hash)`.
`hash = sha256(prev_hash || canonical_json(row))`, one chain per tenant, serialised with `pg_advisory_xact_lock`. The app role has INSERT and SELECT only. `GET /v1/audit/verify` walks the chain and names the first broken row. The chain head is written to `audit_anchors` on a schedule. The tamper demo edits a row through the owner connection, as a database administrator would, and verification catches it.

### 6.8 Rule DSL (Challenge 04)

Rules are data in `rule_versions.dsl` (JSON), never code:

```json
{ "params": { "income_cap": 30000 },
  "required_docs": ["rahat_id"], "payment_pkr": 12000,
  "all": [
    { "id": "income_cap", "hard": true,
      "label_en": "Monthly income at or below Rs 30,000",
      "label_ur": "ماہانہ آمدنی 30,000 روپے یا کم",
      "expr": { "<=": [ { "var": "verified_income_pkr" }, { "param": "income_cap" } ] } },
    { "id": "priority_group", "hard": false,
      "expr": { "or": [ { "var": "is_widow" }, { "var": "has_disability" },
                        { ">=": [ { "var": "household_size" }, 5 ] } ] } } ] }
```

Own interpreter: allowlisted operators only, no `eval`, depth at most 8, at most 200 nodes. **Three-valued logic**: a rule over an unknown variable is `unknown`, never a guess. Each evaluation returns a trace of `{rule_id, result, values_used}`. Versions are immutable; rollback creates a new version. The active pointer is read inside the decision transaction, so a publish takes effect on the very next decision with nothing to restart. Every decision stores `rule_version_id` and its trace.

### 6.9 Offline sync

`POST /v1/sync` with `{device_id, ops: [{op_id, kind, entity_id, base_version, patch, created_at}]}`. `(device_id, op_id)` is unique on the server. Per-op result: `applied | duplicate | conflict{fields, server_value} | rejected{reason}`. Every op is authorised again under the permissions and consent that hold when it is applied, so a withdrawn consent invalidates queued ops.

### 6.10 Data model, created in one migration in Phase 0

`tenants, plans, usage_counters, users, memberships, sessions, api_keys, persons, person_identifiers, name_variants, household_links, duplicate_candidates, helper_delegations, consents, consent_events, correction_requests, programs, applications, documents, document_checks, cases, case_notes, case_events, appeals, rule_sets, rule_versions, policy_documents, decisions, human_reviews, approvals, payments, reconciliation_items, notifications, webhooks, webhook_deliveries, jobs, scam_reports, scam_clusters, public_warnings, takedown_requests, kb_documents, kb_chunks, memory_items, agent_runs, agent_steps, sync_ops, ussd_sessions, eval_runs, twin_runs, model_registry, feedback_labels, security_events, audit_log, audit_anchors`.

Every table has `tenant_id` and timestamps, except the global identity tables `plans`, `tenants`, `users` and `sessions` (a user can belong to several tenants; each access token names exactly one). `decisions` stores the full input snapshot, input hash, rule trace, probabilities, expected costs, route, reasons, handoff package, explanation, guardrail verdicts and latency. National ID and phone are encrypted with AES-GCM using a per-tenant data key wrapped by a master key from the environment, plus an HMAC blind index for lookup. Schema changes after Phase 0 go through the lead.

### 6.11 API conventions

`/v1` prefix. RFC 7807 problem responses with `request_id`; validation errors are repairable and never a 500. Cursor pagination with a hard page cap. `Idempotency-Key` on every POST that creates money, applications or sync ops. Explicit Pydantic input models that forbid extra fields. Access token in memory, refresh token in an httpOnly SameSite cookie, nothing in localStorage. Live updates use SSE with a polling fallback.

## 7. Work orders

Each item is done when it works on the running app, has a test, and is ticked in `docs/STATUS.md`.

### 7.0 Phase 0, foundation (one lead session; subagents for frontend scaffold and deploy)

F1 Repo hygiene: `.gitignore`, `.gitattributes` forcing LF, `.env.example`, README stub with the prototype label.
F2 Backend scaffold: app factory, settings, JSON logs with request ids and PII redaction, problem-details errors, `/healthz`, `/readyz`, `/metrics`, security headers, body size limit. Swagger needs its own relaxed CSP.
F3 All models and the initial migration: roles, grants, RLS policies, `app_can_read_person`, session with RLS context.
F4 Auth: staff email + password (argon2id), citizen phone + PIN, pinned-algorithm JWT with `kid`, issuer and audience, refresh rotation with reuse detection, sessions, lockout.
F5 Policy registry and the test that fails on an undeclared route.
F6 Audit writer with the hash chain, list and verify endpoints.
F7 Contracts package and `docs/CONTRACTS.md`. Stub endpoints for the spine with correct schemas so the frontend can start.
F8 Seed: two tenants, demo users for all five roles, the Rahat program, rule version v1, cost matrix. Idempotent, with `--reset`.
F9 Frontend scaffold: Vite + Preact + Tailwind, tokens, citizen and staff shells, i18n with RTL, generated API client, working login, PWA plugin, bundle-size check.
F10 Root npm scripts: `dev`, `verify`, `verify:fast`, `gen:api`, `seed`. No Makefile.
F11 CI: lint, types, tests against a Postgres service, frontend build with budget, mock-data lint, secret scan.
F12 Dockerfile, start script, first live deploy.

### 7.A Track A, platform core (`backend/app/core`, `modules/{auth,tenancy,people,consent,cases,payments,notifications,webhooks,apikeys,sync,ussd}`, `mocks`)

Phase 1
- A1 Persons and registration, self or helper-assisted, with encrypted identifiers and blind index.
- A2 Consent grant at registration with purpose, field scopes and expiry; consent events.
- A3 Applications: draft, patch, submit; idempotent on `client_op_id`; status machine.
- A4 Document upload: allowlist by magic bytes (JPEG, PNG, WebP), 5 MB cap, pixel cap, re-encode, strip EXIF, random storage key; then Track C's `check_document()`.
- A5 Cases, one generic system for every human handoff: kinds `application_review, duplicate_review, document_review, complaint, appeal, correction, scam_review`; enforced state machine with reopen; notes; SLA; queue API sorted by priority, confidence or age; approve, reject, request proof and escalate each need a reason; no bulk approve of low-confidence items.
- A6 Mock services on an internal port with their own keys, latency and failure injection; adapters with timeout, retry and circuit breaker; plain-language degradation messages.
- A7 Payments: created only from an approved decision; state machine; unique idempotency key and row lock; four-eyes above the tenant limit; reconciliation row.
- A8 Notifications outbox with English and Urdu templates, in-app and mock SMS, retries; the jobs worker.

Phase 2
- A9 API keys: prefix + hash, shown once, scopes, expiry, per-key limit, metering.
- A10 Rate limiting per IP, user, key and tenant; pagination caps; 429 with `Retry-After`.
- A11 Consent centre API: who has my data, access log, narrow, withdraw, correction request, export, delete request, with the side effects in 6.6.
- A12 Helper delegations per person with scopes, expiry and PIN; `X-Acting-For` verified on every request; audit records helper and person.
- A13 Sync endpoint (6.9).
- A14 Security tests: authorisation matrix (role x endpoint x own/other tenant x own/other person), raw-SQL RLS bypass attempts, withdrawal stops access, audit tamper detection, JWT tampering, upload abuse.

Phase 3
- A15 Webhooks: per-endpoint secret, HMAC over timestamp, nonce and body, replay window, retries with backoff, dead letter, delivery log, replay, test-fire. SSRF guard: https only, resolve and block private, link-local and metadata ranges, pin the resolved IP, no redirects.
- A16 Plans and usage: Free, Standard, Enterprise; metered API, OCR, SMS and AI calls; warning at 80%; 402 at the limit.
- A17 USSD/SMS state machine (status check, scam forward, consent withdrawal, call-me-back) and simulator API; verify code on every official message.
- A18 Appeals and complaints on the case system; user and role management with maker-checker for admin grants; jobs dashboard API; reconciliation report; impact report.

### 7.B Track B, decision intelligence (`modules/{rules,decision,matching,evals,twin,anomaly,analytics}`, `synth`)

Phase 1
- B1 Rule interpreter (6.8) with trace and property tests.
- B2 Rule versions: draft, validate, dry run, request approval, publish by a second approver, rollback, diff.
- B3 `decide()` (6.1) as a pure function with the silent-guess invariant and reason codes.
- B4 Explanations: user view from reason-code templates in English and Urdu (at most three short sentences, next step, "ask a person"); auditor trace.
- B5 Synthetic world, seeded and deterministic: 1,200+ persons with messy names, households, registry records, 1,000+ labelled historical cases including adversarial ones.
- B6 Calibrated evidence model for `p_eligible` and `p_genuine`; a `model_registry` row with data hash and metrics.

Phase 2
- B7 Threshold analysis on 1,000+ labelled cases: cost against threshold, ROC and PR, confusion matrix, auto rate, false-approve and false-reject rates, reliability diagram and ECE; stored in `eval_runs`. Cost-matrix edit API recomputes thresholds.
- B8 Name matching: Unicode normalisation, Urdu to Latin transliteration, honorific stripping, phonetic key, Jaro-Winkler and token-set scores, blocking before comparison. Bands: high plus a corroborating identifier links automatically and is logged; middle opens a duplicate-review case; low is distinct. Never merge on name alone. Merges are reversible and audited. 200+ messy fixtures.
- B9 Handoff package builder and "ask the cheapest question".
- B10 Golden tests: every ambiguous fixture routes to human or ask-more; silent-guess rate is 0.
- B11 Replay endpoint.

Phase 3
- B12 Digital Twin: replay a draft version over stored snapshots with no side effects; new approvals, rejections and handoffs; cost change; fairness slices by district, gender, age band and language; publish or discard.
- B13 Eval dashboard API: accuracy, false approve and reject, abstention, silent-guess, latency p50 and p95, cost per decision, failures, per rule version; mistakes ledger from officer overrides.
- B14 Analytics per tenant with CSV export.
- B15 Anomaly detection: IsolationForest on reuse and burst features plus deterministic shared-account, phone and device checks; "why flagged"; feeds the router as a guard.
- B16 Override feedback into `feedback_labels`; rubber-stamp detector.

### 7.C Track C, perception and language AI (`modules/{docs_ai,scam,rag,agent,guardrails,voice,memory}`)

Phase 1
- C1 Mock issuer keys served by the mock identity service; Rahat specimen card generator (fields, signed QR, SPECIMEN watermark, a layout that imitates no real card); variant generator for blur, glare, crop, edited text and swapped QR.
- C2 `check_document()` (6.4): quality gate, QR decode and Ed25519 signature check, OCR, cross-check of OCR text against the signed payload.
- C3 Scam corpus generator in English, Urdu and Roman Urdu across the six classes with hard negatives, **split by template family so test templates are unseen**; classifier; URL and sender analysis (lookalike domains, shorteners, mobile-number senders; never fetch a URL); abstain rule; `POST /v1/scam/check`.

Phase 2
- C4 Voice: `POST /v1/voice/stt` and an answer interpreter for yes/no, numbers and bands in Urdu and Roman Urdu, returning a TypedDecision. Low confidence asks again or falls back to icons.
- C5 Audio assets: a script that generates every fixed prompt, reason-code explanation and digit in Urdu, with a manifest; human recordings drop in by filename.
- C6 Forgery depth: ELA and metadata anomalies; a labelled synthetic document set; metrics including false alarms on genuine cards with glare.
- C7 Scam reports stored with redacted text and district; aggregates with k-anonymity (k at least 5); campaign clustering.
- C8 Scam checker by screenshot and by voice; "this is real, ask a person" opens a case and feeds the mistakes ledger.

Phase 3
- C9 RAG: versioned policy corpus in English and Urdu; hybrid retrieval; answers only from retrieved text with citations to document, version and section; refusal below a score threshold; groundedness test.
- C10 Agent as an explicit state machine with tools `verify_identity, fetch_registry_record, check_duplicates, evaluate_rules, request_proof, submit_payment, file_complaint`; each call authorised as the acting user; step budget; approval gate before payment; resumable from the database; every step audited.
- C11 Guardrails: input (prompt-injection patterns in OCR text, messages and questions; PII masking), output (no eligibility promises, citations must exist), action (payment approval and limits); verdicts stored; red-team suite of at least 50 attacks in three scripts.
- C12 Memory per person: preferences and progress, consent-scoped, visible and deletable, never keyed by helper.
- C13 Optional providers behind the same interfaces (T3).

### 7.D1 Track D1, citizen PWA (`frontend/src/citizen`, `frontend/src/shared`)

Phase 1
- D1.1 Tokens, pictogram set (yes, no, family, widow, disability, document, payment, a person will help, phone, warning, retry), audio player, i18n with RTL.
- D1.2 Citizen login: phone and PIN keypad with spoken digits.
- D1.3 Guided application: one question per screen, prompt plays automatically, large icon answers, progress dots, back; camera capture resized on the device to at most 300 KB; spoken retake hints.
- D1.4 Result screen with pictogram, spoken explanation, next step and "ask a person"; tracker with a status timeline.

Phase 2
- D1.5 PWA: precached shell and audio; IndexedDB autosave; outbox with per-item status; network banner; resume on another device.
- D1.6 Voice answers with read-back and icon confirm.
- D1.7 Consent centre: who has my data, what, until when; narrow; withdraw; access log.
- D1.8 Scam checker: paste, speak or screenshot; verdict with reasons and what to do; "this is real, ask a person".
- D1.9 Helper Mode: person cards, PIN switch, acting-for banner, idle lock, nothing cached across switches.

Phase 3
- D1.10 Sync conflict UI; local data encrypted with a key derived from the PIN; QR switch.
- D1.11 USSD/SMS simulator, symbol tracking code, appeals, "did you understand?" feedback.
- D1.12 Budgets in CI: citizen route at most 100 KB gzipped JS, axe clean, Slow-3G and offline Playwright runs.

### 7.D2 Track D2, staff console and proof (`frontend/src/staff`)

Phase 1
- D2.1 Staff shell: dense, tabular, keyboard-friendly; tenant switcher; role-based navigation.
- D2.2 Officer queue (sort, filters, SLA timers) and case review (handoff package, document viewer with signals, rule trace, actions with required reason).
- D2.3 Auditor decision viewer with both views side by side.

Phase 2
- D2.4 Rule editor: form builder and JSON view, validation, dry run, diff against active, request approval, second-approver publish, rollback.
- D2.5 Cost of being wrong: sliders, derived thresholds, cost curve, confusion matrix, reliability diagram.
- D2.6 Challenge Lab (section 10).
- D2.7 Audit explorer, chain verify, replay button, consent records.

Phase 3
- D2.8 Digital Twin view.
- D2.9 Scam Map: tile grid by district, type filter, trend lines, campaigns, publish a public warning, live updates.
- D2.10 Eval dashboard, analytics, mistakes ledger, impact report.
- D2.11 Admin: users and roles, API keys, webhooks with delivery log, jobs, mock service controls, plans and usage, notifications outbox, system health, `/demo` accounts page.

Charts are hand-written SVG components. No chart or map library, no third-party scripts, no web fonts (system fonts, with the device's own Urdu font).

### 7.E Integration, deploy, QA (lead)

E1 Merge loop about every 90 minutes: rebase, verify, merge, deploy, smoke test the live URL.
E2 Demo fixtures with known outcomes and downloadable specimen cards (genuine, blurry, glare, edited); reset button.
E3 Playwright end-to-end for the three hero flows.
E4 Docs: README, ARCHITECTURE, DECISIONS, EVAL_REPORT, SECURITY_REPORT, THREAT_MODEL, THIRD_PARTY, DEMO.

## 8. Timeline and gates (PKT)

| When | Phase | Gate at the end |
|---|---|---|
| Sat 11:45-12:30 | Decide, accounts, installs (`docs/KICKOFF.md` section 1) | four decisions answered |
| Sat 12:30-15:00 | **Phase 0** foundation, one session | **Gate 0**: live URL, all five demo roles log in, RLS smoke test and `npm run verify` green |
| Sat 15:00-21:00 | **Phase 1** spine, all tracks | **Gate 1**: the anchor flow completes on the live URL |
| Sat 21:00-Sun 03:00 | **Phase 2** eight challenges | **Gate 2**: all eight Challenge Lab cards pass on the live URL |
| Sun 03:00-09:00 | **Phase 3** bonus and the rest; sleep in shifts | **Gate 3**: every T2 item passes its check or is hidden |
| Sun 09:00-12:00 | Integration, bug bash, rehearsal on a real phone. **Feature freeze 10:00.** | full demo script runs twice without help |
| Sun 12:00-16:00 | README, reports, video, slides. **Code freeze 14:00.** | everything in section 13 |
| Sun 16:30 | **Submit** | |
| Sun 16:30-18:00 | Buffer | |
| Mon | Wake the host 30 minutes early, rehearse twice, Plan C ready on the laptop | |

Everyone sleeps at least four hours between Sun 01:00 and 09:00. Give agents long, well-specified tasks before sleeping.

## 9. People and sessions

A seat is one person with one Claude subscription and one machine. Details and prompts are in `docs/KICKOFF.md`.

| Seats | Allocation |
|---|---|
| 4 | Lead: Track A + merges + deploy. Second: Tracks B and C (two sessions, mostly test-verified). Third: D1 with a real phone, Urdu review, audio. Fourth: D2, Challenge Lab, README, video. |
| 3 | Lead: A + merges. Second: B and C. Third: D1 then D2. |
| 2 | First: A, then B, then C by tier. Second: D1, then D2. Expect T0, T1 and the top of T2. |
| 1 | One orchestrating session running the track agents in parallel. Expect T0 and T1. |

Only humans can do these: create accounts and keys, test on a real phone, record audio, review the Urdu wording, rehearse, record the video, submit.

**Current mode (decided Sat 21 Nov): one seat.** The lead session runs the track agents in parallel, each in its own git worktree, then merges, integrates and checks the gate. Languages are Urdu and English; no Sindhi, because nobody on the team can check it.

## 10. Demo

### Challenge Lab cards (each runs real API calls and shows requests, responses and audit ids)

1. **Cost of being wrong**: three seeded cases (clear, borderline, fraud signal) with `p_ok`, expected cost of each action, chosen route.
2. **I am not sure**: an ambiguous case lands in the officer queue with its handoff package; the silent-guess counter stays at 0.
3. **Bad data**: "Muhammed" against an existing "Mohammad" gives "possible duplicate" and a human; a missing field is asked for alone; a garbage payload returns a repairable 422.
4. **Rules that change**: publish a new version with a second approver; the identical case now gets a different outcome; the old decision still shows its version.
5. **Explain and audit**: user view against auditor trace; replay matches; chain verifies.
6. **Consent take-back**: officer reads (200); citizen withdraws; officer reads again (403); the audit shows the withdrawal and the denied attempt.
7. **Works for everyone**: QR to open the citizen flow on a phone; bundle size; offline queue.
8. **Scams and fakes**: scam, verified real message, and an ambiguous one that abstains; edited card against a card with glare; the mistakes ledger.

Security strip: cross-tenant read blocked through the API and through raw SQL, SSRF webhook target blocked, malicious upload rejected, prompt-injection document ignored, tampered audit row detected.

### Eight-minute script (a five-minute cut drops steps 5 and 7)

1. 0:00 Anchor sentence; what is real and what is simulated.
2. 0:20 Widow on a phone, Urdu audio, icon answers, one spoken answer with read-back, connection drops and work continues, blurry ID gets a spoken retake hint, good ID, submit, reconnect, synced once.
3. 2:20 A low-confidence case: "a person will check"; officer sees the handoff package and approves; the agent requests payment through the approval gate; mock payment; SMS with verify code.
4. 3:50 Auditor: two views, replay, chain verify.
5. 4:20 Admin changes the income cap; Digital Twin shows who is affected; second approver publishes; same case, new outcome; old decision unchanged.
6. 5:20 Shopkeeper pastes a fake relief SMS in Roman Urdu; classified with reasons; Scam Map updates; a real message verifies by code.
7. 6:05 Helper switches between two families with PINs; one withdraws; helper and officer are blocked at once.
8. 6:50 Challenge Lab security strip; cost sliders; eval dashboard with false alarms and silent-guess 0.

## 11. Real and simulated (goes in the README)

| Real, working code | Simulated |
|---|---|
| Auth, RBAC, RLS, consent enforcement, hash-chained audit | Identity registry (stands in for a national ID authority) |
| Rule engine, cost-based decisions, calibration, replay | Payment rail (stands in for an instant-payment system) |
| OCR, QR signature check and forgery signals, on our specimen cards | SMS, WhatsApp and email delivery (visible outbox) |
| Scam classifier and name matching, trained and tested on synthetic data | USSD gateway (simulator) |
| Urdu speech input, offline sync, webhooks, rate limits | Every person, case, message and document; billing |

Limitations to state openly: models are trained on synthetic data and real-world accuracy is unknown; `p_ok` assumes independence; Urdu speech recognition is imperfect, which is why every spoken answer is read back; other regional languages are not supported.

## 12. Risks and fallbacks

| Risk | What we do |
|---|---|
| Claude usage limits run out | Spread sessions over teammates' accounts; bulk work on Sonnet; the strongest model for Phase 0, RLS, the decision core and offline sync; check `/usage` |
| Parallel tracks collide | Disjoint directories, contracts fixed in Phase 0, one migration author, merge every 90 minutes |
| An agent reports success that is not real | Gates are checked on the live URL; the `verifier` agent runs things instead of reading code |
| Deploy fails late | Deploy in Phase 0 and after every merge; four ranked hosts; laptop + tunnel as Plan C |
| Voice fails in a noisy room | Icons always work; headset mic; pre-recorded clips through the same endpoint |
| RLS misconfiguration locks everyone out | RLS smoke test in Gate 0; the authorisation matrix test in Phase 2 |
| Judges corrupt demo data | Reset button and `seed --reset` in under a minute |
| Power or internet cut | Cloud host, phone hotspot, charged laptop with the full stack running locally |
| Time overrun | Cut rule in section 4; feature freeze 10:00, code freeze 14:00 |

## 13. Submission checklist

- [ ] Live URL up, `/demo` accounts page, prototype label in every footer
- [ ] Public GitHub repo, history inside the build window, CI green
- [ ] README: anchor sentence, setup, architecture, real and simulated table, cost numbers, model and tool choices, limitations, third-party list
- [ ] Demo video on Google Drive with link sharing set to "Anyone with the link"; opened in a private window to check
- [ ] `docs/EVAL_REPORT.md`, `docs/SECURITY_REPORT.md`, `docs/DECISIONS.md` generated from real runs
- [ ] Slides (optional): six to eight, mirroring the demo script
- [ ] No real personal data anywhere; mock-data lint green
- [ ] Submitted by 16:30 Sunday
