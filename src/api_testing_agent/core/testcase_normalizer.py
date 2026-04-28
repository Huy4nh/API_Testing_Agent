from __future__ import annotations

import uuid

from api_testing_agent.core.ai_testcase_models import AITestCaseDraft
from api_testing_agent.core.models import ApiTarget, OpenApiOperation, TestCase, TestType


class TestCaseNormalizationError(ValueError):
    pass


class TestCaseNormalizer:
    _TYPE_MAP = {
        "positive": TestType.POSITIVE,
        "missing_required": TestType.MISSING_REQUIRED,
        "invalid_type_or_format": TestType.INVALID_TYPE_OR_FORMAT,
        "unauthorized_or_forbidden": TestType.UNAUTHORIZED,
        "resource_not_found": TestType.NOT_FOUND,
    }

    def normalize(
        self,
        *,
        target: ApiTarget,
        operation: OpenApiOperation,
        draft: AITestCaseDraft,
        ignore_fields: list[str] | None = None,
    ) -> TestCase | None:
        if draft.skip:
            return None

        if draft.test_type not in self._TYPE_MAP:
            raise TestCaseNormalizationError(f"Unknown test_type: {draft.test_type}")

        test_type = self._TYPE_MAP[draft.test_type]

        path_params = dict(draft.path_params)
        query_params = dict(draft.query_params)
        headers = dict(draft.headers)
        json_body = dict(draft.json_body) if isinstance(draft.json_body, dict) else None

        headers.pop("Authorization", None)

        if ignore_fields and json_body:
            for field_name in ignore_fields:
                json_body.pop(field_name, None)

        if test_type != TestType.UNAUTHORIZED and operation.auth_required and target.auth_bearer_token:
            headers["Authorization"] = f"Bearer {target.auth_bearer_token}"

        expected_status_codes = self._normalize_expected_statuses(
            draft=draft,
            test_type=test_type,
            operation=operation,
        )

        expected_response_schema = (
            self._response_schema_for_success(operation)
            if test_type == TestType.POSITIVE
            else None
        )

        return TestCase(
            id=str(uuid.uuid4()),
            target_name=target.name,
            operation=operation,
            test_type=test_type,
            description=draft.description,
            path_params=path_params,
            query_params=query_params,
            headers=headers,
            json_body=json_body,
            expected_status_codes=expected_status_codes,
            expected_response_schema=expected_response_schema,
        )

    def _normalize_expected_statuses(
        self,
        *,
        draft: AITestCaseDraft,
        test_type: TestType,
        operation: OpenApiOperation,
    ) -> set[int]:
        parsed = {
            int(code)
            for code in draft.expected_status_codes
            if isinstance(code, int) and 100 <= code <= 599
        }

        if parsed:
            return parsed

        return self._default_expected_statuses(test_type, operation)

    def _default_expected_statuses(
        self,
        test_type: TestType,
        operation: OpenApiOperation,
    ) -> set[int]:
        if test_type == TestType.POSITIVE:
            return self._positive_expected_statuses(operation)
        if test_type in {TestType.MISSING_REQUIRED, TestType.INVALID_TYPE_OR_FORMAT}:
            return {400, 422}
        if test_type == TestType.UNAUTHORIZED:
            return {401, 403}
        if test_type == TestType.NOT_FOUND:
            return {404}
        return {400}

    def _positive_expected_statuses(self, operation: OpenApiOperation) -> set[int]:
        statuses = set()

        for key in operation.responses.keys():
            if str(key).isdigit():
                code = int(key)
                if 200 <= code < 300:
                    statuses.add(code)

        if not statuses:
            statuses = {200, 201}

        return statuses

    def _response_schema_for_success(self, operation: OpenApiOperation) -> dict | None:
        for key, value in operation.responses.items():
            if not str(key).isdigit():
                continue

            code = int(key)
            if not (200 <= code < 300):
                continue

            if not isinstance(value, dict):
                continue

            content = value.get("content")
            if not isinstance(content, dict):
                continue

            media = content.get("application/json")
            if isinstance(media, dict):
                schema = media.get("schema")
                if isinstance(schema, dict):
                    return schema

        return None