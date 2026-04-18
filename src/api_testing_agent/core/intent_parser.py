from __future__ import annotations

import re

from api_testing_agent.core.models import HttpMethod, TestPlan, TestType
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter


class IntentParseError(ValueError):
    pass


class RuleBasedIntentParser:
    def __init__(self, interpreter: NaturalLanguageInterpreter | None = None) -> None:
        self._interpreter = interpreter or NaturalLanguageInterpreter()

    _METHOD_PATTERNS = {
        HttpMethod.GET: r"\bGET\b",
        HttpMethod.POST: r"\bPOST\b",
        HttpMethod.PUT: r"\bPUT\b",
        HttpMethod.PATCH: r"\bPATCH\b",
        HttpMethod.DELETE: r"\bDELETE\b",
    }

    _TEST_TYPE_KEYWORDS = {
        TestType.POSITIVE: [
            "positive",
            "valid",
            "happy path",
            "hợp lệ",
            "hop le",
        ],
        TestType.MISSING_REQUIRED: [
            "missing",
            "omit",
            "without",
            "thiếu",
            "thieu",
            "bỏ field",
            "bo field",
        ],
        TestType.INVALID_TYPE_OR_FORMAT: [
            "invalid",
            "wrong type",
            "wrong format",
            "sai kiểu",
            "sai kieu",
            "sai định dạng",
            "sai dinh dang",
        ],
        TestType.UNAUTHORIZED: [
            "unauthorized",
            "forbidden",
            "401",
            "403",
            "không có quyền",
            "khong co quyen",
        ],
        TestType.NOT_FOUND: [
            "not found",
            "404",
            "không tồn tại",
            "khong ton tai",
        ],
    }

    def parse(self, text: str) -> TestPlan:
        if not text or not text.strip():
            raise IntentParseError("Empty request.")

        raw = text.strip()
        normalized = self._interpreter.normalize(raw)

        target_name = self._extract_target_name(normalized)
        methods = self._extract_methods(normalized)
        test_types = self._extract_test_types(normalized)
        tags = self._extract_tags(normalized)
        paths = self._extract_paths(normalized)
        ignore_fields = self._extract_ignore_fields(normalized)
        limit = self._extract_limit(normalized)

        if not methods:
            methods = [
                HttpMethod.GET,
                HttpMethod.POST,
                HttpMethod.PUT,
                HttpMethod.PATCH,
                HttpMethod.DELETE,
            ]

        if not test_types:
            test_types = [
                TestType.POSITIVE,
                TestType.MISSING_REQUIRED,
                TestType.INVALID_TYPE_OR_FORMAT,
                TestType.UNAUTHORIZED,
                TestType.NOT_FOUND,
            ]

        return TestPlan(
            target_name=target_name,
            tags=tags,
            paths=paths,
            methods=methods,
            test_types=test_types,
            ignore_fields=ignore_fields,
            limit_endpoints=limit,
        )

    def _extract_target_name(self, raw: str) -> str | None:
        patterns = [
            r"\b(?:target|env|system)\b\s*[:=]?\s*([a-zA-Z0-9_-]+)",
            r"\b(?:mục\s*tiêu|muc\s*tieu)\b\s*[:=]?\s*([a-zA-Z0-9_-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_methods(self, raw: str) -> list[HttpMethod]:
        methods: list[HttpMethod] = []

        for method, pattern in self._METHOD_PATTERNS.items():
            if re.search(pattern, raw, flags=re.IGNORECASE):
                methods.append(method)

        return list(dict.fromkeys(methods))

    def _extract_test_types(self, raw: str) -> list[TestType]:
        lower = raw.lower()
        test_types: list[TestType] = []

        for test_type, keywords in self._TEST_TYPE_KEYWORDS.items():
            if any(keyword in lower for keyword in keywords):
                test_types.append(test_type)

        if "negative" in lower or "negative case" in lower or "negative test" in lower:
            return [
                TestType.MISSING_REQUIRED,
                TestType.INVALID_TYPE_OR_FORMAT,
                TestType.UNAUTHORIZED,
                TestType.NOT_FOUND,
            ]

        return list(dict.fromkeys(test_types))

    def _extract_tags(self, raw: str) -> list[str]:
        patterns = [
            r"\b(?:module|tag)\b\s*[:=]?\s*([a-zA-Z0-9_-]+)",
            r"\b(?:mô\s*đun|mo\s*dun|nhóm)\b\s*[:=]?\s*([a-zA-Z0-9_-]+)",
        ]

        tags: list[str] = []

        for pattern in patterns:
            for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
                tags.append(match.group(1))

        return list(dict.fromkeys(tags))

    def _extract_paths(self, raw: str) -> list[str]:
        candidates = re.findall(r"(/[^\s,]+)", raw)
        cleaned = [candidate.rstrip(".,;") for candidate in candidates]
        return list(dict.fromkeys(cleaned))

    def _extract_ignore_fields(self, raw: str) -> list[str]:
        patterns = [
            r"(?:ignore|skip)\s+field\s+([a-zA-Z0-9_-]+)",
            r"(?:bỏ\s*qua|bo\s*qua)\s+field\s+([a-zA-Z0-9_-]+)",
            r"(?:bỏ\s*qua|bo\s*qua)\s+([a-zA-Z0-9_-]+)",
        ]

        fields: list[str] = []

        for pattern in patterns:
            for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
                fields.append(match.group(1))

        return list(dict.fromkeys(fields))

    def _extract_limit(self, raw: str) -> int:
        match = re.search(
            r"(?:limit|giới hạn|gioi han)\s*[:=]?\s*(\d+)",
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            return max(1, min(int(match.group(1)), 200))

        return 50