# Status

Tick an item only after you ran it and saw it work. Item ids match PLAN section 7. `SIMULATED` marks something that needs a real external party. `HIDDEN` marks a feature kept behind a flag because it is not demo-proof.

Last updated: Sat 21 Nov 2026, 15:45 PKT, by the lead session. **Gate 0 passed.** Phase 1 is in progress: track agents are working in the worktrees under `.wt/`.

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

Not verified: any deployed host, running the built image, a real phone, slow or offline network, the service worker in a browser, screen readers, and the Urdu wording by a native speaker. OCR runs locally through RapidOCR (Tesseract is the fallback and is not installed on this machine).

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
- [x] C3 Scam checker: 3,840 synthetic messages in English, Urdu and Roman Urdu (82 families, split by family), calibrated classifier with string-only link and sender signals and verify codes; held-out: 95.5% of scams caught, 0 called real, 2.4% false alarms (0 on Rahat's own messages)

Track D1
- [x] D1.1 Tokens, pictograms, audio player, i18n (Urdu and English)
- [x] D1.2 Citizen PIN login
- [x] D1.3 Guided application: consent, card photo with retake hints, one question per screen, review, send (tested against stubs, Slow 3G and offline in headless Chrome)
- [x] D1.4 Result screen for every outcome, tracker with symbol code, ask a person; 192 Urdu and 192 English voice prompts

Track D2
- [x] D2.1 Staff shell
- [x] D2.2 Officer queue and case review with the handoff package first (urgent cases first)
- [x] D2.3 Auditor decision viewer and audit explorer with chain verification

**Gate 1 passed in tests** (Sat 21 Nov, 14:45): `backend/tests/integration/test_anchor_flow.py` runs the anchor flow through the HTTP API with every track's real code. Aslam is approved and paid by the system alone and his verify code checks out; Zainab, with no income record, is asked for proof, handed to an officer with notes, approved with a reason and paid; the auditor sees both views and an intact chain. **Confirmed on the live URL** (15:00) by running the same flow over HTTPS through the tunnel. That run found a real defect, one person could open two applications for one program and be paid twice, now refused by the service (409 `application_exists`) and by a database index (migration 0004).

## Phase 2: the eight challenges (T1)

- [x] A9 API keys (scoped, hashed, shown once, a second admin for personal-data scopes)  - [x] A10 Rate limiting (per network, user, key and department lanes)  - [x] A11 Consent centre: who has my data, who looked at it (every staff and helper read is logged by person), corrections, export, erasure request  - [x] A12 Helpers: grant by phone, revoke at once, family PIN switch with short-lived tickets, 40 seeded families  - [x] A13 Offline sync: each op applied once, re-authorised under current consent, field-level merge with conflicts  - [x] A14 Security suite: authorisation matrix over every route, IDOR, raw-SQL RLS probes; docs/SECURITY_REPORT.md
- [x] B7 Cost of being wrong: curves, ROC/PR, confusion, reliability (ECE 0.033) on 1,223 held-out cases; what-if in ~45 ms; admin cost matrix  - [x] B8 Name matching and dedupe: 456 messy pairs, 0 wrong links; Mohammad/Muhammed with another phone goes to a person  - [x] B9 Handoff package and cheapest question  - [x] B10 Golden tests (silent guesses 0, measured from stored decisions)  - [x] B11 Replay and decision list
- [x] C4 Voice: Urdu, Roman Urdu and English answers with read-back; 91.8% accurate on unseen families, 0 wrong-but-confident; device speech first, then Gemini (GEMINI_API_KEY) and Groq Whisper (key) on the server; Gemini is SIMULATED in tests (httpx.MockTransport), never run against the real API  - [ ] C5 Audio assets  - [ ] C6 Forgery depth and metrics  - [x] C7 Scam reports (redacted), campaigns by MinHash, Scam Map data with k-anonymity (k=5), public warnings, disputes open a case  - [ ] C8 Scam checker by screenshot and voice
- [x] D1.5 Offline outbox: encrypted with a key from the PIN, ordered queue with idempotency, conflict re-read, idle lock  - [ ] D1.6 Voice answers  - [x] D1.7 Consent centre: who has my data, share less, take back, share again (access log screen still to wire)  - [x] D1.8 Scam checker: paste or speak, pictogram answers read aloud, links never clickable, confirmed-real messages, ask a person  - [ ] D1.9 Helper Mode
- [x] D2.4 Rule editor (two admins, four-eyes publish shown)  - [ ] D2.5 Cost of being wrong  - [ ] D2.6 Challenge Lab  - [x] D2.7 Audit explorer

**Gate 2 passed** (Sat 21 Nov, 23:30, live https://rahat-zeta.vercel.app, run by an independent verifier in the real UI): all eight Challenge Lab cards and the three security cards pass; also checked live: the cost what-if moves the thresholds, replay matches, the audit chain verifies, an API key's 3-a-minute limit answers 429, Helper Mode switches with a PIN, the scam checker in English, Urdu and Roman Urdu, a real verify code, and `*786#` on `/ussd`. The run found that a burst of sign-ins exhausted Supabase's session pooler (`EMAXCONNSESSION`, 500s for minutes); fixed with the transaction pooler (`DB_POOLER_MODE=transaction`), then 90 concurrent sign-ins and 360 reads gave no 5xx. Cards 2, 4, 5 and 6 need the citizen part run first after a reset (`docs/DEMO.md`).

## Phase 3: bonus features and the rest (T2)

- [x] A15 Webhooks: outbox emit from cases, payments and the pipeline; HMAC-signed delivery with backoff and jitter, then dead; resolve-and-pin SSRF guard (private, loopback, metadata, redirects and rebinding refused, tested); delivery log with cursor and redeliver; mock receiver verifies signatures; payloads asserted to carry ids and statuses only  - [x] A16 Plans and usage: `free`, `standard`, `government`; atomic metering at applications, ocr, sms, ai calls and API keys; 429 `plan_limit_reached` with metric, limit, used and reset date; usage report with six months; 14 racing callers for 5 units get exactly 5  - [ ] A17 USSD/SMS and verify code  - [x] A18 Appeals and complaints: a different officer decides (enforced and audited), overturn pays through the payment service, consent and tenant isolation tested (admin users and reports are not part of WP-A and stay open)
- [x] B12 Digital Twin: draft rules replayed over live and labelled cases, fairness slices, no side effects  - [x] B13 Evaluation summary API  - [x] B14 Analytics: `GET /v1/admin/impact` (handoff rate, time to decision, fraud flagged, cost per claim, payments, time saved with named assumptions, synthetic replay headline) and `/staff/impact`  - [x] B15 Anomaly detection (WP-D, branch `track/wpd`): four pure detectors that abstain on thin data, `anomaly_review` cases with handoff and dedupe, job `anomaly.scan`, `/staff/anomalies`; synthetic precision 0.75 / 0.79 / 1.00 / 1.00, recall 1.00 on injected patterns (EVAL_REPORT 11)  - [ ] B16 Override feedback
- [x] C9 RAG: 7 policy documents in English and Urdu, answers copied with citations, refusal below a cost-chosen threshold; 0 wrong answers on dev and test  - [x] C10 Agent (WP-B, branch `track/wpb`): read tools, five action tools that always wait for an officer, local planner (default) and optional Gemini planner, runs API; golden 38/38, 0 actions without approval, 21-attack injection suite 63/63. Not verified: the Gemini planner against the real API (mock transport only); no staff screen yet (WP-E)  - [x] C11 Guardrails: input and output guards, 67-attack red team with 0 false alarms, and the action guard (`guardrails/action_guard.py`, checked at proposal and again at approval, every refusal audited with a code)  - [ ] C12 Memory  - [ ] C13 Optional providers (T3)

- [x] A15 Webhooks: outbox emit from cases, payments and the pipeline; HMAC-signed delivery with backoff and jitter, then dead; resolve-and-pin SSRF guard (private, loopback, metadata, redirects and rebinding refused, tested); delivery log with cursor and redeliver; mock receiver verifies signatures; payloads asserted to carry ids and statuses only; staff screen `/staff/webhooks` (WP-E)  - [x] A16 Plans and usage: `free`, `standard`, `government`; atomic metering at applications, ocr, sms, ai calls and API keys; 429 `plan_limit_reached` with metric, limit, used and reset date; usage report with six months; 14 racing callers for 5 units get exactly 5; staff screen `/staff/usage` (WP-E)  - [ ] A17 USSD/SMS and verify code  - [x] A18 Appeals and complaints: a different officer decides (enforced and audited), overturn pays through the payment service, consent and tenant isolation tested (admin users and reports are not part of WP-A and stay open); staff screens `/staff/appeals` and `/staff/complaints` (WP-E)
- [x] B12 Digital Twin: draft rules replayed over live and labelled cases, fairness slices, no side effects  - [x] B13 Evaluation summary API  - [ ] B14 Analytics  - [ ] B15 Anomaly detection  - [ ] B16 Override feedback
- [x] C9 RAG: 7 policy documents in English and Urdu, answers copied with citations, refusal below a cost-chosen threshold; 0 wrong answers on dev and test  - [x] C10 Agent (WP-B, branch `track/wpb`): read tools, five action tools that always wait for an officer, local planner (default) and optional Gemini planner, runs API; golden 38/38, 0 actions without approval, 21-attack injection suite 63/63. Not verified: the Gemini planner against the real API (mock transport only); staff screen: assistant panel in case review (WP-E, track `track/wpe`)  - [x] C11 Guardrails: input and output guards, 67-attack red team with 0 false alarms, and the action guard (`guardrails/action_guard.py`, checked at proposal and again at approval, every refusal audited with a code)  - [ ] C12 Memory  - [ ] C13 Optional providers (T3)
- [ ] D1.10 Sync conflicts, local encryption  - [ ] D1.11 USSD simulator, symbols  - [ ] D1.12 Budgets in CI

- [ ] A15 Webhooks  - [ ] A16 Plans and usage  - [x] A17 Feature-phone channel: USSD menu (English and Roman Urdu: status by tracking code and phone, check a message by verify code, stop sharing with the PIN through the real consent service, call-me-back case) and SMS commands STATUS, VERIFY, STOP, HELP with replies through the mock SMS gateway carrying a verify code; `POST /v1/channels/ussd` and `/v1/channels/sms/inbound` admit API keys with `channels:ussd` or `channels:sms`; the aggregator and the SMS network are SIMULATED  - [ ] A18 Appeals, complaints, admin users, reports
- [x] B12 Digital Twin: draft rules replayed over live and labelled cases, fairness slices, no side effects  - [x] B13 Evaluation summary API  - [ ] B14 Analytics  - [ ] B15 Anomaly detection  - [ ] B16 Override feedback
- [x] C9 RAG: 7 policy documents in English and Urdu, answers copied with citations, refusal below a cost-chosen threshold; 0 wrong answers on dev and test  - [ ] C10 Agent  - [ ] C11 Guardrails: input and output guards done, 67-attack red team passes with 0 false alarms; action guard still to come with the agent  - [ ] C12 Memory  - [ ] C13 Optional providers (T3)
- [ ] D1.10 Sync conflicts, local encryption  - [x] D1.11 USSD simulator at `/ussd` (own lazy chunk `ussd`, 7 KB gzip, outside the citizen budget and the PWA precache; the status names the tracking symbols)  - [ ] D1.11b links to `/ussd` from `/demo` and `/live` (WP-E)  - [ ] D1.12 Budgets in CI
- [ ] D2.8 Digital Twin view  - [ ] D2.9 Scam Map  - [ ] D2.10 Dashboards  - [ ] D2.11 Admin screens

**Phase 3 done** (Sun 22 Nov, 00:20, commit df139f7; plan in `docs/PLAN_PHASE2_3.md`): WP-A webhooks, plans and usage, appeals and complaints; WP-B agent with an approval gate; WP-C USSD and SMS with `/ussd`; WP-D anomaly detection and the impact report; WP-E their staff screens; WP-F citizen appeal and complaint. `npm run verify`: 1654 passed, citizen JS 100.0 KB (budget 100). Live smoke on Vercel: every page 200, anchor flow passes, no 5xx under a burst. Cut on purpose: memory and override learning (C12, B16). Staff placeholder pages are hidden in every production build.

**Gate 3**: every item passes its check or is `HIDDEN`.

## Hosts

Primary: **https://rahat-zeta.vercel.app** (Vercel, function in bom1 Mumbai, Supabase Postgres 17 in ap-south-1 through the session pooler). Backup: this PC through a Cloudflare quick tunnel on the embedded database (`npm run live:start`; the URL changes when the tunnel restarts).

## Vercel host

- [x] Settings `JOBS_MODE`, `MOCKS_IN_PROCESS`, `CLIENT_IP_HEADER`, `STARTUP_WARMUP`, `CRON_SECRET` (defaults unchanged), tests, anchor flow proven over HTTP in this mode locally
- [x] `api/index.py`, `vercel.json`, `.vercelignore`, `requirements.txt` generator, `deploy/vercel/` env script and README
- [x] Deployed Sat 21 Nov 19:18 (commit f315581). Through the public URL: `/healthz`, `/readyz`, `/` and `/docs` 200 with the CSP, HSTS and DENY headers; the anchor flow over HTTPS (Aslam auto-approved and paid with a verify code that checks; Zainab asked for proof, handed to an officer, approved and paid; inline jobs sent every message; audit chain intact); median 152 ms per call over 17 calls, the helper's 40 families in 152 ms. Supabase was then reset to the clean demo state.
- [x] Uploaded documents in Postgres on Vercel (`DOCUMENT_STORE=db`, migration 0008), because instances share no disk
- [ ] No OCR on Vercel: the RapidOCR stack does not fit the 500 MB function limit, so the printed-text versus QR check runs only on the PC host; the signed QR is verified on both

## Visual language v2: Noor (Sat 21 Nov, 20:00 to 20:50)

- [x] Tokens, motion, ajrak lattice, the self-drawing emblem; rules in `docs/DESIGN.md` (3c6884e)
- [x] Citizen: night start screen, journey stars, verdict reveal with chime and touch, scam shield, verify-code seal, monogram avatars, `+92 999` phone entry and display, new favicon and icons. Citizen JS 92.9 KB gzip (budget 100)
- [x] Staff: night mission control (day toggle), live pulse strip, Ctrl/Cmd+K palette, queue heat bars, decision anatomy, animated replay, hash-chain audit view, dashboards; `/demo` judges' briefing room
- [x] `/live` "Loom of Light": three.js in its own lazy chunks (live 8.7 KB, live-three 136.7 KB gzip, outside the citizen budget and the PWA precache), `GET /v1/public/pulse` (public, aggregate counts only, cached 15 s), static Sankey fallback for no WebGL, reduced motion or Save-Data
- [x] Checked after deploy (71bdf32): `npm run verify` 1271 passed; Vercel READY; `/`, `/demo`, `/staff`, `/live`, `/v1/public/pulse` 200 on https://rahat-zeta.vercel.app; the phone start screen renders at 390 px with no overflow; PC backup updated
- [ ] Not verified on a real phone: sound, vibration, view-transition slide, voice; not verified on a real GPU: `/live` frame rate (36 fps at 1080p on a software rasteriser)

## Final day fixes (Sun 22 Nov)

- [x] Assistant: an undecided document check (`document_needs_review`) is a review guard, so the planner proposes the cheapest proof or abstains with a plain reason instead of `unknown_guard`; 40 golden cases, 0 mismatches (ADR 23, 1fbfcb4)
- [x] Staff v4: case review, audit chain and impact as tabs with less text (5cd7e9f); focused rail per role with a More grid and the Guide page "Where is what" (2b98025)
- [x] `/demo/kit`: the 30 specimen test cards with the measured result of the document check for each (all 30 as labelled, with or without OCR) (d2c7dd9)
- [x] Serverless sign-up: the admin's simulated SMS view reads the department's copies, so a new citizen can finish registering on Vercel; measured 0/3 before, 3/3 after (ADR 24, 24e5e41)
- [x] Staff console opened right-to-left after `/demo` (language race); fixed (d7f2645). Title shows only "Rahat"; footers keep the prototype label (d42ffaf)
- [x] Live database re-seeded after an interrupted reset (logins were failing); officer, admin, auditor and citizen sign-in checked on the live URL
- [x] OCR checked: RapidOCR (PP-OCR models) reads all five fields of a clean card on the PC host in 0.8 s; the hosted deploy has no OCR (size limit, ADR 19) and verifies cards by the signed QR and forensics
- [ ] Citizen sign-up screens and in-app inbox (track/citizen4)  - [ ] Staff unslop pass and per-page chunks (track/staff6)  - [ ] Citizen design pass  - [ ] Device voice prefers the recording voices

## Integration and submission

- [ ] E1 Merge loop running  - [ ] E2 Demo fixtures and reset  - [ ] E3 End-to-end tests  - [ ] E4 Docs and reports
- [ ] Live URL up through Monday  - [ ] README final  - [ ] Demo video on Drive, link checked in a private window  - [ ] Submitted by Sun 16:30
