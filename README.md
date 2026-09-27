# Async Document Processing API

A Django API that generates documents with an LLM in the background. A client submits a request and gets an ID back right away. A worker then calls Claude, checks the output, and saves the result, while the client polls for status.

The first document type is a **pharmacist care plan**. A healthcare worker enters patient and medication information, and the system produces a draft care plan with a problem list, SMART goals, interventions, and a monitoring plan. Each plan currently takes a pharmacist 20–40 minutes to write by hand.

> **Status: v0 prototype.** Generation is still synchronous, and data is held in memory, so it is lost on restart. The async pipeline (PostgreSQL, queue, worker) is the next milestone. See the [roadmap](#roadmap) and the [design doc](docs/design-doc.md).

## How it works

This is the target architecture, from v2 onward:

```
Client                     API (Django)                    Worker
  │  POST /api/orders/        │                               │
  │ ────────────────────────> │ validate, check duplicates    │
  │                           │ save Order + CarePlan(queued) │
  │                           │ enqueue job ────────────────> │
  │ <──── 202 {id, status} ── │                               │ status = processing
  │                           │                               │ call Claude
  │  GET /api/orders/<id>/    │                               │ check required sections
  │ ────────────────────────> │                               │ status = completed | failed
  │ <──── {status, careplan} ─│                               │
```

Each care plan moves through these states:

```
queued ──> processing ──> completed
                │
                └──> failed ──(POST /regenerate/)──> queued
```

A failed generation never deletes the order. The client can retry without re-entering the form.

## Quick start

Requires [Docker](https://www.docker.com/) and an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/ANDY1L/async-document-processing-api.git
cd async-document-processing-api

cp .env.example .env        # then put your real key in .env
docker compose up --build
```

Open http://localhost:8000.

## Configuration

| Variable | Description |
| --- | --- |
| `ANTHROPIC_API_KEY` | Your Anthropic API key. Put it in `.env`, which is git-ignored. Never commit it. |

## API

### Current (v0)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Input form |
| `POST` | `/api/careplans/` | Generate a care plan synchronously from a JSON body of patient fields |
| `GET` | `/api/careplans/<id>/` | Fetch a generated care plan |

### Planned

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/orders/` | Validate, check duplicates, create the order, and enqueue generation. Returns `202` with the order ID and status. |
| `GET` | `/api/orders/<id>/` | Order details and care plan status. Includes the content once `completed`. |
| `POST` | `/api/orders/<id>/regenerate/` | Re-enqueue a failed generation |
| `GET` | `/api/orders/<id>/careplan.txt` | Download the care plan as text |
| `GET` | `/api/reports/export.csv?from=&to=` | Export a report for pharmaceutical companies |

## Roadmap

| Stage | What it adds |
| --- | --- |
| **v0 (current)** | End-to-end flow: Django, in-memory storage, synchronous Claude call |
| v1 | PostgreSQL and the data model (Provider, Patient, Order, CarePlan with a `status` field) |
| v2 | **Async generation**: queue and worker, `202` responses, status polling in the frontend |
| v3 | Backend validation and a standard error format |
| v4 | Duplicate detection (rules R1–R5) with a warning-confirmation flow |
| v5 | Reliability: retries with backoff, output checks, and handling of timeouts and rate limits |
| v6 | Text download and CSV report export |
| v7 | PDF upload and text extraction |

Automated tests are added with each stage, and the LLM is mocked in tests.

## Project structure

```
config/      Django settings and URL routing
careplan/    Views, prompt, and HTML template
docs/        Design doc
```

## Docs

- [Design doc](docs/design-doc.md): requirements, validation rules, data model, async processing, API design, and open questions
