from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from api_testing_agent.logging_config import bind_logger, get_logger


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
        self._logger = get_logger(__name__)

        self._logger.info(
            f"Initialized TargetCandidateService with enabled_target_count={len(self._enabled_target_names)}.",
            extra={"payload_source": "target_candidate_init"},
        )

    def find_candidates(self, text: str) -> list[CandidateScore]:
        logger = bind_logger(
            self._logger,
            payload_source="target_candidate_find",
        )
        logger.info("Starting candidate search.")

        lowered = text.lower().strip()
        if not lowered:
            logger.warning("Candidate search received empty text.")
            return []

        query_tokens = self._extract_query_tokens(lowered)
        logger.info(f"Extracted query_tokens_count={len(query_tokens)}")

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

        result = sorted(scored.values(), key=lambda item: (-item.score, item.name))
        logger.info(f"Candidate search completed. candidate_count={len(result)}")
        return result

    def choose_single_if_confident(self, candidates: list[CandidateScore]) -> str | None:
        """
        Rule cứng:
        - Chỉ auto-select khi có đúng 1 candidate
        - Có từ 2 candidate trở lên thì luôn hỏi user
        """
        logger = bind_logger(
            self._logger,
            payload_source="target_candidate_choose_single",
        )

        if len(candidates) == 1:
            logger.info(f"Auto-selected single confident candidate={candidates[0].name}")
            return candidates[0].name

        logger.info(f"No confident single candidate. candidate_count={len(candidates)}")
        return None

    def parse_user_selection(
        self,
        raw_selection: str,
        candidate_names: list[str],
    ) -> str | None:
        logger = bind_logger(
            self._logger,
            payload_source="target_candidate_parse_selection",
        )
        logger.info(f"Parsing user selection against candidate_count={len(candidate_names)}")

        cleaned = raw_selection.strip()
        if not cleaned:
            logger.warning("User selection is empty.")
            return None

        if cleaned.isdigit():
            index = int(cleaned)
            if 1 <= index <= len(candidate_names):
                selected = candidate_names[index - 1]
                logger.info(f"User selection resolved by index to target={selected}")
                return selected

        lowered = cleaned.lower()
        for name in candidate_names:
            if lowered == name.lower():
                logger.info(f"User selection resolved by exact name to target={name}")
                return name

            if self._normalize_space(lowered) == self._normalize_space(name.lower()):
                logger.info(f"User selection resolved by normalized-space match to target={name}")
                return name

            if self._normalize_compact(lowered) == self._normalize_compact(name.lower()):
                logger.info(f"User selection resolved by normalized-compact match to target={name}")
                return name

        logger.warning("User selection could not be resolved to any candidate.")
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