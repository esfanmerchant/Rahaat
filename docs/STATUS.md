# Status

Tick an item only after you ran it and saw it work. Item ids match PLAN section 7. `SIMULATED` marks something that needs a real external party. `HIDDEN` marks a feature kept behind a flag because it is not demo-proof.

Last updated: Sat 21 Nov 2026, 14:50 PKT, by the lead session. **Gate 0 passed.** Phase 1 is in progress: track agents are working in the worktrees under `.wt/`.

## Phase 0: foundation

- [x] F1 Repo hygiene: `.gitignore`, `.gitattributes` (LF), `.editorconfig`, `.env.example`, README draft with the prototype label
- [x] F2 Backend scaffold: app factory, settings, JSON logs with request ids and redaction, RFC 7807 errors, `/healthz`, `/readyz`, `/metrics`, security headers, body limit
- [x] F3 54 tables, one migration (up, down, up verified on a clean database), roles, grants, RLS on every table, `app_can_read_person`
- [x] F4 Auth: email + password, mock phone + PIN, pinned HS256 with key id, session-bound tokens, refresh rotation with reuse detection, lockout, tenant switch
- [x] F5 Policy registry; test fails on an undeclared route
- [x] F6 Audit writer with hash chain, list and verify endpoints, tamper tests
- [x] F7 Contracts package, `docs/CONTRACTS.md`, dev-only stubs for the spine API
- [x] F8 Seed: two departments, eleven demo accounts in all five roles, Rahat program, rule version 1; idempotent, with `--reset` and `--if-empty`
- [x] F9 Frontend scaffold: Vite + Preact + Tailwind PWA, citizen and staff shells, `/demo`, i18n (en, ur; Sindhi falls back to Urdu), typed client generated from OpenAPI, working sign-in for all roles; citizen JS 28.4 KB gzipped (budget 100)
- [x] F10 Root npm scripts
- [x] F11 CI on GitHub Actions is green: backend tests on Linux against a Postgres service, frontend build and budget, mock-data lint, secret scan, Docker image build
- [x] F12 Live on this PC (`npm run live:start`): a pinned release worktree, its own embedded database, generated secrets, the API on 127.0.0.1:8080, and a Cloudflare quick tunnel (`npm run live:status` prints the URL). The Docker image also builds in CI but has not been run. **The quick-tunnel URL changes when the tunnel restarts**: switch to Tailscale Funnel for a stable URL before submitting.

**Gate 0 passed** on Sat 21 Nov, 14:00. Through the public URL: all 11 demo accounts signed in (admin, officer, auditor, helper, citizen, in both departments); `/healthz` and `/readyz` 200; the citizen, staff, demo and docs pages load; HSTS, CSP, `nosniff` and `DENY` framing headers present; refresh cookie HttpOnly, Secure, SameSite=Lax; dev stubs absent (404); audit chain verifies. Code is on https://github.com/esfanmerchant/Rahaat and CI is green.

Verified locally on Sat 21 Nov, 12:57:
- `npm run verify` green: ruff, mypy, frontend type check, 71 backend tests, frontend build, bundle budget, mock-data lint.
- Migration up, down, up on a clean database: 54 tables with RLS, 67 policies, runtime role without superuser or BYPASSRLS, audit log INSERT and SELECT only.
- Running server: sign-in as officer, citizen (PIN) and auditor; officer blocked from the audit log and the attempt recorded; hash chain verifies; no personal data in logs.
- Demo-mode rehearsal through `deploy/start.sh` with generated secrets: 18 routes, 0 stubs, 0 undeclared; refresh cookie is HttpOnly, Secure, SameSite=Lax; real-looking phone numbers refused.
- Frontend flows in headless Chrome at phone width under the strict CSP (run by the frontend agent): citizen and staff sign-in, wrong-password errors, session restore after reload, sign-out, tenant switch, role-denied page, `/demo` one-click sign-in.

Verified in CI on Sat 21 Nov, 13:30: all five jobs green on three pushes, including the first real Docker build and the 71 backend tests against a Postgres that requires a password for the runtime role.

Not verified: any deployed host, running the built image, a real phone, slow or offline network, the service worker in a browser, screen readers, and the Urdu wording by a native speaker. Tesseract is not installed on this machine, so OCR cannot run here yet (CI installs it).

## Phase 1: the spine (T0)

Track A
- [x] A1 Persons, person context (helpers need a live delegation per person), self-registration with a one-time code
- [x] A2 Consent: grant, narrow, withdraw (holds applications, cancels jobs, purges memory), scopes gate what a client may write
- [x] A3 Applications: idempotent create, versioned patch, trust rule (clients cannot mark data verified), submit pipeline wired to the engine, cases, payments and notifications
- [x] A4 Document upload: magic bytes, size and pixel caps, re-encoded without EXIF, random names, signed card fields merged as verified
- [x] A5 Cases: state machine, queue with filters and keyset paging, assign, notes, actions with required reasons, reopen, SLA, review time
- [x] A6 Mock identity, registry, payment and SMS services with keys and failure injection; adapters with timeout, retry and circuit breaker
- [x] A7 Payments: one per application, released at once up to Rs 15,000, a second officer above it, reconciliation row
- [x] A8 Notifications in English and Urdu with verify codes; Postgres job queue with retries, dead letter and consent-aware workers

Track B
- [x] B1 Rule interpreter: allowlisted operators, three-valued logic, limits, repairable validation, trace
- [x] B2 Rule versions: draft, validate, dry run, diff, request approval, publish by a second admin, rollback; published versions immutable in the database
- [x] B3 `decide()`: pure, cost-based, guards, silent-guess invariant, replayable hashes
- [x] B4 Explanations in English and Urdu, handoff package, citizen and auditor views
- [x] B5 Synthetic world: 1,212 people and 1,843 labelled cases (demo); 3,598 cases for training, split by family
- [x] B6 Calibrated evidence model (logistic regression with isotonic calibration; ECE 0.028 on p_ok, held-out families)

Track C
- [x] C1 Mock issuer (Ed25519), specimen cards with SPECIMEN marks, 9 photo variants per demo citizen with expected outcomes
- [x] C2 `check_document()`: quality gate with spoken retake hints, signed QR, OCR-free print check, ELA and metadata signals; held-out: 99.2% of forgeries flagged, 2.1% false alarms on genuine cards, median 0.35 s
- [ ] C3 Scam corpus, classifier, URL and sender analysis

Track D1
- [x] D1.1 Tokens, pictograms, audio player, i18n (Urdu and English)
- [x] D1.2 Citizen PIN login
- [x] D1.3 Guided application: consent, card photo with retake hints, one question per screen, review, send (tested against stubs, Slow 3G and offline in headless Chrome)
- [x] D1.4 Result screen for every outcome, tracker with symbol code, ask a person; 192 Urdu and 192 English voice prompts

Track D2
- [x] D2.1 Staff shell
- [x] D2.2 Officer queue and case review with the handoff package first (urgent cases first)
- [x] D2.3 Auditor decision viewer and audit explorer with chain verification

**Gate 1 passed in tests** (Sat 21 Nov, 14:45): `backend/tests/integration/test_anchor_flow.py` runs the anchor flow through the HTTP API with every track's real code. Aslam is approved and paid by the system alone and his verify code checks out; Zainab, with no income record, is asked for proof, handed to an officer with notes, approved with a reason and paid; the auditor sees both views and an intact chain. Still to confirm: the same on the live URL.

## Phase 2: the eight challenges (T1)

- [ ] A9 API keys  - [ ] A10 Rate limiting  - [ ] A11 Consent centre API  - [ ] A12 Helper delegations  - [ ] A13 Sync endpoint  - [ ] A14 Security test suite
- [ ] B7 Threshold analysis  - [ ] B8 Name matching and dedupe  - [ ] B9 Handoff package and cheapest question  - [ ] B10 Golden tests  - [ ] B11 Replay
- [ ] C4 Voice  - [ ] C5 Audio assets  - [ ] C6 Forgery depth and metrics  - [ ] C7 Scam reports, aggregates, clustering  - [ ] C8 Scam checker by screenshot and voice
- [ ] D1.5 PWA offline  - [ ] D1.6 Voice answers  - [ ] D1.7 Consent centre  - [ ] D1.8 Scam checker  - [ ] D1.9 Helper Mode
- [ ] D2.4 Rule editor  - [ ] D2.5 Cost of being wrong  - [ ] D2.6 Challenge Lab  - [ ] D2.7 Audit explorer

**Gate 2**: all eight Challenge Lab cards pass on the live URL.

## Phase 3: bonus features and the rest (T2)

- [ ] A15 Webhooks  - [ ] A16 Plans and usage  - [ ] A17 USSD/SMS and verify code  - [ ] A18 Appeals, complaints, admin users, reports
- [ ] B12 Digital Twin  - [ ] B13 Eval dashboard API  - [ ] B14 Analytics  - [ ] B15 Anomaly detection  - [ ] B16 Override feedback
- [ ] C9 RAG  - [ ] C10 Agent  - [ ] C11 Guardrails and red team  - [ ] C12 Memory  - [ ] C13 Optional providers (T3)
- [ ] D1.10 Sync conflicts, local encryption  - [ ] D1.11 USSD simulator, symbols  - [ ] D1.12 Budgets in CI
- [ ] D2.8 Digital Twin view  - [ ] D2.9 Scam Map  - [ ] D2.10 Dashboards  - [ ] D2.11 Admin screens

**Gate 3**: every item passes its check or is `HIDDEN`.

## Integration and submission

- [ ] E1 Merge loop running  - [ ] E2 Demo fixtures and reset  - [ ] E3 End-to-end tests  - [ ] E4 Docs and reports
- [ ] Live URL up through Monday  - [ ] README final  - [ ] Demo video on Drive, link checked in a private window  - [ ] Submitted by Sun 16:30
