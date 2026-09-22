# Deploying CompetitorTrack

Host-agnostic `docker compose`. The documented primary target is the founder's
existing **Oracle Cloud Always Free Ampere A1** (aarch64, 2 OCPU / 12 GB,
Ubuntu) — the same machine Phase 0 measured from, which is why its egress
verdict applies to production. Any Ubuntu 22.04+ / Debian 12+ box with 2 vCPU,
4 GB RAM, Docker Engine + Compose v2, a public IPv4, open 80/443 and a DNS A
record works identically.

---

## 1. Prerequisites checklist

| | Item | State |
|---|---|---|
| ☑ | Server with a public IPv4 | Oracle A1, `130.61.153.125` (AS31898, Frankfurt) |
| ☑ | Domain | `jobsearchpk.site` — registered via Hostinger, paid to 2027-05-20 |
| ☐ | **DNS A record → server IP** | **blocked, see §2 — nothing under the domain resolves today** |
| ☐ | Docker Engine + Compose v2 on the server | §3 |
| ☐ | Ports 80/443 open in the VCN **and** in the instance firewall | §3 — the usual day-one failure |
| ☐ | `deploy/.env` filled from `.env.example`, `chmod 600` | §4 |
| ☐ | Platform SMTP credentials (Gmail App Password) | §4 |
| ☐ | Backup passphrase stored offline in a password manager | needed in P6, not for P1 |
| ☐ | `DEPLOY_SSH_KEY` / `DEPLOY_HOST` / `DEPLOY_USER` GitHub secrets | needed in P6, when CI starts deploying |

The subdomain this deployment uses is **`app.jobsearchpk.site`** (D1.15).

---

## 2. DNS — fix this first

**Current state, measured 2026-09-22 (RDAP + DNS over HTTPS):**

- the registration is fine: created 2026-05-20, expires 2027-05-20, registrar
  "HOSTINGER operations, UAB";
- the nameservers are **`ns1.digitalocean.com`, `ns2.digitalocean.com`,
  `ns3.digitalocean.com`**;
- those nameservers answer **REFUSED** for this zone — DigitalOcean is not
  hosting it. The domain was presumably pointed there for an earlier project and
  the zone has since been deleted.

So `jobsearchpk.site` has no A record, no SOA and no working NS delegation. A
browser cannot reach it and Let's Encrypt cannot validate it. Certificate
issuance uses HTTP-01, which needs working DNS *before* the first start.

### Option A (recommended): move DNS back to Hostinger

1. Log in to Hostinger → **hPanel → Domains → jobsearchpk.site → DNS / Nameservers**.
2. Choose **Change nameservers → Use Hostinger nameservers** (`ns1.dns-parking.com`,
   `ns2.dns-parking.com`).
3. Wait for the change to propagate. Nameserver changes are registry-level: minutes
   is common, up to 24 h is normal.
4. Then **hPanel → Domains → DNS zone** and add:

   | Type | Name | Points to | TTL |
   |---|---|---|---|
   | A | `app` | `130.61.153.125` | 300 (raise later) |

5. Verify from anywhere before touching the server:

   ```bash
   dig +short app.jobsearchpk.site            # expect 130.61.153.125
   curl -s "https://dns.google/resolve?name=app.jobsearchpk.site&type=A"
   ```

   Do not continue until this returns the server's IP. Caddy will otherwise ask
   Let's Encrypt for a certificate it cannot possibly validate.

### Option B: keep the DigitalOcean nameservers

Only if you still have that account: DigitalOcean → **Networking → Domains →
add `jobsearchpk.site`**, then add the same `app` A record there. The delegation
already points at DigitalOcean, so nothing changes at the registrar.

### If you later put Cloudflare in front

Keep the record **DNS-only (grey cloud)** at least until the certificate is
issued — HTTP-01 fails behind the orange-cloud proxy. If you enable the proxy
afterwards, set Caddy's `trusted_proxies` so client IPs in the logs stay real.

---

## 3. Server preparation

```bash
# Docker Engine + Compose v2
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER" && newgrp docker
docker compose version          # expect v2.x

# Confirm the architecture — the A1 is aarch64. An amd64-only image fails here
# with "exec format error"; every base image we use publishes arm64.
uname -m                        # expect aarch64
```

### Oracle Cloud specifics

1. **Two firewalls, not one.** Open 80 and 443 in the VCN security list
   (Networking → Virtual Cloud Networks → your VCN → Security Lists → add
   ingress rules for `0.0.0.0/0` TCP 80 and 443) **and** in the instance's own
   iptables — Oracle's Ubuntu images drop inbound traffic beyond SSH by default.
   This is the single most common day-one failure.

   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save     # survives reboot
   ```

2. **Reclamation.** Always Free instances idling below 20% p95 CPU / network /
   memory for 7 days may be reclaimed. Upgrading the tenancy to Pay-As-You-Go
   stops reclamation while Always Free resources stay free — confirm on Oracle's
   current free-tier page. Keeping the uptime monitor pinging `/api/health` also
   generates baseline traffic.

3. **Outbound port 25 is blocked permanently** and always will be. Irrelevant
   here: Phase 0 verified `smtp.gmail.com` on **587 (STARTTLS)** and **465
   (implicit TLS)** are both reachable from this box with TLSv1.3.

---

## 4. First install

```bash
git clone https://github.com/zaktecs-ai/CompetitorTrack.git ~/CompetitorTrack
cd ~/CompetitorTrack

cp .env.example deploy/.env
chmod 600 deploy/.env
chmod +x deploy/scripts/*.sh     # the exec bit does not always survive a push
```

Now edit `deploy/.env`. Every line marked `CHANGE-ME` must change:

```bash
# a 256-bit signing secret
openssl rand -base64 48

# a Fernet key for MASTER_ENCRYPTION_KEYS (needs the api image, or any python
# with `cryptography` installed)
docker run --rm python:3.12-slim sh -c \
  'pip install -q cryptography && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
```

Also set:

- `POSTGRES_PASSWORD` **and** the same password inside `DATABASE_URL`. They are
  read by different containers and nothing reconciles them for you — and once
  the `pgdata` volume exists, changing `POSTGRES_PASSWORD` has no effect on the
  database that was already initialised.
- `SERVER_NAME=app.jobsearchpk.site`, `PUBLIC_ORIGIN=https://app.jobsearchpk.site`,
  `ACME_EMAIL=<your email>`.
- `PLATFORM_SMTP_URL` — Gmail needs an **App Password** (2-Step Verification must
  be on; "less secure app access" no longer exists). Percent-encode the `@` in
  the username as `%40`. A first login from a new server IP can trigger a
  "suspicious sign-in" block that has to be cleared in the Google account.
- Leave `ACME_CA` on the **staging** URL for now. Let's Encrypt allows only 5
  duplicate certificates per week; iterating against production burns that in an
  afternoon. Clearing the variable switches to production certificates and is a
  P6 go-live step.

---

## 5. Bring it up (and update it) manually

`deploy/scripts/deploy.sh` is a loud stub until P6 (D1.11), so P1 uses the same
commands by hand. Always pass `-f docker-compose.yml` explicitly: that is what
keeps the local development override out of production.

```bash
cd ~/CompetitorTrack/deploy

docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml up -d --remove-orphans
docker compose -f docker-compose.yml ps
```

To update to a newer commit:

```bash
cd ~/CompetitorTrack && git fetch && git checkout <sha>
docker image tag competitortrack-api:latest competitortrack-api:prev   # rollback target
docker image tag competitortrack-web:latest competitortrack-web:prev
cd deploy
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml up -d --remove-orphans
curl -fsS https://app.jobsearchpk.site/api/health/ready
```

Migrations are forward-only and additive, so rolling an image back never needs a
schema downgrade.

---

## 6. Local development

No domain, no certificates, plain HTTP. Compose auto-merges
`docker-compose.override.yml` when you do **not** pass `-f`:

```bash
cp .env.example deploy/.env       # placeholders are fine locally
cd deploy && docker compose up -d --build
docker compose run --rm api alembic upgrade head
open http://localhost
```

The override also publishes PostgreSQL on `127.0.0.1:5432`, so the test suite can
use it:

```bash
cd apps/api
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
DATABASE_URL='postgresql+psycopg://ct:<your password>@localhost:5432/competitortrack' \
  .venv/bin/pytest
```

---

## 7. P1 acceptance checks

Run these on the server once §2–§5 are done. They are P1's Definition of Done,
in order. `-k` on curl is expected: the staging certificate is not trusted.

```bash
cd ~/CompetitorTrack/deploy
C="docker compose -f docker-compose.yml"

# 1 — all five services up, db healthy
$C ps

# 2 — the page renders through Caddy over HTTPS (staging cert)
curl -ks https://app.jobsearchpk.site/ | grep -o "System health"

# 3 — health says everything is ok
curl -ks https://app.jobsearchpk.site/api/health; echo
#    expect: {"api":"ok","db":"ok","scheduler":"ok","heartbeat_age_s":<60,...} with HTTP 200
curl -kso /dev/null -w "ready=%{http_code}\n" https://app.jobsearchpk.site/api/health/ready

# 4 — a dead scheduler pages, but never triggers a rollback.
#     Wait out the 5-minute heartbeat window, then check both endpoints.
$C stop scheduler
sleep 330
curl -kso /dev/null -w "health=%{http_code} (expect 503)\n" https://app.jobsearchpk.site/api/health
curl -kso /dev/null -w "ready=%{http_code}  (expect 200)\n" https://app.jobsearchpk.site/api/health/ready
curl -ks https://app.jobsearchpk.site/api/health; echo     # expect "scheduler":"stale"
$C start scheduler
sleep 10
curl -kso /dev/null -w "health=%{http_code} (expect 200 again)\n" https://app.jobsearchpk.site/api/health

# 5 — a second scheduler refuses to work instead of racing
timeout 25 $C run --rm --no-deps scheduler 2>&1 | grep -m1 "lock held, waiting"

# 6 — compose file is valid as the server reads it
$C config --quiet && echo "compose config ok"

# 7 — the crawler page the User-Agent advertises is live
curl -ks https://app.jobsearchpk.site/bot | grep -o "CompetitorTrackBot/1.0"
```

Check 4 is the interesting one: it is the difference between "the site is up" and
"the product is working". Nothing is scraped while the scheduler is down, so
`/api/health` must fail — and `/api/health/ready` must not, or a deploy that
overlaps two scheduler containers would roll itself back.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Caddy loops on ACME errors | DNS not resolving to this box, or 80/443 closed | §2, then §3 step 1 |
| `exec format error` | an amd64 image on aarch64 | build on the server (`docker compose build`), never copy images from a laptop |
| `/api/health` = 503, `scheduler: "unknown"` | the scheduler has never beaten | `$C logs scheduler` — usually a bad `DATABASE_URL` |
| `/api/health` = 503, `db: "error"` | database down or wrong credentials | `$C logs db`; check `DATABASE_URL` against `POSTGRES_*` |
| Scheduler logs `lock held, waiting` forever | another scheduler (or an old container) holds the lock | `$C ps -a`; remove the stray container |
| `alembic upgrade head` says `DATABASE_URL is not set` | ran outside compose | use `$C run --rm api alembic upgrade head` |
| Browser warns about the certificate | staging ACME, as configured | expected until the P6 go-live step clears `ACME_CA` |
| Port 80 unreachable, VCN rule exists | instance iptables | §3 step 1 |
