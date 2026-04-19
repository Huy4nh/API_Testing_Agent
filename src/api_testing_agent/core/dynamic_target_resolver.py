from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path


class DynamicTargetResolver:
    def __init__(self, alias_to_target: dict[str, str], enabled_target_names: list[str]) -> None:
        self._alias_to_target = alias_to_target
        self._enabled_target_names = enabled_target_names

    @classmethod
    def from_targets_file(cls, path: str) -> "DynamicTargetResolver":
        p = Path(path)
        if not p.exists():
            return cls.empty()

        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls.empty()

        if not isinstance(raw, list):
            return cls.empty()

        enabled_targets: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            if not item.get("enabled", True):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            enabled_targets.append(item)

        if not enabled_targets:
            return cls.empty()

        alias_to_targets: dict[str, set[str]] = {}
        enabled_names: list[str] = []

        for item in enabled_targets:
            target_name = str(item["name"]).strip()
            enabled_names.append(target_name)

            aliases = cls._generate_aliases_for_target(item)

            for alias in aliases:
                alias_to_targets.setdefault(alias, set()).add(target_name)

        # Chỉ giữ alias unique để tránh ambiguous match
        unique_alias_map: dict[str, str] = {}
        for alias, target_names in alias_to_targets.items():
            if len(target_names) == 1:
                unique_alias_map[alias] = next(iter(target_names))

        return cls(unique_alias_map, enabled_names)

    @classmethod
    def from_env_or_default(cls) -> "DynamicTargetResolver":
        path = os.getenv("TARGET_REGISTRY_PATH", "./targets.json")
        return cls.from_targets_file(path)

    @classmethod
    def empty(cls) -> "DynamicTargetResolver":
        return cls(alias_to_target={}, enabled_target_names=[])

    def resolve(self, text: str) -> str | None:
        if not text or not text.strip():
            return None

        searchable = self.to_searchable_text(text)

        # Ưu tiên exact target name trước
        for target_name in self._enabled_target_names:
            normalized_target_name = self.to_searchable_text(target_name)
            if self._contains_phrase(searchable, normalized_target_name):
                return target_name

        # Sau đó mới match alias dài nhất trước
        sorted_aliases = sorted(self._alias_to_target.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if self._contains_phrase(searchable, alias):
                return self._alias_to_target[alias]

        return None

    @staticmethod
    def to_searchable_text(text: str) -> str:
        lowered = text.lower().strip()
        lowered = lowered.replace("đ", "d").replace("Đ", "D")
        normalized = unicodedata.normalize("NFKD", lowered)
        without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_marks).strip()

    @classmethod
    def _generate_aliases_for_target(cls, item: dict) -> list[str]:
        target_name = str(item["name"]).strip()
        aliases: list[str] = []

        # 1) exact name
        aliases.append(cls.to_searchable_text(target_name))

        # 2) from name pieces
        aliases.extend(cls._aliases_from_phrase(target_name))

        # 3) optional aliases field in targets.json
        raw_aliases = item.get("aliases")
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                if isinstance(alias, str) and alias.strip():
                    aliases.append(cls.to_searchable_text(alias))
                    aliases.extend(cls._aliases_from_phrase(alias))

        return list(dict.fromkeys(a for a in aliases if a))

    @classmethod
    def _aliases_from_phrase(cls, phrase: str) -> list[str]:
        searchable = cls.to_searchable_text(phrase)
        aliases: list[str] = []

        # underscore / hyphen -> space phrase
        spaced = re.sub(r"[_\-]+", " ", searchable)
        spaced = re.sub(r"\s+", " ", spaced).strip()

        aliases.append(spaced)

        tokens = [tok for tok in re.split(r"[_\-\s]+", searchable) if tok]
        if not tokens:
            return list(dict.fromkeys(aliases))

        # token đơn, nhưng lọc token quá ngắn để tránh nhiễu
        for tok in tokens:
            if len(tok) >= 4:
                aliases.append(tok)

        # n-gram liên tiếp
        for size in range(2, len(tokens) + 1):
            for start in range(0, len(tokens) - size + 1):
                gram = " ".join(tokens[start : start + size])
                aliases.append(gram)

        return list(dict.fromkeys(a for a in aliases if a))

    @staticmethod
    def _contains_phrase(searchable_text: str, phrase: str) -> bool:
        pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
        return re.search(pattern, searchable_text, flags=re.IGNORECASE) is not None