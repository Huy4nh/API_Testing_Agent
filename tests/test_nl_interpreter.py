from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter


def test_interpreter_keeps_canonical_command_unchanged():
    interpreter = NaturalLanguageInterpreter()

    text = "test target cms_local module posts GET limit 5 ignore field image"
    normalized = interpreter.normalize(text)

    assert normalized == text


def test_interpreter_normalizes_natural_posts_local_get_limit_ignore():
    interpreter = NaturalLanguageInterpreter()

    normalized = interpreter.normalize(
        "Anh test giúp em phần bài viết ở local, chỉ GET thôi, lấy 5 endpoint, bỏ qua image nhé"
    )

    assert "target cms_local" in normalized
    assert "module posts" in normalized
    assert "GET" in normalized
    assert "limit 5" in normalized
    assert "ignore field image" in normalized


def test_interpreter_normalizes_natural_staging_login_negative():
    interpreter = NaturalLanguageInterpreter()

    normalized = interpreter.normalize("Bên staging test giúp login negative case")

    assert "target cms_staging" in normalized
    assert "module auth" in normalized
    assert "negative" in normalized


def test_interpreter_detects_named_target_in_free_text():
    interpreter = NaturalLanguageInterpreter()

    normalized = interpreter.normalize("Giúp mình test cms_local phần bài viết, GET thôi")

    assert "target cms_local" in normalized
    assert "module posts" in normalized
    assert "GET" in normalized


def test_interpreter_detects_path_in_free_text():
    interpreter = NaturalLanguageInterpreter()

    normalized = interpreter.normalize("Ở local test /posts GET trước 3 endpoint thôi")

    assert "target cms_local" in normalized
    assert "/posts" in normalized
    assert "GET" in normalized
    assert "limit 3" in normalized