# Lulu Sales Intelligence Dashboard

> **Enterprise-grade real-time sales analytics platform for Lulu Hypermarket UAE** — featuring live streaming data, AI-powered insights, role-based access control, and comprehensive retail operations management.

[![CI Pipeline](https://github.com/mercydeez/lulu-sales-intelligence-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/mercydeez/lulu-sales-intelligence-dashboard/actions/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=nextdotjs)](https://nextjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql)](https://www.postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://docs.docker.com/compose/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)](https://www.python.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript)](https://www.typescriptlang.org)

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Solution Overview](#solution-overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [Getting Started](#getting-started)
- [Environment Configuration](#environment-configuration)
- [API Documentation](#api-documentation)
- [Deployment](#deployment)
- [Testing](#testing)
- [Security](#security)
- [Scalability](#scalability)
- [Ethical AI & Responsible Design](#ethical-ai--responsible-design)
- [Future Improvements](#future-improvements)
- [Author](#author)

---

## Problem Statement

Large-scale retailers generate millions of transactions daily across geographically distributed stores. Key operational challenges include:

- **Delayed visibility** into real-time sales performance across regions
- **Fragmented data** making cross-store inventory management reactive rather than proactive
- **Limited AI integration** for forecasting, anomaly detection, and actionable insights
- **Lack of role-based governance** exposing sensitive financial data without access controls
- **Manual reporting workflows** consuming analyst time on repetitive tasks

## Solution Overview

Lulu Intelligence Dashboard is a production-grade, full-stack analytics platform that provides:

1. **Real-time streaming** — Server-Sent Events (SSE) push live sales data to dashboards with sub-second latency
2. **AI-powered assistant** — Natural language chatbot with OpenAI integration for querying sales data, generating insights, and voice interaction
3. **Role-based access control (RBAC)** — Granular permissions at region, store, and feature levels with JWT authentication
4. **Predictive analytics** — Time-series forecasting using statistical models for demand planning
5. **Operational modules** — Inventory management, promotions engine, employee performance tracking, and alert systems

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      NGINX (Reverse Proxy)                  │
└─────────────┬───────────────────────────┬───────────────────┘
              │                           │
┌─────────────▼────────────┐  ┌───────────▼───────────────────┐
│   Next.js 14 Frontend    │  │     FastAPI Backend           │
│                          │  │                               │
│  • App Router (RSC)      │  │  • REST API + SSE Streaming   │
│  • Tailwind CSS          │  │  • JWT Auth + RBAC            │
│  • Recharts Viz          │  │  • AI Chat (OpenAI)           │
│  • Auth Context          │  │  • Background Data Generator  │
│  • SSE Consumers         │  │  • Redis Pub/Sub              │
└──────────────────────────┘  └──────┬──────────┬─────────────┘
                                     │          │
                              ┌──────▼───┐ ┌────▼─────┐
                              │PostgreSQL │ │  Redis   │
                              │   15     │ │    7     │
                              │          │ │          │
                              │• Sales   │ │• Pub/Sub │
                              │• Users   │ │• Cache   │
                              │• RBAC    │ │• Sessions│
                              │• Employees│ │• Rate    │
                              │• Inventory│ │  Limiting│
                              └──────────┘ └──────────┘
```

### Data Flow

1. **Background Generator** creates realistic sales events every 10 seconds
2. Events are written to PostgreSQL and published to Redis channels
3. SSE endpoints stream data to connected frontend clients
4. Frontend components update in real-time without polling
5. AI assistant queries live data for natural language responses

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS | Server-side rendering, type safety, responsive UI |
| **Visualization** | Recharts, Lucide Icons | Interactive charts, consistent iconography |
| **Backend** | FastAPI, Python 3.11 | Async REST API, SSE streaming, middleware stack |
| **Database** | PostgreSQL 15 | Persistent storage, complex analytics queries |
| **Cache/PubSub** | Redis 7 | Real-time messaging, response caching, rate limiting |
| **AI/ML** | OpenAI GPT, Deepgram STT/TTS | Conversational AI, voice interface |
| **Auth** | JWT (python-jose), bcrypt | Stateless auth, secure password hashing |
| **Infrastructure** | Docker Compose, NGINX | Container orchestration, reverse proxy |

---

## Features

### Core Dashboard
- **Real-time KPIs** — Total sales, average transaction, active stores, streaming counts
- **Live sales feed** — SSE-powered table showing transactions as they occur
- **Interactive charts** — Sales trends, store comparisons, category breakdowns, daily patterns

### AI Assistant
- **Natural language chat** — Ask questions like "What were Dubai store sales this week?"
- **Streaming responses** — Token-by-token AI responses with OpenAI integration
- **Voice interface** — Speech-to-text input and text-to-speech output via Deepgram
- **Intelligent fallback** — Data-driven responses when OpenAI is unavailable

### Authentication & Authorization
- **JWT authentication** — Access + refresh token flow with automatic renewal
- **Role hierarchy** — Super Admin → Regional Manager → Store Manager → Analyst
- **Row-level security** — Users see only data for their assigned stores/regions
- **Session management** — Token blacklisting on logout, failed-attempt lockout

### Inventory Management
- **Stock monitoring** — Real-time stock levels derived from sales velocity
- **Reorder alerts** — Automatic low-stock and out-of-stock notifications
- **Category analytics** — Inventory health by product category

### Employee Performance
- **360° employee profiles** — Bio cards with performance history
- **Performance scoring** — Composite scores from sales, attendance, customer ratings
- **Live streaming** — Real-time performance metric updates via SSE

### Promotions Engine
- **Active promotions** — Track running campaigns with performance metrics
- **AI suggestions** — Data-driven promotion recommendations
- **ROI tracking** — Measure promotion effectiveness against baselines

### Alerts & Monitoring
- **Anomaly detection** — Statistical deviation alerts for unusual sales patterns
- **System health** — Database, Redis, and API health monitoring
- **Rate limiting** — Redis-backed sliding window with in-memory fallback

### Reporting
- **PDF export** — Professional reports with charts and tables
- **Multi-format** — Sales, inventory, and performance report types

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Git

### Quick Start

```bash
# Clone the repository
git clone https://github.com/your-username/lulu-intelligence-dashboard.git
cd lulu-intelligence-dashboard

# Start all services
docker compose up -d

# Verify services are running
docker compose ps
```

The application will be available at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs (Swagger)**: http://localhost:8000/docs

### Database Migrations

On first run, apply the database migrations:

**Linux / macOS:**
```bash
cat database/migrations/001_auth_system.sql | docker exec -i sales_db psql -U salesuser -d salesdb
cat database/migrations/002_inventory_alerts.sql | docker exec -i sales_db psql -U salesuser -d salesdb
cat database/migrations/003_promotions_analytics.sql | docker exec -i sales_db psql -U salesuser -d salesdb
cat database/migrations/004_employee_system.sql | docker exec -i sales_db psql -U salesuser -d salesdb
```

**Windows (PowerShell):**
```powershell
Get-Content database/migrations/001_auth_system.sql | docker exec -i sales_db psql -U salesuser -d salesdb
Get-Content database/migrations/002_inventory_alerts.sql | docker exec -i sales_db psql -U salesuser -d salesdb
Get-Content database/migrations/003_promotions_analytics.sql | docker exec -i sales_db psql -U salesuser -d salesdb
Get-Content database/migrations/004_employee_system.sql | docker exec -i sales_db psql -U salesuser -d salesdb
```

### Default Users

After running migrations, three demo users are created:

| Role | Email | Access Scope |
|------|-------|-------------|
| Super Admin | `atharva@lulu.ae` | Full access to all regions and stores |
| Regional Manager | `krishna@lulu.ae` | Dubai region only |
| Store Manager | `yash@lulu.ae` | Al Barsha store only |

---

## Environment Configuration

### Backend Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://salesuser:salespass@postgres:5432/salesdb` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `JWT_SECRET_KEY` | — | **Required in production**: Secret for JWT signing |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `OPENAI_API_KEY` | — | Optional: Enables AI chat features |
| `DEEPGRAM_API_KEY` | — | Optional: Enables voice interface |
| `ENVIRONMENT` | `development` | Set to `production` for hardened security |
| `RATE_LIMIT_REQUESTS` | `100` | Max requests per minute per IP |

### Frontend Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API base URL |
| `NEXT_PUBLIC_SSE_URL` | `http://localhost:8000/api/stream` | SSE streaming endpoint |

---

## API Documentation

Interactive Swagger documentation is available at `/docs` when the backend is running.

### Key Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/auth/login` | — | Authenticate user |
| `POST` | `/api/auth/logout` | Bearer | Invalidate session |
| `GET` | `/api/kpis` | Bearer | Dashboard KPI metrics |
| `GET` | `/api/sales/` | Bearer | Sales data with filtering |
| `GET` | `/api/sales/aggregated` | Bearer | Aggregated analytics |
| `GET` | `/stream/sales` | — | SSE real-time sales stream |
| `GET` | `/api/analytics/trends` | Bearer | Sales trend analysis |
| `POST` | `/api/ai/chat/stream` | Bearer | AI chat (streaming) |
| `GET` | `/api/inventory` | Bearer | Inventory status |
| `GET` | `/api/alerts` | Bearer | Active alerts |
| `GET` | `/api/employees` | Bearer | Employee listing |
| `GET` | `/api/reports/sales` | Bearer | Sales reports |
| `GET` | `/health` | — | System health check |

---

## Deployment

### Production with Docker Compose

```bash
docker compose -f docker-compose.production.yml up -d
```

### Production Checklist

1. **Set strong secrets** — Override `JWT_SECRET_KEY` via environment variables
2. **Enable HTTPS** — Configure NGINX with TLS certificates
3. **Restrict CORS** — Set `CORS_ORIGINS` to your production domain only
4. **Database backups** — Configure PostgreSQL point-in-time recovery
5. **Log aggregation** — Forward container logs to a centralized logging system
6. **Health monitoring** — Use `/api/monitoring/health` with your alerting system

---

## Testing

The project includes a **pytest-based test suite** covering security validation, configuration, health checks, and middleware.

### Running Tests Locally

```bash
# Inside the backend container
docker exec sales_backend python -m pytest tests/ -v --tb=short

# Or locally (with dependencies installed)
cd backend
pytest tests/ -v
```

### Test Modules

| Module | Description |
|--------|-------------|
| `test_security.py` | Validates insecure-default detection, production fail-fast, staging checks |
| `test_config.py` | Settings defaults, overrides, and logger setup |
| `test_health.py` | `/health` endpoint response structure and fields |
| `test_middleware.py` | Request ID generation, rate limiting, security headers |

### CI/CD Pipeline

Every push and pull request to `main` triggers a **GitHub Actions** workflow that:

1. **Backend** — Installs Python 3.11, runs pytest
2. **Frontend** — Installs Node 20, TypeScript check, Next.js production build
3. **Docker** — Validates compose config, builds both images

See the badge at the top of this README for current build status.

### Health Check Verification

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "healthy",
  "redis": "healthy",
  "version": "1.0.0"
}
```

### Error Handling

All API errors return a **consistent JSON structure**:

```json
{
  "error": true,
  "status_code": 422,
  "message": "Validation failed",
  "details": [{"field": "body → email", "message": "invalid email", "type": "value_error"}],
  "path": "/api/auth/login",
  "timestamp": "2026-02-25T12:00:00+00:00"
}
```

Three global handlers cover: HTTP errors, validation errors, and unhandled exceptions (logged server-side, safe 500 returned to clients).

---

## Security

### Authentication & Session Management
- **JWT tokens** with configurable expiration (30min access, 7-day refresh)
- **bcrypt** password hashing with automatic salting
- **Account lockout** after 5 failed attempts (30-minute cooldown)
- **Token blacklisting** on logout via Redis

### API Protection
- **Rate limiting** — Redis-backed sliding window (100 req/min default)
- **CSRF protection** — Double-submit cookie pattern for non-Bearer requests
- **Request body limits** — Configurable max payload size (10MB default)
- **Security headers** — CSP, HSTS, X-Frame-Options, X-Content-Type-Options

### Infrastructure
- **Non-root containers** — Backend runs as unprivileged user
- **Network isolation** — Services communicate via internal Docker network
- **No secret leakage** — Secrets loaded from environment variables

---

## Scalability

| Component | Scaling Strategy |
|-----------|-----------------|
| **Frontend** | Horizontal scaling behind load balancer; standalone Next.js output |
| **Backend** | Stateless design enables horizontal scaling; Redis handles shared state |
| **Database** | Read replicas for analytics queries; connection pooling via SQLAlchemy |
| **Redis** | Redis Cluster for high availability; separate instances for cache vs pub/sub |
| **SSE Streams** | Per-connection pub/sub; scales with Redis pub/sub capacity |

---

## Ethical AI & Responsible Design

### Data Fairness
- **Balanced synthetic data** — Employee generation uses equitable gender distribution rather than biased assumptions
- **Inclusive options** — UI forms offer Male, Female, Non-binary, and "Prefer not to say" for gender
- **Transparent scoring** — Performance scoring weights are visible and configurable, not opaque

### AI Transparency
- **Fallback responses** — When AI is unavailable, the system provides data-driven responses rather than hallucinated content
- **Context limits** — AI conversation memory is bounded to prevent resource abuse
- **No PII in AI context** — The AI assistant uses only aggregated business metrics, never individual customer data

### Access Control
- **Least privilege** — Each role sees only the data necessary for their responsibilities
- **Audit logging** — All authentication events and data access are logged for accountability

---

## Future Improvements

### Completed
- [x] **Security validation** — Fail-fast on insecure defaults in production/staging
- [x] **Test suite** — pytest-based tests for security, config, health, and middleware
- [x] **CI/CD pipeline** — GitHub Actions for backend tests, frontend builds, and Docker validation
- [x] **Global error handlers** — Consistent JSON error responses with structured validation details

### Planned
- [ ] **ML forecasting** — Replace statistical models with LSTM/Prophet trained on historical data
- [ ] **WebSocket upgrade** — Bidirectional real-time communication replacing SSE
- [ ] **Frontend tests** — React Testing Library with component-level coverage
- [ ] **Internationalization** — Arabic, Hindi, Urdu support for UAE workforce
- [ ] **Mobile views** — Responsive layouts for store managers on the floor
- [ ] **2FA** — Two-factor authentication (DB schema already prepared)
- [ ] **Accessibility** — WCAG 2.1 AA compliance with ARIA labels and keyboard navigation

---

## Project Structure

```
├── .github/
│   └── workflows/
│       └── ci.yml            # GitHub Actions CI pipeline
├── backend/                  # FastAPI Python backend
│   ├── app/
│   │   ├── main.py          # Application entry point, lifespan & error handlers
│   │   ├── config.py        # Pydantic settings with security validation
│   │   ├── middleware.py     # Security middleware stack
│   │   ├── models/          # SQLAlchemy ORM models
│   │   ├── routes/          # API route handlers
│   │   ├── services/        # Business logic layer
│   │   └── utils/           # Shared utilities
│   ├── tests/               # pytest test suite
│   │   ├── conftest.py      # Shared fixtures
│   │   ├── test_security.py # Security validation tests
│   │   ├── test_config.py   # Configuration tests
│   │   ├── test_health.py   # Health endpoint tests
│   │   └── test_middleware.py # Middleware tests
│   ├── pytest.ini           # pytest configuration
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                 # Next.js TypeScript frontend
│   ├── src/
│   │   ├── app/             # App Router pages
│   │   ├── components/      # Reusable React components
│   │   ├── contexts/        # Auth context provider
│   │   ├── hooks/           # Custom React hooks (SSE, data)
│   │   ├── lib/             # API client & formatting utilities
│   │   └── types/           # TypeScript type definitions
│   ├── Dockerfile
│   └── package.json
├── database/                 # SQL schema & migrations
│   ├── init.sql             # Base schema (auto-run on container init)
│   └── migrations/          # Versioned migration scripts
├── data/                     # Training data (CSV)
├── nginx/                    # Reverse proxy configuration
├── docker-compose.yml        # Development environment
└── docker-compose.production.yml  # Production environment
```

---

## Author

**Atharva Soundankar** — [GitHub](https://github.com/mercydeez)

A production-grade demonstration of full-stack engineering, real-time data systems, and AI integration for enterprise retail analytics.

---

<p align="center">
  <sub>Built with FastAPI · Next.js · PostgreSQL · Redis · OpenAI</sub>
</p>
