from api_testing_agent.core.intent_parser import IntentParseError, RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType


def test_parse_basic_target_module_method():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_local module posts GET")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.methods == [HttpMethod.GET]


def test_parse_negative_case():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_local module auth negative")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["auth"]
    assert plan.test_types == [
        TestType.MISSING_REQUIRED,
        TestType.INVALID_TYPE_OR_FORMAT,
        TestType.UNAUTHORIZED,
        TestType.NOT_FOUND,
    ]


def test_parse_ignore_field_and_limit():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_local module posts POST bỏ qua field image limit 5")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.methods == [HttpMethod.POST]
    assert "image" in plan.ignore_fields
    assert plan.limit_endpoints == 5


def test_parse_path():
    parser = RuleBasedIntentParser()

    plan = parser.parse("test target cms_local /posts GET")

    assert plan.target_name == "cms_local"
    assert plan.paths == ["/posts"]
    assert plan.methods == [HttpMethod.GET]


def test_parse_empty_should_raise():
    parser = RuleBasedIntentParser()

    try:
        parser.parse("   ")
        assert False, "Expected IntentParseError"
    except IntentParseError:
        assert True