# API Testing Hub

> Multi-target, OpenAPI-driven REST API testing chatbot with Telegram interface, structured reporting, and persistent test history.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](#10-development-environment)
[![Poetry](https://img.shields.io/badge/dependency-poetry-blueviolet.svg)](#11-package-management)
[![Telegram Bot](https://img.shields.io/badge/interface-telegram-2CA5E0.svg)](#18-telegram-bot)
[![SQLite](https://img.shields.io/badge/storage-sqlite-003B57.svg)](#24-persistence-and-history)
[![Docker](https://img.shields.io/badge/runtime-docker-2496ED.svg)](#16-running-with-docker)

<img width="100%" height="450" alt="API Testing Hub" src="https://github.com/user-attachments/assets/4e2b48f1-b702-4050-a50b-408c183644a7" />

---

## Overview

**API Testing Agent** is a multi-target REST API testing system that uses **OpenAPI/Swagger** as the source of truth for discovering endpoints, request schemas, response expectations, and security rules.

It is designed to let teams trigger test runs from concise commands or natural-language chat, execute real requests against real API targets, validate results, generate structured reports, and keep a persistent history of runs.

The project is built around a clear separation of concerns:

- natural-language interpretation
- strict command parsing
- OpenAPI ingestion
- deterministic test generation
- real request execution
- structured validation
- persistent reporting

---

## Key Features

- **Dynamic multi-target support** via `targets.json`
- **Natural-language test commands** with backward-compatible canonical commands
- **OpenAPI ingestion** from local files or remote URLs
- **Automatic test generation** for common positive and negative cases
- **Real HTTP execution** with `httpx`
- **Structured response validation**
- **JSON + Markdown reports** per run
- **SQLite-backed run history**
- **Telegram bot interface** for remote control

---

## Core Capabilities

### 1. Dynamic Target Resolution
Targets are loaded at runtime from `targets.json`. They are not hard-coded in the parser or interpreter.

Each target can define:

- `name`
- `base_url`
- `openapi_spec_path`
- `openapi_spec_url`
- `auth_bearer_token`
- `enabled`

### 2. Layered Command Understanding
The command pipeline is intentionally layered:

1. **DynamicTargetResolver** resolves the target from runtime registry data
2. **DomainAliasResolver** maps domain phrases to tags, paths, or methods
3. **NaturalLanguageInterpreter** converts chat-like input into canonical commands
4. **RuleBasedIntentParser** converts canonical commands into a `TestPlan`

This keeps the user-facing interface flexible while preserving a deterministic execution pipeline.

### 3. OpenAPI-Driven Execution
The system reads OpenAPI definitions and extracts:

- endpoints
- HTTP methods
- parameters
- request body schemas
- response schemas
- security requirements

### 4. Test Generation
The generator supports five core test categories:

- positive
- missing required field
- invalid type or format
- unauthorized / forbidden
- resource not found

### 5. Validation and Reporting
Each run validates responses and emits:

- status checks
- required field checks
- schema-oriented checks
- JSON report
- Markdown report
- persistent SQLite history

---

## Architecture

```text
Telegram User
    ↓
Telegram Bot
    ↓
Orchestrator
    ├── NaturalLanguageInterpreter
    │     ├── DynamicTargetResolver
    │     └── DomainAliasResolver
    ├── RuleBasedIntentParser
    ├── Target Registry
    ├── OpenAPI Ingestor
    ├── Test Case Generator
    ├── Execution Engine
    ├── Validator
    ├── Reporter
    └── SQLite Store
```

---

## Example Commands

### Canonical commands

```text
 test target cms_local module posts GET
 test target ngrok_live module auth negative
 test target cms_local /posts GET limit 5
 test target cms_local module posts POST ignore field image
```

### Natural-language commands

```text
 Test the posts APIs on local, GET only, limit to 5 endpoints, ignore image.
 Run negative login tests on ngrok.
 On local, test /posts with GET for the first 3 endpoints.
 Fetch Facebook content on ngrok.
 Post to X from local.
```

---

## Project Structure

```text
API_Testing_Agent/
  .env.example
  targets.json
  src/
    api_testing_agent/
      main.py
      config.py
      bot/
        telegram_bot.py
      core/
        models.py
        dynamic_target_resolver.py
        domain_alias_resolver.py
        nl_interpreter.py
        intent_parser.py
        openapi_ingestor.py
        testcase_generator.py
        execution_engine.py
        validator.py
        reporter.py
      tasks/
        orchestrator.py
      db/
        sqlite_store.py
  data/
  reports/
  tests/
```

---

## Configuration

### `.env`

```env
TARGET_REGISTRY_PATH=./targets.json
HTTP_TIMEOUT_SECONDS=15
MAX_CONCURRENCY=5
SQLITE_PATH=./data/runs.sqlite3
REPORT_OUTPUT_DIR=./reports
TELEGRAM_BOT_TOKEN=replace_me
```

### `targets.json`

```json
[
  {
    "name": "cms_local",
    "base_url": "http://127.0.0.1:8000",
    "openapi_spec_path": "./specs/cms_local.yaml",
    "enabled": true
  },
  {
    "name": "ngrok_live",
    "base_url": "https://example.ngrok-free.app",
    "openapi_spec_url": "https://example.ngrok-free.app/openapi.json",
    "enabled": true
  }
]
```

---

## Development

### Requirements

- Python 3.11+
- Poetry

### Install

```bash
poetry install
```

### Run locally

```bash
poetry run python -m api_testing_agent.main
```

### Run tests

```bash
poetry run pytest tests -v
```

---

## Telegram Bot

The bot acts as the primary operator interface.

Typical commands include:

- `/start`
- `/help`
- `/targets`
- `/last_runs`

Users can also send test requests directly as messages.

---

## Reporting and History

Each run produces:

- a JSON report
- a Markdown report
- a persistent SQLite record

This makes it possible to:

- review previous runs
- compare failures over time
- inspect execution details
- reuse reports in debugging workflows

---

## Design Principles

- **Deterministic execution** after intent parsing
- **Runtime-configured targets**, not hard-coded environments
- **Backward compatibility** for structured commands
- **Separation of interpretation and parsing**
- **Additive extensibility** for new targets and domain aliases
- **Clear operational visibility** through reports and history

---

## Current Limitations

- functional API testing only
- no performance/load testing
- no websocket support
- no advanced stateful API exploration
- local `$ref` support only
- natural-language support is intentionally constrained for predictability

---

## Roadmap

- richer domain alias profiles per target
- stronger JSON Schema validation coverage
- improved stateful test sequencing
- CI/CD integration
- web dashboard for test history and reports
- role-based access and target governance

---

## License

Currently maintained as a proprietary product codebase / internal project unless stated otherwise.
