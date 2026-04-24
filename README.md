# API Testing Agent

> Multi-target, OpenAPI-driven REST API testing chatbot with Telegram interface, structured reporting, and persistent test history.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](#10-development-environment)
[![Poetry](https://img.shields.io/badge/dependency-poetry-blueviolet.svg)](#11-package-management)
[![Telegram Bot](https://img.shields.io/badge/interface-telegram-2CA5E0.svg)](#18-telegram-bot)
[![SQLite](https://img.shields.io/badge/storage-sqlite-003B57.svg)](#24-persistence-and-history)
[![Docker](https://img.shields.io/badge/runtime-docker-2496ED.svg)](#16-running-with-docker)
[![License](https://img.shields.io/badge/license-academic%20prototype-lightgrey.svg)](#39-license)

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Problem Statement](#2-problem-statement)
- [3. Project Scope and Positioning](#3-project-scope-and-positioning)
- [4. Key Objectives](#4-key-objectives)
- [5. Current System Capabilities](#5-current-system-capabilities)
- [6. Non-Goals](#6-non-goals)
- [7. High-Level Architecture](#7-high-level-architecture)
- [8. End-to-End Workflow](#8-end-to-end-workflow)
- [9. Core Design Principles](#9-core-design-principles)
- [10. Development Environment](#10-development-environment)
- [11. Package Management](#11-package-management)
- [12. Project Structure](#12-project-structure)
- [13. Core Modules](#13-core-modules)
- [14. Data Models](#14-data-models)
- [15. Configuration Management](#15-configuration-management)
- [16. Running with Docker](#16-running-with-docker)
- [17. Running Locally](#17-running-locally)
- [18. Telegram Bot](#18-telegram-bot)
- [19. Supported Test Command Patterns](#19-supported-test-command-patterns)
- [20. OpenAPI Support](#20-openapi-support)
- [21. Test Case Generation Strategy](#21-test-case-generation-strategy)
- [22. Validation Strategy](#22-validation-strategy)
- [23. Reporting](#23-reporting)
- [24. Persistence and History](#24-persistence-and-history)
- [25. Multi-Target Support](#25-multi-target-support)
- [26. Security Considerations](#26-security-considerations)
- [27. Error Handling Strategy](#27-error-handling-strategy)
- [28. Testing Strategy](#28-testing-strategy)
- [29. Local Setup Step-by-Step](#29-local-setup-step-by-step)
- [30. Docker Setup Step-by-Step](#30-docker-setup-step-by-step)
- [31. Example End-to-End Scenario](#31-example-end-to-end-scenario)
- [32. Example Output](#32-example-output)
- [33. SQLite Schema Overview](#33-sqlite-schema-overview)
- [34. Operational Checklist](#34-operational-checklist)
- [35. Troubleshooting](#35-troubleshooting)
- [36. Known Limitations](#36-known-limitations)
- [37. Roadmap](#37-roadmap)
- [38. FAQ](#38-faq)
- [39. License](#39-license)
- [40. Acknowledgement of Prototype Status](#40-acknowledgement-of-prototype-status)

---

## 1. Executive Summary

**API Testing Agent** is a prototype chatbot that helps **generate, execute, validate, and report REST API test cases** based on an **OpenAPI Specification**. The system is designed to reduce manual effort in API testing workflows by combining:

- a **Telegram Bot** user interface
- natural-language test request understanding
- **OpenAPI/Swagger** parsing and extraction
- rule-based test case generation
- real HTTP request execution
- structured response validation
- human-readable reporting
- persistent test history stored in **SQLite**

The project focuses on **functional testing** at a controlled prototype level, prioritizing:

- clarity
- measurability
- demo readiness
- future extensibility

This is **not** a full enterprise-grade testing framework, but it is organized close to a real system and is strong enough to support:

- academic projects and capstones
- technical demos
- a foundation for future internal QA tooling

---

## 2. Problem Statement

In systems with many REST APIs, manual testing often introduces the following problems:

- too much time spent reading OpenAPI docs and building requests manually
- negative cases are easy to miss
- pass/fail evaluation is inconsistent
- test scenarios are difficult to reuse
- historical results are difficult to track
- the process depends heavily on repetitive manual actions

In many real-world systems, OpenAPI/Swagger already contains important information such as:

- endpoints
- methods
- parameters
- request body schemas
- responses
- security requirements

The core problem is:

> Can we build a chatbot-driven system that uses OpenAPI to help generate tests, execute real requests, and return structured reports?

This project is a prototype-level answer to that question.

---

## 3. Project Scope and Positioning

This project is positioned as an **AI-assisted API testing prototype**. In the current context, “AI-assisted” means:

- the bot accepts test requests in controlled natural language
- the execution, validation, and reporting pipeline remains deterministic and rule-based
- the workflow is organized in an agent-like manner without delegating the full testing pipeline to an LLM

### Intended positioning

The project sits at the intersection of:

- OpenAPI-based testing
- chatbot-based developer tooling
- semi-automated QA workflows
- deterministic execution and reporting

### Best fit use cases

- graduation thesis or capstone project
- internal prototype tool
- faster API testing support for developers
- a foundation for future QA tooling or CI/CD integration

---

## 4. Key Objectives

The main goals of the system are:

1. Read and analyze OpenAPI/Swagger specifications.
2. Extract:
   - endpoints
   - HTTP methods
   - parameters
   - request body schemas
   - response schemas
   - security requirements
3. Convert user requests into a structured `TestPlan`.
4. Generate automatic test cases for common scenarios.
5. Send real requests to the API target.
6. Evaluate responses using:
   - status code
   - required fields
   - nested schema
   - array item structure
   - enums
   - basic format rules
7. Generate structured reports.
8. Persist test history.
9. Integrate a Telegram bot as the control interface.

---

## 5. Current System Capabilities

The system currently supports the following capabilities.

### 5.1. Dynamic multi-target support
The system supports multiple API targets through `targets.json`. Targets are **not hard-coded in code**; instead, enabled targets are read dynamically from the registry file.

Each target may contain:

- `name`
- `base_url`
- `openapi_spec_path`
- `openapi_spec_url`
- `auth_bearer_token`
- `enabled`

### 5.2. Layered natural-language interpretation
The command understanding pipeline is split into multiple layers:

- `DynamicTargetResolver`: resolves targets dynamically from `targets.json`
- `DomainAliasResolver`: maps business phrases into tags, paths, or methods
- `NaturalLanguageInterpreter`: normalizes free-form user messages into canonical commands
- `RuleBasedIntentParser`: parses canonical commands into `TestPlan`

This makes the system more flexible without breaking downstream deterministic logic.

### 5.3. Backward compatibility for canonical commands
Canonical command patterns remain supported, for example:

- `test target cms_local module posts GET`
- `test target ngrok_live /posts GET limit 5`
- `test target cms_local module auth negative`

### 5.4. OpenAPI ingestion
The system reads OpenAPI from:

- local files
- remote URLs

It parses:

- paths
- methods
- parameters
- request bodies
- responses
- security

### 5.5. Local `$ref` resolution
The system supports local `$ref` resolution inside the same spec, including:

- `components.schemas`
- `components.parameters`
- `components.requestBodies`
- `components.responses`

### 5.6. Global security detection
The system handles:

- root-level security
- operation-level overrides
- `security: []` for public endpoints

### 5.7. Test case generation
The system generates test cases for five major categories:

- positive
- missing required field
- invalid type / invalid format
- unauthorized / forbidden
- resource not found

### 5.8. Real request execution
The execution engine uses `httpx` to send real HTTP requests to target APIs.

### 5.9. Structured validation
The validator currently supports:

- status codes
- object / array / primitive types
- nested objects
- array item validation
- enums
- min/max
- minLength/maxLength
- regex patterns
- email / uuid / date / date-time / uri formats
- nullable handling
- prototype-level `allOf`, `oneOf`, and `anyOf`

### 5.10. Structured reporting
Each test run produces:

- a JSON report
- a Markdown report

### 5.11. Persistent history
Results are stored in SQLite:

- `test_runs`
- `test_results`

### 5.12. Telegram bot control surface
The bot supports:

- `/start`
- `/help`
- `/targets`
- `/last_runs`
- report delivery after test execution

---

## 6. Non-Goals

To keep the project within prototype scope, the following are **not current goals**:

- performance testing / load testing
- advanced security pentesting
- websocket testing
- frontend / UI testing
- complex multipart file uploads
- remote `$ref` from external files or external URLs
- stateful dependency exploration like RESTler
- enterprise-grade access control
- distributed test execution
- full CI/CD integration
- production-grade observability stacks

---

## 7. High-Level Architecture

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

### Notes

- `NaturalLanguageInterpreter` understands loose user messages and produces a canonical command.
- `DynamicTargetResolver` reads runtime targets from `targets.json`, not from hard-coded constants.
- `DomainAliasResolver` enriches the command using business phrase mappings.
- `RuleBasedIntentParser` converts canonical text into `TestPlan`.
- Downstream modules only work with structured data and do not need to understand raw human phrasing.

---

## 8. End-to-End Workflow

1. A user sends a testing request through the Telegram bot.
2. `NaturalLanguageInterpreter` receives the raw text.
3. `DynamicTargetResolver` reads `targets.json` and resolves the target mentioned by the user.
4. `DomainAliasResolver` maps business phrases such as:
   - `posts` / `articles` / `news`
   - `facebook`
   - `post to X`
5. The interpreter builds a canonical command containing:
   - target
   - method
   - tag/path
   - test markers
   - limit
   - ignore fields
6. `RuleBasedIntentParser` parses the canonical command into a `TestPlan`.
7. `TargetRegistry` retrieves the actual target configuration.
8. `OpenAPIIngestor` loads and parses the OpenAPI document for that target.
9. `TestCaseGenerator` generates test cases from the `TestPlan` and operations.
10. `ExecutionEngine` sends real requests.
11. `Validator` evaluates the responses.
12. `Reporter` writes JSON and Markdown reports.
13. `SQLiteStore` persists run history.
14. The Telegram bot returns results to the user.

---

## 9. Core Design Principles

### 9.1. Keep the execution pipeline deterministic
Execution, validation, and reporting should remain transparent and debuggable.

### 9.2. Separate natural-language understanding from strict parsing
Free-form user input should not directly drive execution.

Instead:
- chat text is normalized by `NaturalLanguageInterpreter`
- canonical commands are parsed by `RuleBasedIntentParser`
- downstream modules only consume `TestPlan`

### 9.3. Do not hard-code runtime targets
Targets are runtime entities and must be loaded from `targets.json`.

### 9.4. Preserve backward compatibility
If the user already sends a canonical command, the system keeps the original behavior.

### 9.5. Additive extensibility
New modules such as:
- `DynamicTargetResolver`
- `DomainAliasResolver`
- `NaturalLanguageInterpreter`

are introduced additively, without changing the public parser API.

### 9.6. Clear responsibility boundaries
The system clearly separates:
- target resolution
- domain phrase resolution
- strict parsing
- OpenAPI ingestion
- test generation
- execution
- validation
- reporting

---

## 10. Development Environment

Recommended environment:

- Python 3.11+
- Poetry
- SQLite
- Telegram Bot token
- optional Docker / Docker Compose

The project is designed primarily for local development and prototype deployment.

---

## 11. Package Management

The project uses **Poetry** for dependency management.

Typical commands:

```bash
poetry install
poetry shell
poetry run pytest
```

Core dependencies typically include:

- `python-telegram-bot`
- `httpx`
- `pyyaml`
- `pydantic`
- `pydantic-settings`
- `python-dotenv`

Development tools typically include:

- `pytest`
- `ruff`
- `mypy`

---

## 12. Project Structure

```text
API_Testing_Agent/
  .env.example
  targets.example.json
  src/
    api_testing_agent/
      __init__.py
      main.py
      config.py
      logging_config.py
      bot/
        telegram_bot.py
      core/
        models.py
        target_registry.py
        dynamic_target_resolver.py
        domain_alias_resolver.py
        nl_interpreter.py
        intent_parser.py
        openapi_ingestor.py
        schema_faker.py
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

## 13. Core Modules

### 13.1. `dynamic_target_resolver.py`
Resolves targets dynamically from `targets.json`.

Responsibilities:
- read enabled targets
- match exact target names
- generate aliases automatically from target names
- optionally support aliases declared in `targets.json`
- ignore ambiguous aliases

### 13.2. `domain_alias_resolver.py`
Maps domain/business phrases into:
- tags
- paths
- methods

### 13.3. `nl_interpreter.py`
Normalizes natural-language requests into canonical commands.

### 13.4. `intent_parser.py`
Strict parser that converts canonical commands into `TestPlan`.

Public API remains:
- `parse(text: str) -> TestPlan`

### 13.5. `target_registry.py`
Loads target definitions used by runtime execution.

### 13.6. `openapi_ingestor.py`
Loads and parses OpenAPI specifications.

### 13.7. `testcase_generator.py`
Builds test cases from operations and test plans.

### 13.8. `execution_engine.py`
Executes real HTTP requests.

### 13.9. `validator.py`
Validates responses.

### 13.10. `reporter.py`
Writes JSON and Markdown reports.

### 13.11. `sqlite_store.py`
Persists run history and result history.

---

## 14. Data Models

The system uses structured internal models for:

- `ApiTarget`
- `OpenApiParameter`
- `OpenApiRequestBody`
- `OpenApiOperation`
- `TestPlan`
- `TestCase`
- `ExecutionResult`
- `ValidationResult`
- `TestResult`
- `RunSummary`

These models make the workflow explicit and reduce coupling between modules.

---

## 15. Configuration Management

### 15.1. Static application configuration
Stored in `.env`:

- `TARGET_REGISTRY_PATH`
- `HTTP_TIMEOUT_SECONDS`
- `MAX_CONCURRENCY`
- `SQLITE_PATH`
- `REPORT_OUTPUT_DIR`
- `TELEGRAM_BOT_TOKEN`

### 15.2. Dynamic runtime target configuration
Stored in `targets.json`.

Each target may include:

- `name`
- `base_url`
- `openapi_spec_path`
- `openapi_spec_url`
- `auth_bearer_token`
- `enabled`

Targets are **not hard-coded** in code.

### 15.3. Optional future extension
In the future, `targets.json` may also support:

- `aliases`
- `notes`
- `profile`
- `default_headers`

---

## 16. Running with Docker

The project can be containerized for reproducible execution.

Typical deployment files may include:

- `Dockerfile`
- `docker-compose.yml`

Docker is optional but helpful for demos and controlled environments.

---

## 17. Running Locally

Typical local workflow:

```bash
poetry install
copy .env.example .env
copy targets.example.json targets.json
poetry run python -m api_testing_agent.main
```

Before running, ensure:

- `.env` is configured
- `targets.json` exists
- the Telegram bot token is valid
- the target OpenAPI document is reachable

---

## 18. Telegram Bot

The Telegram bot is the main user-facing control surface.

Typical commands include:

- `/start`
- `/help`
- `/targets`
- `/last_runs`

The bot accepts both:

- canonical commands
- controlled natural-language test requests

Example requests:

```text
/test target cms_local module posts GET
Bên ngrok lấy nội dung facebook giúp mình
Ở local đăng bài lên X giúp mình
```

---

## 19. Supported Test Command Patterns

### 19.1. Canonical command patterns
These are structured commands.

Examples:

```text
test target cms_local module posts GET
test target ngrok_live module auth negative
test target cms_local /posts GET limit 5
test target cms_local module posts POST ignore field image
```

### 19.2. Natural-language command patterns
The system also supports more natural requests.

Examples:

```text
Please test the posts module on local, GET only, limit 5, ignore image
Test login negative case on ngrok
On local, test /posts GET for only 3 endpoints first
On ngrok, fetch Facebook content for me
On local, post to X for me
```

### 19.3. Behavior notes
- Canonical commands are preserved exactly.
- Natural-language input is normalized first.
- This is still a controlled prototype, not unrestricted language understanding.

---

## 20. OpenAPI Support

The system supports OpenAPI loading from:

- local YAML / JSON files
- remote OpenAPI URLs

It extracts:

- endpoint path
- method
- parameters
- request body schema
- response schema
- security requirements

Prototype-level support includes local `$ref` resolution.

---

## 21. Test Case Generation Strategy

The generator creates test cases for five main categories:

### 21.1. Positive
Valid input and expected success.

### 21.2. Missing required field
One required field is removed.

### 21.3. Invalid type / invalid format
A valid field is mutated into a wrong type or invalid value.

### 21.4. Unauthorized / Forbidden
The request is executed without the required authorization context.

### 21.5. Resource not found
The request is executed with a non-existing identifier.

The generator uses:
- OpenAPI schemas
- rule-based sample generation
- limited body mutation

---

## 22. Validation Strategy

The validator evaluates:

- status code
- required fields
- object/array structure
- nested schemas
- enums
- basic format constraints

The validator is intentionally deterministic and explainable.

---

## 23. Reporting

Each run creates:

- a JSON report for machine-readable analysis
- a Markdown report for human-readable review

A report typically includes:

- target
- endpoint
- method
- test type
- expected result
- actual result
- pass/fail
- response time
- validation errors

---

## 24. Persistence and History

SQLite is used to store:

### `test_runs`
Stores summary information for a test run.

### `test_results`
Stores each individual test case result.

This supports:
- run history
- later analysis
- structured reporting for academic evaluation

---

## 25. Multi-Target Support

### 25.1. Why it matters
The same workflow may need to run against:

- local development environments
- public temporary endpoints
- demo environments
- staging-like deployments

### 25.2. Source of truth
`targets.json` is the runtime source of truth for targets.

### 25.3. Dynamic target resolution
Targets are resolved dynamically, not hard-coded.

Resolution can use:
- exact target name
- aliases generated from target name
- optional aliases declared in `targets.json`

### 25.4. Ambiguity handling
If a generated alias can refer to multiple targets, it is ignored.

### 25.5. Separation of concerns
- `DynamicTargetResolver` understands how users refer to targets
- `TargetRegistry` provides the actual runtime configuration used for execution

---

## 26. Security Considerations

This project is a prototype and should be used carefully.

Key considerations:

- avoid testing unintended production endpoints
- secure bot tokens and auth tokens
- do not expose sensitive target definitions publicly
- treat `targets.json` as operational configuration
- prefer read-only or sandbox targets for demonstrations

---

## 27. Error Handling Strategy

The system uses explicit error handling in multiple layers.

### Input layer
- empty requests raise parser errors

### Target resolution layer
- unknown targets resolve to `None`
- ambiguous aliases are ignored

### OpenAPI layer
- invalid spec content raises ingestion errors

### Execution layer
- network errors are captured in execution results

### Validation layer
- validation mismatches are reported structurally

The general goal is to fail clearly and preserve enough information for debugging.

---

## 28. Testing Strategy

### 28.1. Unit tests
The current parser-related test suite covers:

- `DomainAliasResolver`
- `DynamicTargetResolver`
- `NaturalLanguageInterpreter`
- `RuleBasedIntentParser`
- backward compatibility for canonical commands

### 28.2. Test isolation
Most unit tests use temporary `targets.json` files under `tmp_path` to avoid dependency on local runtime configuration.

### 28.3. Runtime checks
Additional integration tests can be added to verify behavior against the real `./targets.json` used by the application.

### 28.4. Current parser test status
In the latest observed run, the parser/interpreter test suite under `tests/test_Intent_parser` passed **29/29** with **1 Pytest collection warning** related to the `TestType` symbol name in tests. fileciteturn10file14

---

## 29. Local Setup Step-by-Step

1. Install Python 3.11+.
2. Install Poetry.
3. Clone the repository.
4. Run:

```bash
poetry install
```

5. Create `.env` from `.env.example`.
6. Create `targets.json` from `targets.example.json`.
7. Verify at least one target has `enabled: true`.
8. Run the app:

```bash
poetry run python -m api_testing_agent.main
```

---

## 30. Docker Setup Step-by-Step

1. Build the container image.
2. Provide `.env` and `targets.json`.
3. Mount `data/` and `reports/` if needed.
4. Start the container.
5. Confirm the Telegram bot is reachable.

Exact Docker commands depend on your Dockerfile and compose setup.

---

## 31. Example End-to-End Scenario

1. The user sends:

```text
On ngrok, fetch Facebook content for me
```

2. The interpreter normalizes the message into something close to:

```text
test target ngrok_live POST /FB
```

3. The parser converts it into a `TestPlan`.
4. The orchestrator loads the target from `targets.json`.
5. The OpenAPI spec is loaded from the target.
6. Test cases are generated.
7. Requests are executed.
8. Validation is performed.
9. Reports are generated and stored.
10. The bot returns a summary and report paths.

---

## 32. Example Output

Example run summary:

```text
Test run completed.
- Target: ngrok_live
- Total cases: 12
- Passed: 10
- Failed: 2
- JSON report: reports/2026...json
- Markdown report: reports/2026...md
```

---

## 33. SQLite Schema Overview

### `test_runs`
Typical fields:

- `run_id`
- `target_name`
- `total`
- `passed`
- `failed`
- `report_json_path`
- `report_md_path`

### `test_results`
Typical fields:

- `run_id`
- `case_id`
- `method`
- `path`
- `test_type`
- `passed`
- `status_code`
- `response_time_ms`
- `errors_json`

---

## 34. Operational Checklist

Before running the system:

- [ ] `.env` exists and is valid
- [ ] `targets.json` exists
- [ ] at least one target is enabled
- [ ] Telegram bot token is valid
- [ ] OpenAPI document is reachable
- [ ] SQLite path is writable
- [ ] reports directory is writable

---

## 35. Troubleshooting

### 35.1. Natural-language command does not resolve target
Check:
- whether the target exists in `targets.json`
- whether it is enabled
- whether the generated alias is ambiguous

### 35.2. Canonical command works but free text does not
Likely causes:
- `DomainAliasResolver` does not have a rule for the phrase
- the sentence is outside the current supported range
- the target resolver cannot resolve the target from the text

### 35.3. Runtime behavior differs from unit tests
Unit tests typically use temporary target files.
Runtime uses the real `./targets.json`.
This difference is intentional for test stability.

### 35.4. `'DynamicTargetResolver' object has no attribute 'parse'`
This means test wiring is wrong:
- `DynamicTargetResolver` is not a parser
- `RuleBasedIntentParser` is the object that provides `.parse(...)`

### 35.5. Unexpected tag extraction from target names
Make sure parser regex for `target`, `module`, and `tag` uses word boundaries (`\b`).

### 35.6. Pytest collection warning for `TestType`
In tests, import it with an alias such as:

```python
from api_testing_agent.core.models import TestType as ApiTestType
```

---

## 36. Known Limitations

Current limitations include:

- natural-language understanding is still rule-based and controlled
- domain alias coverage is incomplete for unrestricted phrasing
- target aliases are limited to exact names, generated aliases, and optional config aliases
- advanced stateful API dependency exploration is not implemented
- remote external `$ref` handling is out of scope
- this is not yet a production-grade access-controlled platform

---

## 37. Roadmap

Potential next steps include:

- target alias support declared directly in `targets.json`
- profile-based domain alias loading per target type
- richer OpenAPI inference for target-specific domain mapping
- integration tests against real runtime target files
- stronger schema validation coverage
- CI integration
- richer Telegram bot workflows

---

## 38. FAQ

### Is this a full API testing framework?
No. It is a structured academic/technical prototype.

### Does it support multiple API targets?
Yes. Targets are loaded dynamically from `targets.json`.

### Are targets hard-coded in code?
No. Runtime targets must come from `targets.json`.

### Can users send natural-language requests?
Yes, within a controlled rule-based range.

### Are canonical commands still supported?
Yes. Backward compatibility is preserved.

### Does the system store history?
Yes, using SQLite.

---

## 39. License

This project is intended primarily as an academic and prototype implementation.

Choose and define the final license according to your institutional or project requirements.

---

## 40. Acknowledgement of Prototype Status

This system is intentionally built as a **prototype with strong structure** rather than a complete enterprise platform.

Its value lies in:

- clear architectural boundaries
- real OpenAPI-driven execution
- deterministic validation and reporting
- multi-target support
- an extendable chatbot-centered workflow

That makes it suitable for:

- academic research
- final-year projects
- technical demonstrations
- future internal tooling evolution

---
