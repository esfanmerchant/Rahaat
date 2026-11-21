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

## 3. This Windows PC + a tunnel (also Monday's Plan C)

Cost: $0. The PC must stay on, awake and online. This runs natively, no Docker.

### 3.1 Prepare

```
npm run install:all
npm --prefix frontend run build
```

### 3.2 Run in demo mode (PowerShell, from the repo root)

```
$env:APP_ENV = "demo"
$env:DATABASE_URL_OWNER = "postgresql://...neon direct string..."
$env:APP_DB_PASSWORD = "..."
$env:SECRET_KEY = "..."
$env:MASTER_KEY = "..."
$env:FRONTEND_DIST = "$PWD\frontend\dist"
npm run migrate
npm run seed -- --if-empty
Start-Process -NoNewWindow uv -ArgumentList "run","--directory","backend","uvicorn","app.mocks.main:app","--host","127.0.0.1","--port","9001"
uv run --directory backend uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers
```

Skip the `Start-Process` line until `backend/app/mocks/main.py` exists. Check locally with `curl.exe -i http://127.0.0.1:8000/healthz`. In Windows power settings, make the PC never sleep.

The API listens on `127.0.0.1` only, so nothing on your network can reach it except through the tunnel, and the tunnel program on the same PC is the one address uvicorn trusts for forwarded headers by default. Do not add `--forwarded-allow-ips "*"` on Windows: uvicorn's command line turns `*` into the file names in the folder and refuses to start.

### 3.3 Tunnel A: Tailscale Funnel (stable URL, recommended)

1. Install Tailscale from https://tailscale.com/download and sign in.
2. In the admin console (https://login.tailscale.com/admin), enable **HTTPS certificates** (DNS page) and allow Funnel for your device (Access controls).
3. In a new PowerShell window:

```
tailscale funnel --bg 8000
tailscale funnel status
```

   The URL is `https://YOUR-PC.YOUR-TAILNET.ts.net` and stays the same every time.
4. Stop it with `tailscale funnel reset`.

### 3.4 Tunnel B: Cloudflare quick tunnel (no account, fallback)

```
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8000
```

It prints a random `https://something.trycloudflare.com` URL that changes on every run. Quick tunnels do **not** support server-sent events (SSE), so live-streaming screens will not update. Prefer Tailscale.

### 3.5 Check and reset

```
curl.exe -i https://YOUR-TUNNEL-URL/healthz
npm run seed -- --reset
```

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
