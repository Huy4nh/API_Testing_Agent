# ![API Testing Hub Logo](https://github.com/user-attachments/assets/b7c3a3b5-734e-445a-bbd9-63a0b639f9dc)

> Multi-target, OpenAPI-driven REST API testing chatbot with Telegram interface, structured reporting, and persistent test history.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](#10-development-environment)
[![Poetry](https://img.shields.io/badge/dependency-poetry-blueviolet.svg)](#11-package-management)
[![Telegram Bot](https://img.shields.io/badge/interface-telegram-2CA5E0.svg)](#18-telegram-bot)
[![SQLite](https://img.shields.io/badge/storage-sqlite-003B57.svg)](#24-persistence-and-history)
[![Docker](https://img.shields.io/badge/runtime-docker-2496ED.svg)](#16-running-with-docker)
<p align="center">
  <img width="100%" height="450" alt="API Testing Hub" src="https://github.com/user-attachments/assets/4e2b48f1-b702-4050-a50b-408c183644a7" />
</p>

---

A review-first, OpenAPI-driven REST API testing assistant that helps interpret user test requests, resolve targets, narrow or broaden testing scope, generate draft test cases, and refine them through iterative feedback before any real execution is performed.

## Current Project Status

This project is currently centered on a **review-first workflow**.

The most mature and stable parts of the system are:

- dynamic target selection
- natural-language request understanding
- scope/function resolution after target selection
- AI-assisted draft test case generation
- multi-round review and feedback refinement
- OpenAPI ingestion and operation extraction
- structured draft reporting

The execution, runtime validation, and final result-reporting branches exist as project directions, but the most reliable and actively refined flow right now is the **draft generation + review loop**.

---

## Core Goals

The system is designed to:

1. read OpenAPI / Swagger specifications
2. resolve which API target the user wants to test
3. understand whether the user wants to test:
   - a specific function / endpoint / module
   - or the entire target
4. generate draft test cases for the selected scope
5. let the user review and refine those draft cases through feedback
6. preserve a structured path toward future execution and reporting

---

## Current Behavior Rules

### 1. Target resolution

The project currently uses a target-selection flow with these rules:

- if exactly one target matches the user request, it is selected automatically
- if multiple targets are plausible, the user is asked to choose
- if no target can be resolved, the system reports that the target could not be found

This part is considered stable and should not be changed casually.

### 2. Function / scope resolution after target is known

Once the target is resolved, the project follows these rules:

#### If the user specifies a valid function
The system must test that function specifically.

Examples:
- image generation on a target
- login on a target
- a specific endpoint such as `/posts` with `GET`

#### If the user does not specify any concrete function
The system must interpret the request as:

**test the entire target**

This is a critical rule.

For example, if the user says something like:

```text
test hello for me
```

and the target is resolved to `hello_world`, the system must **not** arbitrarily collapse the request into a single endpoint like `/img POST`.

Instead, it should proceed as a broad request over the whole target.

#### If the user specifies an invalid or non-existent function
The system must:
- avoid guessing
- avoid silently falling back to another function
- report that the requested function could not be found
- return the available functions / operations of the target

### 3. Review feedback must be able to change scope

Feedback in the review loop must not only rewrite test case wording. It must also be able to modify the operation scope itself.

Examples of supported feedback styles:

- only test image generation
- add post creation as well
- remove YT and FB
- reset to all operations

This is handled by a separate feedback-scope refinement layer.

---

## High-Level Architecture

```text
User request
    ↓
Target candidate retrieval
    ↓
Target disambiguation
    ↓
Selected target
    ↓
Request understanding
    ↓
Scope resolution
    ├── specific function
    ├── all functions in target
    └── invalid function
    ↓
Operation filtering
    ↓
AI draft test case generation
    ↓
Review graph
    ↓
Feedback scope refinement
    ↓
Regenerated draft
```

---

## Current Main Flow

### Step 1 — User submits a request

Examples:
- `test hello for me`
- `test the image generation function of hello_world`
- `test login on cms_local`
- `test /posts GET on cms_local`

### Step 2 — Resolve the target

The system searches target candidates from the target registry.

- one match → auto-select
- many matches → ask user to choose
- no match → stop with target-not-found response

### Step 3 — Resolve the scope

After the target is known, the system decides whether the request means:

- **specific**: a concrete operation, path, or tag/module
- **all**: the user wants to test the whole target
- **invalid_function**: the user mentioned a function that cannot be mapped to the OpenAPI inventory

### Step 4 — Build the test plan

The system transforms the resolved intent into a structured plan containing:

- target name
- selected paths or tags if any
- HTTP methods if constrained
- requested test types
- ignore-field directives
- endpoint limit if specified

### Step 5 — Generate draft test cases

The system builds operation contexts from OpenAPI and generates test case drafts for the active scope.

### Step 6 — Review / revise / approve

The user can:
- approve
- cancel
- revise with feedback

### Step 7 — Refine scope from feedback

If the user feedback changes the intended scope, the system updates the active operation set and regenerates the draft.

---

## Project Structure

```text
API_Testing_Agent/
├── .env
├── .env.example
├── pyproject.toml
├── poetry.lock
├── README.md
├── targets.json
├── targets.example.json
├── specs/
│   └── cms_local.yaml
├── data/
├── reports/
├── src/
│   └── api_testing_agent/
│       ├── config.py
│       ├── logging_config.py
│       ├── main.py
│       ├── manual_review_workflow_test.py
│       ├── bot/
│       │   └── telegram_bot.py
│       ├── core/
│       │   ├── ai_testcase_agent.py
│       │   ├── ai_testcase_models.py
│       │   ├── feedback_scope_agent.py
│       │   ├── feedback_scope_models.py
│       │   ├── feedback_scope_refiner.py
│       │   ├── intent_parser.py
│       │   ├── models.py
│       │   ├── nl_interpreter.py
│       │   ├── openapi_ingestor.py
│       │   ├── openapi_ref_resolver.py
│       │   ├── reporter.py
│       │   ├── request_understanding_service.py
│       │   ├── schema_faker.py
│       │   ├── scope_resolution_agent.py
│       │   ├── scope_resolution_models.py
│       │   ├── target_candidate_service.py
│       │   ├── target_disambiguation_agent.py
│       │   ├── target_disambiguation_models.py
│       │   ├── target_registry.py
│       │   ├── testcase_generator.py
│       │   ├── testcase_normalizer.py
│       │   ├── testcase_review_graph.py
│       │   ├── validator.py
│       │   └── reporter/
│       │       └── testcase/
│       │           └── testcase_reporter.py
│       ├── db/
│       │   └── sqlite_store.py
│       └── tasks/
│           └── orchestrator.py
└── tests/
```

---

## Important Source Components

### `tasks/orchestrator.py`
The main coordinator of the current workflow.

It is responsible for:
- target selection
- request understanding
- building operation hints
- filtering operations
- starting the review graph
- resuming review
- catching invalid-function errors
- returning structured workflow results

### `core/request_understanding_service.py`
The main service for turning a target-resolved user request into an actionable plan.

It handles:
- canonical command compatibility
- scope resolution
- resolved plan building
- invalid function detection
- deterministic canonical command reconstruction

### `core/scope_resolution_agent.py`
AI-assisted scope resolver for the initial user request after target selection.

It decides whether the request should be treated as:
- `specific`
- `all`
- `invalid_function`

### `core/feedback_scope_agent.py`
AI-assisted scope resolver specifically for review feedback.

It is separate from the request scope resolver because feedback operates on the **current scope**, not just on the original request.

### `core/feedback_scope_refiner.py`
Applies feedback-driven scope edits such as:
- replace scope
- add scope
- remove scope
- reset to all

### `core/target_candidate_service.py`
Deterministic target candidate finder.

It supports normalized matching strategies such as:
- exact match
- compact match
- normalized match
- prefix match
- fuzzy similarity match

### `core/target_disambiguation_agent.py`
Ranks and explains target candidates when the request is ambiguous.

### `core/openapi_ingestor.py`
Loads OpenAPI specs from local files or remote URLs and extracts normalized operation definitions.

### `core/openapi_ref_resolver.py`
Handles OpenAPI `$ref` dereferencing.

### `core/testcase_review_graph.py`
The review loop graph responsible for:
- generating draft test cases
- presenting them for review
- receiving feedback
- regenerating drafts
- tracking approval or cancellation

### `core/reporter/testcase/testcase_reporter.py`
Writes testcase draft reports to:
- JSON
- Markdown

and builds the human-readable preview shown in manual review.

---

## Current Review Workflow

The current CLI entry point for the review-first branch is:

```bash
poetry run python -m api_testing_agent.manual_review_workflow_test
```

Typical flow:

1. enter a natural-language test request
2. choose a target if the request is ambiguous
3. inspect the generated draft cases
4. provide feedback or approve
5. repeat until satisfied

---

## Example Scenarios

### Scenario A — broad request

Input:

```text
test hello for me
```

If the user then selects the target `hello_world`, the correct interpretation is:

- test the entire target
- not a single arbitrarily chosen endpoint

Expected broad canonical behavior:

```text
test target hello_world
```

### Scenario B — specific function request

Input:

```text
test the image generation function of hello_world
```

Expected behavior:

- resolve target `hello_world`
- resolve function to the correct image-related operation
- generate draft cases only for that scope

### Scenario C — invalid function request

Input:

```text
test the payment function of hello_world
```

Expected behavior:

- detect that payment does not exist for that target
- do not guess
- return the available target functions

---

## Feedback Scope Examples

The current direction of the project expects feedback like these to affect scope:

### Replace scope

```text
only test image generation
```

Expected effect:
- replace current scope with image-generation operations only

### Add scope

```text
add post creation as well
```

Expected effect:
- keep current scope
- add matching post-creation operations

### Remove scope

```text
remove YT and FB
```

Expected effect:
- remove matching YouTube and Facebook operations from the current scope

### Reset scope

```text
test all again
```

Expected effect:
- restore full target scope

---

## Dependencies and Current Runtime Notes

The project currently still depends on several older foundational files that may look legacy but are still used by runtime import chains:

- `core/nl_interpreter.py`
- `core/domain_alias_resolver.py`
- `core/dynamic_target_resolver.py`
- `core/intent_parser.py`

These should **not** be deleted unless runtime imports are first removed and validated.

---

## Tests That Matter Most Right Now

The most important tests for the current architecture are:

- `tests/test_request_understanding_service_scope.py`
- `tests/test_review_only_orchestrator_scope_resolution.py`
- `tests/test_review_only_orchestrator_target_selection.py`
- `tests/test_feedback_scope_refiner.py`
- `tests/test_review_feedback_scope_refinement.py`
- `tests/test_target_candidate_service.py`
- `tests/test_target_registry.py`
- `tests/test_openapi_schema/test_openapi_ingestor.py`
- `tests/test_openapi_schema/test_openapi_ref_resolver.py`
- `tests/test_openapi_schema/test_schema_faker.py`
- `tests/test_generator/ai/test_testcase_review_graph.py`
- `tests/test_reporter/testcase/test_testcase_draft_reporter.py`

---

## Development Setup

### Requirements

- Python 3.11+
- Poetry

### Install dependencies

```bash
poetry install
```

### Run tests

```bash
poetry run pytest tests -v
```

### Run manual review workflow

```bash
poetry run python -m api_testing_agent.manual_review_workflow_test
```

---

## Current Design Constraints

These are important and should not be broken by future work:

1. Do not auto-pick a single endpoint when the user did not specify a concrete function.
2. Keep the current target-selection behavior stable.
3. Feedback must be able to alter operation scope, not only wording.
4. Do not delete “legacy-looking” files until runtime imports are confirmed removed.
5. Prefer deterministic orchestration around AI outputs rather than allowing the model to invent target or scope freely.

---

## Roadmap Direction

The current project is in a strong position to continue toward:

- richer Telegram bot integration
- execution-stage integration after review approval
- validation and final result-reporting
- better persistence of review threads and feedback history
- more advanced function resolution and domain aliasing
- project cleanup and consolidation once runtime dependencies are fully mapped

---

## Notes for Future Refactoring

Some parts of the codebase still reflect earlier iterations and experiments. Before removing or refactoring files, always verify both:

1. runtime imports
2. test dependencies

A file should only be considered safe to delete when it is no longer required by either.

---

## License / Usage

This repository is currently maintained as a project codebase and should be treated according to the repository owner’s usage policy.
