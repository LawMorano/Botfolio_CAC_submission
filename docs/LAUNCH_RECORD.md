# Botfolio launch record

Production domain: `https://botfoliohq.com`

## Approved launch settings

- Minimum age: 13.
- Users under 18 confirm parent or guardian permission.
- Uploads require a signed-in, email-verified account.
- Models: STL and OBJ only.
- Maximum individual model upload: 2.5 GB.
- Viewer tiers: automatic through 350 MB; explicit opt-in from 350–500 MB;
  download-only above 500 MB.
- Images: up to 8 per design, 8 MB source limit each.
- Users and teams have no cumulative upload or storage quota. Byte counters are
  retained for cost monitoring only.
- AI model: GPT-5.4 mini.
- AI limit: 5 design reviews per user per rolling 24 hours.
- AI scope: FTC robotics design review only; no general chat.
- Removed-content target retention: 30 days. Configure the provider lifecycle rules below before launch.
- Abandoned quarantine target retention: 24 hours. Application cleanup is implemented; an R2 lifecycle rule provides defense in depth.

## Railway variables

Required:

```env
APP_ENV=production
FLASK_SECRET_KEY=<stable random secret>
DATABASE_URL=<Railway PostgreSQL URL>
OPENAI_API_KEY=<Botfolio OpenAI project key>
OPENAI_MODEL=gpt-5.4-mini

S3_BUCKET_IMAGES=botfolio-images
S3_BUCKET_MODELS=botfolio-models
S3_BUCKET_QUARANTINE=botfolio-quarantine
S3_ENDPOINT_URL=https://<cloudflare-account-id>.r2.cloudflarestorage.com
S3_IMAGES_PUBLIC_URL=https://assets.botfoliohq.com
AWS_ACCESS_KEY_ID=<R2 access key id>
AWS_SECRET_ACCESS_KEY=<R2 secret access key>
AWS_REGION=auto

EMAILJS_SERVICE_ID=<service id>
EMAILJS_TEMPLATE_ID=<template id>
EMAILJS_PUBLIC_KEY=<public key>
EMAILJS_PRIVATE_KEY=<private key if server-side sending requires it>
BOTFOLIO_FROM_EMAIL=<verified sender>

METRICS_TOKEN=<stable random secret>
BEHIND_PROXY=true
FORCE_HTTPS=true
HSTS_SECONDS=31536000
```

Required when using multiple application replicas:

```env
REDIS_URL=<Railway Redis URL>
```

Optional operational overrides:

```env
CACHE_SECONDS=30
CACHE_ENABLED=true
RATELIMIT_ENABLED=true
LOG_LEVEL=INFO
LOG_JSON=true
SLOW_REQUEST_MS=1000
```

## Accounts and ownership

Create these under an adult-controlled Botfolio organization wherever possible:

1. GitHub organization/repository.
2. Railway project with application, PostgreSQL, and later Redis.
3. Cloudflare account containing `botfoliohq.com`, DNS, Turnstile, and the three R2 buckets.
4. OpenAI Platform organization/project with billing limits and usage alerts.
5. Transactional email provider with a verified `botfoliohq.com` sender.
6. Domain registrar account for `botfoliohq.com` with renewal and MFA enabled.

## Manual provider configuration

- Keep the quarantine and model buckets private.
- Expose only optimized images through `assets.botfoliohq.com`.
- Give the Railway R2 token access only to the three Botfolio buckets.
- Set an R2 rule to remove abandoned quarantine objects after 24 hours.
- Allow `PUT` from `https://botfoliohq.com` on the quarantine bucket and expose
  the `ETag` response header so the browser can complete multipart uploads.
- Abort incomplete R2 multipart uploads after seven days.
- Set an R2 noncurrent-version expiration rule of 30 days on image and model buckets.
- Schedule `python maintenance.py` at least daily. It expires abandoned upload
  authorizations; 90-day operational and authentication records; age/guardian
  confirmations three years after account closure; policy acceptances five
  years after closure; ordinary moderation records after two years; and
  copyright or material security records after five years. Active retention
  holds suspend those database deletions.
- Configure the production logging provider for 90-day retention. AWS
  CloudWatch is configured in `aws/botfolio.yaml`; Railway or any external log
  drain must be set separately in its dashboard.
- Configure database backups for a 30-60 day rolling window. The AWS template
  uses 35 days; verify the Railway PostgreSQL backup policy separately.
- Use `python maintenance.py hold ...` for database evidence under legal or
  security hold. Export raw provider logs to restricted immutable storage when
  they must survive the provider's 90-day lifecycle.
- Enable PostgreSQL backups and test a restore before public launch.
- Configure OpenAI project budgets and alerts in addition to application request limits.
- Keep an account-wide R2 budget alert enabled. A $10 monthly alert was verified
  on August 14, 2026.
- Add Cloudflare Turnstile to registration and password-reset forms before public launch.
- Route `botfoliohq.com` through Cloudflare to Railway and verify HTTPS/HSTS.

## Remaining launch blockers

- Deploy and exercise the multipart browser-to-R2 upload flow against production
  with representative files from all three viewer tiers before enabling 2.5 GB uploads.
- Add an isolated quarantine validation/scanning worker before supporting any
  archive format. ZIP remains prohibited.
- R2 lifecycle and quarantine CORS rules were verified on August 14, 2026;
  re-verify them after any bucket replacement.
- Run `python tools/restore_drill.py` with `DATABASE_URL` and a separate disposable `RESTORE_TEST_DATABASE_URL`. A successful run writes an auditable JSON record under `docs/restore-drills/`; do not remove this blocker until that record exists and is reviewed.
- Obtain appropriate review of youth privacy, consent, terms, and moderation procedures.
