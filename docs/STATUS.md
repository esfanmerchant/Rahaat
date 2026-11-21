# Status

Tick an item only after you ran it and saw it work. Item ids match PLAN section 7. `SIMULATED` marks something that needs a real external party. `HIDDEN` marks a feature kept behind a flag because it is not demo-proof.

Last updated: Sat 21 Nov 2026, 13:00 PKT, by the lead session.

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
- [x] F11 CI workflow written (`.github/workflows/ci.yml`); **not yet run** (needs the first push)
- [ ] F12 Dockerfile and start script written. The start script was run natively in demo mode with generated secrets (migrate, seed, serve: all passed). **The Docker image has never been built** (no Docker locally; the CI `image` job is the first real build). **Not deployed** (needs a host account).

**Gate 0** is not passed yet. Still needed: a live URL where all five roles can sign in, the first CI run, and the first commit (git `user.name` is not set on this machine).

Verified locally on Sat 21 Nov, 12:57:
- `npm run verify` green: ruff, mypy, frontend type check, 71 backend tests, frontend build, bundle budget, mock-data lint.
- Migration up, down, up on a clean database: 54 tables with RLS, 67 policies, runtime role without superuser or BYPASSRLS, audit log INSERT and SELECT only.
- Running server: sign-in as officer, citizen (PIN) and auditor; officer blocked from the audit log and the attempt recorded; hash chain verifies; no personal data in logs.
- Demo-mode rehearsal through `deploy/start.sh` with generated secrets: 18 routes, 0 stubs, 0 undeclared; refresh cookie is HttpOnly, Secure, SameSite=Lax; real-looking phone numbers refused.
- Frontend flows in headless Chrome at phone width under the strict CSP (run by the frontend agent): citizen and staff sign-in, wrong-password errors, session restore after reload, sign-out, tenant switch, role-denied page, `/demo` one-click sign-in.

Not verified: Docker build, CI, any deployed host, password authentication of the runtime database role (the embedded database trusts local connections), a real phone, slow or offline network, the service worker in a browser, screen readers, and the Urdu wording by a native speaker. Tesseract is not installed on this machine, so OCR cannot run here yet.

## Phase 1: the spine (T0)

Track A
- [ ] A1 Persons and registration
- [ ] A2 Consent grant at registration
- [ ] A3 Applications: draft, patch, submit
- [ ] A4 Document upload (hardened)
- [ ] A5 Cases: state machine, queue, review actions
- [ ] A6 Mock identity, registry, payment and SMS services with failure injection
- [ ] A7 Payments: idempotent, four-eyes
- [ ] A8 Notifications outbox and jobs worker

Track B
- [ ] B1 Rule interpreter with three-valued logic and trace
- [ ] B2 Rule versions: draft, validate, dry run, approve, publish, rollback, diff
- [ ] B3 `decide()` with the silent-guess invariant
- [ ] B4 Explanations: citizen view and auditor trace
- [ ] B5 Synthetic world (1,200+ persons, 1,000+ labelled cases)
- [ ] B6 Calibrated evidence model

Track C
- [ ] C1 Mock issuer, specimen card generator and variants
- [ ] C2 `check_document()`: quality, QR signature, OCR, cross-check
- [ ] C3 Scam corpus, classifier, URL and sender analysis

Track D1
- [ ] D1.1 Tokens, pictograms, audio player, i18n
- [ ] D1.2 Citizen PIN login
- [ ] D1.3 Guided application
- [ ] D1.4 Result screen and tracker

Track D2
- [ ] D2.1 Staff shell
- [ ] D2.2 Officer queue and case review
- [ ] D2.3 Auditor decision viewer

**Gate 1**: the anchor flow completes on the live URL.

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
