# Deploying to production

## No domain? Pick one (all give you HTTPS)
| Option | You need | Steps | Notes |
|---|---|---|---|
| **Fly.io** (recommended for a private repo) | a Fly account (card on file), `flyctl` | `fly launch --copy-config --no-deploy --name <unique>`, `fly secrets set ...`, `fly deploy` (see `fly.toml`) | Builds from your local checkout, no GitHub access needed. Address: `https://<name>.fly.dev`. |
| **Render** | a Render account; the Render GitHub app authorised on the org (an owner approves) | New > Blueprint > pick the repo (`render.yaml`), fill the three secrets | Address: `https://<name>.onrender.com`. Use the `starter` plan, free sleeps when idle. |
| **Any VPS + free hostname** | a server with a public IP | `APP_DOMAIN=<ip-with-dashes>.sslip.io` (e.g. `203-0-113-10.sslip.io`), then the VPS steps below | No DNS to buy or configure; Caddy issues the certificate for that hostname. |
| **Quick demo only** | a laptop | `cloudflared tunnel --url http://localhost:8000` | Temporary URL that changes each run, only while the laptop is on. Not production. |

On Fly, Render and Railway the app learns its own address from the platform, so `APP_URL` is optional there. After
the first deploy, add that exact address to Supabase (Site URL, and `<address>/api/auth/callback` under Redirect
URLs). Use the exact URL, never a wildcard like `*.onrender.com`: that would let anyone's app on that host receive
sign-in codes.

---

## VPS: Docker Compose + Caddy

Caddy terminates HTTPS (automatic Let's Encrypt certificates) and proxies to the app container. The app keeps no
user data on disk beyond scan working copies; accounts and data live in Supabase.

## What you need before starting
| Item | Notes |
|---|---|
| A server with Docker and the compose plugin | Ubuntu 22.04+ is fine. 1 GB RAM minimum, 2 GB recommended. |
| A domain name | An A (and AAAA) record pointing at the server's public IP. Example: `paladin.example.com`. |
| Ports 80 and 443 open | Both. Caddy needs 80 to obtain certificates. |
| The Supabase project | URL, publishable key, service key (see `README.md`, Sign-in). |

## 1. Production `.env` (repo root, next to `docker-compose.yml`)
```bash
APP_DOMAIN=paladin.example.com
APP_URL=https://paladin.example.com
COOKIE_SECURE=1

SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<publishable key>
SUPABASE_SERVICE_KEY=<service key>      # server only

# optional
ANTHROPIC_API_KEY=
GITHUB_APP_ID= ... (see .env.example; leave empty to disable private-repo access)
```
Rules that cause real outages if broken: `APP_DOMAIN` must equal the host in `APP_URL`; `COOKIE_SECURE` must be `1`;
`ALLOWED_ORIGINS` and `DESKTOP_MODE` must be unset. Do not copy `backend/.env` (it is the dev file, with `http`
URLs). `chmod 600 .env`, never commit it (`.dockerignore` already keeps it out of the image).

## 2. Supabase configuration for the production domain
Supabase > Authentication > URL Configuration:
- **Site URL:** `https://paladin.example.com`
- **Redirect URLs:** add `https://paladin.example.com/api/auth/callback` (keep the localhost and desktop entries)

The GitHub OAuth app does not change: its callback stays `https://<project-ref>.supabase.co/auth/v1/callback`.
If you use the GitHub App for repository access, add its production callback
`https://paladin.example.com/api/github/callback` to that app.

## 3. Preflight (on your machine or the server)
```bash
backend/.venv/bin/python scripts/check_signin.py --production --env .env
```
Every line must be `ok` (a `warn` for "not reachable yet" is expected before the first deploy). It checks: https
`APP_URL`, `APP_DOMAIN` match, secure cookies, service key present, project reachable, GitHub provider enabled,
migrations applied, and, once deployed, that `/health` and `/api/config` answer and sign-in is configured.

## 4. First deploy
```bash
git clone https://github.com/Manipal-Hackathon-2026/DATUM.git paladin && cd paladin
# create .env as above
./deploy.sh main            # git pull, then: docker compose up -d --build caddy apc-main
docker compose ps           # apc-main and caddy should be "healthy" / "running"
docker compose logs -f caddy   # watch the certificate being issued
```
Then re-run the preflight; it will now also test the live site. Open `https://paladin.example.com`, click **Sign In
with GitHub**, complete it, and confirm you land on Home.

## 5. Updating
`./deploy.sh main` pulls `main` and rebuilds. Roll back with `git checkout <previous-sha> && docker compose up -d --build apc-main`.
The frozen bug-bounty build is `./deploy.sh bounty` (separate container and `BOUNTY_DOMAIN`).

## Common failures
| Symptom | Cause |
|---|---|
| Login bounces back with an error at the end | the production callback is missing from Supabase's Redirect URLs |
| Certificate never issues | port 80 closed, or DNS not yet pointing at this server |
| "Sign-in is not set up" | `.env` not at the repo root, or `SUPABASE_*` empty (preflight shows which) |
| Signed in but data calls fail | migrations not applied (`supabase/migrations/0001..0003`) |
| Cookie not kept | `COOKIE_SECURE=0` or `APP_URL` is http |
