# Runbook: TLS certificates for the production nginx

`docker-compose.production.yml` fronts everything with nginx, which loads
`/etc/nginx/ssl/cert.pem` + `/etc/nginx/ssl/key.pem` (a read-only bind mount of
`./nginx/ssl/`). **nginx will not start if those two files are missing** — this
was a verified deploy blocker. `nginx/ssl/` is gitignored: certificates and
private keys are never committed; every host provisions its own.

**Honest note up front:** nothing in this repo runs certbot for you. There is no
sidecar, no timer, no automation. Issuance and renewal are operator actions —
renewal is a cron you install yourself (below). The only automation is the
*gate*: `scripts/validate-production-compose.sh` refuses to validate a deploy
until the cert files exist.

---

## 1. Staging / smoke tests — self-signed (5 seconds)

From the repo root:

```bash
bash scripts/gen-self-signed-ssl.sh staging.example.com   # arg optional; default CN=localhost
```

Writes `nginx/ssl/cert.pem` + `nginx/ssl/key.pem` (key chmod 600, valid 365
days, SAN = the hostname you passed).

**Self-signed is for staging/smoke only.** Browsers will show a full-page
security warning, `curl` needs `-k`, and monitoring probes must disable
verification. Do not put a self-signed cert in front of real users — use the
certbot path below.

## 2. Production — Let's Encrypt via certbot (webroot mode)

Prerequisites: DNS for your domain points at this host, and port 80 is open.
The plumbing is already in place:

- `nginx/nginx.conf` serves `/.well-known/acme-challenge/` from
  `/var/www/certbot` **on port 80, before the HTTPS redirect**, so challenges
  work even while everything else redirects to HTTPS.
- The compose file bind-mounts `./nginx/certbot-www` (read-only) at
  `/var/www/certbot` in the nginx container. Certbot writes challenge files
  into that directory from the host side.

### 2a. First issuance

nginx must already be running to serve the challenge. For the very first boot
(no cert yet → nginx won't start) bootstrap with a self-signed pair from step 1,
then replace it:

```bash
cd /path/to/app   # repo root on the server, next to docker-compose.production.yml

docker run --rm \
  -v "$(pwd)/nginx/certbot-www:/var/www/certbot" \
  -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d app.example.com \
  --email ops@example.com --agree-tos --no-eff-email
```

Certbot stores the cert on the host at
`/etc/letsencrypt/live/app.example.com/`. Copy it to where nginx reads it
(copy, not symlink — the nginx container only sees `./nginx/ssl`, and the
`live/` entries are symlinks into `../../archive` that would dangle inside the
mount):

```bash
cp /etc/letsencrypt/live/app.example.com/fullchain.pem nginx/ssl/cert.pem
cp /etc/letsencrypt/live/app.example.com/privkey.pem  nginx/ssl/key.pem
chmod 600 nginx/ssl/key.pem

docker compose -f docker-compose.production.yml exec nginx nginx -s reload
```

### 2b. Renewal — operator cron (nothing does this for you)

Let's Encrypt certs live 90 days. Install a weekly root cron on the host
(`crontab -e`), adjusting the repo path and domain:

```cron
17 3 * * 1  cd /path/to/app && \
  docker run --rm -v "$(pwd)/nginx/certbot-www:/var/www/certbot" -v /etc/letsencrypt:/etc/letsencrypt \
    certbot/certbot renew --webroot -w /var/www/certbot --quiet && \
  cp /etc/letsencrypt/live/app.example.com/fullchain.pem nginx/ssl/cert.pem && \
  cp /etc/letsencrypt/live/app.example.com/privkey.pem  nginx/ssl/key.pem && \
  chmod 600 nginx/ssl/key.pem && \
  docker compose -f docker-compose.production.yml exec nginx nginx -s reload
```

`certbot renew` is a no-op until ~30 days before expiry, so the weekly cadence
is safe. Verify after the first renewal window:
`openssl x509 -enddate -noout -in nginx/ssl/cert.pem`.

## 3. How deploys are gated

`scripts/validate-production-compose.sh` (run by the `validate-deploy-config`
job in `.github/workflows/deploy.yml` and the `deploy-config` job in `ci.yml`,
and runnable by hand on the server before `docker compose up`) hard-fails
unless:

- `nginx/ssl/cert.pem` and `nginx/ssl/key.pem` exist — pointing you at
  `scripts/gen-self-signed-ssl.sh` (staging) or this runbook (production);
- `NEXT_PUBLIC_API_URL` is set and contains neither `backend:8000` nor
  `localhost` — it is baked into the frontend bundle at build time, so it must
  be the public origin browsers will actually call (the compose file also
  enforces this with `${NEXT_PUBLIC_API_URL:?...}`).

CI satisfies the cert check with a throwaway self-signed pair generated in the
workflow (never committed); real deploys must have real material on the host.

## Related

- `scripts/gen-self-signed-ssl.sh` — staging/self-signed generator
- `scripts/validate-production-compose.sh` — the deploy gate
- `docs/runbooks/DEPLOY_PIPELINE.md` — the deploy flow this slots into
