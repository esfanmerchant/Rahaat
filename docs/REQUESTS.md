# Requests to another owner

Need a change outside the directories you own (a contract, a table or column, a dependency, a shared component)? Add it here and tell the lead. Do not make the change yourself.

Format:

```
## <short title>
From: Track <letter>   To: lead | Track <letter>   Status: open | done | declined
What: the exact change (file, field, type, default)
Why: what it unblocks
Until then: what you are doing instead
```

---

## Case priority direction in the officer queue
From: lead   To: Track D2   Status: open
What: `Case.priority` is 0 for the most urgent (see `app/db/models/casework.py`). The queue sorts higher numbers first. Sort ascending by default.
Why: urgent cases must be at the top.
Until then: fixed by the lead when merging D2 with the real cases API.

## Server-side filters, sorting and paging for the case list
From: Track D2   To: Track A (cases)   Status: open
What: `GET /v1/cases` query parameters for status, kind, assignee, sort and cursor; and the assignee's display name in `CaseSummary`.
Why: the queue filters in the browser today and cannot page.
Until then: client-side filtering over one page.

## Decision list and replay
From: Track D2   To: Track B   Status: done (B2: GET /v1/decisions, POST /v1/decisions/{id}/replay)
What: `GET /v1/decisions` (auditor, paged) and `POST /v1/decisions/{id}/replay` returning `ReplayResult`; a named response model for `GET /v1/decisions/{id}` instead of a map.
Why: the decision viewer needs a list and a replay button.
Until then: the viewer opens a decision by id and says replay is not available.

## Response fields with defaults should be required in the generated client
From: Track D2   To: lead   Status: open
What: make output schemas list fields that have defaults as required (Pydantic `json_schema_serialization_defaults_required=True` on response models), then regenerate the client.
Why: the client marks always-present fields as optional, so the screens are full of `?? []`.
Until then: guards in the staff code.

## Idempotency-Key on document upload
From: Track D1   To: Track A   Status: open
What: `POST /v1/applications/{id}/documents` should honour the `Idempotency-Key` header the citizen app already sends: keep the key with the document, and a repeat with the same key returns the first document and its check.
Why: a photo whose response was lost must never be stored twice (offline outbox, "sync later without duplicating data").
Until then: the outbox counts the documents of that kind before the first try and, after a lost response, looks for the photo on the server before sending it again (`sendUpload` in `frontend/src/citizen/apply/flow.ts`).

## Batched sync for the outbox
From: Track D1   To: Track A (A13)   Status: open
What: when `POST /v1/sync` lands, per-op results `applied | duplicate | conflict{fields, server_value} | rejected{reason}`, with the application's new version on an applied patch, for the kinds consent, create, patch and submit (photos stay multipart on the documents endpoint).
Why: the outbox sends through a small `Transport` (`setTransport` in `frontend/src/citizen/apply/flow.ts`); switching to the batch is one file.
Until then: REST calls, one at a time, with the same idempotency guarantees.

## "Who looked at my data" for the consent centre
From: Track D1   To: Track A (whoever builds the access log)   Status: done (GET /v1/me/access-log is in use)
What: the path and response shape of the citizen's access log (per read: who, which department or role, when, for what).
Why: D1.7 "access log". The place is reserved: `AccessLogSection` and `ACCESS_LOG_READY = false` in `frontend/src/citizen/mydata/parts.tsx`.
Until then: hidden; nothing is drawn or fetched. Built: `frontend/src/citizen/mydata/MoreData.tsx`.

## Invalid UTF-8 byte in the staff queue
From: Track D1   To: Track D2   Status: open
What: `frontend/src/staff/pages/QueuePage.tsx` has byte 0x85 (a Windows-1252 ellipsis) in `"Loading the queue…"`. It is not valid UTF-8 and shows as a replacement character. Use `...` or a real UTF-8 ellipsis.
Why: noticed while scanning the frontend sources; not D1's file.

## Status, decisions and demo notes for Phase 2 of D1
From: Track D1   To: lead   Status: open
What: tick D1.5 (outbox, encrypted local queue, statuses, banner), D1.7 (consent centre, access log reserved), D1.8 (scam checker by paste and speech; screenshot is C8); D1.6 voice answers are done for the scam checker only. ADR text is in the D1 report: the vault key from the PIN, the idle lock keeps sealed unsent work instead of wiping it, a reload asks for the PIN.
Why: STATUS.md and DECISIONS.md are the lead's files.
Until then: the rules are in `docs/DESIGN.md` (sections "Scam checker", "Consent centre", "Offline").

## Idempotency-Key on the citizen's data and helper POSTs
From: Track D1   To: Lead (OpenAPI contract) / Track A   Status: open
What: declare the optional `Idempotency-Key` header on `POST /v1/me/corrections`, `POST /v1/me/erasure-request` and `POST /v1/me/helpers`, and make a repeat with the same key return the first result (CLAUDE.md: creating POSTs take one).
Why: the typed client only sends headers the schema names, so these three go without a key today. After a lost response a retry could create a second request (erasure and correction already answer 409 for an open duplicate, which the screens show as "you already asked").
Until then: the screens treat 409 as "already asked".

## A new family switch should end the previous ticket
From: Track D1   To: Track A (helpers)   Status: done (already enforced: a ticket must match the newest switch row of its session, so a second switch ends the first at once; covered by `helpers/tests/test_helpers_api.py::test_a_ticket_belongs_to_one_session_and_one_family`)
What: confirm that `POST /v1/helper/switch` for a second family makes the first family's ticket useless at once (not only `/switch/end`), and that a ticket is bound to the person it names.
Why: the app ends the ticket when the helper changes family, but `/switch/end` cannot be sent offline. The phone drops the ticket from memory anyway, so it is only exposed if copied out of memory; one live ticket per helper session would remove the question.
Until then: the app drops the ticket from memory first and calls `/switch/end` best effort.

## Access log: collapse a helper's repeated reads
From: Track D1   To: Track A (consent)   Status: open
What: one helper session opening a family writes a `person.data_viewed` row per list and per read (`applications_list`, `application`, ...). The citizen's log then shows the same helper "looked at your information" many times in a minute.
Why: a family is better served by one line, "Rubina helped you on 21 November", than twenty identical rows; the demo log gets long fast.
Until then: every row is shown as the server sends it.

## Staff lookup of a case by tracking code, and a count for the live pulse
From: Track D2   To: Track A (cases)   Status: open
What: (1) `GET /v1/cases?q=` matching the application's tracking code (`R-12345`), the case id prefix and the subject name; `CaseSummary` would carry `tracking_code`. (2) optional `total` (an exact count) on the case, decision, payment and scam-report lists, or a small `GET /v1/stats/today`.
Why: the command palette promises "open a case by id or tracking code", but staff cannot see a tracking code today, so it matches id, application id and name from the first 100 cases only. The pulse strip counts one page of up to 100 rows and shows a plus sign beyond that.
Until then: the palette and pulse use the existing list endpoints and say so in their hints.

## Person-level security for appeals
From: Track A (WP-A)   To: Lead (models and migrations)   Status: declined (Sat 21 Nov, 23:10; tried as migration 0009 and withdrawn)
Lead's answer: with the person policy an officer's read after a consent withdrawal becomes a silent 404 the service cannot see, so the denial is no longer audited and the list cannot show the appeal without its code; C06 requires blocked attempts on record. Both tests that encode this failed. The service-level check (read through the consent-checked application, 403 `consent_required`, audited) stays the control, with tenant RLS underneath; raw SQL as `rahat_app` is already out of scope (DECISIONS 5).
What: `appeals` has a `person_id` but only the tenant policy. Add `rls.enable_person_rls(op, "appeals", "person_id")` in a new migration (as for `applications`).
Why: appeals name a person's application and the citizen's reason. The service already reads the application through its own consent-checked policy and filters by person, but the database should say the same.
Until then: officers reach an appeal only through the appeals service, which reads the person's application under Row Level Security and answers 403 `consent_required` without consent; citizens see only their own rows.

## Add the new message templates to the scam checker
From: Track A (WP-A)   To: Track C (scam)   Status: open
What: `notifications.templates.EXTRA_TEMPLATES` (`appeal_received`, `appeal_upheld`, `appeal_overturned`, `complaint_received`, `complaint_resolved`, `complaint_closed`) are real Rahat messages. Fold them into `scam/signals.py::_template_patterns` and `scam/corpus.py::_program_messages`, regenerate the corpus (`uv run python -m app.modules.scam.corpus`), then merge the dict into `TEMPLATES`.
Why: a citizen who pastes an official appeal message into the scam checker should see it recognised as a program message. They were kept out of `TEMPLATES` because the committed corpus test (`test_the_committed_corpus_is_exactly_what_the_seeded_generator_writes`) would fail.
Until then: such a message is judged by the classifier like any unknown message; its verify code still checks out at `POST /v1/notifications/verify`.

## Meter the rules assistant and the agent as `ai_calls`
From: Track A (WP-A)   To: Track C (rag, agent)   Status: open
What: call `app.modules.plans.service.consume_committed(principal.rls(), principal.tenant_id, "ai_calls")` at the top of `rag.service.ask` when a principal is present, and in each agent run. It raises the 429 `plan_limit_reached` problem. Voice routes are already metered in `people.context.acting_person`.
Why: `POST /v1/ask` is public and takes no department session, so the platform cannot meter it without touching the rag module.
Until then: only speech and API keys count against `ai_calls` and `api_calls`.

## Staff3 (Command Center)
- **District on application list rows** (Track A): the Overview hex map can colour provinces by scam reports only. A staff endpoint that returns applications or cases with a `district` (or counts of applications per district) would let it show where applications come from. Until then it says so on screen rather than guessing.

## Paid application: the amount and the verify code as fields
From: Track D1   To: Track A (cases, payments)   Status: open
What: `ApplicationOut` (and `ApplicationSummary`) would carry, once paid, `payment: { amount_pkr, paid_at, verify_code }` (null before). Today the citizen app reads `GET /v1/notifications`, takes the `payment_sent` message, finds its `verify_code` and reads the amount as the first number in the message text.
Why: parsing a sentence is fragile (a changed template breaks the "Paid" card on home) and the citizen cannot call `/v1/payments`.
Until then: the Paid card shows the amount only when that number is found, never a guessed one.

## A `callback` case kind, regenerated OpenAPI, and an ADR for the feature-phone channel
From: Track A (A17)   To: Lead   Status: open
What: (1) add `"callback"` to `CaseKind` in `contracts/common.py` (SLA about 24 hours, like `correction`) so a call-back request from USSD or SMS is not filed as a `complaint`; the code uses `kind="complaint"` with `opened_reason="callback_requested"` today and switches in one line. (2) Regenerate `backend/openapi.json` and the typed client (`npm run gen:api`): the new routes `/v1/channels/*`, `/v1/demo/ussd*` and `/v1/demo/sms` are not in it yet (the simulator uses plain `fetch` for the demo relay, so nothing is blocked). (3) An ADR in `docs/DECISIONS.md`: the simulator calls a demo-mode relay instead of holding a channel key (a key in the bundle would be usable by anyone); Roman Urdu is the regional language on feature phones, which rarely draw Urdu script.
Why: the case-kind list, the OpenAPI file and DECISIONS are the lead's.
Until then: callbacks show in the officer queue as `complaint` with reason `callback_requested`.

## Anomaly guard in the submit pipeline, a scan trigger and a case SLA
From: Track B (WP-D)   To: Track A (applications pipeline, cases)   Status: open
What: (1) In `applications/pipeline.py`, before `decide`, set `inp.anomaly = anomaly.service.anomaly_evidence_for(db, tenant_id, application.id)` so an application named in an open anomaly case is held for a person by the engine's existing `anomaly_flag` guard (it returns `None` when nothing is flagged). (2) After an application is submitted, call `anomaly.service.enqueue_scan(db, tenant_id, trigger="event")`; it reuses a waiting job, so a burst of submissions makes one scan. Until then the scan runs when an admin or officer presses "Run detection now". (3) Add `"anomaly_review": 24` to `SLA_HOURS` in `cases/rules.py` (it defaults to 48 hours today).
Why: the detectors only help a decision if the guard sees them, and a ring is easiest to stop before the second payment.
Until then: anomaly cases are reviewed on their own; no decision is held because of them.

## Regenerate the API client after WP-D merges
From: Track B (WP-D)   To: Lead   Status: open
What: run `npm run gen:api` once the branch is merged. `CaseKind` gained `anomaly_review` and three routes were added (`/v1/anomalies`, `/v1/anomalies/run`, `/v1/admin/impact`). The WP-D pages use the types in `frontend/src/staff/pages/wpdApi.ts` so that `schema.d.ts` (shared, generated) was not edited on this branch.

## Staff screens for WP-A and WP-B (WP-E)
From: Track D2 (WP-E)   To: Track A (appeals), Lead (contracts, agent schemas)   Status: open
- **Payment in the appeal decision response** (Track A): `POST /v1/appeals/{id}/decide` returns `AppealStaffDetail`, which has no payment fields. After an overturn the staff screen has to read `GET /v1/payments` and match by `application_id` to show the payment status. Please add `payment: { id, amount_pkr, status } | null` to the decide response (null unless overturned).
- **Duplicate schema name `ApprovalOut`** (Lead): `agent/schemas.py::ApprovalOut` collides with `contracts/api.py::ApprovalOut`; the generated client now names the payment one `app__contracts__api__ApprovalOut`. Rename the agent one (for example `AgentStepApprovalOut`) so both read well in the client.
- **Guard codes on a 409** (Lead): `agent_action_blocked` returns all codes in a `codes` array, but `Problem` in the client has no such field, so the screen reads it through a cast. Declare `codes` in the problem schema for this route (or document it in `responses`).
- **Failure injection for webhook retries** (Track A): the mock receiver's `fail_next` and `down` can only be set in process, so the Webhooks screen cannot show a failed or dead delivery in a live demo. Expose them on the admin mock controls (`POST /v1/admin/mocks`, service `webhook`) so the retry and dead states can be shown to judges.
- **Reading a run as admin or auditor** (Track A/C): they may read runs, but only by run id (`GET /v1/agent/runs/{id}`); the case page is officer-only. The staff console links to `/staff/agent-runs/:id` from the audit log. A list endpoint (`GET /v1/agent/runs`, newest first) would let them browse.

