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
From: Track D2   To: Track B   Status: open (Phase 2, item B11)
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
From: Track D1   To: Track A (whoever builds the access log)   Status: open
What: the path and response shape of the citizen's access log (per read: who, which department or role, when, for what).
Why: D1.7 "access log". The place is reserved: `AccessLogSection` and `ACCESS_LOG_READY = false` in `frontend/src/citizen/mydata/parts.tsx`.
Until then: hidden; nothing is drawn or fetched.

## Invalid UTF-8 byte in the staff queue
From: Track D1   To: Track D2   Status: open
What: `frontend/src/staff/pages/QueuePage.tsx` has byte 0x85 (a Windows-1252 ellipsis) in `"Loading the queue…"`. It is not valid UTF-8 and shows as a replacement character. Use `...` or a real UTF-8 ellipsis.
Why: noticed while scanning the frontend sources; not D1's file.

## Status, decisions and demo notes for Phase 2 of D1
From: Track D1   To: lead   Status: open
What: tick D1.5 (outbox, encrypted local queue, statuses, banner), D1.7 (consent centre, access log reserved), D1.8 (scam checker by paste and speech; screenshot is C8); D1.6 voice answers are done for the scam checker only. ADR text is in the D1 report: the vault key from the PIN, the idle lock keeps sealed unsent work instead of wiping it, a reload asks for the PIN.
Why: STATUS.md and DECISIONS.md are the lead's files.
Until then: the rules are in `docs/DESIGN.md` (sections "Scam checker", "Consent centre", "Offline").
