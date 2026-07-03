---
title: Revio AI
emoji: 🟢
colorFrom: green
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
---

# Revio AI Backend

Autonomous revenue intelligence platform — event-driven multi-agent operating system for revenue operations.

## Architecture

```
┌─────────────┐     webhooks/schedules      ┌──────────────────┐
│  FastAPI    │◄───────────────────────────►│  Celery Workers  │
│  API Server │                               │  (7 Agents)      │
└──────┬──────┘                               └────────┬─────────┘
       │                                               │
       ▼                                               ▼
┌─────────────┐     task queues              ┌──────────────────┐
│  Supabase   │◄────────────────────────────►│  Redis           │
│  PostgreSQL │                               │  (Broker/Cache)  │
└─────────────┘                               └──────────────────┘
       ▲
       │ orchestrator chains:
       │ CRM Sync → REVIVE → MESSAGE → EXECUTION
       │ PULSE (2h) | SCOUT (6am) | REPORT (7am) | RESPONSE (5min)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| Database | PostgreSQL (Supabase) |
| Queue | Redis + Celery |
| Scheduler | Celery Beat |
| Billing | Stripe |
| CRM | HubSpot + Salesforce OAuth |
| LLM | OpenAI / Anthropic |
| Email | SendGrid + Resend |
| SMS | Twilio |
| Monitoring | Sentry |

## Project Structure

```
revio-ai/
├── app/
│   ├── main.py                 # FastAPI entrypoint
│   ├── config.py               # Settings via pydantic-settings
│   ├── core/                   # Security, encryption, rate limits, Sentry
│   ├── db/models/              # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── api/routes/             # REST endpoints
│   ├── services/               # Business logic layer
│   │   ├── billing/            # Stripe
│   │   ├── crm/                # HubSpot, Salesforce, sync
│   │   ├── llm/                # OpenAI/Anthropic
│   │   ├── messaging/          # Email, SMS
│   │   └── import/             # CSV upload
│   ├── agents/                 # 7 specialized AI agents
│   ├── orchestrator/           # Master orchestration engine
│   └── workers/                # Celery app + tasks
├── alembic/                    # Database migrations
├── supabase/rls_policies.sql   # Row-level security
├── docker-compose.yml
└── railway.toml                # Deployment configs
```

## Agents

| Agent | Schedule | Queue | Purpose |
|-------|----------|-------|---------|
| REVIVE | Daily 9am | `revive` | Analyze dormant leads, score recovery |
| PULSE | Every 2h | `pulse` | Pipeline health, revenue at risk |
| SCOUT | Daily 6am | `scout` | External buying signals (Apollo, Crunchbase) |
| MESSAGE | Post-REVIVE | `message` | Generate email/SMS/WhatsApp copy |
| EXECUTION | Post-MESSAGE | `execution` | Autonomous multi-channel delivery |
| RESPONSE | Every 5min | `response` | Detect engagement, reactivate leads |
| REPORT | Daily 7am | `report` | Executive daily report via Resend |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/stripe/webhook` | Stripe billing events |
| GET/POST | `/api/v1/crm/hubspot/oauth` | HubSpot OAuth |
| GET/POST | `/api/v1/crm/salesforce/oauth` | Salesforce OAuth |
| POST | `/api/v1/upload/csv` | CSV lead import |
| GET | `/api/v1/dashboard/overview` | Dashboard metrics |
| GET | `/api/v1/leads` | List leads |
| GET | `/api/v1/leads/{id}` | Lead detail + analysis |
| GET | `/api/v1/reports/daily` | Daily AI reports |
| GET | `/api/v1/campaigns` | Campaign history |
| POST | `/api/v1/campaign/send` | Manual campaign send |
| GET | `/api/v1/agent/logs` | Agent execution logs |
| GET | `/api/v1/pipeline/health` | Pipeline health score |

## Quick Start

```bash
cp .env.example .env
# Fill in Supabase, Redis, Stripe, LLM, and messaging credentials

pip install -r requirements.txt
alembic upgrade head

# Start services
docker-compose up -d

# Or locally:
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q revive,pulse,scout,message,execution,response,report,orchestrator,scheduler
celery -A app.workers.celery_app beat
```

## Deployment (Railway)

1. Create three Railway services from the same repo:
   - **API** — use `railway.toml`
   - **Worker** — use `railway.worker.toml`
   - **Beat** — use `railway.beat.toml`
2. Add Redis plugin and set `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`
3. Connect Supabase PostgreSQL as `DATABASE_URL` and `DATABASE_URL_SYNC`
4. Set all secrets from `.env.example`
5. Run `alembic upgrade head` via Railway deploy hook
6. Apply `supabase/rls_policies.sql` in Supabase SQL editor

## Security

- OAuth tokens encrypted at rest (Fernet)
- JWT authentication on all API routes
- Rate limiting via SlowAPI
- Stripe webhook signature verification
- HubSpot webhook HMAC verification
- Supabase RLS for multi-tenant isolation

## License

Proprietary — Revio AI
