# A-Share Research Agent — Deployment Guide

English | [简体中文](DEPLOYMENT.zh-CN.md)

This guide covers deployment, configuration, data initialisation, release and rollback, backup, and troubleshooting for three environments: local development, local full stack, and cloud demo.

Related documents: [Architecture](ARCHITECTURE.md) · [Technical Decision Handbook](TECH_DECISIONS.md)

> This guide defines the deployment specification. The components each command depends on are delivered milestone by milestone (architecture document §23).

---

## 1. Environments

| Environment | Purpose | Shape | Exposure |
|---|---|---|---|
| Local development | Day-to-day coding and debugging | Database and Redis in containers; api, worker and frontend as local processes with hot reload | Localhost only |
| Local full stack | Integration testing, evaluation, fault injection | All services via `docker compose` | Localhost only |
| Cloud demo | Public demo and real-user trials | One cloud VM + compose + Caddy | Ports 80 / 443 only |

## 2. Services

| Service | Image | Port (in container) | Network | Persistence |
|---|---|---|---|---|
| frontend | Custom (Nginx + static build) | 80 | default | — |
| api | Custom (FastAPI / Uvicorn) | 8000 | default, sandbox_net | — |
| worker | Custom (reuses api code) | — | default, sandbox_net | — |
| sandbox-runner | Custom | 8080 | sandbox_net (`internal: true`) | — |
| postgres | Custom (PostgreSQL 16 + pgvector + Chinese tokenizer extension) | 5432 | default | `pgdata` |
| redis | redis:7 | 6379 | default | `redisdata` (AOF) |
| otel-collector | Official image | 4317 / 4318 | default | — |
| prometheus | Official image (profile: obs) | 9090 | default | `prometheus_data` |
| grafana | Official image (profile: obs) | 3000 | default | — |
| caddy | Official image (cloud only) | 80 / 443 | default | `caddy_data` |

**postgres needs a custom image.** Chinese full-text search depends on a Chinese tokenizer extension (zhparser or pg_jieba), which the official pgvector image does not include. The image is built from `infra/postgres/Dockerfile`; the init script runs `CREATE EXTENSION vector;`, creates the tokenizer extension, and defines the Chinese text search configuration.

## 3. Prerequisites

### 3.1 Software

| Software | Version | Purpose |
|---|---|---|
| Docker Engine | 24 or later | Containers |
| Docker Compose | v2 (`docker compose` subcommand) | Orchestration |
| Python | 3.12 or later | Local development |
| Node.js | 20 LTS or later | Frontend development |
| Git | Any recent version | Source control |

### 3.2 Hardware

| Scenario | Minimum | Recommended |
|---|---|---|
| Local development | 4 cores / 8 GB | 8 cores / 16 GB |
| Cloud demo (embedding and reranking via cloud services) | 2 cores / 4 GB | 4 cores / 8 GB |
| Cloud demo (self-hosted embedding and reranking models) | 4 cores / 16 GB | 8 cores / 32 GB, or a GPU |

Model choice for embedding and reranking is covered by decision D11 in the handbook. Self-hosted models need considerably more memory; factor this in when choosing.

### 3.3 External services

| Service | Required | Notes |
|---|---|---|
| Model provider API key | Yes (except in mock mode) | See §5 Region and models |
| Domain name | Required for the cloud demo | Needed for HTTPS certificates |
| ICP filing | Required when the domain points to a server in mainland China | See §5 |

## 4. Configuration

All configuration is injected through environment variables. Copy `.env.example` to `.env` and fill it in. `.env` is excluded by `.gitignore` and must never be committed.

### 4.1 Environment variables

| Variable | Required | Description | Example |
|---|---|---|---|
| `APP_ENV` | Yes | `dev` / `local` / `prod`; controls log format, migration policy and similar | `dev` |
| `LLM_PROVIDER` | Yes | `mock` / `anthropic` / `openai_compat`. `mock` returns canned responses and needs no API key | `mock` |
| `ANTHROPIC_API_KEY` | Optional | Required when `LLM_PROVIDER=anthropic` | — |
| `ANTHROPIC_MODEL` | Optional | Anthropic model identifier | — |
| `OPENAI_COMPAT_BASE_URL` | Optional | OpenAI-compatible endpoint | DeepSeek: `https://api.deepseek.com`; Qwen: `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `OPENAI_COMPAT_API_KEY` | Optional | Required when `LLM_PROVIDER=openai_compat` | — |
| `OPENAI_COMPAT_MODEL` | Optional | Model identifier | `deepseek-chat`, `qwen-plus` |
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql+psycopg://app:***@postgres:5432/research` |
| `REDIS_URL` | Yes | Redis connection string | `redis://redis:6379/0` |
| `SANDBOX_URL` | Yes | sandbox-runner address | `http://sandbox-runner:8080` |
| `JWT_SECRET` | Yes | Token signing secret, at least 32 random bytes | — |
| `DAILY_COST_LIMIT_USD` | Required in cloud | Global daily cost ceiling; new tasks are rejected once exceeded | `5` |
| `USER_DAILY_COST_LIMIT_USD` | Required in cloud | Per-user daily cost ceiling | `1` |
| `MAX_DEPTH` | Required in cloud | Maximum allowed research depth | `standard` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional | Trace export endpoint | `http://otel-collector:4317` |
| `PIP_INDEX_URL` | Optional | Faster Python package installs from mainland China | A domestic mirror URL |
| `NPM_REGISTRY` | Optional | Faster frontend package installs from mainland China | A domestic mirror URL |

Model-tier mappings, the model price table, retrieval parameters and budget settings live in version-controlled `config/*.yaml` files, not in environment variables.

### 4.2 Secrets

- Secrets live only in `.env` or the cloud host's environment, never in code, images or logs.
- Secret fields are masked in logs and traces.
- On the cloud host, `.env` has mode `600` and is owned by the deploy user.
- After rotating a key, restart the affected services and revoke the old key in the provider console.

## 5. Region and models

The deployment region determines which model services are available and which compliance requirements apply. Decide it before deploying.

| | Deployed in mainland China | Deployed outside mainland China |
|---|---|---|
| Available models | Models that can be called compliantly from mainland China (for example Qwen, DeepSeek), with `LLM_PROVIDER=openai_compat` | Anthropic and other international providers; domestic providers are usually reachable too |
| Unavailable | Anthropic's model services are not offered in mainland China | — |
| Domain | Must complete ICP filing to point at a mainland server | No filing needed |
| Access from mainland China | Fast and stable | Must be measured; may be unstable |
| Image and package downloads | Configure `PIP_INDEX_URL`, `NPM_REGISTRY` and a Docker registry mirror | Not needed |

Switching models only requires changing environment variables and the tier mapping in `config/models.yaml`. Quantify the quality difference between mappings with the evaluation harness (Experiment D) before choosing the deployment configuration.

## 6. Local development

```bash
# 1. Code and configuration
git clone <repo-url> && cd <repo>
cp .env.example .env              # keep LLM_PROVIDER=mock to start

# 2. Database and Redis
docker compose up -d postgres redis

# 3. Backend
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 4. Worker (new terminal, from the repository root)
cd worker && python -m app.consumer

# 5. sandbox-runner (new terminal; runs as a plain process in local development)
cd sandbox-runner && python -m app.main

# 6. Frontend (new terminal)
cd frontend && npm install && npm run dev
```

In local development the sandbox-runner runs as an ordinary process with no container isolation, for debugging only. Anything that tests sandbox security must run in the local full stack.

## 7. Local full stack

```bash
docker compose up -d --build                  # core services
docker compose --profile obs up -d            # add Prometheus and Grafana
docker compose ps                             # all services should be healthy
```

Health checks enforce start-up order: api and worker start only after postgres and redis are healthy. The api's `/readyz` checks database connectivity, Redis connectivity and the migration version.

**Check**

```bash
curl -f http://localhost:8000/healthz
curl -f http://localhost:8000/readyz
```

## 8. Data initialisation

Run these in order on first deployment or when rebuilding an environment.

### 8.1 Database migrations

```bash
docker compose run --rm api alembic upgrade head
```

| `APP_ENV` | Behaviour when the migration version does not match at start-up |
|---|---|
| `dev` / `local` | Upgrade automatically |
| `prod` | Refuse to start; migrations must be run explicitly as part of release |

### 8.2 Data ingestion

```bash
# Security master data (including delisted securities)
docker compose run --rm worker python -m app.data.ingest securities

# Structured financial data (bitemporal, with revisions)
docker compose run --rm worker python -m app.data.ingest fundamentals --symbols <symbol list> --years 2021-2024

# Annual reports and announcements: download, parse, chunk, embed, index
docker compose run --rm worker python -m app.rag.ingest filings --symbols <symbol list> --years 2021-2024
```

- Ingestion deduplicates by `content_hash`; re-running produces no duplicates, so a failed run can simply be repeated.
- Accounting identity checks run during ingestion; records that fail are marked with `quality_flag`.
- Embedding calls are billed per use when a cloud embedding service is used. Estimate the cost with one or two companies before the first full ingestion.
- Check the terms of use of each data source before any public deployment.

### 8.3 Evaluation set and baseline

```bash
harness run --suite factual --repeat 3
harness report --out docs/EVAL_REPORT.md
```

The first run's results are stored as the baseline in `harness/baselines/`.

## 9. Cloud demo deployment

### 9.1 Host preparation

1. Choose the region per §5 and the size per §3.2; a system disk of 50 GB or more is recommended.
2. Create a non-root deploy user; allow SSH key login only and disable password login.
3. The firewall (security group) allows only 22 (restricted source IPs), 80 and 443. Database, Redis, Grafana and other ports are not exposed.
4. Install Docker Engine and the Compose plugin; add the deploy user to the `docker` group.
5. Point the domain's A record at the host's public IP. Mainland hosts must complete ICP filing first.

### 9.2 Deploy

```bash
git clone <repo-url> && cd <repo>
cp .env.example .env && chmod 600 .env       # fill in production values, APP_ENV=prod

docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Differences in `docker-compose.prod.yml` relative to development:

| Item | Development | Cloud |
|---|---|---|
| Port exposure | Every service exposed to the host | Only caddy exposes 80 / 443 |
| Restart policy | `no` | `unless-stopped` |
| Resource limits | None | `mem_limit` on every service |
| Logs | Text | JSON with size-based rotation |
| Database migrations | Automatic at start-up | Explicit step in the release process |
| Images | Built locally | Tagged with the commit SHA |

### 9.3 Reverse proxy

Caddy is the only public entry point and obtains and renews HTTPS certificates automatically.

```
example.com {
    encode gzip

    handle /v1/* {
        reverse_proxy api:8000 {
            flush_interval -1
        }
    }

    handle {
        reverse_proxy frontend:80
    }
}
```

**SSE requires proxy buffering to be off.** `flush_interval -1` forwards responses immediately. Without it, events are batched and the frontend appears frozen before dumping all output at once. If the Nginx inside the frontend container also proxies API requests, set `proxy_buffering off;` there too, or have the api return an `X-Accel-Buffering: no` header on SSE responses.

### 9.4 Cost protection

An unprotected public LLM application can exhaust a model quota in a very short time. All of the following must be active in the cloud environment:

| Measure | Configuration |
|---|---|
| Mandatory login | Every `/v1/*` endpoint requires a valid token; no anonymous access |
| Per-account and per-IP rate limits | Caps on request rate and concurrent tasks per account and per IP |
| Daily cost circuit breaker | `DAILY_COST_LIMIT_USD`, `USER_DAILY_COST_LIMIT_USD`; new tasks are rejected once exceeded |
| Depth ceiling | `MAX_DEPTH`, which bounds the token budget per research run |
| Provider-side quota | A spending cap set in the model provider's console, as the last line of defence |

Trial accounts are created by an administrator; self-service sign-up is not offered.

## 10. Release and rollback

### 10.1 Release

```
PR merged to main
  → CI passes (lint, type check, tests, evaluation gate)
  → images built, tagged with the commit SHA
  → cloud host pulls the new images
  → if there are database migrations: run them first
  → docker compose up -d (recreates only changed services)
  → check /readyz and key pages
```

Migrations must be backward compatible: new columns start nullable, and dropping a column takes two releases (stop using it, then drop it), so that rolling back to the previous code still works against the current schema.

### 10.2 Rollback

```bash
# Set the image tag in .env or the compose file back to the previous commit SHA
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Roll the database back only when a migration was not backward compatible, and only after a restore drill has confirmed it works.

### 10.3 Graceful shutdown

On SIGTERM, a worker stops claiming new tasks, waits for its current node to finish and write its checkpoint, then exits. Give the worker a `stop_grace_period` in compose no shorter than the per-node timeout. Unfinished tasks resume from their checkpoint on another worker or after restart.

## 11. Backup and restore

| Target | Method | Frequency | Retention |
|---|---|---|---|
| PostgreSQL | `pg_dump` logical backup, compressed and stored off-host | Daily | 14 days |
| Redis | AOF persistence | Continuous | — |
| `.env` and configuration | Encrypted offline copy | On change | — |

```bash
# Backup
docker compose exec -T postgres pg_dump -U app -Fc research > backup_$(date +%F).dump

# Restore (into an empty database)
docker compose exec -T postgres pg_restore -U app -d research --clean < backup_YYYY-MM-DD.dump
```

- Redis holds only the queue, caches and rate-limit state. If it is lost, tasks are recovered from run state and checkpoints in the database; Redis backups are not relied upon.
- Run a restore drill at least monthly: restore into a separate environment and run an evaluation subset to confirm the data is usable.

## 12. Monitoring and alerts

With the `obs` profile enabled, Grafana reads metrics from Prometheus. Grafana is not exposed publicly; reach it through an SSH tunnel:

```bash
ssh -L 3000:localhost:3000 <user>@<host>
```

| Alert | Condition |
|---|---|
| Cost anomaly | Cost per unit time exceeds a multiple of baseline, or approaches the daily ceiling |
| Rising failure rate | Run failure rate exceeds threshold |
| Queue backlog | `queue_depth` stays above threshold |
| Latency regression | End-to-end P95 exceeds threshold |
| Retry surge | Abnormal growth in `llm_retries_total`, usually a provider outage or rate limiting |
| Short retrieval results | Abnormal growth in `retrieval_short_results_total` |
| Disk | Data volume usage above 80% |

## 13. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Report shows nothing for a long time, then appears all at once | A proxy is buffering SSE | Check Caddy's `flush_interval -1` and Nginx's `proxy_buffering off` |
| Every calculation question fails; logs show sandbox unreachable | sandbox-runner is not on `sandbox_net`, or `network_mode: none` was used | Check compose networks: api, worker and sandbox-runner must all be on `sandbox_net` |
| Keyword search returns almost nothing | Chinese tokenizer extension not installed, or the tsvector was not built with the Chinese configuration | Check the extension exists; rebuild the `tsv` column and index with the Chinese configuration |
| Noticeably fewer results when filtering to a single security | Filtered recall shortfall on the approximate index | Check that `hnsw.iterative_scan` is enabled; inspect `retrieval_short_results_total` |
| Model calls time out or are refused | The deployment region cannot reach that provider | Switch to a provider available in that region, per §5 |
| Many 429 responses from the model provider | Provider rate limiting | Lower the concurrent task cap; check that the global retry budget is in effect |
| api fails to start; `/readyz` reports a migration version mismatch | Migrations not run in production | Run migrations explicitly per §8.1 |
| Task stuck in running | Worker lost and orphan recovery not triggered | Check worker heartbeats and the recovery job; check whether the run's recovery count has hit its limit |
| All new tasks rejected for the day | Daily cost circuit breaker tripped | Check the cost dashboard for abnormal usage; if legitimate, it resets the next day |

## 14. Go-live checklist

- [ ] Deployment region matches the model provider (§5); mainland hosts have completed ICP filing
- [ ] `.env` is complete, mode `600`, `APP_ENV=prod`, and `LLM_PROVIDER` is not `mock`
- [ ] Security group allows only 22 (restricted source), 80 and 443
- [ ] Migrations have run and `/readyz` is healthy
- [ ] HTTPS certificate issued
- [ ] SSE output streams incrementally over the public internet
- [ ] All cost protections are active (§9.4) and a spending cap is set in the provider console
- [ ] The sandbox cannot reach the internet (run an outbound request in the sandbox and confirm it fails)
- [ ] Daily backups are scheduled and one restore drill has been completed
- [ ] Alerts are configured and have been test-fired once
- [ ] The holdout evaluation has been run against this deployment configuration and recorded in the evaluation report
