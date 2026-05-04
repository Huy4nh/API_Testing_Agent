from __future__ import annotations

import re
from typing import Iterable


def format_operation_description(
    *,
    method: str,
    path: str,
    operation_id: str | None = None,
    summary: str | None = None,
    tags: Iterable[str] | None = None,
) -> str:
    """
    Convert raw OpenAPI-ish metadata into a more natural English description.

    Examples:
    - "Fb Get Content" -> "Retrieve content from Facebook."
    - "Yt Get Content" -> "Retrieve content from YouTube."
    - "X Post" -> "Publish a post to X."
    - "Image Generate" -> "Generate an image from the provided content."
    """
    normalized_method = (method or "").strip().upper()
    normalized_path = (path or "").strip()
    normalized_operation_id = (operation_id or "").strip()
    normalized_summary = (summary or "").strip()
    normalized_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]

    tokens = _collect_tokens(
        method=normalized_method,
        path=normalized_path,
        operation_id=normalized_operation_id,
        summary=normalized_summary,
        tags=normalized_tags,
    )
    entity = _detect_entity(tokens=tokens, path=normalized_path, operation_id=normalized_operation_id)

    # Prefer natural, domain-specific descriptions first.
    if entity == "image":
        if "generate" in tokens or normalized_path.lower() == "/img":
            return "Generate an image from the provided content."

    if entity == "facebook" and "content" in tokens:
        return "Retrieve content from Facebook."

    if entity == "youtube" and "content" in tokens:
        return "Retrieve content from YouTube."

    if entity == "x" and "post" in tokens:
        return "Publish a post to X."

    if entity == "x" and "content" in tokens:
        return "Retrieve content from X."

    # If summary is already reasonably natural, keep it with minimal cleanup.
    if normalized_summary and _looks_like_natural_sentence(normalized_summary):
        return _normalize_sentence(normalized_summary)

    # If summary is raw/short, try to rewrite it.
    if normalized_summary:
        rewritten = _rewrite_raw_summary(normalized_summary, entity=entity, method=normalized_method)
        if rewritten:
            return rewritten

    # Generic fallbacks.
    if entity is not None and "content" in tokens:
        return f"Retrieve content from {entity}."

    if entity is not None and "post" in tokens:
        return f"Publish content to {entity}."

    if entity is not None and normalized_method == "POST":
        return f"Submit a POST request for {entity.lower()} processing."

    if normalized_method and normalized_path:
        return f"Call {normalized_method} {normalized_path}."

    return "No short description is available."


def _collect_tokens(
    *,
    method: str,
    path: str,
    operation_id: str,
    summary: str,
    tags: list[str],
) -> set[str]:
    tokens: set[str] = set()

    for text in [method, path, operation_id, summary, *tags]:
        for token in _split_tokens(text):
            tokens.add(token)

    return tokens


def _split_tokens(text: str) -> list[str]:
    if not text:
        return []

    text = text.strip()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.replace("/", " ").replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()

    raw_tokens = text.split(" ")
    return [_normalize_token(token) for token in raw_tokens if token.strip()]


def _normalize_token(token: str) -> str:
    mapping = {
        "fb": "facebook",
        "yt": "youtube",
        "img": "image",
        "imgs": "image",
        "x": "x",
        "posts": "post",
        "contents": "content",
        "generate": "generate",
        "generator": "generate",
        "get": "get",
        "fetch": "get",
        "create": "post",
        "publish": "post",
    }
    return mapping.get(token, token)


def _detect_entity(
    *,
    tokens: set[str],
    path: str,
    operation_id: str,
) -> str | None:
    path_lower = path.lower()
    op_lower = operation_id.lower()

    if "image" in tokens or path_lower == "/img" or "img" in op_lower:
        return "Image"

    if "facebook" in tokens or "/fb" in path_lower or "fb_" in op_lower:
        return "Facebook"

    if "youtube" in tokens or "/yt" in path_lower or "yt_" in op_lower:
        return "YouTube"

    # Detect X after more specific entities.
    if "x" in tokens or "/x" in path_lower or "x_" in op_lower:
        return "X"

    return None


def _looks_like_natural_sentence(summary: str) -> bool:
    cleaned = summary.strip()
    if not cleaned:
        return False

    lower = cleaned.lower()
    if len(cleaned.split()) >= 4 and any(
        phrase in lower
        for phrase in [
            "from ",
            "to ",
            "with ",
            "using ",
            "provided",
            "retrieve ",
            "generate ",
            "publish ",
        ]
    ):
        return True

    return False


def _rewrite_raw_summary(
    summary: str,
    *,
    entity: str | None,
    method: str,
) -> str | None:
    lower = summary.strip().lower()

    if "generate" in lower and entity == "Image":
        return "Generate an image from the provided content."

    if ("get content" in lower or "content" in lower) and entity == "Facebook":
        return "Retrieve content from Facebook."

    if ("get content" in lower or "content" in lower) and entity == "YouTube":
        return "Retrieve content from YouTube."

    if "post" in lower and entity == "X":
        return "Publish a post to X."

    if "content" in lower and entity == "X":
        return "Retrieve content from X."

    if entity is not None and method == "POST":
        return f"Submit a POST request for {entity.lower()} processing."

    return None


def _normalize_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return "No short description is available."

    cleaned = cleaned[0].upper() + cleaned[1:]
    if not cleaned.endswith("."):
        cleaned += "."
    return cleaned