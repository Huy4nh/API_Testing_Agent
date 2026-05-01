from api_testing_agent.core.validation_models import ValidationVerdict
from api_testing_agent.core.validator import Validator


def test_validate_case_pass_with_direct_schema():
    validator = Validator()

    execution_case = {
        "testcase_id": "case-1",
        "logical_case_name": "get_post_positive",
        "target_name": "cms_local",
        "operation_id": "get_post",
        "method": "GET",
        "path": "/posts/1",
        "final_url": "http://127.0.0.1:8000/posts/1",
        "expected_statuses": [200],
        "actual_status": 200,
        "response_json": {
            "id": 1,
            "title": "hello",
            "meta": {
                "published": True,
            },
        },
        "response_time_ms": 12.5,
        "network_error": None,
        "skip": False,
        "test_type": "positive",
        "expected_response_schema": {
            "type": "object",
            "required": ["id", "title", "meta"],
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "meta": {
                    "type": "object",
                    "required": ["published"],
                    "properties": {
                        "published": {"type": "boolean"},
                    },
                },
            },
        },
    }

    result = validator.validate_case(execution_case)

    assert result.verdict == ValidationVerdict.PASS
    assert result.status_check_passed is True
    assert result.schema_check_passed is True
    assert result.required_fields_check_passed is True
    assert result.issues == []


def test_validate_case_skip():
    validator = Validator()

    execution_case = {
        "testcase_id": "case-skip",
        "target_name": "cms_local",
        "operation_id": "skip_case",
        "skip": True,
        "skip_reason": "User canceled during review",
        "expected_statuses": [200],
        "actual_status": None,
    }

    result = validator.validate_case(execution_case)

    assert result.verdict == ValidationVerdict.SKIP
    assert result.skip is True
    assert result.skip_reason == "User canceled during review"
    assert result.status_check_passed is None


def test_validate_case_network_error():
    validator = Validator()

    execution_case = {
        "testcase_id": "case-error",
        "target_name": "cms_local",
        "operation_id": "network_fail_case",
        "skip": False,
        "network_error": "connection refused",
        "expected_statuses": [200],
        "actual_status": 0,
    }

    result = validator.validate_case(execution_case)

    assert result.verdict == ValidationVerdict.ERROR
    assert result.network_error == "connection refused"
    assert any(issue.code == "execution_error" for issue in result.issues)


def test_validate_case_missing_required_field_and_type_mismatch():
    validator = Validator()

    execution_case = {
        "testcase_id": "case-fail",
        "logical_case_name": "bad_response_case",
        "target_name": "cms_local",
        "operation_id": "get_bad_post",
        "method": "GET",
        "path": "/posts/2",
        "expected_statuses": [200],
        "actual_status": 200,
        "response_json": {
            "id": "not-integer",
            "meta": {},
        },
        "skip": False,
        "network_error": None,
        "expected_response_schema": {
            "type": "object",
            "required": ["id", "title", "meta"],
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "meta": {
                    "type": "object",
                    "required": ["published"],
                    "properties": {
                        "published": {"type": "boolean"},
                    },
                },
            },
        },
    }

    result = validator.validate_case(execution_case)

    assert result.verdict == ValidationVerdict.FAIL
    assert result.status_check_passed is True
    assert result.schema_check_passed is False
    assert result.required_fields_check_passed is False
    assert "title" in result.missing_required_fields
    assert any(issue.code == "schema_type_mismatch" for issue in result.issues)
    assert any(issue.code == "missing_required_field" for issue in result.issues)


def test_validate_batch_summary_counts():
    validator = Validator()

    execution_batch = {
        "thread_id": "thread-1",
        "target_name": "cms_local",
        "results": [
            {
                "testcase_id": "pass-case",
                "expected_statuses": [200],
                "actual_status": 200,
                "response_json": {"id": 1},
                "expected_response_schema": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "integer"},
                    },
                },
                "skip": False,
                "network_error": None,
            },
            {
                "testcase_id": "skip-case",
                "skip": True,
                "skip_reason": "No approved testcase",
                "expected_statuses": [200],
                "actual_status": None,
            },
            {
                "testcase_id": "error-case",
                "skip": False,
                "network_error": "timeout",
                "expected_statuses": [200],
                "actual_status": 0,
            },
            {
                "testcase_id": "fail-case",
                "skip": False,
                "network_error": None,
                "expected_statuses": [200],
                "actual_status": 500,
                "response_json": {"detail": "server error"},
            },
        ],
    }

    result = validator.validate_batch(execution_batch)

    assert result.thread_id == "thread-1"
    assert result.target_name == "cms_local"
    assert result.total_cases == 4
    assert result.validated_cases == 4
    assert result.pass_cases == 1
    assert result.skip_cases == 1
    assert result.error_cases == 1
    assert result.fail_cases == 1