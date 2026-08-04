# Deploy checklist — LitPilot (v4.4.x)

Operator-facing steps to run a clean host. Product scope stays multi-library +
student starting point; optional SMTP, quota, and SQLCipher are deploy options.

Copy variables from [`.env.example`](../.env.example). Never commit `.env` or
provider secret dumps (`mailersend-*.txt`, etc.).

**Current public hostname (self-host):** `https://litpilot.duckdns.org`  
See also **[SELFHOST.md](SELFHOST.md)** (DuckDNS token, Pi-hole on :80/:443, tunnel vs port-forward, light TLS).

---

## 1. Runtime

| Item | Value |
|------|--------|
| Python | **3.14** (matches CI, Docker, Render) |
| Entrypoint | `uvicorn app.main:app --host 0.0.0.0 --port <PORT>` |
| Default port | `7860` (Docker / HF Spaces); Render uses `$PORT` |
| Health check | `GET /health` → `200` and JSON `status: healthy` |
| App version | `GET /health` → `version` (also in OpenAPI) |

**Docker**

```bash
docker build -t litpilot .
docker run -p 7860:7860 \
  -e SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  litpilot
curl -sS http://127.0.0.1:7860/health
```

**Render** — `render.yaml` sets `PYTHON_VERSION=3.14`, generates `SECRET_KEY`,
starts uvicorn on `$PORT`, health check `/health`. Add other env vars in the
dashboard (SMTP, `PUBLIC_BASE_URL`, quota, etc.).

**Local dev** — prefer `./run_dev.sh` (`DEBUG=true`, reload). Do not use that
profile as a public HTTPS deploy.

### Self-host on this machine (DuckDNS)

Target origin: **`https://litpilot.duckdns.org`**

App env (gitignored `.env`):

```bash
DEBUG=false
PUBLIC_BASE_URL=https://litpilot.duckdns.org
SECRET_KEY=…          # already required
MAX_LOADED_MODELS=3   # shared embedding weights; keep small on one box
# SMTP_* optional — trial MailerSend From is fine; links use PUBLIC_BASE_URL
```

Run the app **bound to localhost** (not exposed on the LAN) and put a tunnel
or reverse proxy in front:

```bash
# Production-ish process (no --reload)
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 7860
```

**Cloudflare Tunnel (`cloudflared`)** — recommended for a home box:

- Does **not** require opening router ports.
- Adds a small amount of latency (typically tens of ms RTT), not seconds.
  Search/embeddings still run **on this machine**; the tunnel only carries
  HTTP. That lag is negligible next to model load or a multi-source fetch.
- TLS is terminated at Cloudflare; set `DEBUG=false` so Secure cookies work.
- Point the tunnel public hostname at `http://127.0.0.1:7860`.
- DuckDNS alone only maps a name → IP. With a tunnel you still need DNS that
  reaches Cloudflare (CNAME to the tunnel, or a Cloudflare-managed zone). If
  you only update a DuckDNS **A record** to your home IP, you are on the
  port-forward path instead (below).

**DuckDNS token** — useful when:

- Your public IP is **dynamic**, and
- DuckDNS holds an **A record** for `litpilot` that must track that IP
  (port-forward / direct-to-home path).

Store the token only in a gitignored file or env (e.g. `DUCKDNS_TOKEN=`), never
in the repo. A cron/`systemd` timer can hit DuckDNS’s update URL periodically.
The token is **not** required for the LitPilot app process itself and is
**not** needed if DNS for the public hostname is handled entirely by
Cloudflare Tunnel config (no A-record chasing).

**Port-forward path** (no tunnel): router :443 → host, Caddy/nginx + Let’s
Encrypt, DuckDNS A record + token updater. More router work; similar app
performance; slightly lower RTT than a tunnel for nearby clients.

### Efficiency on one machine (same performance level)

| Knob | Why |
|------|-----|
| **One uvicorn worker** | Extra workers each load torch/models (multiplies RAM). |
| `MAX_LOADED_MODELS=3` | Caps concurrent embedding models in the shared registry. |
| Shared model registry | Already in app — concurrent users share weights. |
| `EMBEDDING_DEVICE` | Leave auto, or set `cuda` if you have a GPU. |
| `MAX_USER_STORAGE_MB` | Default 500; lower if disk is tight and the site is public. |
| No `--reload` in prod | Reload doubles process churn. |
| Bind `127.0.0.1` | Only the tunnel/proxy should face the network. |

Heavy work (fetch, embed, cluster) is CPU/GPU and disk on this host either way;
the edge path only shuttles bytes.

---

## 2. Required secrets

### `SECRET_KEY` (required when `DEBUG=false`)

- Signs JWT session cookies.
- Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- Store in the host secret manager (Render env, HF secret, Docker `-e`, never git).
- Rotating it invalidates all sessions and can drop unreadable AI keys at rest
  (keys are derived via HKDF from `SECRET_KEY`).

Without `SECRET_KEY` and with `DEBUG=false`, the process **refuses to start**.

### `DEBUG`

| Value | When |
|-------|------|
| `false` (default) | Real HTTPS hosts (Render, HF Spaces, reverse-proxy TLS) |
| `true` | Local plain `http://localhost` only |

Effects of `DEBUG=true`:

1. App may start without `SECRET_KEY` (tokens still need a key to log in).
2. Auth cookies are **not** `Secure` (browsers store them on http).
3. Password-reset codes may be shown on screen when SMTP is off
   (`RESET_CODES_IN_RESPONSE` can force that on a non-DEBUG host).

With `DEBUG=false` over plain http, login appears to succeed then bounce back
to login — browsers drop `Secure` cookies. That is expected; use HTTPS or
`DEBUG=true` only for local work.

---

## 3. Recommended host settings

### `PUBLIC_BASE_URL`

Public origin users type in the browser, **no trailing slash**.

- Local: `http://localhost:7860`
- Production: `https://your-host.example`

Used in recovery-email verification and reset links. Wrong value → links in
mail point at the wrong host.

### Storage quota — `MAX_USER_STORAGE_MB`

- Default **500** (MB per account under `user_data/<uid>/`).
- **`0`** = unlimited (fine for single-user local).
- Over cap: fetch / prepare / sample-corpus return **HTTP 507**.

### Memory — `MAX_LOADED_MODELS`

Embedding models are shared across all users in one process, so RAM scales with
the number of **distinct models in use**, not the number of people signed in.
Measured on CPU: ~175 MB for imports, then a one-time ~1.1–1.4 GB on the first
model load (that is the torch runtime, not the weights), and roughly **0 MB per
extra concurrent user**.

- Default **3** resident models; raise only if you genuinely offer more.
- Budget roughly **2 GB** for a single-model instance, plus ~0.3–0.5 GB per
  additional distinct model students select.
- Note the app runs a **single uvicorn worker** — adding `--workers N`
  multiplies all of the above by N, since each worker is a separate process
  with its own copy.

### Extra embedding models — `EXTRA_EMBEDDING_MODELS`

Request bodies may only name models from the built-in catalog (anything else is
rejected with HTTP 422), so users cannot make the server download arbitrary
models. To offer more, allow-list them here — comma-separated, either
`shortname=org/model` or a bare `org/model`:

```
EXTRA_EMBEDDING_MODELS=biolink=michiyasunaga/BioLinkBERT-base
```

They must work with plain cosine similarity (no query/passage prefixes), since
search, clustering, and dedup all compare vectors directly.

### Optional outbound email (SMTP)

Leave `SMTP_HOST` empty → recovery-email UI stays off; password reset keeps the
on-screen code path when DEBUG / `RESET_CODES_IN_RESPONSE` allows it.

| Variable | Notes |
|----------|--------|
| `SMTP_HOST` | e.g. `smtp.mailersend.net` |
| `SMTP_PORT` | `587` (STARTTLS) or `465` (`SMTP_SSL=true`) |
| `SMTP_USER` / `SMTP_PASSWORD` | Provider SMTP user + secret |
| `SMTP_FROM` | Verified sender on the provider domain |
| `SMTP_STARTTLS` / `SMTP_SSL` | Usually STARTTLS on 587 |
| `PUBLIC_BASE_URL` | Must match the live site (see above) |

Smoke (after fill-in):

```bash
./venv/bin/python tools/send_test_email.py you@example.com
```

Secrets stay in `.env` only. Local dumps like `mailersend-smtp.txt` are gitignored.

### Optional SQLCipher — `DB_ENCRYPTION_KEY`

- Unset = plain SQLite (default).
- Set only **after** converting existing DBs, or the app refuses to open them.
- Prefer the env var (the tool reads `$DB_ENCRYPTION_KEY`). Avoid putting the
  key on the command line — it can show up in shell history and process lists.

```bash
export DB_ENCRYPTION_KEY='…'   # from your secret store; not in git
python tools/encrypt_databases.py          # dry run
python tools/encrypt_databases.py --apply  # convert
# decrypt: python tools/encrypt_databases.py --decrypt --apply
```

Losing the key loses the data. Keep it in the host secret store.

### AI study aid (optional)

- Env: `LLM_PROVIDER`, `OPENAI_*`, `ANTHROPIC_*`, `OLLAMA_*` — see `.env.example`.
- Or Account → AI settings → `user_data/ai_settings.json` (AES-GCM `enc:v2:`,
  derived from `SECRET_KEY`). File mode `600`.
- Shared multi-user hosts: consider `AI_ALLOW_SETTINGS_WRITE=false` so only the
  deployer sets keys.

### Other optional knobs

| Variable | Role |
|----------|------|
| `NASA_ADS_TOKEN` | Enables NASA ADS fetcher |
| `EMBEDDING_DEVICE` | `cpu` / `cuda` / `mps` (default: auto) |
| `USER_DATA_DIR` | Override data root (default `user_data/`) |
| `HIDE_STUDY_TYPE_TAGS` / `HIDE_AI_BUTTONS` | Classroom UI toggles |

Persist `user_data/` (and `users.db` if not under that tree) on a volume so
accounts and libraries survive restarts.

---

## 4. Smoke checklist (do this after deploy)

Run against the live base URL (examples use `http://127.0.0.1:7860`).

```bash
# 1. Process is up
curl -sS -o /tmp/health.json -w "%{http_code}\n" http://127.0.0.1:7860/health
# expect: 200 and {"status":"healthy","version":"4.4.0"}

# 2. Landing (no auth)
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7860/
# expect: 200

# 3. Login page
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7860/login
# expect: 200
```

Manual (browser, HTTPS host or local with appropriate `DEBUG`):

1. Register a throwaway account (or login).
2. Account page loads; if SMTP is configured, recovery-email section appears.
3. Optional: Data Management → load sample corpus (or a small fetch).
4. Optional: Create embeddings → Search one query.
5. Confirm disk under `user_data/` is writable and not exploding past quota.

**Production-ish local** (HTTPS via tunnel; Secure cookies):

```bash
# With .env already set to DEBUG=false and PUBLIC_BASE_URL=https://litpilot.duckdns.org
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 7860
curl -sS http://127.0.0.1:7860/health
# After tunnel/DNS: curl -sS https://litpilot.duckdns.org/health
```

Note: with `DEBUG=false` on plain `http://localhost`, browser login may not
stick (Secure cookies). Use HTTPS (tunnel or reverse proxy) for real logins.

---

## 5. Security reminders

- TLS terminates at the host (Render / HF / reverse proxy). App sends HSTS when
  not in DEBUG (`app/security.py`).
- Sessions: HttpOnly + Secure (when not DEBUG) + SameSite=Lax JWT cookie;
  password change bumps `token_version` and signs out other sessions.
- CSRF double-submit on mutating routes.
- Do not commit `.env`, `user_data/`, `*.db`, or SMTP password files.

---

## 6. Done criteria (roadmap Phase 3)

- [ ] `SECRET_KEY` set from a secret store; `DEBUG=false` on the public host
- [ ] `PUBLIC_BASE_URL` matches the public origin (if using email)
- [ ] Quota / SMTP / SQLCipher choices documented for this host
- [ ] `GET /health` returns 200 on the intended host
- [ ] `user_data/` (or equivalent volume) persists across restarts
