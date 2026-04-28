from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from api_testing_agent.core.intent_parser import RuleBasedIntentParser
from api_testing_agent.core.models import HttpMethod, TestType
from api_testing_agent.core.nl_interpreter import NaturalLanguageInterpreter
from api_testing_agent.core.scope_resolution_agent import ScopeResolutionAgent
from api_testing_agent.core.scope_resolution_models import ScopeResolutionDecision


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


class RequestUnderstandingService:
    """
    Flow mới:
    1. Nếu input đã là canonical command thì parse theo parser cũ để giữ backward compatibility.
    2. Nếu là natural language:
       - target đã được resolve từ trước
       - scope_resolution_agent quyết định:
         * all
         * specific
         * invalid_function
       - sau đó build plan một cách deterministic
    """

    DEFAULT_LIMIT = 50

    def __init__(
        self,
        *,
        parser: RuleBasedIntentParser | None = None,
        nl_interpreter: NaturalLanguageInterpreter | None = None,
        scope_resolution_agent: ScopeResolutionAgent | None = None,
    ) -> None:
        self._parser = parser or RuleBasedIntentParser()
        self._nl_interpreter = nl_interpreter or NaturalLanguageInterpreter()
        self._scope_resolution_agent = scope_resolution_agent

    def understand(
        self,
        raw_text: str,
        *,
        forced_target_name: str,
        operation_hints: list[dict],
    ) -> UnderstandingResult:
        cleaned = raw_text.strip()
        if not cleaned:
            raise UnderstandingError("Input text is empty.")

        if not forced_target_name:
            raise UnderstandingError("forced_target_name is required.")

        # 1. backward compatibility cho canonical command
        if self._looks_like_canonical_command(cleaned):
            canonical_command = self._inject_or_replace_target(cleaned, forced_target_name)
            parsed = self._parser.parse(canonical_command)
            plan = ResolvedPlan(
                target_name=parsed.target_name or forced_target_name,
                tags=list(parsed.tags),
                methods=list(parsed.methods),
                paths=list(parsed.paths),
                test_types=list(parsed.test_types),
                ignore_fields=list(parsed.ignore_fields),
                limit_endpoints=int(parsed.limit_endpoints),
            )
            return UnderstandingResult(
                original_text=cleaned,
                canonical_command=canonical_command,
                plan=plan,
            )

        if self._scope_resolution_agent is None:
            raise UnderstandingError(
                "ScopeResolutionAgent is required for natural-language understanding."
            )

        scope_decision = self._scope_resolution_agent.decide(
            raw_text=cleaned,
            forced_target_name=forced_target_name,
            operation_hints=operation_hints,
        )

        return self._build_result_from_scope_decision(
            raw_text=cleaned,
            forced_target_name=forced_target_name,
            operation_hints=operation_hints,
            scope_decision=scope_decision,
        )

    def _build_result_from_scope_decision(
        self,
        *,
        raw_text: str,
        forced_target_name: str,
        operation_hints: list[dict],
        scope_decision: ScopeResolutionDecision,
    ) -> UnderstandingResult:
        methods_override = self._extract_methods(raw_text)
        test_types = self._extract_test_types(raw_text)
        ignore_fields = self._extract_ignore_fields(raw_text)
        limit_endpoints = self._extract_limit(raw_text) or self.DEFAULT_LIMIT

        if scope_decision.scope_mode == "all":
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
            return UnderstandingResult(
                original_text=raw_text,
                canonical_command=canonical_command,
                plan=plan,
            )

        if scope_decision.scope_mode == "invalid_function":
            available_functions = self._build_available_functions(operation_hints)
            invalid_name = scope_decision.invalid_requested_function or "unknown function"
            raise InvalidFunctionRequestError(
                (
                    f"Không tìm thấy chức năng '{invalid_name}' trong target '{forced_target_name}'."
                ),
                available_functions=available_functions,
            )

        # specific
        matched_plan = self._build_specific_plan(
            forced_target_name=forced_target_name,
            operation_hints=operation_hints,
            scope_decision=scope_decision,
            methods_override=methods_override,
            test_types=test_types,
            ignore_fields=ignore_fields,
            limit_endpoints=limit_endpoints,
        )

        canonical_command = self._build_canonical_command(matched_plan)
        return UnderstandingResult(
            original_text=raw_text,
            canonical_command=canonical_command,
            plan=matched_plan,
        )

    def _build_specific_plan(
        self,
        *,
        forced_target_name: str,
        operation_hints: list[dict],
        scope_decision: ScopeResolutionDecision,
        methods_override: list[HttpMethod],
        test_types: list[TestType],
        ignore_fields: list[str],
        limit_endpoints: int,
    ) -> ResolvedPlan:
        operation_by_id = {
            item.get("operation_id"): item
            for item in operation_hints
            if item.get("operation_id")
        }

        matched_operation = None

        if scope_decision.matched_operation_id:
            matched_operation = operation_by_id.get(scope_decision.matched_operation_id)

        if matched_operation is None and scope_decision.matched_path and scope_decision.matched_method:
            for item in operation_hints:
                if (
                    item.get("path") == scope_decision.matched_path
                    and str(item.get("method", "")).upper() == str(scope_decision.matched_method).upper()
                ):
                    matched_operation = item
                    break

        if matched_operation is not None:
            method = self._coerce_http_method(matched_operation.get("method"))
            if method is None:
                raise UnderstandingError("Matched operation has invalid HTTP method.")

            return ResolvedPlan(
                target_name=forced_target_name,
                tags=[],
                methods=[method],
                paths=[matched_operation["path"]],
                test_types=test_types,
                ignore_fields=ignore_fields,
                limit_endpoints=limit_endpoints,
            )

        # Nếu không match được 1 operation cụ thể, cho phép match theo path hoặc tag
        if scope_decision.matched_path:
            methods = methods_override
            if scope_decision.matched_method:
                method = self._coerce_http_method(scope_decision.matched_method)
                if method is not None:
                    methods = [method]

            if not any(item.get("path") == scope_decision.matched_path for item in operation_hints):
                raise InvalidFunctionRequestError(
                    f"Không tìm thấy path '{scope_decision.matched_path}' trong target '{forced_target_name}'.",
                    available_functions=self._build_available_functions(operation_hints),
                )

            return ResolvedPlan(
                target_name=forced_target_name,
                tags=[],
                methods=methods,
                paths=[scope_decision.matched_path],
                test_types=test_types,
                ignore_fields=ignore_fields,
                limit_endpoints=limit_endpoints,
            )

        if scope_decision.matched_tag:
            tag_lower = scope_decision.matched_tag.lower()
            if not any(tag_lower in {str(tag).lower() for tag in item.get("tags", [])} for item in operation_hints):
                raise InvalidFunctionRequestError(
                    f"Không tìm thấy module/tag '{scope_decision.matched_tag}' trong target '{forced_target_name}'.",
                    available_functions=self._build_available_functions(operation_hints),
                )

            methods = methods_override
            if scope_decision.matched_method:
                method = self._coerce_http_method(scope_decision.matched_method)
                if method is not None:
                    methods = [method]

            return ResolvedPlan(
                target_name=forced_target_name,
                tags=[scope_decision.matched_tag],
                methods=methods,
                paths=[],
                test_types=test_types,
                ignore_fields=ignore_fields,
                limit_endpoints=limit_endpoints,
            )

        raise InvalidFunctionRequestError(
            f"Không xác định được chức năng cụ thể trong target '{forced_target_name}'.",
            available_functions=self._build_available_functions(operation_hints),
        )

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

        methods: list[HttpMethod] = []
        explicit_patterns = {
            HttpMethod.GET: r"\bget\b",
            HttpMethod.POST: r"\bpost\b",
            HttpMethod.PUT: r"\bput\b",
            HttpMethod.PATCH: r"\bpatch\b",
            HttpMethod.DELETE: r"\bdelete\b",
        }
        natural_patterns = {
            HttpMethod.GET: [r"\bxem\b", r"\bdoc\b", r"\blay\b"],
            HttpMethod.POST: [r"\btao\b", r"\bgui\b", r"\bcreate\b"],
            HttpMethod.PUT: [r"\bthay the\b"],
            HttpMethod.PATCH: [r"\bcap nhat\b", r"\bsua\b", r"\bupdate\b"],
            HttpMethod.DELETE: [r"\bxoa\b", r"\bremove\b"],
        }

        for method, pattern in explicit_patterns.items():
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                methods.append(method)

        if methods:
            return list(dict.fromkeys(methods))

        for method, patterns in natural_patterns.items():
            for pattern in patterns:
                if re.search(pattern, lowered, flags=re.IGNORECASE):
                    methods.append(method)
                    break

        return list(dict.fromkeys(methods))

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

        if re.search(
            r"\bunauthorized\b|\bforbidden\b|\b401\b|\b403\b|\bkhong co quyen\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            tokens.append(TestType.UNAUTHORIZED)

        if re.search(
            r"\bnot found\b|\b404\b|\bkhong ton tai\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            tokens.append(TestType.NOT_FOUND)

        if re.search(
            r"\bmissing\b|\bomit\b|\bwithout\b|\bthieu\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            tokens.append(TestType.MISSING_REQUIRED)

        if re.search(
            r"\binvalid\b|\bwrong type\b|\bwrong format\b|\bsai kieu\b|\bsai dinh dang\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            tokens.append(TestType.INVALID_TYPE_OR_FORMAT)

        if tokens:
            return list(dict.fromkeys(tokens))

        # mặc định nếu user không nói gì thêm: chạy cả positive lẫn nhóm negative cơ bản
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

        return list(dict.fromkeys(fields))

    def _coerce_http_method(self, raw_value: Any) -> HttpMethod | None:
        if raw_value is None:
            return None

        text = str(raw_value).strip().upper()
        for method in HttpMethod:
            if method.value.upper() == text or method.name.upper() == text:
                return method

        return None

    def _inject_or_replace_target(self, canonical_command: str, forced_target_name: str) -> str:
        text = canonical_command.strip()

        if re.search(r"\btarget\s+[a-zA-Z0-9_-]+\b", text, flags=re.IGNORECASE):
            return re.sub(
                r"\btarget\s+[a-zA-Z0-9_-]+\b",
                f"target {forced_target_name}",
                text,
                flags=re.IGNORECASE,
                count=1,
            )

        if text.lower().startswith("test "):
            return f"test target {forced_target_name} {text[5:].strip()}"

        return f"test target {forced_target_name} {text}"

    def _looks_like_canonical_command(self, text: str) -> bool:
        return bool(
            re.match(
                r"^\s*test\s+target\s+[a-zA-Z0-9_-]+",
                text,
                flags=re.IGNORECASE,
            )
        )