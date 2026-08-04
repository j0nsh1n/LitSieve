# Local secrets (not committed)

| File | Purpose |
|------|---------|
| `cloudflared.token` / `cloudflared.env` | Cloudflare Tunnel token (`TUNNEL_TOKEN=…`) |
| `letsencrypt/` | Optional local ACME material for Caddy (if used) |

```bash
chmod 600 secrets/cloudflared.env secrets/cloudflared.token 2>/dev/null || true
```

Never commit tokens, private keys, or `.env`.
