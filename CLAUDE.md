# Rahat: rules for every Claude Code session

**Prototype. Not an official service. All identity, payment and data services are simulated.**

Hackathon build for Coder's Cup '26 (ACM FAST-NUCES Karachi). Deadline **Sun 22 Nov 2026, 18:00 PKT**; live in-person demo on Mon 23 Nov. `PLAN.md` is the source of truth. Read the sections your task names before writing code.

## What we are building

One multi-tenant SaaS platform, not a chatbot. It helps a low-literacy widow, a scam-targeted shopkeeper and a community helper serving 40 families apply for and track a mock Relief Payment ("Rahat"). It must decide, explain, protect, and say "I am not sure" and hand over to a human. Judges score how the system behaves live, not what we claim.

## Priorities, in order

1. The live demo of the anchor flow never breaks. `main` is always deployable.
2. Finish the current tier (PLAN section 4) before touching the next.
3. A feature is demo-proof or hidden behind a flag. Never leave a half-built screen reachable.
4. When in doubt, pick the safer and more explainable option and add a short ADR to `docs/DECISIONS.md`.

## Non-negotiables

- **Mock data only.** Mock IDs are `00000-NNNNNNN-C`, mock phones are `0999-NNNNNNN`, shown in Pakistan's format `+92 XXXXXXXXXX` as `+92 999NNNNNNN`. Never add anything that looks like a real CNIC, phone number or person, and never process a real ID image. Real personal data disqualifies the team.
- **Security is enforced on the server**: the policy registry plus Postgres Row Level Security. Hiding a button is never the control. Never weaken a security or consent check to make a demo easier.
- **No silent guessing.** Every AI component returns a `TypedDecision` and can abstain. Unknown stays unknown. Low confidence goes to ask-more or to a human with a handoff package.
- **Wrong approvals cost more than slow ones.** Routing comes from the cost matrix in PLAN 6.1, not from ad hoc thresholds. Auto-reject only on a hard rule failing on verified input.
- **Zero-cost core.** Every AI capability has a local implementation that works with no paid API and no network. Hosted providers are optional and sit behind the same interface.
- **Label the prototype** in every footer, the API docs and the README.
- Detection details (why a document or message was flagged) go to staff and auditor views only. Citizens hear "a person will check".

## Stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync, psycopg 3), Alembic, PostgreSQL 16 with RLS and pgvector (Neon). Jobs are a Postgres table with `SKIP LOCKED`; there is no Redis. Frontend is Vite, Preact, TypeScript, Tailwind, PWA, served as static files by FastAPI. One Docker image. Reasons are in PLAN 5.1; do not reopen these choices.

## Commands (created in Phase 0; keep them working)

```
npm run install:all   # backend (uv sync) and frontend (npm install) dependencies
npm run migrate       # apply migrations
npm run seed          # idempotent seed; add -- --reset for a clean demo state
npm run dev           # API with reload on :8000 + Vite dev server on :5173
npm run verify        # lint, types, all tests, frontend build, bundle budget, mock-data lint
npm run verify:fast   # lint, types, DB-free tests, mock-data lint
npm run gen:api       # export OpenAPI and regenerate the typed frontend client
npm run db:stop       # stop the embedded dev database
cd backend && uv run pytest app/modules/<name> -q      # one module's tests
```

There is nothing to set up for the database in dev or test: with `DATABASE_URL_OWNER` unset the backend starts an embedded PostgreSQL 16 (the `pgserver` package). Read `docs/CONTRACTS.md` before your first change; it is the map of the foundation.

## Repo map and ownership

| Path | Owner |
|---|---|
| `backend/app/core`, `mocks`, `modules/{auth,tenancy,people,consent,cases,payments,notifications,webhooks,apikeys,sync,ussd}` | Track A |
| `backend/app/modules/{rules,decision,matching,evals,twin,anomaly,analytics}`, `backend/app/synth` | Track B |
| `backend/app/modules/{docs_ai,scam,rag,agent,guardrails,voice,memory}` | Track C |
| `frontend/src/citizen`, `frontend/src/shared` | Track D1 |
| `frontend/src/staff` | Track D2 |
| `backend/app/contracts`, `backend/app/db/models`, `backend/migrations`, `deploy`, CI | Lead |

Stay inside the directories you own. If you need a change elsewhere (a contract, a model, a migration, a shared component), write the request in `docs/REQUESTS.md` and tell the user; do not edit it yourself.

## Conventions

- **API**: `/v1`, RFC 7807 errors with `request_id`, cursor pagination with a cap, `Idempotency-Key` on creating POSTs, input models that forbid extra fields. Every route declares a policy; a test fails the build otherwise.
- **Database**: every table has `tenant_id` except the global identity tables (`plans`, `tenants`, `users`, `sessions`). Use the shared session dependency; it sets the RLS context per transaction. Commit explicitly when the work is done. Never build SQL from strings. Every mutation writes an audit row through `core.audit`.
- **Logic lives in pure functions** (decision, rules, matching, classifiers, guardrails) with DB-free tests that run in seconds. Integration tests are fewer and use Postgres.
- **Determinism**: synthetic data, training and evals take a fixed seed. A decision replayed from its snapshot must match exactly.
- **Text for citizens**: about grade 5 reading level, at most three short sentences, keyed by reason code, in English and Urdu, with an audio file. No free-form model text reaches a citizen outside a validated structure.
- **Frontend**: citizen route at most 100 KB gzipped JS; no third-party scripts loaded at runtime, chart libraries, map tiles or web fonts; every screen handles loading, empty, error, offline and permission-denied; tap targets at least 48 px; RTL correct. Staff screens are dense and tabular. Visual language is "Noor" (`docs/DESIGN.md`, decided by the owner on 21 Nov), unslopped at the owner's request on 22 Nov: quiet graphite chrome, noor gold as the one accent, no glow, gradients or uppercase tracked labels on chrome, colour only in content moments, one entrance per screen; WebGL only in the lazy `/live` chunk. No emoji as icons, placeholder text, or claims the live system cannot back; respect reduced motion.
- **Dependencies**: prefer boring, well-tested libraries; no custom crypto. Only the lead changes `pyproject.toml`, `package.json` or a lockfile (lockfile conflicts across branches are expensive): ask in `docs/REQUESTS.md`. Each new one is recorded with its licence in `docs/THIRD_PARTY.md`.

## Definition of done

A task is done when it works on the running app, has a test that you ran, is ticked in `docs/STATUS.md`, and is committed. Reading the code is not verification.

## How to work

- Small commits, one vertical slice each, with a clear message.
- Run `npm run verify:fast` before every commit and `npm run verify` before every merge.
- Report honestly at the end of a task: what you ran and its result, what failed, what you could not verify. Do not describe untested work as working.
- If blocked by an external service or key, build the interface and the local implementation, mark it `SIMULATED` in `docs/STATUS.md`, and continue.

## Dev machine notes

Windows 11, PowerShell, no Docker and no `make`. Python 3.14 is the default interpreter but the project pins **3.12** through `uv`. Use npm, not pnpm. Ruff allows 150 characters per line. A server started in the background keeps running after its task or terminal is stopped: free the port with `Get-NetTCPConnection -LocalPort 8000 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`. Never pass a bare `*` argument to a Python command-line tool on Windows (it is expanded into file names); use an environment variable instead. Force LF line endings (`.gitattributes`); a CRLF shell script will not run in the Linux container. Tesseract and ffmpeg may be absent locally: code must degrade gracefully and report the missing provider in `/v1/system/health`.
