# Rahat: The Last Mile, AI on Public Rails

> **Prototype. Not an official service. All identity, payment and data services are simulated.**
> Built for Coder's Cup '26 (ACM FAST-NUCES Karachi), 20 to 22 November 2026. Every person, case, message and document in this repository is invented.

**Rahat is one multi-tenant platform that helps a low-literacy widow, a scam-targeted shopkeeper and a community helper serving 40 families apply for and track a mock Relief Payment, by voice and pictures, on a weak connection. Unlike a chatbot, it decides, explains, protects, and says "I am not sure" and hands the case to a person with a briefing, because a wrong approval is priced at 31 times a human review.**

**Live:** https://rahat-zeta.vercel.app (sign-ins on [`/demo`](https://rahat-zeta.vercel.app/demo), the decision engine visualised on [`/live`](https://rahat-zeta.vercel.app/live), API docs on `/docs`). Backup URL: given at the demo. Demo script: [docs/DEMO.md](docs/DEMO.md). Evaluation numbers and commands: [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md).

## What judges can try (demo accounts)

The `/demo` page signs in with one tap. Citizens use a mock phone and the PIN `4826`; staff use the password `Rahat-Demo-2026!`.

| Account | Sign-in | What it shows |
|---|---|---|
| Zainab Bibi, widow | `0999-0000201` | Urdu voice and icon application, card photo, "needs proof", then a person decides |
| Aslam Khan, shopkeeper | `0999-0000202` | Approved and paid by the system alone; scam checker; verify code |
| Rubina Shaikh, helper | `0999-0000101` | Helper Mode: 40 families, a PIN per family |
| Officer, auditor, admins | `officer@`, `auditor@rahat.example`, `admin@`, `approver@sindh.rahat.example` | Case review, decision replay, audit chain, rules with two-admin publish, cost sliders, Digital Twin |

Specimen ID cards for the camera step are in `data/demo_cards/`.

## What it does (rubric to feature)

| Need | What is built |
|---|---|
| Decide | Rule engine with versions, plus a calibrated evidence model, plus a cost matrix and three-way routing (act, ask more, hand to a human) |
| Explain | Two views of every decision (plain text for the citizen in English and Urdu, full trace for staff and auditors); replay gives the identical result |
| Protect | Scam checker (English, Urdu, Roman Urdu), forged-card checks (signed QR, print against QR, image signals), prompt-injection guards, Row Level Security, consent enforced in the database |
| Say "I am not sure" | Every AI component returns a typed decision and can abstain; handoff package for the officer; silent-guess count is 0 on the held-out set |
| Work for everyone | Urdu voice with read-back, one question per screen with pictograms, offline outbox, citizen JavaScript 92.9 KB gzipped (budget 100) |
| Show it | "Noor" visual language from the Sindhi ajrak (docs/DESIGN.md): a self-drawing eight-point-star emblem, a verdict reveal with a chime, a night "mission control" for staff, and `/live`, the real decision engine replaying the synthetic eval set in WebGL with live counters (a static diagram when WebGL, motion or data is limited) |
| SaaS | Departments (tenants), roles, API keys with scopes, rate limits, audit chain, mock identity, payment and SMS services, job queue, `/healthz`, `/metrics` |

## Run it locally

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node 24. No database setup: an embedded PostgreSQL 16 starts by itself when `DATABASE_URL_OWNER` is unset.

```
npm install
npm run install:all     # backend (uv sync) and frontend (npm install)
npm run migrate         # schema, Row Level Security, runtime role
npm run seed            # two departments, demo accounts, 40 families
npm run dev             # API on :8000, web app on :5173
```

Open http://localhost:5173/demo, or http://localhost:8000/docs for the API.

| Command | What it does |
|---|---|
| `npm run verify` | lint, types, all tests, frontend build, bundle budget, mock-data lint |
| `npm run verify:fast` | the same without database tests and the build |
| `npm run seed -- --reset` | wipe and reseed the demo data |
| `npm run gen:api` | export OpenAPI and regenerate the typed client |
| `npm run db:stop` | stop the embedded database |
| `cd backend && uv run pytest app/modules/<name> -q` | one module's tests |

The full suite last reported 1259 passed, 2 skipped. Eval commands are in [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md).

## Architecture

```
 Phone / laptop (Preact PWA, offline outbox, encrypted draft)
        | HTTPS
        v
 Vercel CDN: static app          Vercel function (bom1): FastAPI /v1
                                   |  policy registry on every route
                                   |  modules: auth, people, consent, applications, cases, payments,
                                   |           rules, decision, matching, evals, docs_ai, scam, rag,
                                   |           voice, guardrails, helpers, notifications, jobs
                                   |  adapters (timeout, retry, circuit breaker) --> mock identity,
                                   |           registry, payment, SMS  (simulated, in process)
                                   v
 PostgreSQL (Supabase, ap-south-1): Row Level Security, consent function,
 hash-chained audit log, job queue (SKIP LOCKED), immutable rule versions

 Backup host: a PC with embedded PostgreSQL 16 and a Cloudflare quick tunnel (same code).
```

The AI logic is pure functions (decision, rules, matching, classifiers, guardrails) with tests that run without a database. Key choices, each with its reason in [docs/DECISIONS.md](docs/DECISIONS.md):

- **Cost-based decisions, not thresholds picked by hand** (PLAN 6.1). Thresholds follow from the price of each mistake and move with the cost sliders.
- **Postgres Row Level Security and consent inside the database** (DECISIONS 5, 6). Withdrawing consent stops officers, helpers and API keys on the next query.
- **Postgres as the job queue, no Redis** (3). **Vite and Preact, not Next.js** (2), to stay under 100 KB. **Embedded Postgres for dev and tests** (4).
- **Hash-chained audit** (10); **mock-shaped IDs only** (12), so real data cannot be stored; **Urdu only, no Sindhi** (16), because nobody on the team can check Sindhi.
- **Vercel as primary host with serverless settings** (19); one worktree and one agent per track (15).

Contracts and module map: [docs/CONTRACTS.md](docs/CONTRACTS.md). Status of each item: [docs/STATUS.md](docs/STATUS.md). Visual language: [docs/DESIGN.md](docs/DESIGN.md).

## Models and tools

Every AI capability has a local implementation that needs no paid API and no network. Hosted providers are optional and sit behind the same interface.

| Job | Default (free, local) | Optional |
|---|---|---|
| Decision | numpy logistic regression with isotonic calibration, a cost matrix, three-way routing. Small, explainable, replayable | none |
| Printed-text OCR | RapidOCR (ONNX, Apache-2.0), then Tesseract if installed, then none | none |
| Card checks | OpenCV: signed QR (Ed25519), quality gate, error-level and metadata signals | none |
| Speech to text | On-device browser speech first | Gemini `gemini-3.1-flash-lite` (measured 2 to 3 s on Urdu prompts), then Groq Whisper |
| Voice answers to form questions | local interpreter with a confidence floor | none |
| Scam checker | local classifier plus link and sender signals plus verify codes | none |
| Rules assistant | local lexical retrieval; answers copied from policy text with citations | none |
| Name matching | RapidFuzz, transliteration, phonetic keys | none |
| Guardrails | rule-based input, output and action guards with a red-team suite | none |

A language model is never allowed to write free text for a citizen. Citizen messages come from fixed, reviewed text keyed by reason code.

## Cost

- **Zero-cost core.** The whole app, every model and all evaluations run on a laptop with no API key and no network.
- **Hosting used for the demo:** Vercel and Supabase. We have not measured or priced their plans; no cost per application is claimed.
- **Optional hosted speech** (Gemini, Groq) is used only if keys are set. We measured latency, not cost, and do not quote per-call prices.
- **Expected cost in the decision model** is in abstract units, not rupees: 2.381 per case against 3.200 if every case went to a person, on 1,223 held-out synthetic cases ([EVAL_REPORT](docs/EVAL_REPORT.md)).

## Measured results (synthetic data; details and commands in EVAL_REPORT)

| Measure | Result |
|---|---|
| Wrong approvals / wrong rejections (1,223 held-out cases) | 1 / 5 |
| Not decided alone (proof or person) | 74.5%, by design |
| Silent guesses | 0 |
| Calibration | ECE 0.033, Brier 0.062 |
| Name matching, 456 messy pairs | 0 wrong links; all 288 true duplicates reached the same or possible band |
| Scam checker, 1,164 unseen messages | 95.5% caught, 0 called real, 2.4% false alarms on legitimate; Roman Urdu false alarms 14.7% |
| Red team | 67 of 67 attacks blocked, 30 of 30 benign passed |
| Rules assistant | 0 wrong answers on 98 questions; 61.5% on a 19-question new-wording hold-out, with 2 wrong |
| Voice interpreter, unseen families | 91.8% accurate, 0 wrong but confident |
| Live latency on Vercel | median 152 ms over 17 calls |

## Real and simulated

| Real, working code | Simulated |
|---|---|
| Sign-in, roles, Row Level Security, consent enforcement, hash-chained audit | Identity registry (stands in for a national ID authority) |
| Rule engine, cost-based decisions, calibration, replay | Payment rail (stands in for an instant-payment system) |
| OCR, QR signature checks and forgery signals, on our own specimen cards | SMS, WhatsApp and email delivery (a visible outbox) |
| Scam classifier and name matching, trained and tested on synthetic data | USSD gateway (simulator only) |
| Urdu speech input path, offline sync, rate limits | Every person, case, message and document; billing |

## Security

Access is enforced on the server twice: every route declares a policy (a test fails the build otherwise), and Postgres Row Level Security scopes each query to the department. Personal-data tables also need an active consent, checked in the database. Uploads are checked by magic bytes, re-encoded without EXIF and size-capped; logs redact identifiers; errors never leak internals; the audit log is hash-chained and append-only for the app role. The security suite covers the authorisation matrix, cross-department reads, raw-SQL bypass attempts and rate limits. Findings, fixes and open gaps are in [docs/SECURITY_REPORT.md](docs/SECURITY_REPORT.md).

## Limitations

- **Everything is synthetic.** Models are trained and scored on invented data; accuracy on real data is unknown. The held-out sets show generalisation to unseen synthetic people only.
- **The engine is cautious.** About three quarters of cases go to a person or ask for a proof. That is the cost model working, but a real department would need staff for it.
- **Weak spots measured:** Roman Urdu scam false alarms (14.7%); the rules assistant on re-worded questions (61.5% on the hold-out); pixel-level forgery detection (ELA) is weak, forgeries are caught mainly by the signed QR and the print-against-QR comparison.
- **No OCR on Vercel** (function size limit): only the signed QR is verified there. OCR runs on the PC host.
- **Row Level Security protects against application bugs and insecure object references, not against an attacker who controls the API process.** A known weakness in the consent function's search path is reported in the security report.
- **Sign-in** is a mock phone and a PIN. A real service would add a one-time code or device binding.
- **Rate limits live in one process.** Webhooks, plans and billing, USSD and some staff screens are not finished; unfinished screens are hidden or marked in [docs/STATUS.md](docs/STATUS.md).
- **Not tested:** a real phone on a real weak network, screen readers, Urdu wording by a native speaker, real phone photos of cards.
- **Only Urdu and English.** No Sindhi or other regional language.
- The mock ID is `00000-NNNNNNN-C` and the mock phone `0999-NNNNNNN` (also written `+92 999 NNNNNNN`). The API refuses any other shape.

## How AI was used to build this

Rahat was built with Claude Code. One lead session fixed the contracts first, then ran one agent per track (platform, decision intelligence, perception and language, citizen app, staff console, deploy, an independent verifier and security reviewer), each in its own git worktree and branch so that one half-written file could not break another track. Tests were the gate: nothing counted as done until a test the agent had run passed, and a separate verifier agent re-ran the demo flows instead of reading code. The lead merged the branches, wired them together, and checked the live URL. The decisions made along the way are in [docs/DECISIONS.md](docs/DECISIONS.md). The product itself does not depend on any AI service at run time.

## Third-party software

See [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). No web fonts, chart libraries, map tiles or third-party scripts are loaded by the citizen app.

---

**Prototype. Not an official service. All identity, payment and data services are simulated.**
