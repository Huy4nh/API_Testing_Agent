from __future__ import annotations

import re
import unicodedata
from typing import Literal

SupportedLanguage = Literal["vi", "en"]


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    no_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return no_marks.replace("đ", "d").replace("Đ", "D")


def normalize_ascii(text: str) -> str:
    return normalize_text(strip_accents(text))


def coerce_supported_language(
    value: str | None,
    fallback: SupportedLanguage = "vi",
) -> SupportedLanguage:
    if value == "vi":
        return "vi"
    if value == "en":
        return "en"
    return fallback


def is_ambiguous_short_control_input(text: str) -> bool:
    cleaned = normalize_ascii(text)

    if not cleaned:
        return True

    if cleaned.isdigit():
        return True

    ambiguous_tokens = {
        "1",
        "2",
        "3",
        "local",
        "staging",
        "production",
        "prod",
        "stage",
        "yes",
        "ok",
        "okay",
        "done",
        "save",
        "cancel",
        "approve",
        "revise",
        "help",
        "status",
    }
    return cleaned in ambiguous_tokens


def detect_user_language(
    text: str,
    *,
    fallback: SupportedLanguage | None = None,
) -> SupportedLanguage | None:
    cleaned = normalize_text(text)
    if not cleaned:
        return fallback

    if re.search(r"[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", cleaned):
        return "vi"

    ascii_text = normalize_ascii(cleaned)
    tokens = set(re.findall(r"[a-zA-Z]+", ascii_text))

    vi_markers = {
        "toi",
        "ban",
        "hay",
        "thu",
        "chuc",
        "nang",
        "moi",
        "truong",
        "hien",
        "tai",
        "giai",
        "thich",
        "tom",
        "tat",
        "dang",
        "co",
        "nhung",
        "gi",
        "luu",
        "huy",
        "them",
        "vao",
    }
    en_markers = {
        "please",
        "test",
        "image",
        "function",
        "what",
        "available",
        "explain",
        "summary",
        "review",
        "scope",
        "report",
    }

    vi_score = sum(1 for token in tokens if token in vi_markers)
    en_score = sum(1 for token in tokens if token in en_markers)

    if vi_score > en_score:
        return "vi"
    if en_score > vi_score:
        return "en"

    if any(phrase in ascii_text for phrase in ["chuc nang", "moi truong", "hien tai", "dang co"]):
        return "vi"
    if any(phrase in ascii_text for phrase in ["what functions", "what operations", "image generation", "please test"]):
        return "en"

    return fallback


def choose_workflow_language(
    new_text: str,
    current_language: str = "vi",
) -> SupportedLanguage:
    current = coerce_supported_language(current_language, fallback="vi")

    if is_ambiguous_short_control_input(new_text):
        return current

    detected = detect_user_language(new_text, fallback=current)
    return detected or current