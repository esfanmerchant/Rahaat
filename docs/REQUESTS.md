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

(no requests yet)

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
