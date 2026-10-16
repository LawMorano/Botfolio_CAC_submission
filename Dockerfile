# Botfolio container image.
#
# Used by Railway (which will build this instead of guessing at a Python setup)
# and by AWS ECS. The same image runs in both, which is the point: staging and
# production differ by environment variables, not by build.

FROM python:3.12-slim AS base

# - PYTHONDONTWRITEBYTECODE: .pyc files in a container are written once and
#   never reused, so they are pure image bloat.
# - PYTHONUNBUFFERED: without it, Python buffers stdout when it is a pipe,
#   which means logs appear minutes late or vanish entirely if the container
#   is killed. Every log line in infra/logging_setup.py depends on this.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements are copied and installed before the source is copied. Docker
# caches each layer, so this way editing a template does not reinstall every
# dependency — it turns a three-minute rebuild into a five-second one.
COPY requirements.txt requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY . .

# Normally run as a non-root user. Railway sets RAILWAY_RUN_UID=0 only for
# volume preparation; production_boot.py drops back to botfolio before serving.
RUN useradd --create-home --uid 10001 botfolio \
    && mkdir -p /app/static/uploads /app/static/models \
    && chown -R botfolio:botfolio /app
USER botfolio

# Documentation only — the platform decides the real port via $PORT.
EXPOSE 8080

# Checked by the container runtime, and separately by Railway and the ALB.
# Points at /healthz, which deliberately does not touch the database: see the
# comment on that route in infra/metrics.py.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/healthz').read()"

# Both platforms inject $PORT and expect the app to bind it, so it cannot be
# hard-coded. Exec form via sh -c is needed for the variable to be expanded.
#
# Flags, and why each one:
#   --workers 2         two processes, so one slow request does not block the
#                       whole site. More than that needs more memory than a
#                       small instance has.
#   --threads 4         uploads and downloads spend their time waiting on the
#                       network, which threads handle far more cheaply than
#                       processes.
#   --timeout 300       a 350 MB model upload over a school connection takes
#                       minutes; the 30-second default kills it mid-transfer.
#   --access-logfile -  to stdout, where the platform collects it.
CMD ["python", "production_boot.py"]
