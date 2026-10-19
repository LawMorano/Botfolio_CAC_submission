# Independent CAC deployment

Target: `https://botfoliosimple-production.up.railway.app`.

## Resource boundary

| Resource | CAC | Main site |
|---|---|---|
| Railway project | `7ef1cdea-6185-4602-ab8e-6961ea39dbf4` | `a8b38490-9ac0-4d4b-b2c8-b564b6b9b25b` |
| App service | `6ed7b60a-e7c0-441b-9716-91b9c037c083` | `683006a1-0ce2-426d-901a-433a93675ad8` |
| PostgreSQL service | `11faaf52-9031-4b89-8d9c-c0376a6ef82e` | `31d9371d-e054-4936-836d-549bbb79ea76` |
| Image bucket | `botfolio-cac-images` | `botfolio-images` |
| Model bucket | `botfolio-cac-models` | `botfolio-models` |
| Quarantine bucket | `botfolio-cac-quarantine` | `botfolio-quarantine` |

The original CAC SQLite database is on volume `5070a38d-d9e0-45a4-a26a-c0c5f0870363`.
It had zero users and zero designs before migration. A consistent copy was made
at `/data/cac-sqlite-pre-postgres-20261018.db` on that volume. Keep the volume
attached and untouched until the PostgreSQL deployment and persistence test pass.
The same backup was downloaded to the operator's
`C:\Users\lawgm\Downloads\cac-sqlite-pre-postgres-20261018.db`.
An additional local copy is in `.backups/` (ignored by Git). Its SQLite
integrity check passed, with zero users and zero designs.
The volume's `uploads` and `models` directories contained no files.

## CAC app variables

Set these as **service variables on the CAC app only**, never as project shared
variables. Bind `DATABASE_URL` as a Railway reference to the PostgreSQL service
in the CAC project. Verify the reference source is service
`11faaf52-9031-4b89-8d9c-c0376a6ef82e` before deploying.

```env
CAC_ISOLATED_DEPLOYMENT=true
CAC_POSTGRES_SERVICE_ID=11faaf52-9031-4b89-8d9c-c0376a6ef82e
APP_ENV=production
SITE_URL=https://botfoliosimple-production.up.railway.app
DATABASE_URL=${{Postgres.DATABASE_URL}}
S3_BUCKET_IMAGES=botfolio-cac-images
S3_BUCKET_MODELS=botfolio-cac-models
S3_BUCKET_QUARANTINE=botfolio-cac-quarantine
S3_ENDPOINT_URL=https://f49134581f8815cebd081da262395c56.r2.cloudflarestorage.com
S3_IMAGES_PUBLIC_URL=https://pub-1e5cbc3385a9496bb58f46e6c65e9750.r2.dev
AWS_REGION=auto
BEHIND_PROXY=true
FORCE_HTTPS=true
```

Set fresh, CAC-only values for `FLASK_SECRET_KEY`, `AWS_ACCESS_KEY_ID`, and
`AWS_SECRET_ACCESS_KEY`. Do not commit or print them. Use a randomly generated
`FLASK_SECRET_KEY` of at least 32 characters; the startup guard rejects shorter
values. The R2 credential must be restricted to the three CAC buckets. Keep
`S3_BUCKET`, `S3_PUBLIC_URL`,
`REDIS_URL`, and `BOTFOLIO_DATA_DIR` unset. Remove all `EMAILJS_*` variables
and `BOTFOLIO_FROM_EMAIL` from the CAC service; its existing EmailJS settings
belong to the main site. CAC disables all outgoing mail, account email
verification, and email-based password resets. The password-reset link displays
a demo notice without issuing a token or sending mail. Remove the pre-existing
Gemini variable until it has a dedicated CAC credential. Leave Google OAuth disabled until a separate CAC client registers exactly
`https://botfoliosimple-production.up.railway.app/auth/google/callback`.

`production_boot.py` validates this boundary before starting. On the first
boot it initializes the **empty** CAC PostgreSQL database from `schema.sql`
without the `DROP TABLE` statements. A database with tables but no `users`
table is rejected. Do not run `db.init_db()` or the obsolete `seed.py`
instruction against PostgreSQL; those instructions can destroy data.

## R2 policy

- Images: public read URL for the CAC bucket only.
- Models and quarantine: no public URL or custom domain.
- Quarantine CORS: origin exactly the CAC Railway URL, `PUT`, request header
  `Content-Type`, exposed response header `ETag`.
- Quarantine: expire uploaded objects after one day. Each new bucket already
  has Cloudflare's default incomplete multipart abort after seven days.
- Keep active image and model objects indefinitely. Do not apply an ordinary
  object expiration rule to them. If R2 later offers version expiration,
  remove noncurrent versions after 30 days.

The `railway.app` hostname belongs to Railway. No Cloudflare DNS zone or proxy
entry is required for it.
Cloudflare labels `r2.dev` as rate limited and unsuitable for a higher traffic
production site. A user-owned custom domain would be needed for that upgrade.
