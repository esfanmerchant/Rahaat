# Decisions

Short records of choices we must be able to defend to the judges. Newest at the bottom. Add one whenever you pick between real alternatives.

## 1. Build the whole brief in score order, not everything at once
**Context.** About 30 hours and an empty repository. Judges score live behaviour and say a half-finished feature is worth less than none.
**Decision.** Four tiers (PLAN section 4). Each tier is live before the next starts. A feature is demo-proof or hidden.
**Cost.** Enterprise extras (Kubernetes, read replicas, DAST) are documented as a scale path, not built.

## 2. Vite + Preact instead of Next.js
**Context.** The citizen flow must load on a weak connection. Our budget is 100 KB of JavaScript.
**Decision.** Preact (about 5 KB) with Vite; the static build is served by FastAPI.
**Why.** Next.js App Router ships most of that budget as framework code. One origin and one container also simplify cookies, the service worker and deployment.
**Cost.** No server rendering. The app shell is cached by the service worker after the first visit instead.

## 3. Postgres as the job queue instead of Redis + Dramatiq
**Decision.** A `jobs` table claimed with `SELECT ... FOR UPDATE SKIP LOCKED`; rate limits in process.
**Why.** One fewer service to deploy, monitor and debug in 30 hours. `enqueue()` keeps the same shape if Redis is added.
**Cost.** In-process limits assume one API process. That is how the prototype is deployed, and it is stated in the deploy notes.

## 4. Embedded Postgres for development and tests
**Context.** Dev machines are Windows with no Docker.
**Decision.** The `pgserver` package provides PostgreSQL 16 with pgvector; the backend starts it when `DATABASE_URL_OWNER` is unset.
**Why.** Every teammate and every agent gets a real Postgres with RLS and no setup. Tests run against the same engine as production.
**Cost.** A background Postgres process stays running on the dev machine (`npm run db:stop`).

## 5. Row Level Security with transaction-local context
**Decision.** The app connects as `rahat_app` (not owner, no BYPASSRLS). Policies read four settings set with `set_config(..., true)` at the start of every transaction. No context means no rows.
**Why.** Access control holds even if an endpoint forgets a filter, and it is safe under connection pooling.
**Honest limit.** The settings are chosen by the API process. RLS protects against application bugs and insecure direct object references; it does not protect against an attacker who fully controls the API process. A `system` context exists for sign-in lookups, the job dispatcher and the seed; every use is explicit and searchable.

## 6. Consent is checked inside the database
**Decision.** Tables holding a person's data carry a restrictive policy calling `app_can_read_person()`, which looks for the citizen themself, a live helper delegation, or an active consent held by the caller's department.
**Why.** "Withdrawal must truly stop access." With this, withdrawal takes effect on the next query for officers, helpers, API clients and workers, with no cache to invalidate.
**Consequence.** Admins and auditors cannot read raw personal records at all; auditors see redacted snapshots through the API.

## 7. One active tenant per token; users are global
**Decision.** `users`, `sessions`, `plans` and `tenants` are global. Every role, including citizen and helper, is a membership in a tenant, and each access token names exactly one tenant and role. Switching tenant re-issues the token and invalidates the old one.
**Why.** One uniform rule for every query: the tenant comes from the verified token, never from the request.

## 8. HS256 access tokens with a key ring, opaque rotating refresh tokens
**Decision.** Access tokens are HS256 with a pinned algorithm, `kid`, issuer and audience, valid for 10 minutes, and bound to a session row that is checked on every request. Refresh tokens are random, stored only as a hash, kept in an httpOnly SameSite cookie, rotated on every use; presenting an old one revokes the whole session family.
**Why not asymmetric keys.** One service signs and verifies, so a shared secret is simpler to deploy correctly in a weekend. The key ring allows rotation.
**Cost.** One extra indexed read per request to check the session. In return sign-out and revoke-all are immediate.

## 9. Explicit commits; ids and timestamps generated in Python
**Decision.** Endpoints call `db.commit()`; the request session rolls back anything left. No insert uses `RETURNING`.
**Why.** FastAPI may run dependency teardown after the response is sent, so a commit there could lose a race with the client's next request. `RETURNING` is checked against SELECT policies, which a freshly inserted person row cannot pass in the same statement.

## 10. Audit log: one hash chain per tenant, details stored as canonical text
**Decision.** Each row hashes its content and the previous hash. Appends take a per-tenant advisory lock. `details` is canonical JSON text. The app role cannot update or delete. A platform chain holds events that belong to no tenant, such as failed sign-ins.
**Why text.** JSONB normalises numbers and key order, so the bytes that were hashed could not be reproduced exactly.
**Honest limit.** A database owner can still rewrite the entire chain consistently. Anchoring the head elsewhere (the `audit_anchors` table now, an external store later) is what makes that detectable.

## 11. Sign-in gives nothing away
**Decision.** One generic error for wrong password and unknown account; a hash verification always runs; unknown identifiers lock out after the same number of failures as real accounts.
**Honest limit.** Citizens sign in with a mock phone number and a 4 to 6 digit PIN, protected by lockout. A real service would add a one-time code or device binding.

## 12. The API accepts only mock identifier formats
**Decision.** IDs must be `00000-NNNNNNN-C` with a Luhn check digit; phones must be `0999-NNNNNNN`. Anything else is refused at the edge, and CI fails on real-looking values in the repository.
**Why.** Real personal data disqualifies the team. The system cannot store it even by accident.

## 13. Contract stubs in dev and test only
**Decision.** `app/modules/zz_stubs` answers the spine API with fixed examples so the frontend tracks can start. It never loads when `APP_ENV` is `demo` or `prod`, and a real route always wins.
**Why.** Parallel work without ever showing fake behaviour to a judge.

## 14. Lint line length 150
**Decision.** Ruff allows 150 characters.
**Why.** Many lines carry Urdu strings and long keyword calls; wrapping them cost readability and time.

## 15. One lead session, track agents in isolated worktrees
**Context.** One person, one Claude seat, about 28 hours left.
**Decision.** The lead session fixes the cross-track contracts first (`app/contracts/engine.py`), then runs one agent per track in parallel, each in its own git worktree and branch. Agents commit to their branch; the lead merges, wires the tracks together and checks the gate by running the flow.
**Why.** In a shared working tree one agent's half-written file breaks every other agent's tests. Worktrees give each agent a consistent tree, and hooks (`router.py`, `seed_step.py`, `lifecycle.py`) mean no two agents edit the same file.
**Cost.** A merge and integration step after every wave, done by the lead.

## 16. Urdu is the voice language; no Sindhi
**Context.** The brief asks for speech in "Urdu or a regional language". Nobody on the team speaks a regional language other than Urdu.
**Decision.** Ship Urdu (prompts, speech input, read-back) and English. Remove the Sindhi option.
**Why.** A language nobody can check is a half-finished feature shown to judges who may speak it. Urdu already meets the requirement.

## 17. Payments: a second person above Rs 15,000
**Decision.** A payment at or below the tenant's limit (seeded at Rs 15,000) is released as soon as the decision is approved, whether by the engine alone or by an officer. Above the limit a second person, different from whoever approved the case, must release it. The limit is tenant configuration.
**Why.** The standard Rs 12,000 payment must be able to complete without a human when the engine is confident enough, otherwise nothing ever "acts alone". Larger amounts keep maker-checker. Lowering the limit in the demo shows the gate.

## 18. RapidOCR is the default OCR; Gemini is an optional first speech provider
**Decision.** `rapidocr-onnxruntime` 1.4.4 (Apache-2.0, PP-OCR ONNX models bundled in the wheel) is tried first for the printed card fields, then Tesseract, then nothing. It runs the recogniser only, on each field band. opencv stays headless: uv `override-dependencies` drops `opencv-python` and the direct `opencv-python-headless` dependency supplies `cv2`, so the slim image needs no libGL and no apt change. Gemini (REST through httpx, key only in a header) is tried before Groq when `GEMINI_API_KEY` is set; it gives no confidence, so a spoken answer from it is always read back for confirmation.
**Why.** Tesseract is not installed on dev machines, so the OCR-versus-QR mismatch signal never fired locally. RapidOCR needs no binary and no network. With no key, speech behaves as before.
