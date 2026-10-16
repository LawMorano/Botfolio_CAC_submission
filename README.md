<img src="static/images/botfolio-logo.png" alt="Botfolio logo" width="600">

# Botfolio

Botfolio is a community library where FTC robotics teams publish robot and
mechanism designs, share CAD files or links, discuss designs, and request
structured AI feedback.

## Main features

- Searchable gallery with season, archetype, tag, CAD, and tested filters.
- STL, OBJ, and GLB previews in three.js; STEP remains an editable download.
- Direct multipart S3 uploads in production and local-file development.
- Personal accounts, team claiming and membership, design attribution,
  comments, community tags, saved designs, notifications, and moderation.
- Optional OpenAI moderation and structured design feedback.
- SQLite locally and PostgreSQL in deployment through a compatibility layer.

## Run locally

Botfolio requires Python 3.10 or newer.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py seed.py
flask --app app run
```

Open <http://127.0.0.1:5000>. `seed.py` drops and rebuilds the local database,
so do not run it against data you need to keep.

The core app works without an OpenAI key. Copy `.env.example` to `.env.local`
and set `OPENAI_API_KEY` to enable AI moderation and design review. Never commit
`.env.local`, API keys, database files, or user uploads.

## Architecture

```text
app.py                    Flask routes, validation, and view logic
config.py                 product limits and policy versions
db.py                     request-scoped SQLite/PostgreSQL connections
schema.sql                database schema
seed.py                   local demo database and sample data
services/                 email, AI, and reusable team services
robotics/                 FTC and FRC team-registry integrations

infra/
  settings.py             environment parsing
  database.py             SQLite-to-PostgreSQL compatibility
  storage.py              local/S3 file storage
  security.py             cookie, proxy, CSP, and response hardening
  ratelimit.py            local/Redis request limits
  cache.py                local/Redis response cache
  logging_setup.py        structured request logging
  metrics.py              health, readiness, and metrics endpoints

templates/                Jinja pages and reusable partials
static/                   CSS, browser JavaScript, images, vendored libraries
tests/                    Python tests and a JavaScript harness
tools/                    smoke, restore, and SQL-translation checks
docs/                     deployment and operations documentation
aws/ and railway.json     deployment configuration
```

`app.py` remains large because the project currently uses one Flask module for
all routes. Route extraction should be done feature by feature with Blueprints
and regression tests; moving routes only for appearance would add submission
risk.

## Verification

```powershell
py -m unittest discover -s tests -v
py -m compileall -q app.py config.py db.py services robotics infra maintenance.py production_readiness.py seed.py tests tools
```

Deployment dependencies are in `requirements-deploy.txt`. Railway builds the
root `Dockerfile` and checks `/healthz`. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for release steps.
