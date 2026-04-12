from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HttpMethod(str, Enum):
    GET = "get"
    POST = "post"
    PUT = "put"
    PATCH = "patch"
    DELETE = "delete"


class ParamLocation(str, Enum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


class TestType(str, Enum):
    POSITIVE = "positive"
    MISSING_REQUIRED = "missing_required"
    INVALID_TYPE_OR_FORMAT = "invalid_type_or_format"
    UNAUTHORIZED = "unauthorized_or_forbidden"
    NOT_FOUND = "resource_not_found"


@dataclass(frozen=True)
class ApiTarget:
    name: str
    base_url: str
    openapi_spec_path: str | None = None
    openapi_spec_url: str | None = None
    auth_bearer_token: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class OpenApiParameter:
    name: str
    location: ParamLocation
    required: bool
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenApiRequestBody:
    required: bool
    content_type: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenApiOperation:
    operation_id: str
    method: HttpMethod
    path: str
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    parameters: list[OpenApiParameter] = field(default_factory=list)
    request_body: OpenApiRequestBody | None = None
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    auth_required: bool = False


@dataclass(frozen=True)
class TestPlan:
    target_name: str | None = None
    tags: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    methods: list[HttpMethod] = field(default_factory=list)
    test_types: list[TestType] = field(default_factory=list)
    ignore_fields: list[str] = field(default_factory=list)
    limit_endpoints: int = 50


@dataclass(frozen=True)
class TestCase:
    id: str
    target_name: str
    operation: OpenApiOperation
    test_type: TestType
    description: str
    path_params: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    expected_status_codes: set[int] = field(default_factory=set)
    expected_response_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionResult:
    status_code: int
    elapsed_ms: float
    response_headers: dict[str, str]
    response_json: Any | None
    response_text: str | None
    error: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    status_code_ok: bool
    schema_ok: bool | None
    required_fields_ok: bool | None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TestResult:
    test_case: TestCase
    execution: ExecutionResult
    validation: ValidationResult


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    target_name: str
    total: int
    passed: int
    failed: int
    report_json_path: str
    report_md_path: str