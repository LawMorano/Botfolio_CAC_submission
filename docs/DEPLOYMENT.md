# Deploying Botfolio

Nothing in this document is needed to work on Botfolio. `python app.py` still
runs the site off a SQLite file with uploads in `static/`, exactly as before —
every piece of infrastructure described here switches on only when the matching
environment variable is set, and falls back to the local behaviour when it
isn't.

---

## The one thing you must not get wrong

**Containers have a temporary disk.** On Railway, on ECS, on almost any modern
host, the filesystem your app writes to is thrown away and recreated on every
deploy. If uploads are still going to `static/uploads/`, then the first time you
push a change after launch, every photo and every STL file anyone has ever
uploaded is deleted. The SQLite file goes with it — accounts, designs, comments,
all of it.

This is not a rare edge case. It happens on the first redeploy, silently, and
there is no way to get the files back.

So there are exactly two settings that carry real risk if they are missing:

| Variable | Without it |
|---|---|
| `DATABASE_URL` | The database resets to empty on every deploy |
| `S3_BUCKET` | Every uploaded photo and model is deleted on every deploy |

Everything else in this document is an improvement. Those two are the
difference between a site that works and a site that loses users' work.

---

## Choosing a path

Two options are supported, and both use the same code and the same container.

**Path A — Railway for the app, AWS for the data.** Railway runs the container;
an S3 bucket holds uploads and an RDS Postgres instance holds the data. Deploys
are a `git push`. This is the recommended starting point: it is the least to
learn, and because the data lives in AWS, moving the app to AWS later is a
change of host, not a migration.

**Path B — entirely AWS.** The same container on ECS Fargate behind a load
balancer, with the same S3 and RDS. More moving parts and more to configure, but
one bill and one place where everything lives.

You do not have to decide permanently. `aws/botfolio.yaml` has a
`DeploymentMode` parameter: deploy it as `DataOnly` for Path A, and later
redeploy the same stack as `Full` to add the application half.

---

## Path A — Railway + AWS data

### 1. Create the AWS resources

```bash
aws cloudformation deploy \
  --template-file aws/botfolio.yaml \
  --stack-name botfolio-production \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      DeploymentMode=DataOnly \
      EnvironmentName=production \
      VpcId=vpc-xxxxxxxx \
      SubnetIds=subnet-aaaa,subnet-bbbb
```

`VpcId` can be the account's default VPC. `SubnetIds` needs two subnets in
different availability zones — RDS requires two even for a single-AZ database,
because it needs somewhere to fail over to.

Read what it produced:

```bash
aws cloudformation describe-stacks --stack-name botfolio-production \
  --query 'Stacks[0].Outputs' --output table
```

### 2. Get the database password

CloudFormation generated one and stored it in Secrets Manager rather than
printing it. Using the `DatabaseSecretArn` from the outputs:

```bash
aws secretsmanager get-secret-value --secret-id <DatabaseSecretArn> \
  --query SecretString --output text
```

### 3. Open the database to Railway — deliberately

The template creates the database with **no inbound rule at all**. Nothing can
connect to it yet, including Railway.

This is on purpose. Railway publishes no fixed set of addresses its containers
run from, so the only rule that always works is one that allows the whole
internet to reach the database port. A template that did that silently would be
handing you an internet-facing database without saying so. Adding it yourself
means you know it happened.

```bash
aws ec2 authorize-security-group-ingress \
  --group-id <DatabaseSecurityGroup from the stack outputs> \
  --protocol tcp --port 5432 --cidr 0.0.0.0/0
```

What still protects the database with that rule in place: it is a random
30-character password, TLS is required (`sslmode=require` in the connection
string), and the only account has rights to this one database. That is
meaningfully weaker than a private network, and it is the actual cost of
splitting the app across two providers. If it matters more than deploy
convenience, Path B removes it — in `Full` mode the rule references the
application's security group by ID and nothing else in the account can connect.

### 4. Create the S3 access key

`DataOnly` mode creates an IAM user whose entire permission set is read, write
and delete on the `uploads/` and `models/` prefixes of the one bucket. Using
`RailwayAccessUserName` from the outputs:

```bash
aws iam create-access-key --user-name <RailwayAccessUserName>
```

Save both halves — the secret is shown once.

### 5. Deploy on Railway

Point a Railway project at the GitHub repo. It reads `railway.json`, which tells
it to build the `Dockerfile` and to treat `/healthz` as the health check.

Then set these variables in the Railway dashboard:

```
APP_ENV=production
DATABASE_URL=postgresql://botfolio:<password>@<DatabaseEndpoint>:5432/botfolio?sslmode=require
S3_BUCKET=<S3Bucket>
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<from step 4>
AWS_SECRET_ACCESS_KEY=<from step 4>
FLASK_SECRET_KEY=<a long random string>
OPENAI_API_KEY=<your Botfolio project key>
OPENAI_MODEL=gpt-5.4-mini
METRICS_TOKEN=<a long random string>
```

The `daily-maintenance` cron service uses `/railway.maintenance.json` as its
custom Railway config file. Keeping it separate from `/railway.json` matters:
the website must answer `/healthz`, while `python maintenance.py` is a one-shot
job and never starts an HTTP server. The maintenance config also owns the cron
schedule while Railway chooses a current region from the project's deployment
settings.

`FLASK_SECRET_KEY` must be a real, stable random value. It signs session
cookies: if it changes, everyone is logged out, and if it is guessable, sessions
can be forged. Generate one with `python -c "import secrets;
print(secrets.token_urlsafe(48))"`.

### 6. Create the schema

The database starts empty. Once, from a Railway shell (or locally with the same
`DATABASE_URL` exported):

```bash
python seed.py
```

### 7. Check it

```bash
curl https://<your-app>.up.railway.app/healthz    # {"status":"ok"} — the app is alive
curl https://<your-app>.up.railway.app/readyz     # also checks database and S3
```

`/readyz` is the one that matters here. It reports each dependency separately,
so if the database password is wrong or the bucket is unreachable, it tells you
which — rather than the site simply returning 500s.

---

## Path B — entirely AWS

Everything from Path A applies, minus Railway and minus the manual security
group rule.

### 1. Build and push the image

```bash
aws ecr create-repository --repository-name botfolio
aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com

docker build -t botfolio .
docker tag botfolio:latest <account>.dkr.ecr.<region>.amazonaws.com/botfolio:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/botfolio:latest
```

### 2. Deploy the full stack

```bash
aws cloudformation deploy \
  --template-file aws/botfolio.yaml \
  --stack-name botfolio-production \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      DeploymentMode=Full \
      EnvironmentName=production \
      VpcId=vpc-xxxxxxxx \
      SubnetIds=subnet-aaaa,subnet-bbbb \
      ContainerImage=<account>.dkr.ecr.<region>.amazonaws.com/botfolio:latest
```

This adds the load balancer, the ECS service, and the security group rules that
connect them. The database becomes reachable only from the application's own
containers. S3 access comes from the task role, so there are no AWS keys to
store anywhere — delete the ones from Path A if you are migrating.

`SiteUrl` in the outputs is the load balancer address. For a real domain, point
a Route 53 alias at it and add an ACM certificate to the listener; until then it
is HTTP only, which is also why `FORCE_HTTPS` should stay off until the
certificate exists.

### 3. Create the schema

The database is now private, so `python seed.py` has to run from inside the VPC.
The simplest way is a one-off ECS task using the same image and task definition
with an overridden command.

---

## Staging

Deploy the same template a second time with different names:

```bash
aws cloudformation deploy \
  --template-file aws/botfolio.yaml \
  --stack-name botfolio-staging \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides DeploymentMode=DataOnly EnvironmentName=staging ...
```

This gives a separate bucket and a separate database. That separation is the
entire point: a staging environment that shares production's database is not a
staging environment, because the way you find out a migration was wrong is that
it has already run on the real data.

Set `APP_ENV=staging` on the Railway staging environment. HSTS stays off there,
which matters — a browser that receives an HSTS header from a staging domain
will refuse to load it over HTTP for a year afterwards.

---

## After it is running

**Logs.** Every line is JSON, and every line carries a `request_id`. When
someone reports an error, the page shows them a reference code; searching the
logs for that code finds the exact request, its route, its user, and the full
traceback. Passwords, tokens and cookies are stripped before anything is
written.

**Metrics.** `GET /metrics` with `Authorization: Bearer $METRICS_TOKEN` returns
request counts, error counts, requests per second and p50/p95/p99 response times
per endpoint. Without `METRICS_TOKEN` set, the route returns 404 in production
rather than exposing traffic data to anyone who guesses the path.

**Health checks.** `/healthz` answers only "is this process alive" and
deliberately does not touch the database. This is not laziness: if the liveness
check failed during a database blip, the orchestrator would conclude the
containers were broken and kill them — turning a recoverable database problem
into a total outage. `/readyz` is the one that checks dependencies.

**Backups.** RDS takes automated snapshots with a 35-day retention window. The S3
bucket has versioning on, so a deleted or overwritten file can be recovered for
30 days. Neither is a substitute for occasionally checking that a restore
actually works.

Run a non-destructive restore drill against a separate disposable PostgreSQL
database before launch and after material backup changes:

```powershell
$env:RESTORE_TEST_DATABASE_URL = '<separate disposable PostgreSQL URL>'
python tools/restore_drill.py
```

The command refuses to use the production database as its restore target. It
compares core table row counts and writes a timestamped success record only
after the restored database passes verification. Schedule `python
maintenance.py` daily, and configure Cloudflare R2 to expire quarantine objects
after 24 hours and noncurrent image/model versions after 30 days.

**Retention and holds.** Configure the production log provider to expire
routine application logs after 90 days. The AWS template does this for
CloudWatch; on Railway, set the equivalent retention in the Railway logging
destination. Botfolio separately records minimal authentication/security
events and the daily maintenance job expires them after 90 days.

Create a database hold before evidence would otherwise expire:

```bash
python maintenance.py hold content_report 123 "Active legal investigation"
python maintenance.py hold security_event 456 "Security incident preservation"
```

Release it with `python maintenance.py release <hold-id>`. For raw provider
logs, export the relevant time range to access-controlled immutable storage
before the 90-day provider expiration; a database hold cannot stop a hosting
provider from applying its own log lifecycle.

**Scaling.** If you run more than one container, set `REDIS_URL`. The rate
limiter and cache keep their state inside the process by default, so two
containers keep two separate sets of counters and the real rate limit becomes
double what is configured. Redis gives them one shared view.

---

## Reference

- `aws/README.md` — what each resource in the CloudFormation template is for
- `.env.example` — every variable, with what happens when it is unset
- `infra/settings.py` — the single place the environment is read
- `tools/smoke.py` — requests every page; run it against a new deployment
- `tools/check_translation.py` — proves every SQL statement is valid Postgres
