import json

from api_testing_agent.core.dynamic_target_resolver import DynamicTargetResolver
from api_testing_agent.core.intent_parser import IntentParseError, RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType as ApiTestType
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter

CACHE_RUNTIME = True

def _make_parser(tmp_path):
    path = tmp_path / "targets.json"
    path.write_text(
        json.dumps(
            [
                {"name": "cms_local", "enabled": True},
                {"name": "ngrok_live", "enabled": True},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    interpreter = NaturalLanguageInterpreter(
        target_resolver=DynamicTargetResolver.from_targets_file(str(path))
    )
    return RuleBasedIntentParser(interpreter=interpreter)


def test_old_canonical_command_still_works(tmp_path):
    parser = _make_parser(tmp_path) if CACHE_RUNTIME else DynamicTargetResolver.from_targets_file("./targets.json")

    plan = parser.parse("test target cms_local module posts GET")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.paths == []
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 50
    assert plan.ignore_fields == []


def test_old_negative_command_still_works(tmp_path):
    parser = _make_parser(tmp_path) if CACHE_RUNTIME else DynamicTargetResolver.from_targets_file("./targets.json")

    plan = parser.parse("test target ngrok_live module auth negative")

    assert plan.target_name == "ngrok_live"
    assert plan.tags == ["auth"]
    assert plan.test_types == [
        ApiTestType.MISSING_REQUIRED,
        ApiTestType.INVALID_TYPE_OR_FORMAT,
        ApiTestType.UNAUTHORIZED,
        ApiTestType.NOT_FOUND,
    ]


def test_old_path_limit_ignore_still_works(tmp_path):
    parser = _make_parser(tmp_path) if CACHE_RUNTIME else DynamicTargetResolver.from_targets_file("./targets.json")

    plan = parser.parse("test target cms_local /posts GET limit 5 ignore field image")

    assert plan.target_name == "cms_local"
    assert plan.paths == ["/posts"]
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 5
    assert plan.ignore_fields == ["image"]


def test_empty_input_should_raise_error(tmp_path):
    parser = _make_parser(tmp_path) if CACHE_RUNTIME else DynamicTargetResolver.from_targets_file("./targets.json")

    try:
        parser.parse("   ")
        assert False, "Expected IntentParseError"
    except IntentParseError:
        assert True