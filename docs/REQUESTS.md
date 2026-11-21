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

## Staff3 (Command Center)
- **District on application list rows** (Track A): the Overview hex map can colour provinces by scam reports only. A staff endpoint that returns applications or cases with a `district` (or counts of applications per district) would let it show where applications come from. Until then it says so on screen rather than guessing.
