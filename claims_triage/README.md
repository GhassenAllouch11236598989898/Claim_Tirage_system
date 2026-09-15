# 🏥 Autonomous Multi-Agent Claims Triage System

> Insurance claims → Specialized AI agents → Recommendation → Human approval

A production-grade autonomous claims triage system built with **LangGraph**, **FastAPI**, **Redis**, and **PostgreSQL**. Claims flow through a directed agent graph with crash recovery, budget enforcement, and full decision tracing.

---

## 🏗️ Architecture

```
                    ┌──────────────────────────────────────────┐
                    │          LangGraph State Machine          │
                    │                                          │
  POST /claims ──►  │  ┌────────────┐    ┌──────────────────┐  │
                    │  │ Classifier │───►│ Severity Scorer  │  │
                    │  │   (LLM)    │    │     (LLM)        │  │
                    │  └────────────┘    └──────────────────┘  │
                    │                           │              │
                    │                    ┌──────▼──────────┐   │
                    │                    │   Reviewer      │   │
                    │                    │    (LLM)        │   │
                    │                    └──────┬──────────┘   │
                    │                           │              │
                    │                    ┌──────▼──────────┐   │
                    │                    │  Human Gate     │   │
                    │                    │   (Logic)       │   │
                    │                    └──┬──────────┬───┘   │
                    │                       │          │       │
                    │              ┌────────▼─┐  ┌────▼─────┐ │
                    │              │ Auto     │  │ Pending  │ │
                    │              │ Approve  │  │ Human    │ │
                    │              └──────────┘  └──────────┘ │
                    └──────────────────────────────────────────┘
                           │                          │
                    ┌──────▼──────┐           ┌──────▼──────┐
                    │   Redis     │           │ PostgreSQL  │
                    │ Checkpoint  │           │ Approvals   │
                    │ (Recovery)  │           │ + Traces    │
                    └─────────────┘           └─────────────┘
```

## 🤖 Agents

| Agent | Type | Purpose |
|-------|------|---------|
| **Classifier** | LLM (GPT-4o-mini) | Categorize: `injury` / `property` / `auto` |
| **Severity Scorer** | LLM (GPT-4o-mini) | Score: `low` / `medium` / `high` + estimated payout |
| **Reviewer** | LLM (GPT-4o-mini) | Quality check + confidence score + flags |
| **Human Gate** | Logic | Route to human if `severity=high` OR `confidence<0.8` |

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/claims` | Submit a new claim |
| `GET` | `/claims/{id}/trace` | View decision tree |
| `GET` | `/claims/{id}` | Get claim status |
| `GET` | `/pending_approvals` | Claims waiting for human |
| `POST` | `/approve/{id}` | Human approval decision |
| `POST` | `/claims/resume/{id}` | Resume interrupted claim |
| `GET` | `/checkpoints` | List active checkpoints |
| `GET` | `/health` | Health check |

## 🚀 Quick Start

### 1. Set up environment

```bash
# Copy and edit environment variables
cp claims_triage/.env.example claims_triage/.env
# Edit .env and add your OPENAI_API_KEY
```

### 2. Start with Docker

```bash
docker compose -f docker-compose.claims.yml up --build
```

This starts:
- **FastAPI** on `http://localhost:8000`
- **Redis** on `localhost:6379`
- **PostgreSQL** on `localhost:5432`

### 3. Submit a claim

```bash
curl -X POST http://localhost:8000/claims \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Vehicle rear-ended at intersection causing whiplash and bumper damage",
    "policy_number": "POL-2024-001234",
    "policy_limit": 100000,
    "claimant_name": "John Smith",
    "incident_date": "2024-11-15",
    "claimed_amount": 15000,
    "supporting_info": "Police report filed"
  }'
```

### 4. View decision trace

```bash
curl http://localhost:8000/claims/{claim_id}/trace
```

### 5. Run tests

```bash
# Unit tests (no Docker needed)
pip install -r claims_triage/requirements.txt
pytest claims_triage/tests/test_unit.py -v

# Integration tests (Docker must be running)
python claims_triage/tests/test_integration.py
```

## 🔒 Safety Features

### Budget Ceiling
- **50,000 token** hard limit per claim
- **5 minute** wall-clock timeout
- Automatic termination on breach → `BUDGET_EXCEEDED` status

### Crash Recovery
- Redis checkpoint after **every agent step**
- On restart: `POST /claims/resume/{id}` resumes from last checkpoint
- Checkpoints auto-expire after 24 hours

### Human Approval Gate
- Triggers when:
  - `severity = HIGH`
  - `overall_confidence < 0.8`
  - Reviewer flags for human review
- Human decisions via `POST /approve/{id}`

### Step-Level Tracing
Every decision logged with:
- Agent name + reasoning
- Latency (ms) + tokens used
- Input/output data
- Error details (if any)

## 📁 Project Structure

```
claims_triage/
├── __init__.py           # Package init
├── config.py             # Settings (env-based)
├── models.py             # Pydantic schemas (17 models)
├── agents.py             # 4 specialized agents
├── graph.py              # LangGraph state machine
├── checkpointing.py      # Redis crash recovery
├── budget.py             # Budget enforcement
├── tracing.py            # Step-level tracing
├── database.py           # PostgreSQL ORM + CRUD
├── api.py                # FastAPI application
├── init.sql              # DB schema
├── requirements.txt      # Python dependencies
├── .env.example          # Environment template
└── tests/
    ├── test_unit.py          # Unit tests
    └── test_integration.py   # Integration test suite

docker-compose.claims.yml    # Docker setup (3 services)
Dockerfile.claims            # FastAPI container
```

## 🧪 Test Claims

The integration test suite includes 5 diverse claims:

1. **Simple Auto** — Minor fender bender ($1,200) → Expected: auto/low/auto-approve
2. **Simple Property** — Burst pipe ($8,500) → Expected: property/low/auto-approve
3. **Complex Multi-Factor** — Highway collision with injuries ($125k) → Expected: auto/high/human
4. **High-Severity Injury** — Spinal cord injury ($750k) → Expected: injury/high/human
5. **Property Disaster** — House fire ($350k) → Expected: property/high/human

## ⚙️ Configuration

All settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM model |
| `MAX_TOKENS` | `50000` | Budget ceiling |
| `MAX_WALL_CLOCK_SECONDS` | `300` | Time ceiling (5min) |
| `HUMAN_GATE_CONFIDENCE_THRESHOLD` | `0.8` | Auto-approve above this |
| `REDIS_HOST` | `localhost` | Redis host |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
