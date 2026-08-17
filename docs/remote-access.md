# Remote board access — jobs.hihelloreid.com (RC1-281)

The job board stays **local-first**: `scripts/serve.py` on the Mac is the only
server, and `data/jobs.json` + `data/state.json` remain the only source of
truth. Remote access is a **Cloudflare Tunnel** that forwards
`https://jobs.hihelloreid.com` to `localhost:8000`, with a **Cloudflare
Access** policy in front so only an allow-listed email can get through. There
is no hosted clone, no second data store, nothing to reconcile.

```
browser ──▶ Cloudflare edge ──▶ Access check (email allowlist + OTP/Google)
                                    │ pass
                                    ▼
                            Cloudflare Tunnel ──▶ cloudflared (launchd, Mac)
                                                        │
                                                        ▼
                                            serve.py @ 127.0.0.1:8000
                                            (writes state.json directly)
```

**Auth boundary:** the *edge* is the gate. `serve.py` itself has no auth — it
still binds `127.0.0.1` only, so the sole ways in are (a) the Mac itself, or
(b) through the tunnel, which Cloudflare refuses to route until the visitor
passes the Access policy. Write endpoints (`/api/decision`, the queues) work
through the tunnel exactly as they do locally, because it *is* the local
server.

**Known limitation (accepted):** the board is reachable only while the Mac is
awake and logged in — which is also the only time its data is fresh, since the
pipeline runs on the same machine. A read-only static snapshot for
Mac-asleep hours is a possible follow-up, out of scope here.

---

## Component 1 — serve.py keep-alive (launchd)

`ops/install-keepalive.sh` renders `ops/com.jobboard.serve.plist.template`
into `~/Library/LaunchAgents/com.jobboard.serve.plist` and bootstraps it:

```bash
./ops/install-keepalive.sh
```

- Starts the board at login; restarts it if it crashes (`KeepAlive`).
- Kills any manually-started server holding port 8000 first (otherwise the
  agent would crash-loop on a busy port).
- Logs to `data/logs/serve.log` (gitignored).
- **Stale-code fix:** `serve.py` now watches its own and `render.py`'s mtimes
  and re-execs itself on the first request after they change, so merged board
  changes go live without a manual kill. Assets (`board.css`/`js`/html shells)
  were already read per request.

Manage it:

```bash
launchctl kickstart -k gui/$UID/com.jobboard.serve   # force restart now
launchctl bootout   gui/$UID/com.jobboard.serve      # stop + uninstall
tail -f data/logs/serve.log                          # watch logs
```

## Component 2 — DNS migration (IONOS ➜ Cloudflare)

Cloudflare Tunnel + Access require the `hihelloreid.com` zone to be served by
Cloudflare (CNAME-only setup is Business-plan, subdomain zones are
Enterprise), so the domain's nameservers move from IONOS to Cloudflare.
**Moving nameservers changes who answers DNS queries, not where anything is
hosted** — every existing record is recreated verbatim, so the sites and mail
below keep working unchanged.

### Pre-migration record inventory (externally probed 2026-08-17)

| Name | Type | Value | Serves | Cloudflare proxy mode |
| --- | --- | --- | --- | --- |
| `hihelloreid.com` | A | `74.208.236.235` | IONOS webspace (resume site) | DNS only |
| `hihelloreid.com` | AAAA | `2607:f1c0:100f:f000::200` | IONOS webspace | DNS only |
| `www` | CNAME | `www.hihelloreid.com.herokudns.com` | Heroku | DNS only |
| `incidents` | A | `76.76.21.21` | **Vercel** (incidents site) | DNS only |
| `hihelloreid.com` | MX | `10 mx00.ionos.com`, `10 mx01.ionos.com` | IONOS mail | n/a |
| `hihelloreid.com` | TXT | `v=spf1 include:_spf-us.ionos.com ~all` | SPF (IONOS mail) | n/a |
| `_dmarc` | CNAME | `dmarc.ionos.com` | DMARC (IONOS mail) | DNS only |

> This table is what could be seen from outside. The migration checklist
> below also cross-checks the IONOS DNS panel for records external probing
> can't discover (DKIM selectors, verification TXTs, etc.) and records the
> final authoritative list in the as-executed log at the bottom of this file.

### Migration checklist

1. Create/log into a Cloudflare account (free plan) → **Add a domain** →
   `hihelloreid.com`. Cloudflare scans and imports records it can find.
2. Open the IONOS DNS panel side-by-side. For **every** record in IONOS,
   confirm an identical record exists in the Cloudflare zone; add any the
   scan missed (the scan checks common names — `incidents` may be missed).
3. Set **every imported record to "DNS only" (grey cloud)**. Proxying
   (orange cloud) would put Cloudflare in front of Vercel/Heroku/IONOS and
   can break their TLS/routing. Only the new `jobs` record (created later by
   the tunnel) is proxied.
4. In IONOS: change the domain's nameservers to the two assigned by
   Cloudflare. **Do not delete the IONOS DNS zone** — it keeps answering
   during propagation and is the instant rollback.
5. Wait for Cloudflare to mark the zone **Active** (minutes to ~24 h).
   Verify: `dig +short NS hihelloreid.com` shows `*.ns.cloudflare.com`, and
   `dig @<cf-ns> incidents.hihelloreid.com` returns `76.76.21.21`.

**Rollback:** switch the nameservers back to
`ns1022.ui-dns.{com,biz,org,de}` in IONOS. The untouched IONOS zone resumes
authoritatively; nothing else to undo.

## Component 3 — Cloudflare Tunnel (cloudflared)

```bash
brew install cloudflared
cloudflared tunnel login                    # browser auth; pick hihelloreid.com
cloudflared tunnel create jobboard          # note the tunnel UUID
# Render ops/cloudflared-config.yml.template → ~/.cloudflared/config.yml
#   {{TUNNEL_ID}} = the UUID, {{HOSTNAME}} = jobs.hihelloreid.com
cloudflared tunnel route dns jobboard jobs.hihelloreid.com   # creates proxied CNAME
cloudflared tunnel run jobboard             # foreground smoke test first
sudo cloudflared service install            # LaunchDaemon: starts at boot, restarts on crash
```

The tunnel makes an *outbound* connection from the Mac to Cloudflare — no
router ports opened, nothing listens on a public interface. `serve.py` stays
bound to `127.0.0.1`.

## Component 4 — Cloudflare Access (the gate)

In the Cloudflare **Zero Trust** dashboard:

1. **Access → Applications → Add application → Self-hosted.**
2. Application domain: `jobs.hihelloreid.com` (protect the whole hostname,
   every path — the write endpoints must be behind the gate too).
3. Policy: **Allow** → Include → **Emails** → the allow-listed email(s).
   Login methods: One-Time PIN (email code) — add Google SSO if desired.
4. Session duration: per preference (e.g. 1 week — it's a personal tool on
   personal devices).

Result: an unauthenticated visitor to any path on `jobs.hihelloreid.com`
gets the Cloudflare Access login wall; only after passing does any request
reach the tunnel.

## Acceptance verification (RC1-281)

- [ ] `https://jobs.hihelloreid.com` renders the live board after Access
      login; a logged-out/other-email visitor gets the Access wall.
- [ ] A status change made through the tunnel appears in local
      `data/state.json`.
- [ ] Reboot the Mac, log in: board and tunnel come back without manual
      starts. (`serve.py` = LaunchAgent, at login; `cloudflared` =
      LaunchDaemon, at boot.)
- [ ] `http://127.0.0.1:8000` still works unchanged.
- [ ] `incidents.hihelloreid.com`, `www.hihelloreid.com`,
      `hihelloreid.com`, and IONOS mail unaffected after the NS move.

---

## As-executed log

*(filled in as the migration is performed — authoritative record of every
change made)*
