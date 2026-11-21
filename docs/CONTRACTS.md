# Contracts: how to build on the foundation

Read this before writing code in any track. It tells you where things are, the rules the foundation enforces, and the shapes other tracks rely on. The OpenAPI document (`/docs`, `backend/openapi.json`) is the exact schema; this page is the map.

## Where things are

| Need | Use |
|---|---|
| Settings | `app.core.config.get_settings()` |
| A database session for a request | `db: Session = Depends(get_db)` from `app.core.deps` |
| The caller | `principal: Principal = Depends(Policy("name", roles=[...]))` from `app.core.policy` |
| A session outside a request (worker, seed, pre-auth lookup) | `app.core.db.session_scope(RlsContext(...))` or `system_session()` |
| Audit a change | `app.core.audit.write(db, tenant_id=..., action="thing.verb", ...)` |
| Record a denied attempt | `app.core.audit.write_independent(...)` (commits on its own) |
| Errors | raise `NotFound`, `Forbidden`, `Conflict`, `Unprocessable`, ... from `app.core.errors` |
| Encrypt an identifier | `app.core.crypto.encrypt_field(tenant.wrapped_dek, value)` plus `blind_index(value, scope=str(tenant.id))` |
| Mock formats | `app.core.mockdata` (`make_mock_id`, `normalise_mock_phone`, `mock_id_valid`, `mask_identifier`) |
| Redact text before logging or sending it out | `app.core.logging.redact` |
| Tables | `from app.db import models` |
| Shared shapes | `from app.contracts import ...` |

## Adding an endpoint

1. Create `backend/app/modules/<name>/router.py` with `router = APIRouter(prefix="/v1/...", tags=[...])`. It is discovered automatically; do not edit `app/main.py`.
2. Every route takes exactly one marker: `Depends(Policy("cases:review", roles=["officer"]))` or `Depends(Public("why this is open"))`. A test fails the build when a route has none.
3. Request bodies subclass `app.contracts.common.Strict`, so unknown fields are rejected.
4. Do the work in a `service.py` function that takes `db` and `principal`. Keep decisions and calculations in pure functions with DB-free tests.
5. Write an audit row for every mutation, in the same transaction.
6. **Commit explicitly** (`db.commit()`) when the work is complete. The request session rolls back anything uncommitted. Do not rely on dependency teardown to commit: the response may already have been sent.
7. Paginate with a cursor and `limit` capped at `MAX_PAGE_SIZE`. Creating POSTs accept an `Idempotency-Key`.

A role check in the policy is the first layer. Row Level Security is the second. Do both; never one instead of the other.

## Database rules

- The app connects as `rahat_app` (not the owner, no BYPASSRLS). Each transaction carries `app.role`, `app.tenant_id`, `app.user_id`, `app.person_id`. With no context a query returns nothing.
- **Tenant tables**: a row is visible only inside its tenant. Always set `tenant_id` on new rows; a wrong value is rejected by the database.
- **Person tables** (`persons`, `applications`, `documents`, `document_checks`, `memory_items`): also need `app_can_read_person(person_id)` to be true. That means: the citizen themself, a helper with a live delegation, or an officer, API client or worker whose tenant holds an active, unexpired consent. Admins and auditors do not read these tables. A withdrawn consent stops access on the next query.
- **Global tables**: `plans`, `tenants`, `users`, `sessions`. A user sees their own user and session rows, and the tenants they belong to.
- **System context** (`system_session()`) bypasses tenant checks. It exists for sign-in lookups, the job dispatcher and the seed. Each use must be narrow and obvious. A worker should run a job in the job's tenant with role `worker`, so consent still applies.
- **Append-only**: the app role can only INSERT and SELECT on `audit_log`, `audit_anchors`, `consent_events`.
- **No `RETURNING`**: ids and timestamps are generated in Python (`Base` sets `eager_defaults=False`). A fresh person row is not readable by the consent check inside the statement that inserts it, so an insert that asked for `RETURNING` would fail.
- JSON columns are not mutation-tracked. Assign a new dict or list.
- Never build SQL from strings (ruff rule S608 enforces it).
- **Schema changes go through the lead.** Put the request in `docs/REQUESTS.md`. A new tenant table calls `rls.enable_tenant_rls(op, "<table>")` in its migration; a table with a person's data also calls `rls.enable_person_rls(op, "<table>", "<column>")`. Many columns already have a `data`/`config`/`payload` JSON field for details that do not need their own column.
- **Dependencies are changed only by the lead** (lockfile conflicts across branches are expensive). Ask in `docs/REQUESTS.md`.

## Shared shapes (`backend/app/contracts/`)

| File | What |
|---|---|
| `common.py` | `Role`, `Route` (`auto`, `ask_more`, `human`), `Provenance`, statuses, `IncomeBand`, `Strict`, page sizes |
| `decision.py` | `TypedDecision[T]`, `CostMatrix` (with derived thresholds), `RuleTraceItem`, `HandoffPackage`, `Explanation`, `DecisionUserView`, `DecisionTrace`, `ReplayResult` |
| `application.py` | `FieldValue[T]`, `ApplicationFormV1`, `apply_patch` |
| `documents.py` | `DocumentCheck`, `DocumentCitizenView`, `QrResult`, `OcrResult`, `DocumentSignal` |
| `api.py` | request and response models of the spine API below |

Rules that the models enforce: an abstained `TypedDecision` cannot be routed `auto`; only `qr_signed` and `registry` values can be `verified`; an unknown field value has confidence 0.

## Spine API (final paths; stubs answer in dev until the real endpoint lands)

| Method and path | Roles | Request | Response | Owner |
|---|---|---|---|---|
| `GET /v1/me/person` | citizen, helper | | `PersonOut` | A |
| `GET /v1/programs` | any | | `ProgramOut[]` | A |
| `GET /v1/consents` | citizen, helper | | `ConsentOut[]` | A |
| `POST /v1/consents` | citizen, helper | `ConsentCreate` | `ConsentOut` | A |
| `POST /v1/consents/{id}/withdraw` | citizen, helper | | `ConsentOut` | A |
| `GET /v1/applications` | citizen, helper | | `ApplicationList` | A |
| `POST /v1/applications` | citizen, helper | `ApplicationCreate` | `ApplicationOut` | A |
| `GET /v1/applications/{id}` | citizen, helper | | `ApplicationOut` | A |
| `PATCH /v1/applications/{id}` | citizen, helper | `ApplicationPatch` | `ApplicationOut` | A |
| `POST /v1/applications/{id}/submit` | citizen, helper | | `SubmitOut` | A (calls B's `decide`) |
| `POST /v1/applications/{id}/documents` | citizen, helper | multipart `file`, `kind` | `DocumentOut` | A (calls C's `check_document`) |
| `GET /v1/notifications` | any | | `NotificationList` | A |
| `GET /v1/cases` | officer | | `CaseList` | A |
| `GET /v1/cases/{id}` | officer | | `CaseDetail` | A |
| `POST /v1/cases/{id}/actions` | officer | `CaseActionIn` | `CaseDetail` | A |
| `POST /v1/cases/{id}/notes` | officer | `CaseNoteIn` | `CaseDetail` | A |
| `GET /v1/decisions/{id}` | officer, auditor | | `{user_view, trace}` | B |

Already real: `/v1/auth/*` (login, refresh, switch, logout, me, sessions), `/v1/audit`, `/v1/audit/verify`, `/v1/system/{info,health,policies}`, `/v1/demo/accounts`, `/healthz`, `/readyz`, `/metrics`.

Stubs live in `backend/app/modules/zz_stubs`. They load only in dev and test, mark responses with `X-Rahat-Stub: 1`, and lose to any real route with the same method and path. Delete a stub when its real endpoint is merged.

Functions other tracks call (define them with these names so integration is a one-line import):

- Track B: `app.modules.decision.engine.decide(inp, rules, costs, model) -> DecisionResult` (pure; also re-exported from `decision.service`).
- Track C: `app.modules.docs_ai.service.check_document(image_bytes, kind, *, document_id) -> DocumentCheck` (pure, never raises; checks run one at a time per process). `citizen_view(check)` gives the citizen's answer and `providers()` the active providers (`ocr_rapidocr`, `ocr_tesseract`, `ocr_engine`). OCR engine order: RapidOCR, Tesseract, none. Voice `stt.transcribe` order: Gemini (`GEMINI_API_KEY`, `GEMINI_STT_MODEL`), Groq, local whisper, else 501; Gemini returns `confidence=None`, which the interpreter treats as unknown and always reads back; `audible=false` returns empty text (say it again).
- Track C: `app.modules.scam.service.classify_message(text, sender) -> TypedDecision[ScamLabel]`.

## Tests

- Fixtures in `backend/conftest.py`: `client` (TestClient), `factory` (makes isolated tenants and accounts, `factory.headers(client, account)` signs in), `database`, `app`.
- Any test that uses those fixtures is marked `db` automatically. `npm run test:fast` runs everything else in a few seconds.
- Every test creates its own tenants. Never rely on rows from another test, and never truncate.
- Put module tests in `backend/app/modules/<name>/tests/` and cross-cutting ones in `backend/tests/`.
- Test real-looking identifiers only to prove they are refused, and add `# mock-lint: allow` on that line.

## Things that surprise people

- FastAPI in this project keeps included routers lazy, so `app.routes` does not list API routes. Use `app.core.policy.describe_routes(app)`.
- Python's clock on Windows ticks about every 15 ms. Two rows created in one request can share a `created_at`; never use it alone to order.
- SQLAlchemy `text()` reads `:name` as a parameter. Pass JSON and anything with a colon as a bound value.
- The first start of the embedded database takes about 15 seconds; after that it stays running. `npm run db:stop` stops it.

## The decision pipeline: who builds what

`backend/app/contracts/engine.py` defines the shapes and lists the exact import path of every function below.

1. Track A's submit pipeline gathers evidence: the form, the stored `DocumentCheck`s, an `IdentityCheck` and a `RegistryRecord` from the mock services. It builds a `DecisionInput`.
2. Track B's `decide_and_record` reads the active rule version, the tenant's cost matrix and the active evidence model, calls the pure `decide`, stores the `decisions` row and writes the audit entry.
3. Track A applies the result. Approve leads to `request_payment`. `ask_more` sets the application to `needs_proof`. `human` opens a case with the handoff package. Every outcome sends a notification.

Until another track's function exists in your tree, import it inside the function that needs it and degrade safely when the import fails: no document check yet means "a person will check"; no engine yet means the case goes to a human. Never fake a result. Tests replace the import with a fake.

Trust rule for form fields: a client may send only provenance `tapped`, `typed` or `spoken`, and never `verified`. Only the server sets `qr_signed` or `registry`, after it has checked a signature or called the registry.

## Hooks instead of shared files

| To do this | Add this file | Do not |
|---|---|---|
| Add endpoints | `app/modules/<name>/router.py` defining `router` | edit `app/main.py` |
| Add demo data | `app/modules/<name>/seed_step.py` defining `seed(db)` (optional `ORDER`); safe to run twice | edit `app/seed.py` |
| Start or stop something with the app | `app/modules/<name>/lifecycle.py` defining `startup()` and `shutdown()`; check `get_settings().worker_enabled_effective` | edit `app/main.py` |
| Module test fixtures | `app/modules/<name>/tests/conftest.py` | edit `backend/conftest.py` |
| Run background work | `app/modules/<name>/job_handlers.py` defining `HANDLERS = {"kind": fn}` and optionally `ON_FAILURE`; enqueue with `app.modules.jobs.service.enqueue(db, *, tenant_id, kind, payload=None, person_id=None, ...)` | start threads yourself |

Demo citizens (names, mock IDs, dates of birth) come from `app.demo_accounts.demo_citizens()`. Specimen cards and the mock registry are built from it, so they always agree with the seed.

Tracking codes: `app.contracts.common.tracking_symbols(number)` gives three pictogram names from `TRACKING_SYMBOLS`.

Each test run gets its own throwaway database, so several runs at once do not disturb each other.

## Built in Phase 1, track A2 (cases, payments, notifications, jobs, integrations)

- Notification templates (`notify(..., template=...)`): `application_received`, `person_will_check`, `proof_needed`, `approved`, `rejected`, `payment_sent`, `payment_delayed`. Payload keys kept: `tracking_code`, `amount_pkr`, `rail_ref`, `proof_kind` (`rahat_id`, `income_proof`, `other`), `application_id`, `payment_id`, `case_id`. An unknown template raises `ValueError`. Every message ends with a verify code; `lookup_verify_code(code)` checks one, and `POST /v1/notifications/verify` is the public check.
- `request_payment` needs the application already in `approved` and an approved engine decision or an officer's approval. Up to the tenant's `payment_four_eyes_limit_pkr` it releases at once; above it a second officer, not the one who approved the case, must decide on `POST /v1/approvals/{id}/decide`.
- More helpers: `cases.service.proof_received`, `cases.service.reopen_for_application`, `jobs.service.cancel_for_person`, `jobs.service.run_pending` (tests), `integrations.service.submit_payment`, `send_sms`, `degradation_message(service, lang)`.
- Adapters return a status on an outage (`unavailable`), never raise. Transport is in-process in dev and test and HTTP to `MOCK_BASE_URL` elsewhere (`MOCK_TRANSPORT` overrides). Each mock service has its own key (`MOCK_*_KEY`).
- `notifications` has a `person_id` but no consent policy in the database; the API filters it. Known gap, accepted for now.

## Built in Phase 1, track B (rules and decisions)

- `decide_and_record(...)` does not commit. It raises `NotFound` with code `program_not_found` or `no_active_rules`.
- Engine values without their own column (`ask_proof`, `payment_pkr`, `rule_version_no`, `thresholds`, `p_eligible`, `p_genuine`) are in `decision.explanation["engine"]`; read them with `app.modules.decision.service.engine_extras(decision)`.
- Pass `identity=None` only when no identity check was attempted (it goes to a person). Fill `queue_days` from the live queue.
- QR payload keys the engine reads: `national_id` (or `id`, `nid`), `full_name` (or `name`), `dob`; income proof `monthly_income_pkr` (or `income_pkr`). Track C's card uses `full_name`, `national_id`, `dob`, `gender`, `district`.
- An automatic approve or reject needs a verified identity; declared values never settle a hard rule; ties in cost go to the safer action (human, then ask, then approve, then reject).
- The database refuses to change a published or retired rule version (except published to retired) and any stored decision except its `case_id` and `superseded_by` (migration 0002).

## Built in Phase 2, track B

- `app.modules.matching.service.check_duplicates(db, *, tenant_id, person_id, application_id=None) -> DuplicateEvidence | None`, called by the pipeline where the engine decides. Links are stored records, never merged rows; officers link, mark distinct or unlink with a reason.
- Policy changes ship as rule parameters in a new version, so old decisions replay exactly (`stale_income_settles_below`, `identity_partial_min_name_score`).
- Endpoints: `/v1/evals/*` (analysis, what-if, runs, summary, names), `/v1/cost-matrix`, `/v1/decisions` (list) and `/{id}/replay`, `/v1/duplicates/*`, `/v1/matching/compare`, `/v1/twin/runs/*`.

## Built in Phase 2, track A3 (keys, limits, security)

- `Policy(name, roles, api_scopes=[...], cost=n)` admits API keys by scope only; `Cost(n)` sets a route's rate-limit cost; `Public(reason)` routes are rate limited too. `get_db` depends on `get_credential`; `get_claims` refuses API keys. `Principal.api_key` and `Principal.scopes` are new.
- A new route is covered by the authorisation matrix in `backend/tests/security` automatically.
- Look objects up by id **and** tenant, even though RLS also filters: two lookups did not, and the suite showed they relied on RLS alone.

## Serverless hosting (Vercel) settings

All default to today's behaviour. See `deploy/vercel/README.md` and DECISIONS 19.

- `JOBS_MODE=thread|inline`: `inline` starts no worker thread (`settings.job_thread_enabled` is false). `jobs.service.enqueue` marks the request (`core.context.note_job_enqueued`); the middleware then runs `jobs.inline.drain()` before the final response byte. Handlers must not assume a long-lived process.
- `GET /v1/admin/jobs/drain`: `Public` route guarded by `Authorization: Bearer $CRON_SECRET`; 404 while `CRON_SECRET` is unset.
- `MOCKS_IN_PROCESS=true`: `integrations.settings.transport_effective()` returns `inprocess` unless `MOCK_TRANSPORT` says otherwise. Mock state (failure injection, SMS outbox, payment ledger) lives in each instance's memory.
- `CLIENT_IP_HEADER`: when set, `current_client_ip()` is the first address of that header. Set it only where the platform overwrites the header.
- `STARTUP_WARMUP=false`: only the `jobs` lifecycle hook runs at start; other hooks (evidence model, OCR, corpus, scam model) load on first use.

## Built in Phase 3, WP-B (agent with an approval gate)

- Endpoints (all under `/v1`): `POST /cases/{case_id}/agent/runs` (officer; starts a run, read steps execute, the action waits; starting again while a run waits returns that run with `reused: true`), `GET /cases/{case_id}/agent/runs`, `GET /agent/runs/{agent_run_id}` (officer, admin, auditor; admin and auditor get no case text: no rationale, no read-step output), `POST /agent/steps/{step_id}/approve` and `/reject` (officer; body `{reason}`, 5 to 1000 characters).
- A run is `agent_runs` plus `agent_steps` (no migration). `agent_runs.goal` is `case_review:<case_id>`; `state` holds `case_id`, `planner {type, model_version, fallback_reason}`, `decision` (a `TypedDecision`: `choice`, `confidence`, `abstained`, `route` always `human`), `rationale`, `flags`, `outcome`, `phase`. Step `input` is `{args, rationale, key}`; step `output` is the tool's typed output, plus `_approval` once an officer decided. Step status: `done | waiting_approval | rejected | failed | blocked`.
- Tools. Read (no approval): `get_case`, `get_handoff`, `explain_decision`, `check_rules`, `find_duplicates` (stored candidates only), `search_policy` (RAG, cited, refuses when weak). Action (always `waiting_approval`): `request_proof {proof_kind}`, `send_template_message {template: person_will_check|proof_needed}`, `approve_and_pay {}` (no amount, no payee: the amount is the rule version's), `reject_with_reason {reason_code, rule_id}`, `escalate {reason_code}`. Inputs forbid extra fields. Actions run through `cases.service.act` and `notifications.service.notify` as the approving officer, so the case state machine, `request_payment` (idempotent, four-eyes above the tenant limit) and the audit rows are the officer's own.
- Action guard: `app.modules.guardrails.action_guard.check_action(ActionContext) -> GuardVerdict` (pure; codes in its docstring). Checked when a step is proposed and again, with the case read afresh, when it is approved. A refusal at approval commits a `blocked` step, an `agent.step_blocked` and a `guardrail.verdict` audit row, and answers 409 `agent_action_blocked` with the first code as `code` and all codes in `codes` (a refusal only about who approves answers 403 and leaves the step waiting).
- Settings (module-local, `agent/settings.py`): `AGENT_PLANNER=local|gemini` (default `local`), `GEMINI_API_KEY`, `GEMINI_AGENT_MODEL` (default `gemini-3.1-flash-lite`), `GEMINI_AGENT_THINKING` (`minimal`), `AGENT_PLANNER_TIMEOUT_S`, `AGENT_STEP_BUDGET` (12). `/v1/system/health` lists `agent_planner`, `agent_planner_requested`, `agent_gemini`, `agent_planner_model` and `guardrails_action` under `providers.guardrails`.
- Audit actions: `agent.run_started`, `agent.step_executed` (reads), `agent.step_proposed`, `agent.step_approved`, `agent.step_done`, `agent.step_rejected`, `agent.step_blocked`, `agent.step_failed`, plus `guardrail.verdict` for every refusal and every flagged piece of case text.
- Security suite fixtures: `agent_run_id` and `step_id` in `tests/security/support.py`.

## Built in Phase 3, WP-A (webhooks, plans, appeals)

**Webhooks** (`modules/webhooks`, admin only, `/v1/admin/webhooks`)
- Raise an event with one call from any service, in the caller's transaction: `from app.modules.webhooks.emit import emit; emit(db, tenant_id, "case.opened", {"case_id": case.id, "status": "open"})`. It writes `webhook_deliveries` rows and queues `webhook.deliver` jobs (outbox), never sends, never raises, and keeps only ids and status words (`rules.ALLOWED_KEYS`, plain tokens only), so no name, phone or national ID can leave. Add a new event name to `rules.EVENTS` first.
- Events and where they are raised: `case.opened` (`cases.open_case`, new cases only), `case.resolved` (`cases.act` approve or reject, `cases.resolve_with_outcome`), `decision.made` (submit pipeline after the engine decides, `cases.act` on an application review, appeal decision with `route: appeal`), `payment.sent` and `payment.settled` (`payments.release_payment`; the mock rail takes and confirms in one call, so both fire together), `appeal.opened` and `appeal.resolved` (`appeals.service`). `webhook.test` is sent by the Test button.
- A delivery is `POST` JSON `{id, event, created_at, data}` with `X-Rahat-Event`, `X-Rahat-Delivery`, `X-Rahat-Timestamp`, `X-Rahat-Signature: sha256=HMAC_SHA256(secret, timestamp + "." + body)` (`core/webhook_signing.py`) and `X-Rahat-Webhook`. One job is one attempt. A failure sets `response_code`, `last_error`, `next_attempt_at` (30 s doubling, equal jitter, capped at 1 h) and queues the next job; after 6 attempts the delivery is `dead` and `webhook.delivery_dead` is audited. A refused target is dead at once.
- SSRF: https only (plain http only in dev and test), no user name in the URL, the host is resolved at save time and again at send time, every address must be public (private, loopback, link-local including 169.254.169.254, multicast, reserved, CGNAT, IPv4 hidden in IPv6 are refused), the request connects to the checked address with the host name kept for `Host` and TLS, redirects are never followed, 5 s timeout, the answer body is not kept. The one non-public target is `mock://receiver`.
- Mock receiver: `app/mocks/receiver.py` (`PUT /webhooks/config/{id}`, `POST /webhooks/receive`, `GET /webhooks/received`), key `MOCK_WEBHOOK_KEY`. It verifies the signature and keeps what it got; `PUT config {"down": true}` or `{"fail_next": n}` shows retries. The platform tells it the secret before each delivery, so it works after a restart. State is per instance (`MOCKS_IN_PROCESS`).
- API: `GET/POST /v1/admin/webhooks`, `GET /events`, `GET /mock-receiver/received`, `GET/PATCH/DELETE /{id}`, `POST /{id}/rotate-secret`, `POST /{id}/test`, `GET /{id}/deliveries` (cursor), `POST /{id}/deliveries/{delivery_id}/redeliver` (a new delivery). The signing secret is in the create and rotate responses only; it is stored encrypted with the department key.

**Plans and usage** (`modules/plans`)
- `plans.service.consume(db, tenant_id, metric)` raises `PlanLimitReached` (429, code `plan_limit_reached`, `metric`, `limit`, `used`, `resets_at`, `Retry-After`); `try_consume` returns False instead. The increment is one atomic upsert (`ON CONFLICT DO UPDATE ... WHERE count + n <= limit`), in the caller's transaction. No plan, or a metric the plan does not list, means unlimited (still counted).
- Metered at: `applications` (`applications.create_core`, refused with 429 at creation; an idempotent replay is not counted), `ocr` (`documents.upload`: over the limit the photo is kept and left for a person, nothing is lost), `sms` (`notifications.notify`: over the limit the message stays in the app), `ai_calls` (`POST /v1/voice/interpret` and `/stt`, counted in `people.context.acting_person`; 429 over the limit, typing still works), `api_calls` (`core.policy` refuses a key over its limit; `core.apikeys.record_use` counts). Not metered yet: `/v1/ask` (public, no department) and the agent.
- `GET /v1/admin/usage` (admin): this month with `limit`, `used`, `percent_used`, `reached`, `resets_at`, and the five months before. `GET /v1/plans` is public. Plans `free`, `standard`, `government` are seeded; the demo departments are on `government`. There is no platform-admin role, so a department's plan changes by seed or `plans.service.set_tenant_plan` only.

**Appeals and complaints** (`modules/appeals`)
- Citizen or helper (`apply` scope to file, `track` to read): `POST /v1/appeals {application_id, reason}` (`Idempotency-Key`), `GET /v1/me/appeals`, `POST /v1/complaints {category, details?}` (`Idempotency-Key`), `GET /v1/me/complaints`. Responses carry `status`, `status_key` and a `message` with keyed `en` and `ur` text, never the officer's notes.
- Officer: `GET /v1/appeals` (also auditor, no personal data), `GET /v1/appeals/{id}` (`can_decide`), `POST /v1/appeals/{id}/decide {outcome: upheld|overturned, reason}`, `GET /v1/complaints`, `POST /v1/complaints/{case_id}/resolve {outcome: resolved|dismissed, reason}`. The generic `POST /v1/cases/{id}/actions` approve or reject answers 409 `use_dedicated_endpoint` for these cases.
- Rules (`appeals/rules.py`): only a `rejected` application, within 30 days of the decision, one open appeal at a time, one decided appeal per decision. A different officer decides: nobody who reviewed or second-approved the application's earlier cases (`appeal_same_officer`, 403, audited in its own transaction). Overturned: application `approved`, `appeal_overturned` message, `payments.request_payment` (idempotent, four-eyes above the limit; the appeal officer cannot release it). Upheld: `appeal_upheld` message.
- A complaint is a case: `complaint`, or `scam_review` for category `scam_attempt` (priority 20), with `opened_reason` `complaint_<category>`. Officers read an appeal's application and a complaint's person through consent, so withdrawn consent gives 403 `consent_required` on the next request.
- New message templates `appeal_received`, `appeal_upheld`, `appeal_overturned`, `complaint_received`, `complaint_resolved`, `complaint_closed` are in `notifications.templates.EXTRA_TEMPLATES` (not `TEMPLATES`, so the frozen scam corpus is unchanged).
