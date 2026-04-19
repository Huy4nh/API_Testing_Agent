import json
import os

from api_testing_agent.core.domain_alias_resolver import DomainAliasResolver
from api_testing_agent.core.dynamic_target_resolver import DynamicTargetResolver
from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType as ApiTestType
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter


CACHE_RUNTIME = os.getenv("TEST_CACHE_RUNTIME", "0") == "0"


def _make_parser(tmp_path, resolver=None):
    """
    Tạo parser từ file targets.json tạm cho unit test độc lập.
    """
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
        resolver=resolver if resolver is not None else DomainAliasResolver(),
        target_resolver=DynamicTargetResolver.from_targets_file(str(path)),
    )
    return RuleBasedIntentParser(interpreter=interpreter)


def _make_runtime_parser(resolver=None):
    """
    Tạo parser đọc từ targets.json thật của project.
    Dùng khi muốn integration test với file runtime thật.
    """
    interpreter = NaturalLanguageInterpreter(
        resolver=resolver if resolver is not None else DomainAliasResolver(),
        target_resolver=DynamicTargetResolver.from_targets_file("./targets.json"),
    )
    return RuleBasedIntentParser(interpreter=interpreter)


def _get_parser(tmp_path, resolver=None):
    """
    Nếu CACHE_RUNTIME=1 -> dùng file targets.json thật
    Nếu không -> dùng file tạm trong tmp_path
    """
    if CACHE_RUNTIME:
        return _make_runtime_parser(resolver=resolver)
    return _make_parser(tmp_path, resolver=resolver)


def test_natural_language_local_posts_get_limit_ignore(tmp_path):
    parser = _get_parser(tmp_path)

    plan = parser.parse(
        "Anh test giúp em phần bài viết ở local, chỉ GET thôi, lấy 5 endpoint, bỏ qua image nhé"
    )

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 5
    assert "image" in plan.ignore_fields


def test_natural_language_ngrok_auth_negative(tmp_path):
    parser = _get_parser(tmp_path)

    plan = parser.parse("Bên ngrok test giúp login negative case")

    assert plan.target_name == "ngrok_live"
    assert plan.tags == ["auth"]
    assert plan.test_types == [
        ApiTestType.MISSING_REQUIRED,
        ApiTestType.INVALID_TYPE_OR_FORMAT,
        ApiTestType.UNAUTHORIZED,
        ApiTestType.NOT_FOUND,
    ]


def test_natural_language_direct_path_should_still_work(tmp_path):
    parser = _get_parser(tmp_path)

    plan = parser.parse("Ở local test /posts GET trước 3 endpoint thôi")

    assert plan.target_name == "cms_local"
    assert plan.paths == ["/posts"]
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 3


def test_natural_language_social_facebook_path_resolution(tmp_path):
    parser = _get_parser(tmp_path)

    plan = parser.parse("Bên ngrok lấy nội dung facebook giúp mình")

    assert plan.target_name == "ngrok_live"
    assert plan.paths == ["/FB"]
    assert plan.methods == [HttpMethod.POST]


def test_natural_language_social_x_post_resolution(tmp_path):
    parser = _get_parser(tmp_path)

    plan = parser.parse("Ở local đăng bài lên X giúp mình")

    assert plan.target_name == "cms_local"
    assert plan.paths == ["/post/x"]
    assert plan.methods == [HttpMethod.POST]


def test_disable_domain_alias_resolver_to_avoid_new_matches(tmp_path):
    parser = _get_parser(tmp_path, resolver=DomainAliasResolver.empty())

    plan = parser.parse("Ở local đăng bài lên X giúp mình")

    assert plan.target_name == "cms_local"
    assert plan.paths == []
    
def test_natural_language_social_x_post_resolution_customize(tmp_path):
    parser = _get_parser(tmp_path)

    plan = parser.parse("Ở hello world đăng bài lên X giúp mình")
    assert plan.target_name == "hello_world_love"
    assert plan.paths == ["/post/x"]
    assert plan.methods == [HttpMethod.POST]