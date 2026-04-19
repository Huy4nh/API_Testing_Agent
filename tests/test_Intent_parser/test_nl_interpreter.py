import json

from api_testing_agent.core.domain_alias_resolver import DomainAliasResolver
from api_testing_agent.core.dynamic_target_resolver import DynamicTargetResolver
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter


def _make_target_resolver(tmp_path):
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
    return DynamicTargetResolver.from_targets_file(str(path))


def test_interpreter_keeps_canonical_command_unchanged(tmp_path):
    interpreter = NaturalLanguageInterpreter(target_resolver=_make_target_resolver(tmp_path))

    text = "test target cms_local module posts GET limit 5 ignore field image"
    normalized = interpreter.normalize(text)

    assert normalized == text


def test_interpreter_normalizes_generic_free_text(tmp_path):
    interpreter = NaturalLanguageInterpreter(
        resolver=DomainAliasResolver.empty(),
        target_resolver=_make_target_resolver(tmp_path),
    )

    normalized = interpreter.normalize(
        "Ở local test /posts GET trước 3 endpoint thôi, bỏ qua image nhé"
    )

    assert "target cms_local" in normalized
    assert "/posts" in normalized
    assert "GET" in normalized
    assert "limit 3" in normalized
    assert "ignore field image" in normalized


def test_interpreter_uses_domain_alias_for_cms_posts(tmp_path):
    interpreter = NaturalLanguageInterpreter(target_resolver=_make_target_resolver(tmp_path))

    normalized = interpreter.normalize("Anh test giúp em phần bài viết ở local")

    assert "target cms_local" in normalized
    assert "module posts" in normalized


def test_interpreter_uses_domain_alias_for_facebook(tmp_path):
    interpreter = NaturalLanguageInterpreter(target_resolver=_make_target_resolver(tmp_path))

    normalized = interpreter.normalize("Bên ngrok lấy nội dung facebook giúp mình")

    assert "target ngrok_live" in normalized
    assert "/FB" in normalized
    assert "POST" in normalized


def test_interpreter_uses_domain_alias_for_x_post(tmp_path):
    interpreter = NaturalLanguageInterpreter(target_resolver=_make_target_resolver(tmp_path))

    normalized = interpreter.normalize("Ở local đăng bài lên X giúp mình")

    assert "target cms_local" in normalized
    assert "/post/x" in normalized
    assert "POST" in normalized