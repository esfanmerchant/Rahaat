# Deploying Rahat

Prototype. Not an official service. All identity, payment and data services are simulated.

Try the hosts in this order. Give each one at most 40 minutes, then move to the next. The database is the same free Neon Postgres in every case.

## 0. Shared setup (do this once)

### 0.1 Create the database on Neon

1. Sign up at https://neon.tech (free plan, no card).
2. Create a project. Pick Postgres 16 and the region closest to your host.
3. Open the project dashboard and click **Connect**. Turn **Connection pooling OFF** so you see the **direct** connection string (the host has no `-pooler` in it). It looks like `postgresql://USER:PASSWORD@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`.
4. That string is your `DATABASE_URL_OWNER`. Keep it secret.
5. Do nothing else. On first start the migration creates a low-privilege role called `rahat_app` (using `APP_DB_PASSWORD`). The app connects as `rahat_app`, never as the owner, so you do not need to set `DATABASE_URL`.

### 0.2 Generate the secrets

Run each on any computer with Python and paste the output into the host's settings:

```
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

In order, these are `SECRET_KEY`, `MASTER_KEY` and `APP_DB_PASSWORD`. `APP_ENV=demo` refuses to start with default or empty secrets. Never commit them.

### 0.3 Environment variables (every host)

| Variable | Value |
|---|---|
| `APP_ENV` | `demo` |
| `DATABASE_URL_OWNER` | Neon direct connection string |
| `APP_DB_PASSWORD` | generated above |
| `SECRET_KEY` | generated above |
| `MASTER_KEY` | generated above |
| `PORT` | `8000` (the image default) |
| `AI_PROFILE` | `full` (`lite` on Render) |
| `GROQ_API_KEY`, `ANTHROPIC_API_KEY` | optional; leave out to use the local models |

The image sets `FRONTEND_DIST` and `MOCK_BASE_URL` itself.

### 0.4 Check it works (any host)

```
curl -i https://YOUR-URL/healthz
```

You want `200`. Also open `https://YOUR-URL/` and `https://YOUR-URL/docs` in a browser.

### 0.5 Reset demo data

The start script seeds only when the database is empty. For a clean demo state run the seed with `--reset`: inside the container (host sections below) or from your own PC against Neon, in PowerShell from the repo root:

```
$env:DATABASE_URL_OWNER = "postgresql://...neon direct string..."
$env:APP_DB_PASSWORD = "..."
npm run seed -- --reset
```

## 1. Azure for Students VM + Docker + Caddy (preferred, about 45 minutes)

Cost: $0 from the student credit. Free HTTPS name like `rahat-demo.southeastasia.cloudapp.azure.com`.

### 1.1 Create the VM

1. Sign in at https://azure.microsoft.com/free/students with your university email.
2. Portal, **Create a resource**, **Virtual machine**:
   - Image: **Ubuntu Server 24.04 LTS**
   - Size: **Standard_B2ms** (2 vCPU, 8 GB), or B2s (4 GB) if that is all you get
   - Authentication: SSH public key (download the `.pem`), username `azureuser`
   - Inbound ports: allow **SSH (22), HTTP (80), HTTPS (443)**
3. After creation open the VM's **Public IP address** resource, **Configuration**, and set a **DNS name label**, for example `rahat-demo`. Your host name is then `rahat-demo.<region>.cloudapp.azure.com`.

### 1.2 Install Docker

```
ssh -i path/to/key.pem azureuser@rahat-demo.<region>.cloudapp.azure.com
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Log in again so the group change applies.

### 1.3 Get the code and configure

```
git clone https://github.com/YOUR-ORG/YOUR-REPO.git ~/rahat
cd ~/rahat/deploy/azure-vm
cp ../../.env.example .env
nano .env
```

In `.env` set the variables from 0.3 and add the line `DOMAIN=rahat-demo.<region>.cloudapp.azure.com`. Save with Ctrl+O, Enter, Ctrl+X.

### 1.4 Start

```
./deploy.sh
```

The first build takes several minutes. Caddy fetches the HTTPS certificate on the first request (ports 80 and 443 must be open).

### 1.5 Check, update, reset

```
curl -i https://rahat-demo.<region>.cloudapp.azure.com/healthz
docker compose logs -f app
cd ~/rahat/deploy/azure-vm && ./deploy.sh
docker compose exec app sh -c "cd /app/backend && uv run --no-sync python -m app.seed --reset"
```

These are: check health, follow logs, pull and rebuild after a push, reset demo data. To save credit, **Stop** the VM in the portal when you are not demoing, and start it again before.

## 2. Hugging Face Docker Space (simplest; needs PRO and a card)

Hugging Face reads its configuration from a front-matter block at the top of the repo `README.md`, and the app port must be declared with `app_port: 8000`. The ready-made block is `deploy/hf-space/README.header.md`.

1. Create an account at https://huggingface.co, then **New Space**: SDK **Docker**, blank template, the largest CPU hardware your plan gives you.
2. In the Space, **Settings**, **Variables and secrets**: add the variables from 0.3 as **Secrets**.
3. Push the code. Manual way:

```
git clone https://huggingface.co/spaces/YOUR-USER/rahat hf-rahat
```

   Copy the repo contents into `hf-rahat` (everything except `.git`), then build its `README.md` from the header plus the real README, and push:

```
cat deploy/hf-space/README.header.md README.md > hf-rahat/README.md
cd hf-rahat
git add -A
git commit -m "deploy"
git push
```

4. Automatic way: copy `deploy/hf-space/sync-to-hf.yml.example` to `.github/workflows/sync-to-hf.yml`, add the GitHub secret `HF_TOKEN` (a Hugging Face write token) and the repository variable `HF_SPACE` (`YOUR-USER/rahat`). Every push to `main` then syncs. It stays an example until you copy it, so it never runs without secrets.
5. Wait for the Space to show **Running**. URL: `https://YOUR-USER-rahat.hf.space`.
6. Check: `curl -i https://YOUR-USER-rahat.hf.space/healthz`.
7. Reset demo data: the Space has no shell. Run the reset from your PC against Neon (0.5), then restart the Space from its Settings page.

## 3. This Windows PC + a tunnel (the current live demo, and Monday's Plan C)

Cost: $0. No Docker and no database account: the database is an embedded PostgreSQL on this PC. The PC must stay on, awake and online for the URL to work.

### 3.1 Commands (PowerShell or any terminal, from the repo root)

| Command | What it does |
|---|---|
| `npm run live:start` | Builds a release of `main` in `.live\app`, starts the database, the API on `127.0.0.1:8080` and a tunnel, and prints the public URL |
| `npm run live:update` | Moves the release to the newest `main` commit, migrates and restarts the API. The tunnel keeps running, so the URL stays the same |
| `npm run live:status` | What is running, the local and public health checks, and the URL |
| `npm run live:reset` | Wipes and reseeds the live demo data |
| `npm run live:stop` | Stops the API, the mock services and the tunnel. The data is kept |

Everything is in `.live\` (git-ignored): the release worktree, the database files, logs, the tunnel program and `secrets.env`, whose secrets are generated on the first start. Never commit or share that folder. Logs are in `.live\logs`.

The release is a separate git worktree pinned to one commit, so merging into `main` never changes the running site until you run `live:update`.

### 3.2 Before it is public

- Keep the PC awake while plugged in, from an administrator PowerShell: `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0`.
- After a reboot run `npm run live:start` again.
- The API listens on `127.0.0.1` only. Nothing on your network reaches it except through the tunnel, and uvicorn trusts forwarded headers only from `127.0.0.1`, which is the tunnel program. Do not add `--forwarded-allow-ips "*"`: on Windows uvicorn turns `*` into the file names in the folder and refuses to start.
- The embedded database also listens on `127.0.0.1` only and trusts local connections, so its password is not checked. Acceptable for a demo on one PC; a real deployment uses a managed database with passwords (sections 1 and 2).

### 3.3 Tunnel A: Cloudflare quick tunnel (default, no account)

`live:start` downloads the official `cloudflared` build (version and SHA-256 pinned in `deploy/local/live.ps1`, checked before it runs) and opens a quick tunnel. The URL looks like `https://some-random-words.trycloudflare.com`. It changes whenever the tunnel restarts: after `live:stop`, a reboot, or a crash. Quick tunnels do not carry server-sent events, so live screens fall back to polling.

### 3.4 Tunnel B: Tailscale Funnel (stable URL, use it for the submission)

1. Install Tailscale from https://tailscale.com/download and sign in.
2. In the admin console (https://login.tailscale.com/admin), turn on **HTTPS certificates** (DNS page) and allow Funnel for this device (Access controls).
3. `npm run live:stop`, then `powershell -NoProfile -ExecutionPolicy Bypass -File deploy/local/live.ps1 start -Tunnel tailscale`.

The URL is `https://YOUR-PC.YOUR-TAILNET.ts.net` and stays the same across restarts and reboots.

### 3.5 Check it from outside

```
curl.exe -i https://YOUR-URL/healthz
curl.exe https://YOUR-URL/v1/demo/accounts
```

Then open the URL on a phone on mobile data, not your Wi-Fi.

## 4. Render free web service (last resort, `AI_PROFILE=lite`)

512 MB of RAM, so `lite` is required. The service sleeps after 15 minutes idle; the first request after that takes about a minute.

1. Push the repo to GitHub. Sign up at https://render.com with GitHub.
2. **New**, **Blueprint**, pick the repo. Render looks for `render.yaml` at the repo root, so copy it there on a deploy branch (`cp deploy/render.yaml render.yaml`), or create a **Web Service** by hand with Runtime **Docker** and the same settings as in `deploy/render.yaml`.
3. Render asks for the four values marked `sync: false`: `DATABASE_URL_OWNER`, `APP_DB_PASSWORD`, `SECRET_KEY`, `MASTER_KEY` (see 0.1 and 0.2). `AI_PROFILE=lite` and `APP_ENV=demo` are already in the file.
4. Deploy. URL: `https://rahat.onrender.com` (or the name Render assigns).
5. Check: `curl -i https://YOUR-SERVICE.onrender.com/healthz`.
6. Keep it awake with a free pinger (for example UptimeRobot, 5 minute interval) on `/healthz`.
7. Reset demo data: the free plan has no shell. Run the reset from your PC against Neon (0.5).

## Troubleshooting

- Container exits at once: read the logs. A message about default secrets means `SECRET_KEY` or `MASTER_KEY` is missing.
- Migration cannot connect: you used the pooled Neon string, or dropped `?sslmode=require`. Use the direct string.
- A shell script fails with `^M` or "not found": it has CRLF line endings. Run `git add --renormalize .`; `.gitattributes` forces LF.
