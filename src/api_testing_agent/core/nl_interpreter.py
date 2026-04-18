from __future__ import annotations

import re
import unicodedata

from api_testing_agent.core.models import HttpMethod


class NaturalLanguageInterpreter:
    """
    Lớp này nhận text chat tự nhiên và chuẩn hóa nó thành
    một canonical command gần chuẩn để parser strict xử lý.

    Ví dụ:
    "Anh test giúp em phần bài viết ở local, chỉ GET thôi, lấy 5 endpoint, bỏ qua image nhé"
    -> "test target cms_local module posts GET limit 5 ignore field image"
    """

    _TARGET_ALIASES = {
        "cms_local": [
            r"\blocal\b",
            r"\btren local\b",
            r"\bben local\b",
            r"\bo local\b",
            r"\bmoi truong local\b",
        ],
        "cms_staging": [
            r"\bstaging\b",
            r"\btren staging\b",
            r"\bben staging\b",
            r"\bo staging\b",
            r"\bmoi truong staging\b",
        ],
        "cms_prod": [
            r"\bproduction\b",
            r"\bprod\b",
            r"\bmoi truong production\b",
            r"\bmoi truong prod\b",
        ],
    }

    _MODULE_ALIASES = {
        "posts": [
            r"\bposts?\b",
            r"\barticles?\b",
            r"\bbai viet\b",
            r"\bphan bai viet\b",
            r"\btin tuc\b",
        ],
        "auth": [
            r"\bauth\b",
            r"\blogin\b",
            r"\bdang nhap\b",
            r"\bxac thuc\b",
        ],
        "users": [
            r"\busers?\b",
            r"\buser\b",
            r"\bnguoi dung\b",
            r"\btai khoan\b",
            r"\baccounts?\b",
        ],
    }

    _NATURAL_METHOD_ALIASES = {
        HttpMethod.GET: [
            r"\bxem\b",
            r"\bdoc\b",
            r"\bdanh sach\b",
            r"\bchi tiet\b",
            r"\blay\b",
        ],
        HttpMethod.POST: [
            r"\btao\b",
            r"\bthem moi\b",
            r"\bcreate\b",
        ],
        HttpMethod.PUT: [
            r"\bthay the\b",
        ],
        HttpMethod.PATCH: [
            r"\bcap nhat\b",
            r"\bsua\b",
            r"\bupdate\b",
        ],
        HttpMethod.DELETE: [
            r"\bxoa\b",
            r"\bdelete\b",
            r"\bremove\b",
        ],
    }

    def normalize(self, text: str) -> str:
        if not text or not text.strip():
            return text

        raw = text.strip()

        # Nếu user đã gõ gần đúng cú pháp chuẩn thì giữ nguyên
        if self._looks_like_canonical_command(raw):
            return raw

        searchable = self._to_searchable_text(raw)

        parts: list[str] = ["test"]

        target_name = self._detect_target_name(searchable)
        if target_name:
            parts.extend(["target", target_name])

        module_name = self._detect_module_name(searchable)
        if module_name:
            parts.extend(["module", module_name])

        methods = self._detect_methods(searchable)
        if methods:
            parts.extend([method.value.upper() for method in methods])

        test_markers = self._detect_test_markers(searchable)
        if test_markers:
            parts.extend(test_markers)

        paths = self._extract_paths(raw)
        if paths:
            parts.extend(paths)

        limit = self._extract_limit(searchable)
        if limit is not None:
            parts.extend(["limit", str(limit)])

        ignore_fields = self._extract_ignore_fields(searchable)
        for field_name in ignore_fields:
            parts.extend(["ignore", "field", field_name])

        canonical = " ".join(parts)
        canonical = re.sub(r"\s+", " ", canonical).strip()

        return canonical

    def _looks_like_canonical_command(self, raw: str) -> bool:
        lower = raw.lower()

        return any(
            keyword in lower
            for keyword in [
                "target ",
                "target:",
                "target=",
                "module ",
                "module:",
                "module=",
                "tag ",
                "tag:",
                "tag=",
                "ignore field",
                "skip field",
                "limit ",
                "limit:",
                "limit=",
            ]
        )

    def _to_searchable_text(self, raw: str) -> str:
        lowered = raw.lower().strip()
        normalized = unicodedata.normalize("NFKD", lowered)
        without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_marks).strip()

    def _detect_target_name(self, searchable: str) -> str | None:
        for target_name, patterns in self._TARGET_ALIASES.items():
            for pattern in patterns:
                if re.search(pattern, searchable, flags=re.IGNORECASE):
                    return target_name

        # Nếu user gõ trực tiếp tên target như cms_local trong chat tự nhiên
        direct_match = re.search(r"\b([a-z][a-z0-9]*_[a-z0-9_-]+)\b", searchable, flags=re.IGNORECASE)
        if direct_match:
            return direct_match.group(1)

        return None

    def _detect_module_name(self, searchable: str) -> str | None:
        for module_name, patterns in self._MODULE_ALIASES.items():
            for pattern in patterns:
                if re.search(pattern, searchable, flags=re.IGNORECASE):
                    return module_name
        return None

    def _detect_methods(self, searchable: str) -> list[HttpMethod]:
        methods: list[HttpMethod] = []

        # Ưu tiên method HTTP chuẩn nếu user có nói thẳng GET/POST/PUT/PATCH/DELETE
        explicit_method_patterns = {
            HttpMethod.GET: r"\bGET\b",
            HttpMethod.POST: r"\bPOST\b",
            HttpMethod.PUT: r"\bPUT\b",
            HttpMethod.PATCH: r"\bPATCH\b",
            HttpMethod.DELETE: r"\bDELETE\b",
        }

        for method, pattern in explicit_method_patterns.items():
            if re.search(pattern, searchable, flags=re.IGNORECASE):
                methods.append(method)

        if methods:
            return list(dict.fromkeys(methods))

        for method, patterns in self._NATURAL_METHOD_ALIASES.items():
            for pattern in patterns:
                if re.search(pattern, searchable, flags=re.IGNORECASE):
                    methods.append(method)
                    break

        return list(dict.fromkeys(methods))

    def _detect_test_markers(self, searchable: str) -> list[str]:
        if re.search(
            r"\bnegative\b|\bnegative case\b|\bnegative test\b|\btest am\b|\btest loi\b",
            searchable,
            flags=re.IGNORECASE,
        ):
            return ["negative"]

        markers: list[str] = []

        if re.search(r"\bpositive\b|\bhop le\b|\bvalid\b", searchable, flags=re.IGNORECASE):
            markers.append("positive")

        if re.search(
            r"\bunauthorized\b|\bforbidden\b|\b401\b|\b403\b|\bkhong co quyen\b",
            searchable,
            flags=re.IGNORECASE,
        ):
            markers.append("unauthorized")

        if re.search(
            r"\bnot found\b|\b404\b|\bkhong ton tai\b",
            searchable,
            flags=re.IGNORECASE,
        ):
            markers.append("not found")

        if re.search(
            r"\bmissing\b|\bomit\b|\bwithout\b|\bthieu\b",
            searchable,
            flags=re.IGNORECASE,
        ):
            markers.append("missing")

        if re.search(
            r"\binvalid\b|\bwrong type\b|\bwrong format\b|\bsai kieu\b|\bsai dinh dang\b",
            searchable,
            flags=re.IGNORECASE,
        ):
            markers.append("invalid")

        return list(dict.fromkeys(markers))

    def _extract_limit(self, searchable: str) -> int | None:
        patterns = [
            r"\blimit\s*[:=]?\s*(\d+)\b",
            r"\b(?:khoang|tam|toi da)\s*(\d+)\s*(?:endpoint|api|case)?\b",
            r"\blay\s*(\d+)\s*(?:endpoint|api|case)\b",
            r"\b(\d+)\s*(?:endpoint|api|case)\s*(?:thoi|truoc)?\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, searchable, flags=re.IGNORECASE)
            if match:
                return max(1, min(int(match.group(1)), 200))

        return None

    def _extract_ignore_fields(self, searchable: str) -> list[str]:
        patterns = [
            r"\bignore field ([a-zA-Z0-9_-]+)\b",
            r"\bskip field ([a-zA-Z0-9_-]+)\b",
            r"\bbo qua field ([a-zA-Z0-9_-]+)\b",
            r"\bbo qua ([a-zA-Z0-9_-]+)\b",
        ]

        fields: list[str] = []

        for pattern in patterns:
            for match in re.finditer(pattern, searchable, flags=re.IGNORECASE):
                fields.append(match.group(1))

        return list(dict.fromkeys(fields))

    def _extract_paths(self, raw: str) -> list[str]:
        candidates = re.findall(r"(/[^\s,]+)", raw)
        cleaned = [candidate.rstrip(".,;") for candidate in candidates]
        return list(dict.fromkeys(cleaned))