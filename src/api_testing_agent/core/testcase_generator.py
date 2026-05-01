import copy
import uuid
from typing import Any

from api_testing_agent.core.models import (
    ApiTarget,
    OpenApiOperation,
    ParamLocation,
    TestCase,
    TestPlan,
    TestType,
)
from api_testing_agent.core.schema_faker import SchemaFaker
from api_testing_agent.logging_config import bind_logger, get_logger


class TestCaseGenerator:
    def __init__(self) -> None:
        self._faker = SchemaFaker()
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized TestCaseGenerator.",
            extra={"payload_source": "testcase_generator_init"},
        )

    def generate(
        self,
        target: ApiTarget,
        operations: list[OpenApiOperation],
        plan: TestPlan,
    ) -> list[TestCase]:
        logger = bind_logger(
            self._logger,
            target_name=target.name,
            payload_source="testcase_generator_generate",
        )
        logger.info(
            f"Starting testcase generation. operations={len(operations)}, requested_test_types={len(plan.test_types)}"
        )

        filtered_operations = self._filter_operations(operations, plan)
        filtered_operations = filtered_operations[: plan.limit_endpoints]

        logger.info(f"Filtered operations count={len(filtered_operations)} after applying plan.")

        test_cases: list[TestCase] = []

        for operation in filtered_operations:
            operation_logger = bind_logger(
                self._logger,
                target_name=target.name,
                operation_id=operation.operation_id,
                payload_source="testcase_generator_operation",
            )
            operation_logger.info(
                f"Generating cases for operation {operation.method.value.upper()} {operation.path}"
            )

            for test_type in plan.test_types:
                case = self._build_case(
                    target=target,
                    operation=operation,
                    test_type=test_type,
                    ignore_fields=plan.ignore_fields,
                )
                if case is not None:
                    test_cases.append(case)

            operation_logger.info("Finished generating cases for operation.")

        logger.info(f"Testcase generation completed. total_cases={len(test_cases)}")
        return test_cases

    def _filter_operations(
        self,
        operations: list[OpenApiOperation],
        plan: TestPlan,
    ) -> list[OpenApiOperation]:
        filtered: list[OpenApiOperation] = []

        for operation in operations:
            if plan.methods and operation.method not in plan.methods:
                continue

            if plan.tags:
                operation_tags_lower = {tag.lower() for tag in operation.tags}
                plan_tags_lower = {tag.lower() for tag in plan.tags}
                if not operation_tags_lower.intersection(plan_tags_lower):
                    continue

            if plan.paths and operation.path not in plan.paths:
                continue

            filtered.append(operation)

        return filtered

    def _build_case(
        self,
        target: ApiTarget,
        operation: OpenApiOperation,
        test_type: TestType,
        ignore_fields: list[str],
    ) -> TestCase | None:
        logger = bind_logger(
            self._logger,
            target_name=target.name,
            operation_id=operation.operation_id,
            payload_source="testcase_generator_build_case",
        )
        logger.info(f"Building case for test_type={test_type.value}")

        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        headers: dict[str, str] = {}
        json_body: dict[str, Any] | None = None

        for parameter in operation.parameters:
            value = self._faker.example_for_schema(parameter.schema)

            if parameter.location == ParamLocation.PATH:
                path_params[parameter.name] = value
            elif parameter.location == ParamLocation.QUERY:
                query_params[parameter.name] = value

        if operation.request_body and operation.request_body.content_type == "application/json":
            generated = self._faker.example_for_schema(operation.request_body.schema)
            if isinstance(generated, dict):
                json_body = generated
            else:
                json_body = None

        if ignore_fields and json_body:
            for field_name in ignore_fields:
                json_body.pop(field_name, None)

        if test_type == TestType.POSITIVE:
            if target.auth_bearer_token and operation.auth_required:
                headers["Authorization"] = f"Bearer {target.auth_bearer_token}"

            logger.info("Built positive testcase.")
            return self._make_case(
                target_name=target.name,
                operation=operation,
                test_type=test_type,
                description="Positive case with valid input.",
                path_params=path_params,
                query_params=query_params,
                headers=headers,
                json_body=json_body,
                expected_status_codes=self._positive_expected_statuses(operation),
                expected_response_schema=self._response_schema_for_success(operation),
            )

        if test_type == TestType.MISSING_REQUIRED:
            mutated_body = copy.deepcopy(json_body) if json_body else None

            if mutated_body and operation.request_body:
                required_fields = operation.request_body.schema.get("required") or []
                if required_fields:
                    mutated_body.pop(required_fields[0], None)

            if target.auth_bearer_token and operation.auth_required:
                headers["Authorization"] = f"Bearer {target.auth_bearer_token}"

            logger.info("Built missing_required testcase.")
            return self._make_case(
                target_name=target.name,
                operation=operation,
                test_type=test_type,
                description="Missing one required field.",
                path_params=path_params,
                query_params=query_params,
                headers=headers,
                json_body=mutated_body,
                expected_status_codes={400, 422},
                expected_response_schema=None,
            )

        if test_type == TestType.INVALID_TYPE_OR_FORMAT:
            mutated_body = copy.deepcopy(json_body) if json_body else None

            if mutated_body and operation.request_body:
                mutated_body = self._mutate_one_invalid_field(
                    body=mutated_body,
                    schema=operation.request_body.schema,
                )

            if target.auth_bearer_token and operation.auth_required:
                headers["Authorization"] = f"Bearer {target.auth_bearer_token}"

            logger.info("Built invalid_type_or_format testcase.")
            return self._make_case(
                target_name=target.name,
                operation=operation,
                test_type=test_type,
                description="Invalid field type or format.",
                path_params=path_params,
                query_params=query_params,
                headers=headers,
                json_body=mutated_body,
                expected_status_codes={400, 422},
                expected_response_schema=None,
            )

        if test_type == TestType.UNAUTHORIZED:
            if not operation.auth_required:
                logger.info("Skipped unauthorized testcase because operation does not require auth.")
                return None

            logger.info("Built unauthorized testcase.")
            return self._make_case(
                target_name=target.name,
                operation=operation,
                test_type=test_type,
                description="Unauthorized or forbidden request without token.",
                path_params=path_params,
                query_params=query_params,
                headers={},
                json_body=json_body,
                expected_status_codes={401, 403},
                expected_response_schema=None,
            )

        if test_type == TestType.NOT_FOUND:
            mutated_path_params = dict(path_params)

            if not mutated_path_params:
                logger.info("Skipped not_found testcase because there are no path params.")
                return None

            for key in mutated_path_params:
                mutated_path_params[key] = 999999999

            if target.auth_bearer_token and operation.auth_required:
                headers["Authorization"] = f"Bearer {target.auth_bearer_token}"

            logger.info("Built not_found testcase.")
            return self._make_case(
                target_name=target.name,
                operation=operation,
                test_type=test_type,
                description="Resource not found using non-existing path parameter.",
                path_params=mutated_path_params,
                query_params=query_params,
                headers=headers,
                json_body=json_body,
                expected_status_codes={404},
                expected_response_schema=None,
            )

        logger.warning(f"Unsupported test_type encountered: {test_type}")
        return None

    def _make_case(
        self,
        *,
        target_name: str,
        operation: OpenApiOperation,
        test_type: TestType,
        description: str,
        path_params: dict[str, Any],
        query_params: dict[str, Any],
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        expected_status_codes: set[int],
        expected_response_schema: dict[str, Any] | None,
    ) -> TestCase:
        return TestCase(
            id=str(uuid.uuid4()),
            target_name=target_name,
            operation=operation,
            test_type=test_type,
            description=description,
            path_params=path_params,
            query_params=query_params,
            headers=headers,
            json_body=json_body,
            expected_status_codes=expected_status_codes,
            expected_response_schema=expected_response_schema,
        )

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

    def _response_schema_for_success(self, operation: OpenApiOperation) -> dict[str, Any] | None:
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

    def _mutate_one_invalid_field(
        self,
        body: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            return body

        mutated = dict(body)

        for field_name, field_schema in properties.items():
            if field_name not in mutated:
                continue
            if not isinstance(field_schema, dict):
                continue

            field_type = field_schema.get("type")

            if field_type == "string":
                mutated[field_name] = 12345
                return mutated

            if field_type == "integer":
                mutated[field_name] = "invalid_integer"
                return mutated

            if field_type == "number":
                mutated[field_name] = "invalid_number"
                return mutated

            if field_type == "boolean":
                mutated[field_name] = "invalid_boolean"
                return mutated

        return mutated