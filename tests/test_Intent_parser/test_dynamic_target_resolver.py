import json

from api_testing_agent.core.dynamic_target_resolver import DynamicTargetResolver


def _write_targets_file(tmp_path, data):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def test_resolve_exact_name_from_file(tmp_path):
    path = _write_targets_file(
        tmp_path,
        [
            {"name": "cms_local", "enabled": True},
            {"name": "ngrok_live", "enabled": True},
        ],
    )

    resolver = DynamicTargetResolver.from_targets_file(path)

    assert resolver.resolve("test target cms_local module posts") == "cms_local"
    assert resolver.resolve("test ngrok_live now") == "ngrok_live"


def test_resolve_generated_aliases_from_target_name(tmp_path):
    path = _write_targets_file(
        tmp_path,
        [
            {"name": "cms_local", "enabled": True},
            {"name": "ngrok_live", "enabled": True},
        ],
    )

    resolver = DynamicTargetResolver.from_targets_file(path)

    assert resolver.resolve("ở local test giúp mình") == "cms_local"
    assert resolver.resolve("bên ngrok lấy nội dung facebook") == "ngrok_live"


def test_resolve_optional_aliases_from_targets_json(tmp_path):
    path = _write_targets_file(
        tmp_path,
        [
            {"name": "client_demo", "enabled": True, "aliases": ["public demo", "demo public"]},
        ],
    )

    resolver = DynamicTargetResolver.from_targets_file(path)

    assert resolver.resolve("test public demo đi") == "client_demo"
    assert resolver.resolve("chạy trên demo public nhé") == "client_demo"


def test_ambiguous_alias_is_ignored(tmp_path):
    path = _write_targets_file(
        tmp_path,
        [
            {"name": "cms_local", "enabled": True},
            {"name": "client_local", "enabled": True},
        ],
    )

    resolver = DynamicTargetResolver.from_targets_file(path)

    # "local" giờ mơ hồ nên không resolve được
    assert resolver.resolve("test local giúp mình") is None


def test_disabled_target_is_ignored(tmp_path):
    path = _write_targets_file(
        tmp_path,
        [
            {"name": "cms_local", "enabled": False},
            {"name": "ngrok_live", "enabled": True},
        ],
    )

    resolver = DynamicTargetResolver.from_targets_file(path)

    assert resolver.resolve("test local giúp mình") is None
    assert resolver.resolve("test ngrok giúp mình") == "ngrok_live"