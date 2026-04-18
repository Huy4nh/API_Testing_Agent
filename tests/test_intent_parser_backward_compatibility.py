from api_testing_agent.core.intent_parser import IntentParseError, RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType


def test_old_canonical_command_still_works():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_local module posts GET")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.paths == []
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 50
    assert plan.ignore_fields == []


def test_old_negative_command_still_works():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_staging module auth negative")

    assert plan.target_name == "cms_staging"
    assert plan.tags == ["auth"]
    assert plan.test_types == [
        TestType.MISSING_REQUIRED,
        TestType.INVALID_TYPE_OR_FORMAT,
        TestType.UNAUTHORIZED,
        TestType.NOT_FOUND,
    ]


def test_old_path_limit_ignore_still_works():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_local /posts GET limit 5 ignore field image")

    assert plan.target_name == "cms_local"
    assert plan.paths == ["/posts"]
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 5
    assert plan.ignore_fields == ["image"]


def test_empty_input_should_raise_error():
    parser = RuleBasedIntentParser()

    try:
        parser.parse("   ")
        assert False, "Expected IntentParseError"
    except IntentParseError:
        assert True