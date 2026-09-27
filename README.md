# Care Plan Auto-Generation

A Django web app that generates pharmacist care plans with Claude. A healthcare worker enters patient and medication information, and the app returns a draft care plan with a problem list, SMART goals, interventions, and a monitoring plan.

> **Status: early prototype.** Care plans are generated synchronously, and data is held in memory, so it is lost on restart. See the [design doc](docs/design-doc.md) for the full scope and iteration plan.

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

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Input form |
| `POST` | `/api/careplans/` | Generate a care plan from a JSON body of patient fields |
| `GET` | `/api/careplans/<id>/` | Fetch a generated care plan |

## Project structure

```
config/      Django settings and URL routing
careplan/    Views, prompt, and HTML template
docs/        Design doc
```

## Docs

- [Design doc](docs/design-doc.md): requirements, validation rules, data model, API design, and open questions
