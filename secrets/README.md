# Local secrets (not committed)

| File | Purpose |
|------|---------|
| `duckdns.env` | DuckDNS token + domain for IP updater |

Copy the example, then put your real token from
https://www.duckdns.org (account page):

```bash
cp secrets/duckdns.env.example secrets/duckdns.env
# edit secrets/duckdns.env — set DUCKDNS_TOKEN=…
chmod 600 secrets/duckdns.env
./tools/duckdns_update.sh
```

Never commit `duckdns.env` or any real token.
