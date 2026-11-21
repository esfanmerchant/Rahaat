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


## Feature-phone channel (A17, `modules/ussd`)

Most relief beneficiaries have no smartphone. The same platform answers on a feature phone: a USSD menu and SMS commands. Both are **simulated** (there is no real aggregator); the shapes are the ones a real aggregator uses.

**Endpoints**

| Route | Who | What |
|---|---|---|
| `POST /v1/channels/ussd` | API key with scope `channels:ussd` | `{session_id, msisdn, text, service_code}` as JSON; `text` is the `*`-joined input history, empty on the first dial. Answers `text/plain` that starts with `CON ` (the session goes on) or `END `. |
| `POST /v1/channels/sms/inbound` | API key with scope `channels:sms` | `{msisdn, text, message_id?}`. Answers `{accepted, command, reply_sent}`; the reply goes out as an SMS. The same `message_id` is answered once. |
| `POST /v1/demo/ussd`, `POST /v1/demo/sms`, `GET /v1/demo/sms`, `GET /v1/demo/ussd/personas` | public, `DEMO_MODE` only (404 otherwise) | The simulator relay (below). |

**Auth design.** A channel key can carry the line but proves nothing about the person. Both scopes are `personal_data`, so a new key waits for a second admin like any key that can read personal data. A signed-in user, even an officer, cannot call the channel routes (the role list is empty). The simulator in the browser never holds a key: it calls the demo relay, which runs the same service code (`ussd.service.handle_ussd` and `handle_sms`) with a server-side demo channel, in the demo department, for mock numbers only, rate limited per network, and answering 404 unless `DEMO_MODE` is on (like `/v1/demo/accounts`). A key in the bundle would be usable by anyone who opened the page; this way there is nothing to steal. The relay lists the demo numbers and their latest tracking code for the presenter; that is demo-only data.

**What the person must prove** (the msisdn is the claim; the code or PIN is the proof)

- Only mock numbers are accepted (`0999-NNNNNNN` or `+92 999NNNNNNN`). A real-looking number gets `END This prototype accepts only mock numbers.`, one denied audit row and nothing stored. Sessions keep a blind index of the number, never the number.
- **Status**: the tracking code (`R-12345`, typed as 12345) together with the phone. The lookup runs as that citizen (RLS context `citizen` with their person id), so another person's code, a wrong code and an unregistered phone all give the same "Not found". At most 6 lookups a minute per phone; three wrong tries end the session. The answer is the status line and the three symbol names, nothing else (no name, amount or reason).
- **Check a message**: the 6-character verify code (`notifications.lookup_verify_code`). Verify codes have letters; a plain keypad types digits in USSD unless the handset allows letters (the simulator has multi-tap after `#`). SMS `VERIFY` has no such limit.
- **Stop sharing my data**: the PIN. It is checked like a sign-in (always one hash verification, the same failure counters and account lockout as `/v1/auth/login`, a per-phone bucket of 5 tries a minute that also covers unregistered numbers), then `consent.service.withdraw` runs for every active consent, so the database stops officer, helper and API-key reads on the next query. A PIN is never logged, audited or stored.
- **Talk to a person**: a `complaint` case with `opened_reason=callback_requested` and a handoff note (`guards: ["channel:ussd", "callback"]`), one open case per person. An unregistered number gets the same words ("If this number is registered, a person will call you") and no case.
- **Free text by SMS** that is not a command is checked with `scam.service.classify_message`; a scam label gets a warning, anything else gets HELP. The text is not stored.

**Menu** (a pure state machine, `ussd/menu.py`; 0 goes back one screen, 00 goes to the main menu; a session ends after 3 minutes)

```
lang          1 English   2 Roman Urdu     (Roman Urdu is Urdu in Latin letters: feature phones rarely draw Urdu script)
  menu        1 Check my application  -> status_ask  -> status_result   (typing digits on a result checks another)
              2 Check a message       -> verify_ask  -> verify_result
              3 Stop sharing my data  -> stop_ask (PIN) -> END
              4 Talk to a person      -> callback_confirm (1 yes) -> END
```

Every screen is 182 characters or less and every SMS reply fits one 160-character message with its verify code; both limits are tests (`ussd/tests/test_menu_unit.py`). Citizen text is keyed in `ussd/texts.py`, in English and Roman Urdu, at most three short sentences. Replies are sent with `notifications.service.send_reply`, which adds a verify code, so a reply can itself be checked with option 2 or `VERIFY`. `notifications.templates` now knows the language `ru` (it falls back to English text; the channel supplies its own).

**Audit.** Every action writes a row whose `details.channel` is `ussd` or `sms` and `details.phone_ref` is the first 12 characters of the blind index: `channel.status_checked`, `channel.message_checked`, `channel.consent_withdrawn` (plus the consent service's own `consent.withdrawn`), `channel.consent_stop_refused` (denied, in its own committed transaction), `channel.callback_requested`, `channel.message_unrecognised`, `channel.refused`. Rate-limit refusals are not audited, so a flood cannot grow the chain.

**Sessions.** `ussd_sessions` rows (`session_key` is a blind index of the aggregator's session id, `msisdn_hash`, `state`, `data`) carry the menu state, the step count and the last reply, so a repeated request (aggregators retry) gets the same answer and no second step. A session id is bound to the phone that opened it. Rows older than 10 minutes are deleted when a new session starts.

**Simulator** `/ussd` (`frontend/src/ussd/`, lazy chunk `ussd`, excluded from the citizen budget and from the PWA precache): an SVG and CSS handset with a lit LCD, working keypad (multi-tap letters after `#`), keyboard input, a 3-minute session bar, the SMS thread of the chosen number and a persona selector (Zainab, Aslam). Option 3 in the simulator really withdraws consent for the demo person.
