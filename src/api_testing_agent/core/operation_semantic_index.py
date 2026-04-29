from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class OperationMatch:
    operation: dict
    matched_by: str
    matched_term: str


class OperationSemanticIndex:
    """
    Index semantic nhẹ, deterministic, để match feedback/user text
    với operation thật của target.

    Nguồn alias được sinh từ:
    - path
    - path segments
    - tags
    - summary
    - operation_id
    """

    _STOPWORDS = {
        "test",
        "chuc",
        "chức",
        "nang",
        "năng",
        "function",
        "api",
        "endpoint",
        "operation",
        "post",
        "get",
        "put",
        "patch",
        "delete",
        "them",
        "thêm",
        "bo",
        "bỏ",
        "di",
        "đi",
        "chi",
        "chỉ",
        "lai",
        "lại",
        "toan",
        "toàn",
        "bo",
        "bộ",
        "scope",
    }

    def __init__(self, operation_contexts: list[dict]) -> None:
        self._operation_contexts = operation_contexts
        self._entries = [self._build_entry(item) for item in operation_contexts]

    def find_matches(self, raw_text: str) -> tuple[list[OperationMatch], list[str]]:
        """
        Trả:
        - list matched operations
        - list terms không match được
        """
        normalized_text = self._normalize(raw_text)

        # ưu tiên path literal trước
        literal_path_matches = self._match_paths_from_text(normalized_text)

        extracted_terms = self._extract_candidate_terms(normalized_text)

        matches: list[OperationMatch] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for match in literal_path_matches:
            key = self._key_for_operation(match.operation)
            if key not in seen_keys:
                seen_keys.add(key)
                matches.append(match)

        unmatched_terms: list[str] = []

        for term in extracted_terms:
            found = self._match_term(term)
            if not found:
                unmatched_terms.append(term)
                continue

            for item in found:
                key = self._key_for_operation(item.operation)
                if key not in seen_keys:
                    seen_keys.add(key)
                    matches.append(item)

        return matches, unmatched_terms

    def describe_available_functions(self) -> list[str]:
        lines: list[str] = []
        for op in self._operation_contexts:
            method = str(op.get("method", "")).upper()
            path = str(op.get("path", ""))
            summary = str(op.get("summary", "")).strip()
            tags = op.get("tags", []) or []

            extra = ""
            if summary:
                extra = f" — {summary}"
            elif tags:
                extra = f" — tags: {', '.join(tags)}"

            lines.append(f"{method} {path}{extra}")
        return lines

    def _build_entry(self, operation: dict) -> dict:
        path = str(operation.get("path", ""))
        method = str(operation.get("method", "")).upper()
        summary = str(operation.get("summary", ""))
        operation_id = str(operation.get("operation_id", ""))
        tags = [str(tag) for tag in operation.get("tags", [])]

        aliases: set[str] = set()

        # path nguyên bản
        if path:
            aliases.add(self._normalize(path))

        # path segments
        for segment in re.findall(r"[a-zA-Z0-9_/-]+", path):
            seg = segment.strip("/")
            if seg:
                aliases.add(self._normalize(seg))
                aliases.add(self._normalize(seg.replace("_", " ")))
                aliases.add(self._normalize(seg.replace("-", " ")))

        # operation_id tokens
        for token in self._tokenize(operation_id):
            aliases.add(token)

        # tags
        for tag in tags:
            aliases.add(self._normalize(tag))
            for token in self._tokenize(tag):
                aliases.add(token)

        # summary tokens / phrases
        normalized_summary = self._normalize(summary)
        if normalized_summary:
            aliases.add(normalized_summary)

        for token in self._tokenize(summary):
            aliases.add(token)

        # alias tăng cường từ path rất phổ biến
        # nhưng vẫn sinh từ path chứ không hardcode theo project riêng
        aliases |= self._derive_generic_aliases_from_path(path)

        return {
            "operation": operation,
            "path": self._normalize(path),
            "method": method,
            "aliases": {item for item in aliases if item},
        }

    def _derive_generic_aliases_from_path(self, path: str) -> set[str]:
        """
        Alias sinh ra một cách tương đối tổng quát từ path.
        Ví dụ:
        - /FB -> fb, facebook
        - /YT -> yt, youtube
        - /img -> img, image
        - /X/content -> x, content, x content
        """
        normalized_path = self._normalize(path)
        segments = [seg for seg in normalized_path.split("/") if seg]
        aliases: set[str] = set()

        for seg in segments:
            aliases.add(seg)

            if seg == "fb":
                aliases.add("facebook")
            elif seg == "yt":
                aliases.add("youtube")
            elif seg == "img":
                aliases.add("image")
                aliases.add("sinh anh")
                aliases.add("sinh anh")
            elif seg == "x":
                aliases.add("twitter")
                aliases.add("tweet")

        if len(segments) >= 2:
            aliases.add(" ".join(segments))

        return aliases

    def _match_paths_from_text(self, normalized_text: str) -> list[OperationMatch]:
        matches: list[OperationMatch] = []
        raw_paths = re.findall(r"/[a-zA-Z0-9/_-]+", normalized_text)

        for raw_path in raw_paths:
            norm_path = self._normalize(raw_path)
            for entry in self._entries:
                if entry["path"] == norm_path:
                    matches.append(
                        OperationMatch(
                            operation=entry["operation"],
                            matched_by="path",
                            matched_term=raw_path,
                        )
                    )
        return matches

    def _extract_candidate_terms(self, normalized_text: str) -> list[str]:
        """
        Tách các terms có ý nghĩa khỏi feedback.

        Hỗ trợ:
        - nối bằng "và", "voi", ","
        - phrases nhiều từ
        """
        cleaned = normalized_text

        # bỏ những phrase command phổ biến để còn lại phần target scope
        command_phrases = [
            "chi test",
            "chi",
            "them chuc nang",
            "them",
            "bo",
            "bo di",
            "loai",
            "loai bo",
            "test lai toan bo",
            "quay lai toan bo",
            "test toan bo",
            "toan bo",
        ]
        for phrase in command_phrases:
            cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned)

        # split theo liên từ
        parts = re.split(r"\bva\b|,|;", cleaned)

        terms: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # giữ nguyên phrase nếu nó có ý nghĩa
            if len(part) >= 2:
                terms.append(part)

            # đồng thời tách token
            for token in self._tokenize(part):
                if token not in terms:
                    terms.append(token)

        # unique preserve order
        unique_terms: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term and term not in seen:
                seen.add(term)
                unique_terms.append(term)

        return unique_terms

    def _match_term(self, term: str) -> list[OperationMatch]:
        matches: list[OperationMatch] = []

        for entry in self._entries:
            aliases: set[str] = entry["aliases"]

            # exact alias match
            if term in aliases:
                matches.append(
                    OperationMatch(
                        operation=entry["operation"],
                        matched_by="alias",
                        matched_term=term,
                    )
                )
                continue

            # contains match hai chiều để bắt được "youtube", "yt"
            for alias in aliases:
                if term == alias:
                    matches.append(
                        OperationMatch(
                            operation=entry["operation"],
                            matched_by="alias",
                            matched_term=term,
                        )
                    )
                    break

                if len(term) >= 2 and len(alias) >= 2:
                    if term in alias or alias in term:
                        matches.append(
                            OperationMatch(
                                operation=entry["operation"],
                                matched_by="fuzzy_alias",
                                matched_term=term,
                            )
                        )
                        break

        return matches

    def _key_for_operation(self, operation: dict) -> tuple[str, str, str]:
        return (
            str(operation.get("operation_id", "")),
            str(operation.get("path", "")),
            str(operation.get("method", "")),
        )

    def _tokenize(self, value: str) -> list[str]:
        normalized = self._normalize(value)
        raw_tokens = re.findall(r"[a-zA-Z0-9_/-]+", normalized)

        tokens: list[str] = []
        for token in raw_tokens:
            token = token.strip()
            if not token:
                continue
            if token in self._STOPWORDS:
                continue
            if len(token) < 2:
                continue
            tokens.append(token)

            token_space = token.replace("_", " ").replace("-", " ")
            token_space = re.sub(r"\s+", " ", token_space).strip()
            if token_space and token_space != token:
                tokens.append(token_space)

        # unique preserve order
        unique: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token not in seen:
                seen.add(token)
                unique.append(token)
        return unique

    def _normalize(self, value: str) -> str:
        value = value.strip().lower()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.replace("đ", "d")
        value = re.sub(r"\s+", " ", value)
        return value.strip()