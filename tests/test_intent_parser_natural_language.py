from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType


def test_natural_language_local_posts_get_limit_ignore():
    parser = RuleBasedIntentParser()

    plan = parser.parse(
        "Anh test giúp em phần bài viết ở local, chỉ GET thôi, lấy 5 endpoint, bỏ qua image nhé"
    )

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 5
    assert "image" in plan.ignore_fields


def test_natural_language_staging_auth_negative():
    parser = RuleBasedIntentParser()

    plan = parser.parse("Bên staging test giúp login negative case")

    assert plan.target_name == "cms_staging"
    assert plan.tags == ["auth"]
    assert plan.test_types == [
        TestType.MISSING_REQUIRED,
        TestType.INVALID_TYPE_OR_FORMAT,
        TestType.UNAUTHORIZED,
        TestType.NOT_FOUND,
    ]


def test_natural_language_vietnamese_get_phrase():
    parser = RuleBasedIntentParser()

    plan = parser.parse("Ở local xem danh sách bài viết trước nhé")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.methods == [HttpMethod.GET]


def test_natural_language_direct_named_target():
    parser = RuleBasedIntentParser()

    plan = parser.parse("Giúp mình test cms_local phần bài viết, GET thôi")

    assert plan.target_name == "cms_local"
    assert plan.tags == ["posts"]
    assert plan.methods == [HttpMethod.GET]


def test_natural_language_direct_path_should_still_work():
    parser = RuleBasedIntentParser()

    plan = parser.parse("Ở local test /posts GET trước 3 endpoint thôi")

    assert plan.target_name == "cms_local"
    assert plan.paths == ["/posts"]
    assert plan.methods == [HttpMethod.GET]
    assert plan.limit_endpoints == 3