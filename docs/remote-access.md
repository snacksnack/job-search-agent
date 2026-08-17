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
cloudflared service install                 # user LaunchAgent: starts at login, restarts on crash
```

The service is installed **without sudo** on purpose: that makes it a user
LaunchAgent (`~/Library/LaunchAgents/com.cloudflare.cloudflared.plist`,
logs in `~/Library/Logs/com.cloudflare.cloudflared.{out,err}.log`) that runs
while the user is logged in — the same lifecycle as the board server it
fronts, which is also a login LaunchAgent. A root install (LaunchDaemon, runs
from boot) would only add a window where the tunnel is up but the board
isn't.

> **Gotcha (hit during setup):** `cloudflared service install` (2026.8.2)
> writes a plist whose `ProgramArguments` is just `cloudflared` with no
> arguments — which prints "use `cloudflared tunnel run`…" and exits 1 in a
> KeepAlive crash-loop, so the edge serves **Error 1033**. And the Access
> wall's 302 does NOT prove the tunnel is up — it's served by the edge
> before the tunnel matters. Fix: append `tunnel run` to the plist's
> ProgramArguments (`/usr/libexec/PlistBuddy -c "Add :ProgramArguments:1
> string tunnel" -c "Add :ProgramArguments:2 string run" …`) and reload;
> then confirm with `launchctl list | grep cloudflared` (PID + status 0) and
> "Registered tunnel connection" lines in
> `~/Library/Logs/com.cloudflare.cloudflared.err.log`. 

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
      starts. (Both are login LaunchAgents — `com.jobboard.serve` and
      `com.cloudflare.cloudflared`.)
- [ ] `http://127.0.0.1:8000` still works unchanged.
- [ ] `incidents.hihelloreid.com`, `www.hihelloreid.com`,
      `hihelloreid.com`, and IONOS mail unaffected after the NS move.

---

## As-executed log

### 2026-08-17 — DNS migration (IONOS ➜ Cloudflare)

1. **Keep-alive installed** (`ops/install-keepalive.sh`): took over from the
   manually-started server (old pid 9063 killed); crash-restart verified with
   a `kill -9`; code-change auto-re-exec verified on a scratch port.
2. **Cloudflare zone added**: existing account `hihelloreid@gmail.com`, free
   plan, quick-scan import. Onboarding AI-policy defaults kept except
   **"Block training in robots.txt" turned OFF** (avoids Cloudflare serving a
   managed robots.txt on any proxied host).
3. **Quick-scan gap**: the scan found only 11 of the zone's records. The
   IONOS DNS panel (filter reset to "Display all records") showed **32
   records** — the authoritative inventory. Missing from the scan:
   `incidents` (Vercel), the three IONOS **DKIM** CNAMEs
   (`s1-ionos`/`s2-ionos`/`s42582890` `._domainkey`), the `_dep_ws_mutex`
   TXT, all `planner` (Fly.io) and `realestate` (+`www`, MX,
   autodiscover) records, `blog`'s AAAA/MX/`ftp.blog`/`autodiscover.blog`,
   and `www.blog`'s AAAA.
4. **Gap filled**: `incidents A 76.76.21.21` added by hand; the remaining 20
   records imported via a BIND zone file (every value first confirmed with
   `dig` against the live IONOS nameservers; the truncated `_dep_ws_mutex`
   TXT value recovered the same way). The import dialog's "Proxy imported
   DNS records" checkbox re-checks itself on the confirm step — unchecked
   before upload.
5. **All 32 records set to DNS only** (grey cloud). Nothing proxied yet.
6. **Pre-flip verification**: every record queried against
   `derek.ns.cloudflare.com` and diffed against the IONOS values — **29/29
   checks OK** (MX pairs checked together). `dig DS hihelloreid.com` empty →
   no DNSSEC to disable.
7. **Nameservers flipped at IONOS** (Name server → Use custom name servers):
   `derek.ns.cloudflare.com` + `fiona.ns.cloudflare.com`, replacing
   `ns1022.ui-dns.{com,biz,org,de}`. IONOS confirmed "Name server
   successfully changed"; its DNS zone is retained (deactivated, not
   deleted) — switching the nameservers back remains the instant rollback.
8. Cloudflare notified ("I updated my nameservers"); zone pending
   activation (registrar propagation, typically 1–2 h).

### 2026-08-17 — Tunnel + Access (same evening)

9. **Zone went Active** within minutes of the flip (registrar propagated
   fast; Cloudflare confirmed while the tunnel was being authorized).
10. **Tunnel authorized + created**: `cloudflared tunnel login` (cert for
    zone `hihelloreid.com`), tunnel **`jobboard`**, id
    `481f8633-3ef5-4366-9a50-14bd21b7ee32`; config rendered from
    `ops/cloudflared-config.yml.template` to `~/.cloudflared/config.yml`;
    `cloudflared tunnel route dns jobboard jobs.hihelloreid.com` added the
    proxied CNAME (the zone's only proxied record).
11. **Zero Trust set up** (free plan, auto-assigned team name
    **`super-morning-8df7`**, renamed the same evening to **`hihelloreid`** →
    login page `hihelloreid.cloudflareaccess.com`). Access self-hosted app
    **`jobs`** protecting `jobs.hihelloreid.com` (no path — all routes),
    policy **`Reid Only`**: Allow, Include Emails =
    `hi.hello.reid@gmail.com`, One-Time PIN login. (The dashboard UI was set
    up by hand in the browser; the Claude-in-Chrome extension could not
    script the Cloudflare One SPA.)
12. **Access verified before the tunnel went permanent**: with the tunnel
    running in the foreground, unauthenticated `GET /` and `POST
    /api/decision` both returned 302 to the Access login — nothing reached
    the local server; `http://127.0.0.1:8000` unchanged (200).
13. **Service installed**: `cloudflared service install` (no sudo → user
    LaunchAgent, login lifecycle matching the board's own agent).
14. **Error 1033 on first real visit**: the installed plist ran `cloudflared`
    with no args → exit-1 crash-loop (see the Gotcha in Component 3; the
    Access 302 had masked it). Fixed by appending `tunnel run` to
    `ProgramArguments` and reloading; 4 QUIC connections registered.

Assigned Cloudflare nameservers: **derek** / **fiona** `.ns.cloudflare.com`.
Zone also hosts (unchanged, all DNS-only): apex + `blog` + `ftp.blog` +
`www.blog` (IONOS webspace), `www` (Heroku), `incidents` (Vercel), `planner`
(Fly.io), `realestate` + `www.realestate` (DigitalOcean), IONOS mail
(MX/SPF/DMARC/DKIM/autodiscover), `_domainconnect`, `_dep_ws_mutex`.
