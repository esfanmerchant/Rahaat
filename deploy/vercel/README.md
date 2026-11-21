# Deploying Rahat on Vercel

Prototype. Not an official service. All identity, payment and data services are simulated.

This is an optional host. The PC with the Cloudflare tunnel and the Docker image keep working exactly as before: every Vercel difference is a setting whose default is today's behaviour (DECISIONS 19).

## How it is wired

| Part | Where |
|---|---|
| Frontend (`frontend/`, built to `frontend/dist`) | Vercel CDN. Missing paths fall back to `index.html`. Security and cache headers come from `vercel.json`, with the same values as `core/middleware.py`. |
| API (`backend/app`) | One Python 3.12 function, `api/index.py`, region `bom1` (Mumbai), `maxDuration` 60 s. `vercel.json` rewrites `/v1/*`, `/healthz`, `/readyz`, `/metrics`, `/docs`, `/redoc`, `/openapi.json` to it. |
| Python packages | Root `requirements.txt`, generated from `backend/uv.lock` by `npm run vercel:requirements` (runtime packages only). |
| Database | Supabase Postgres 17 (ap-south-1) through the session pooler. Migrated and seeded from this PC, never on Vercel. |
| Not in the bundle | `frontend/`, `docs/`, `deploy/`, `scripts/`, tests, `backend/migrations`, `data/demo_cards`, `.wt`, `.live`, `node_modules`, virtual environments (`vercel.json` `excludeFiles` and `.vercelignore`). |

Installed size is about 456 MB for the Linux wheels (limit 500 MB), measured with `uv pip install --target` for `manylinux_2_28`, Python 3.12. That is close to the limit, which is why the RapidOCR stack (about 100 MB) is left out; see "What behaves differently".

## Settings used on Vercel

Set by `push-env.ps1`; defaults elsewhere are unchanged.

| Setting | Value | Why |
|---|---|---|
| `APP_ENV` | `demo` | Refuses to start on default secrets. |
| `JOBS_MODE` | `inline` | No worker thread on a serverless function. |
| `MOCKS_IN_PROCESS` | `true` | Mock services run inside the function; nothing listens on 9001. |
| `CLIENT_IP_HEADER` | `x-vercel-forwarded-for` | Vercel overwrites this header on every request (it states it does so to prevent IP spoofing), so rate-limit lanes and sign-in lockouts see the real client. `x-real-ip` and `x-forwarded-for` hold the same value; `x-vercel-forwarded-for` is the one that is not rewritten by a proxy placed in front of Vercel. |
| `STARTUP_WARMUP` | `false` | Models, OCR and the corpus load on first use, not at every cold start. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `2` / `1` | See "Pool sizing". |
| `UPLOAD_DIR` | `/tmp/rahat-uploads` | The deployment filesystem is read-only except `/tmp`; unused while `DOCUMENT_STORE=db`. |
| `DOCUMENT_STORE` | `db` | Uploads go to the `document_blobs` table: `/tmp` is not shared between instances, so a file written by one would be missing on another. |
| `DB_POOLER_MODE` | `transaction` | No client-side pool and no prepared statements; `DATABASE_URL_OWNER` uses Supabase's transaction pooler (port 6543). The session pooler caps clients at 15, and on Sat 21 Nov a burst of sign-ins across instances exhausted it (`EMAXCONNSESSION`, 500s for minutes). |
| `CRON_SECRET` | generated | Vercel Cron sends it as `Authorization: Bearer ...` to `GET /v1/admin/jobs/drain`. |
| `DATABASE_URL_OWNER` | from `SUPABASE_URL_OWNER` | The app role's URL is derived from it (`rahat_app.<ref>`); the app never runs as the owner. |
| `SECRET_KEY`, `MASTER_KEY`, `APP_DB_PASSWORD`, `MOCK_*_KEY` | copied from `.live\secrets.env` | The Supabase data was seeded with these exact values. Changing any of them breaks sign-in and decryption. |
| `GEMINI_API_KEY` | copied if present | Optional speech-to-text. |

## Steps

Run everything from the repository root in PowerShell. Nothing here is run for you.

1. **Get a token.** In Vercel: Account Settings, Tokens, create one. Add the line `VERCEL_TOKEN=...` to `.live\secrets.env`. Never commit that file.

2. **Check the generated files are current.**
   ```powershell
   npm run vercel:requirements -- --check
   ```
   If it fails, run `npm run vercel:requirements` and commit `requirements.txt`.

3. **Link the project.** Put the token in the environment for this shell only, without printing it:
   ```powershell
   $env:VERCEL_TOKEN = ((Get-Content .live\secrets.env | Where-Object { $_ -like 'VERCEL_TOKEN=*' }) -split '=', 2)[1]
   npx --yes vercel@66.6.0 link --yes --project rahat
   ```
   This creates `.vercel/` (git-ignored). In the project settings, leave Framework Preset on **Other**; `vercel.json` sets the install and build commands and the output directory.

4. **Push the environment variables.** Dry run first (prints names only, changes nothing):
   ```powershell
   npm run vercel:push-env -- -DryRun
   npm run vercel:push-env
   ```
   Values are sent on standard input and never printed. `CRON_SECRET` is regenerated each run, so redeploy after running it again.

5. **Deploy.**
   ```powershell
   npx --yes vercel@66.6.0 deploy --prod
   ```

6. **Migrations and seed (from this PC, against Supabase).** Supabase is already migrated and seeded; repeat only after a schema change or to restore the demo state. Load the values into this shell, then use the normal scripts:
   ```powershell
   Get-Content .live\secrets.env | Where-Object { $_ -match '^[A-Z_]+=' } | ForEach-Object {
     $k, $v = $_ -split '=', 2
     Set-Item -Path "Env:$k" -Value $v
   }
   $env:DATABASE_URL_OWNER = $env:SUPABASE_URL_OWNER
   $env:APP_ENV = 'demo'
   npm run migrate
   npm run seed -- --if-empty        # or: npm run seed -- --reset   (wipes the demo data)
   ```
   Open a new shell afterwards so these variables do not leak into other work.

7. **Check the deployment.** Replace the URL with the one the deploy printed:
   ```powershell
   curl.exe -s -o NUL -w "healthz %{http_code}\n" https://YOUR-APP.vercel.app/healthz
   curl.exe -s -o NUL -w "readyz  %{http_code}\n" https://YOUR-APP.vercel.app/readyz
   curl.exe -s -o NUL -w "home    %{http_code}\n" https://YOUR-APP.vercel.app/
   curl.exe -s -o NUL -w "docs    %{http_code}\n" https://YOUR-APP.vercel.app/docs
   curl.exe -sI https://YOUR-APP.vercel.app/ | Select-String "content-security-policy|cache-control|x-frame"
   ```
   Expect 200 for all four. `readyz` 503 means the function cannot reach the database: check `DATABASE_URL_OWNER` and the pool numbers. Then sign in with a demo account and run the anchor flow once.

## How jobs behave

With `JOBS_MODE=inline` there is no worker thread. When a request queues a job (SMS, payment), the middleware, after the endpoint has committed and before the last response byte, runs due jobs for at most 5 seconds or 25 jobs (`JOBS_INLINE_BUDGET_SECONDS`, `JOBS_INLINE_MAX_JOBS`). The client therefore waits for them, usually tens of milliseconds. This is deliberate: Vercel documents no way to run Python work after the response, and a frozen function may never finish it. Jobs waiting for a retry, or beyond the budget, run on the next request that queues work or on the Vercel Cron call. `vercel.json` schedules it once a day (`0 0 * * *`), the most the Hobby plan allows; on a paid plan change it to `*/5 * * * *`.

## What behaves differently

- **Mock services are per instance.** Failure injection set on the mocks page, the SMS outbox and the payment ledger of the mock live in each function instance's memory, so a setting may apply to only some requests and is lost when an instance is recycled. Real data (applications, payments, notifications) is in Postgres and unaffected. For a failure-injection demo, set the control and repeat the action; to be sure, keep traffic to one instance (a single browser tab and no parallel load).
- **Uploaded documents are in Postgres.** With `DOCUMENT_STORE=db` the bytes go into `document_blobs` in the same transaction as the document row (migration 0008), so every instance can serve them and erasure deletes them with the document.
- **No OCR.** The RapidOCR stack is not in the Vercel bundle (size limit). The document check reports OCR as unavailable and still verifies the signed QR; the printed-text mismatch signal does not fire. `npm run vercel:requirements -- --with-ocr` keeps it, but the function then exceeds 500 MB unless Large Functions are enabled on the account.
- **Cold start.** With `STARTUP_WARMUP=false` the first request after a cold start loads the app (about 6 s locally from process start to the first `/readyz`, which includes the Python start and a database connection). The first decision trains the evidence model on demand (about 1 s extra locally; the first submit took 2.7 to 3.5 s). `maxDuration` is 60 s, well above this.
- **Rate limits are per instance** (in-memory), as on any multi-process host; they are per real client address because of `CLIENT_IP_HEADER`.

## Pool sizing

Supabase session mode allows about 15 client connections in total. Each function instance keeps its own pool of `DB_POOL_SIZE` plus up to `DB_MAX_OVERFLOW` extra connections, and several instances can run at once. Recommended for Vercel: `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=1`, so an instance holds at most 3 and five instances stay at the cap. Raise them only after checking how many instances run (Vercel Observability) and keep instances times (pool plus overflow) under 15 minus your own psql sessions. If you see `remaining connection slots` errors, lower the numbers or move to Supabase's transaction pooler.

## What is not verified yet

Nothing in this folder has been deployed. Unverified until the first real deploy: that Vercel passes the original request path to the function after the rewrite, the real installed bundle size, the latency of bom1 to the Supabase region, and the Cron call.
