from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType
from api_testing_agent.core.scope_resolution_agent import ScopeResolutionAgent
from api_testing_agent.core.scope_resolution_models import ScopeResolutionDecision
from api_testing_agent.logging_config import bind_logger, get_logger


class UnderstandingError(ValueError):
    pass


class InvalidFunctionRequestError(UnderstandingError):
    def __init__(self, message: str, available_functions: list[str]) -> None:
        super().__init__(message)
        self.available_functions = available_functions


@dataclass(frozen=True)
class ResolvedPlan:
    target_name: str
    tags: list[str]
    methods: list[HttpMethod]
    paths: list[str]
    test_types: list[TestType]
    ignore_fields: list[str]
    limit_endpoints: int


@dataclass(frozen=True)
class UnderstandingResult:
    original_text: str
    canonical_command: str
    plan: ResolvedPlan
    explanation: str


class RequestUnderstandingService:
    DEFAULT_LIMIT = 50

    def __init__(
        self,
        *,
        parser: RuleBasedIntentParser | None = None,
        scope_resolution_agent: ScopeResolutionAgent | None = None,
    ) -> None:
        self._parser = parser or RuleBasedIntentParser()
        self._scope_resolution_agent = scope_resolution_agent
        self._logger = get_logger(__name__)

        self._logger.info(
            "Initialized RequestUnderstandingService.",
            extra={"payload_source": "understanding_init"},
        )

    def understand(
        self,
        raw_text: str,
        *,
        forced_target_name: str,
        operation_hints: list[dict],
    ) -> UnderstandingResult:
        logger = bind_logger(
            self._logger,
            target_name=forced_target_name or "-",
            payload_source="understanding",
        )
        logger.info(
            f"Starting understand(). operation_hints_count={len(operation_hints)}"
        )

        cleaned = raw_text.strip()
        if not cleaned:
            logger.warning("Understanding failed because input text is empty.")
            raise UnderstandingError("Input text is empty.")

        if not forced_target_name:
            logger.warning("Understanding failed because forced_target_name is missing.")
            raise UnderstandingError("forced_target_name is required.")

        if self._looks_like_canonical_command(cleaned):
            logger.info("Detected canonical command input. Parsing directly.")
            parsed = self._parser.parse(cleaned)
            plan = ResolvedPlan(
                target_name=parsed.target_name or forced_target_name,
                tags=list(parsed.tags),
                methods=list(parsed.methods),
                paths=list(parsed.paths),
                test_types=list(parsed.test_types),
                ignore_fields=list(parsed.ignore_fields),
                limit_endpoints=int(parsed.limit_endpoints),
            )
            logger.info(
                f"Canonical command parsed successfully. methods={len(plan.methods)}, paths={len(plan.paths)}, test_types={len(plan.test_types)}"
            )
            return UnderstandingResult(
                original_text=cleaned,
                canonical_command=cleaned,
                plan=plan,
                explanation="Yêu cầu đã ở dạng canonical command, giữ nguyên và parse trực tiếp.",
            )

        if self._scope_resolution_agent is None:
            logger.error("ScopeResolutionAgent is required but not configured.")
            raise UnderstandingError("ScopeResolutionAgent is required.")

        logger.info("Invoking ScopeResolutionAgent.")
        decision = self._scope_resolution_agent.decide(
            raw_text=cleaned,
            target_name=forced_target_name,
            operation_hints=operation_hints,
        )
        logger.info(f"Scope resolution completed. scope_mode={decision.scope_mode}")

        return self._build_result_from_scope_decision(
            raw_text=cleaned,
            forced_target_name=forced_target_name,
            operation_hints=operation_hints,
            decision=decision,
        )

    def _build_result_from_scope_decision(
        self,
        *,
        raw_text: str,
        forced_target_name: str,
        operation_hints: list[dict],
        decision: ScopeResolutionDecision,
    ) -> UnderstandingResult:
        logger = bind_logger(
            self._logger,
            target_name=forced_target_name,
            payload_source="understanding_scope_decision",
        )
        logger.info(f"Building UnderstandingResult from scope_mode={decision.scope_mode}")

        methods_override = self._extract_methods(raw_text)
        test_types = self._extract_test_types(raw_text)
        ignore_fields = self._extract_ignore_fields(raw_text)
        limit_endpoints = self._extract_limit(raw_text) or self.DEFAULT_LIMIT

        logger.info(
            f"Extracted constraints. methods_override={len(methods_override)}, test_types={len(test_types)}, ignore_fields={len(ignore_fields)}, limit_endpoints={limit_endpoints}"
        )

        if decision.scope_mode == "all":
            plan = ResolvedPlan(
                target_name=forced_target_name,
                tags=[],
                methods=methods_override,
                paths=[],
                test_types=test_types,
                ignore_fields=ignore_fields,
                limit_endpoints=limit_endpoints,
            )
            canonical_command = self._build_canonical_command(plan)
            logger.info("Resolved scope_mode=all successfully.")
            return UnderstandingResult(
                original_text=raw_text,
                canonical_command=canonical_command,
                plan=plan,
                explanation=(
                    f"Đã xác định target là '{forced_target_name}'. "
                    "User không chỉ rõ chức năng cụ thể nên hệ thống sẽ test toàn bộ chức năng của target."
                ),
            )

        if decision.scope_mode == "invalid_function":
            available_functions = self._build_available_functions(operation_hints)
            invalid_name = decision.invalid_requested_function or "unknown function"
            logger.warning(
                f"Resolved scope_mode=invalid_function. invalid_requested_function={invalid_name}"
            )
            raise InvalidFunctionRequestError(
                f"Không tìm thấy chức năng '{invalid_name}' trong target '{forced_target_name}'.",
                available_functions=available_functions,
            )

        matched = self._resolve_specific_matches(
            operation_hints=operation_hints,
            matched_operation_ids=decision.matched_operation_ids,
            matched_paths=decision.matched_paths,
            matched_tags=decision.matched_tags,
        )

        logger.info(f"Resolved specific matches count={len(matched)}")

        if not matched:
            logger.warning("No specific matches resolved from scope decision.")
            raise InvalidFunctionRequestError(
                f"Không xác định được chức năng cụ thể trong target '{forced_target_name}'.",
                available_functions=self._build_available_functions(operation_hints),
            )

        plan = ResolvedPlan(
            target_name=forced_target_name,
            tags=[],
            methods=self._resolve_methods_for_specific(
                matched=matched,
                methods_override=methods_override,
            ),
            paths=self._resolve_paths_for_specific(matched),
            test_types=test_types,
            ignore_fields=ignore_fields,
            limit_endpoints=limit_endpoints,
        )
        canonical_command = self._build_canonical_command(plan)

        matched_labels = [f"{item.get('method', '')} {item.get('path', '')}" for item in matched]
        logger.info(
            f"Built specific-scope understanding successfully. matched_labels={matched_labels}"
        )
        return UnderstandingResult(
            original_text=raw_text,
            canonical_command=canonical_command,
            plan=plan,
            explanation=(
                f"Đã xác định target là '{forced_target_name}' và đã match đúng chức năng cụ thể: "
                f"{', '.join(matched_labels)}."
            ),
        )

    def _resolve_specific_matches(
        self,
        *,
        operation_hints: list[dict],
        matched_operation_ids: list[str],
        matched_paths: list[str],
        matched_tags: list[str],
    ) -> list[dict]:
        matched_ids = {item for item in matched_operation_ids if item}
        matched_paths_set = {item for item in matched_paths if item}
        matched_tags_set = {item.lower() for item in matched_tags if item}

        resolved: list[dict] = []
        for item in operation_hints:
            op_id = str(item.get("operation_id", ""))
            path = str(item.get("path", ""))
            tags = {str(tag).lower() for tag in item.get("tags", [])}

            if matched_ids and op_id in matched_ids:
                resolved.append(item)
                continue
            if matched_paths_set and path in matched_paths_set:
                resolved.append(item)
                continue
            if matched_tags_set and tags.intersection(matched_tags_set):
                resolved.append(item)
                continue

        return self._unique_operations(resolved)

    def _resolve_methods_for_specific(
        self,
        *,
        matched: list[dict],
        methods_override: list[HttpMethod],
    ) -> list[HttpMethod]:
        if methods_override:
            return methods_override

        methods: list[HttpMethod] = []
        for item in matched:
            method = self._coerce_http_method(item.get("method"))
            if method is not None:
                methods.append(method)

        unique: list[HttpMethod] = []
        seen: set[str] = set()
        for method in methods:
            if method.value not in seen:
                seen.add(method.value)
                unique.append(method)
        return unique

    def _resolve_paths_for_specific(self, matched: list[dict]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()

        for item in matched:
            path = str(item.get("path", ""))
            if path and path not in seen:
                seen.add(path)
                paths.append(path)

        return paths

    def _build_available_functions(self, operation_hints: list[dict]) -> list[str]:
        lines: list[str] = []
        for item in operation_hints:
            method = str(item.get("method", "")).upper()
            path = str(item.get("path", ""))
            summary = str(item.get("summary", "")).strip()
            tags = item.get("tags", []) or []

            extra = ""
            if summary:
                extra = f" — {summary}"
            elif tags:
                extra = f" — tags: {', '.join(tags)}"

            lines.append(f"{method} {path}{extra}")

        return lines

    def _build_canonical_command(self, plan: ResolvedPlan) -> str:
        parts: list[str] = ["test", "target", plan.target_name]

        for tag in plan.tags:
            parts.extend(["module", tag])

        for path in plan.paths:
            parts.append(path)

        for method in plan.methods:
            parts.append(method.value.upper())

        parts.extend(self._build_test_type_tokens(plan.test_types))

        if plan.limit_endpoints != self.DEFAULT_LIMIT:
            parts.extend(["limit", str(plan.limit_endpoints)])

        for field_name in plan.ignore_fields:
            parts.extend(["ignore", "field", field_name])

        return " ".join(parts).strip()

    def _build_test_type_tokens(self, test_types: list[TestType]) -> list[str]:
        negative_types = self._negative_test_types()

        if self._same_test_type_set(test_types, negative_types):
            return ["negative"]

        if self._same_test_type_set(test_types, [TestType.POSITIVE]):
            return ["positive"]

        tokens: list[str] = []
        if TestType.POSITIVE in test_types:
            tokens.append("positive")
        if TestType.UNAUTHORIZED in test_types:
            tokens.append("unauthorized")
        if TestType.NOT_FOUND in test_types:
            tokens.append("not_found")
        if TestType.MISSING_REQUIRED in test_types:
            tokens.append("missing")
        if TestType.INVALID_TYPE_OR_FORMAT in test_types:
            tokens.append("invalid")
        return tokens

    def _negative_test_types(self) -> list[TestType]:
        return [
            TestType.MISSING_REQUIRED,
            TestType.INVALID_TYPE_OR_FORMAT,
            TestType.UNAUTHORIZED,
            TestType.NOT_FOUND,
        ]

    def _same_test_type_set(self, left: list[TestType], right: list[TestType]) -> bool:
        return {item.value for item in left} == {item.value for item in right}

    def _extract_methods(self, raw_text: str) -> list[HttpMethod]:
        lowered = raw_text.lower()
        explicit_patterns = {
            HttpMethod.GET: r"\bget\b",
            HttpMethod.POST: r"\bpost\b",
            HttpMethod.PUT: r"\bput\b",
            HttpMethod.PATCH: r"\bpatch\b",
            HttpMethod.DELETE: r"\bdelete\b",
        }

        methods: list[HttpMethod] = []
        for method, pattern in explicit_patterns.items():
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                methods.append(method)

        unique: list[HttpMethod] = []
        seen: set[str] = set()
        for method in methods:
            if method.value not in seen:
                seen.add(method.value)
                unique.append(method)
        return unique

    def _extract_test_types(self, raw_text: str) -> list[TestType]:
        lowered = raw_text.lower()

        if re.search(
            r"\bnegative\b|\bnegative case\b|\bnegative test\b|\btest am\b|\btest loi\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            return self._negative_test_types()

        tokens: list[TestType] = []

        if re.search(r"\bpositive\b|\bhop le\b|\bvalid\b", lowered, flags=re.IGNORECASE):
            tokens.append(TestType.POSITIVE)
        if re.search(r"\bunauthorized\b|\bforbidden\b|\b401\b|\b403\b", lowered, flags=re.IGNORECASE):
            tokens.append(TestType.UNAUTHORIZED)
        if re.search(r"\bnot found\b|\b404\b", lowered, flags=re.IGNORECASE):
            tokens.append(TestType.NOT_FOUND)
        if re.search(r"\bmissing\b|\bomit\b|\bwithout\b|\bthieu\b", lowered, flags=re.IGNORECASE):
            tokens.append(TestType.MISSING_REQUIRED)
        if re.search(r"\binvalid\b|\bwrong type\b|\bwrong format\b", lowered, flags=re.IGNORECASE):
            tokens.append(TestType.INVALID_TYPE_OR_FORMAT)

        if tokens:
            seen: set[str] = set()
            unique: list[TestType] = []
            for item in tokens:
                if item.value not in seen:
                    seen.add(item.value)
                    unique.append(item)
            return unique

        return [
            TestType.POSITIVE,
            TestType.MISSING_REQUIRED,
            TestType.INVALID_TYPE_OR_FORMAT,
            TestType.UNAUTHORIZED,
            TestType.NOT_FOUND,
        ]

    def _extract_limit(self, raw_text: str) -> int | None:
        patterns = [
            r"\blimit\s*[:=]?\s*(\d+)\b",
            r"\b(?:khoang|tam|toi da)\s*(\d+)\s*(?:endpoint|api|case)?\b",
            r"\blay\s*(\d+)\s*(?:endpoint|api|case)\b",
            r"\b(\d+)\s*(?:endpoint|api|case)\s*(?:thoi|truoc)?\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, raw_text, flags=re.IGNORECASE)
            if match:
                return max(1, min(int(match.group(1)), 200))
        return None

    def _extract_ignore_fields(self, raw_text: str) -> list[str]:
        patterns = [
            r"\bignore field ([a-zA-Z0-9_-]+)\b",
            r"\bskip field ([a-zA-Z0-9_-]+)\b",
            r"\bbo qua field ([a-zA-Z0-9_-]+)\b",
            r"\bbo qua ([a-zA-Z0-9_-]+)\b",
        ]

        fields: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, raw_text, flags=re.IGNORECASE):
                fields.append(match.group(1))

        unique: list[str] = []
        seen: set[str] = set()
        for field in fields:
            if field not in seen:
                seen.add(field)
                unique.append(field)
        return unique

    def _coerce_http_method(self, raw_value: Any) -> HttpMethod | None:
        if raw_value is None:
            return None

        text = str(raw_value).strip().upper()
        for method in HttpMethod:
            if method.value.upper() == text or method.name.upper() == text:
                return method
        return None

    def _unique_operations(self, operations: list[dict]) -> list[dict]:
        unique: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        for item in operations:
            key = (
                str(item.get("operation_id", "")),
                str(item.get("path", "")),
                str(item.get("method", "")),
            )
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _looks_like_canonical_command(self, text: str) -> bool:
        return bool(
            re.match(r"^\s*test\s+target\s+[a-zA-Z0-9_-]+", text, flags=re.IGNORECASE)
        )