from __future__ import annotations

import re

from api_testing_agent.core.domain_alias_resolver import DomainAliasResolver
from api_testing_agent.core.dynamic_target_resolver import DynamicTargetResolver
from api_testing_agent.core.models import HttpMethod
from api_testing_agent.logging_config import bind_logger, get_logger


class NaturalLanguageInterpreter:
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
            r"\bgui\b",
            r"\bcreate\b",
            r"\bpost\b",
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

    _EXPLICIT_METHOD_PATTERNS = {
        HttpMethod.GET: r"\bGET\b",
        HttpMethod.POST: r"\bPOST\b",
        HttpMethod.PUT: r"\bPUT\b",
        HttpMethod.PATCH: r"\bPATCH\b",
        HttpMethod.DELETE: r"\bDELETE\b",
    }

    def __init__(
        self,
        resolver: DomainAliasResolver | None = None,
        target_resolver: DynamicTargetResolver | None = None,
    ) -> None:
        self._resolver = resolver or DomainAliasResolver()
        self._target_resolver = target_resolver or DynamicTargetResolver.from_env_or_default()
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized NaturalLanguageInterpreter.",
            extra={"payload_source": "nl_interpreter_init"},
        )

    def normalize(self, text: str) -> str:
        logger = bind_logger(
            self._logger,
            payload_source="nl_interpreter_normalize",
        )
        logger.info("Starting natural language normalization.")

        if not text or not text.strip():
            logger.warning("Normalization received empty text. Returning original value.")
            return text

        raw = text.strip()

        if self._looks_like_canonical_command(raw):
            logger.info("Input already looks like canonical command. Returning original text.")
            return raw

        searchable = DynamicTargetResolver.to_searchable_text(raw)
        resolved = self._resolver.resolve(searchable)

        resolved_methods = list(getattr(resolved, "methods", []) or [])
        resolved_tags = list(getattr(resolved, "tags", []) or [])
        resolved_paths = list(getattr(resolved, "paths", []) or [])
        resolved_extra_tokens = list(getattr(resolved, "extra_tokens", []) or [])

        parts: list[str] = ["test"]

        target_name = self._target_resolver.resolve(searchable)
        if target_name:
            parts.extend(["target", target_name])
            logger.info(f"Resolved target during normalization: {target_name}")

        explicit_methods = self._detect_explicit_methods(searchable)
        if explicit_methods:
            methods = explicit_methods
            logger.info("Using explicit HTTP methods from user text.")
        elif resolved_methods:
            methods = resolved_methods
            logger.info("Using methods resolved from domain alias.")
        else:
            methods = self._detect_natural_methods(searchable)
            logger.info("Using natural-language method detection.")

        tags = resolved_tags

        paths = self._extract_paths(raw)
        if not paths:
            paths = resolved_paths

        test_markers = self._detect_test_markers(searchable)
        limit = self._extract_limit(searchable)
        ignore_fields = self._extract_ignore_fields(searchable)

        for tag in tags:
            parts.extend(["module", tag])

        for method in methods:
            parts.append(method.value.upper())

        parts.extend(test_markers)
        parts.extend(paths)

        if limit is not None:
            parts.extend(["limit", str(limit)])

        for field_name in ignore_fields:
            parts.extend(["ignore", "field", field_name])

        for token in resolved_extra_tokens:
            parts.append(token)

        canonical = " ".join(parts)
        canonical = re.sub(r"\s+", " ", canonical).strip()

        logger.info(
            f"Normalization completed. target_name={target_name}, methods={len(methods)}, tags={len(tags)}, paths={len(paths)}, test_markers={len(test_markers)}, ignore_fields={len(ignore_fields)}, limit={limit}"
        )
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

    def _detect_explicit_methods(self, searchable: str) -> list[HttpMethod]:
        methods: list[HttpMethod] = []

        for method, pattern in self._EXPLICIT_METHOD_PATTERNS.items():
            if re.search(pattern, searchable, flags=re.IGNORECASE):
                methods.append(method)

        return list(dict.fromkeys(methods))

    def _detect_natural_methods(self, searchable: str) -> list[HttpMethod]:
        methods: list[HttpMethod] = []

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