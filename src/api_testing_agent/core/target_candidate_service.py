from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


@dataclass(frozen=True)
class CandidateScore:
    name: str
    score: float
    reason: str


class TargetCandidateService:
    _STOPWORDS = {
        "hãy",
        "hay",
        "test",
        "cho",
        "toi",
        "tôi",
        "cua",
        "của",
        "chuc",
        "chức",
        "nang",
        "năng",
        "api",
        "module",
        "target",
        "giup",
        "giúp",
    }

    def __init__(self, enabled_target_names: Iterable[str]) -> None:
        self._enabled_target_names = list(dict.fromkeys(enabled_target_names))

    def find_candidates(self, text: str) -> list[CandidateScore]:
        lowered = text.lower().strip()
        if not lowered:
            return []

        query_tokens = self._extract_query_tokens(lowered)
        scored: dict[str, CandidateScore] = {}

        for target_name in self._enabled_target_names:
            target_lower = target_name.lower()
            target_space = self._normalize_space(target_lower)
            target_compact = self._normalize_compact(target_lower)

            best_score = 0.0
            best_reason = ""

            for token in query_tokens:
                token_space = self._normalize_space(token)
                token_compact = self._normalize_compact(token)

                score, reason = self._score_token_against_target(
                    token=token,
                    token_space=token_space,
                    token_compact=token_compact,
                    target_name=target_name,
                    target_lower=target_lower,
                    target_space=target_space,
                    target_compact=target_compact,
                )

                if score > best_score:
                    best_score = score
                    best_reason = reason

            if best_score > 0:
                scored[target_name] = CandidateScore(
                    name=target_name,
                    score=best_score,
                    reason=best_reason,
                )

        return sorted(scored.values(), key=lambda item: (-item.score, item.name))

    def choose_single_if_confident(self, candidates: list[CandidateScore]) -> str | None:
        """
        Rule cứng:
        - Chỉ auto-select khi có đúng 1 candidate
        - Có từ 2 candidate trở lên thì luôn hỏi user
        """
        if len(candidates) == 1:
            return candidates[0].name
        return None

    def parse_user_selection(
        self,
        raw_selection: str,
        candidate_names: list[str],
    ) -> str | None:
        cleaned = raw_selection.strip()
        if not cleaned:
            return None

        if cleaned.isdigit():
            index = int(cleaned)
            if 1 <= index <= len(candidate_names):
                return candidate_names[index - 1]

        lowered = cleaned.lower()
        for name in candidate_names:
            if lowered == name.lower():
                return name

            if self._normalize_space(lowered) == self._normalize_space(name.lower()):
                return name

            if self._normalize_compact(lowered) == self._normalize_compact(name.lower()):
                return name

        return None

    def _extract_query_tokens(self, lowered_text: str) -> list[str]:
        raw_tokens = re.findall(r"[a-zA-Z0-9_-]+", lowered_text)
        filtered = [
            token
            for token in raw_tokens
            if len(token) >= 3 and token not in self._STOPWORDS
        ]
        return list(dict.fromkeys(filtered))

    def _score_token_against_target(
        self,
        *,
        token: str,
        token_space: str,
        token_compact: str,
        target_name: str,
        target_lower: str,
        target_space: str,
        target_compact: str,
    ) -> tuple[float, str]:
        if token == target_lower:
            return 100.0, "Exact target name match"

        if token_space == target_space:
            return 98.0, "Normalized exact match"

        if token_compact == target_compact:
            return 96.0, "Compact exact match"

        if target_lower.startswith(token):
            return 88.0, "Prefix match on target name"

        if target_space.startswith(token_space):
            return 86.0, "Prefix match on normalized target name"

        if target_compact.startswith(token_compact):
            return 84.0, "Prefix match on compact target name"

        if token_compact in target_compact:
            similarity = SequenceMatcher(None, token_compact, target_compact).ratio()
            return 60.0 + similarity * 10.0, "Substring / partial compact match"

        similarity = SequenceMatcher(None, token_compact, target_compact).ratio()
        if similarity >= 0.72:
            return 50.0 + similarity * 10.0, "Fuzzy similarity match"

        return 0.0, ""

    def _normalize_space(self, value: str) -> str:
        value = value.lower().replace("_", " ").replace("-", " ")
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _normalize_compact(self, value: str) -> str:
        return value.lower().replace("_", "").replace("-", "").replace(" ", "").strip()