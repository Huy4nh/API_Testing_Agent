from __future__ import annotations

import hashlib
from typing import Any

from langchain.chat_models import init_chat_model

from api_testing_agent.logging_config import bind_logger, get_logger


class UnknownOutputDescriptionService:
    """
    Dùng AI để mô tả đại khái một response thành công nhưng không nhận diện chắc là:
    - JSON
    - text thường
    - binary quen thuộc (image/pdf/zip...)

    Lưu ý:
    - Không gửi toàn bộ raw output cho AI
    - Chỉ gửi metadata + sample nhỏ, an toàn
    - Không cố parse/không dump raw bytes ra log
    """

    def __init__(
        self,
        *,
        model_name: str,
        model_provider: str | None = None,
        max_bytes_for_signature: int = 64,
        max_text_preview_chars: int = 240,
    ) -> None:
        self._logger = get_logger(__name__)
        self._model_name = model_name.strip()
        self._model_provider = model_provider.strip() if model_provider else None
        self._max_bytes_for_signature = max_bytes_for_signature
        self._max_text_preview_chars = max_text_preview_chars

        if not self._model_name:
            raise ValueError("model_name must not be empty.")

        init_logger = bind_logger(
            self._logger,
            payload_source="unknown_output_service_init",
        )
        init_logger.info(
            f"Initializing UnknownOutputDescriptionService. model_name={self._model_name}, model_provider={self._model_provider}"
        )

        self._llm = init_chat_model(
            self._model_name,
            model_provider=self._model_provider,
            temperature=0,
        )

        init_logger.info("UnknownOutputDescriptionService initialized successfully.")

    def describe(
        self,
        *,
        status_code: int,
        headers: dict[str, str],
        raw_bytes: bytes,
    ) -> str:
        logger = bind_logger(
            self._logger,
            payload_source="unknown_output_describe",
        )
        logger.info(
            f"Describing unknown successful output. status_code={status_code}, size_bytes={len(raw_bytes)}"
        )

        content_type = str(headers.get("content-type", "")).strip()
        size_bytes = len(raw_bytes)

        payload = {
            "status_code": status_code,
            "content_type": content_type or "unknown",
            "size_bytes": size_bytes,
            "sha256_prefix": hashlib.sha256(raw_bytes).hexdigest()[:16] if raw_bytes else "",
            "leading_bytes_hex": raw_bytes[: self._max_bytes_for_signature].hex(),
            "printable_text_preview": self._build_printable_preview(raw_bytes),
        }

        prompt = self._build_prompt(payload)

        try:
            result = self._llm.invoke(prompt)
            content = self._extract_model_text(result).strip()

            if content:
                logger.info("Unknown output description generated successfully by AI.")
                return content

            logger.warning("AI returned empty description for unknown output. Using fallback summary.")
            return self._fallback_summary(payload)

        except Exception:
            logger.exception("AI description for unknown output failed. Using fallback summary.")
            return self._fallback_summary(payload)

    def _build_printable_preview(self, raw_bytes: bytes) -> str:
        if not raw_bytes:
            return ""

        decoded = raw_bytes.decode("utf-8", errors="replace")
        printable: list[str] = []

        for ch in decoded:
            if ch.isprintable() or ch in "\n\r\t":
                printable.append(ch)
            else:
                printable.append("?")

        preview = "".join(printable).strip()
        if len(preview) > self._max_text_preview_chars:
            preview = preview[: self._max_text_preview_chars] + "..."

        return preview

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        return f"""
Bạn là bộ mô tả output API cho execution engine.

Nhiệm vụ:
- Chỉ mô tả ĐẠI KHÁI response thành công nhưng không xác định chắc loại output.
- Không được khẳng định quá mức.
- Không được bịa nội dung không có trong metadata.
- Không được yêu cầu chạy code hay decode thêm.
- Trả lời ngắn gọn bằng tiếng Việt, tối đa 2 câu.
- Nên nói theo kiểu:
  - "Có vẻ đây là ..."
  - "Response này dường như là ..."
  - "Chưa thể xác định chính xác, nhưng ..."
- Nếu không đủ tín hiệu, hãy nói rõ là chưa xác định chính xác.

Metadata:
{payload}
        """.strip()

    def _extract_model_text(self, result: Any) -> str:
        content = getattr(result, "content", None)

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "\n".join(chunks)

        return str(result)

    def _fallback_summary(self, payload: dict[str, Any]) -> str:
        content_type = payload.get("content_type", "unknown")
        size_bytes = payload.get("size_bytes", 0)
        preview = payload.get("printable_text_preview", "")

        if preview:
            return (
                f"Response thành công nhưng không xác định chắc loại output. "
                f"Content-Type hiện tại là '{content_type}', kích thước khoảng {size_bytes} bytes, "
                f"và có một phần preview ký tự có thể đọc được."
            )

        return (
            f"Response thành công nhưng không xác định chắc loại output. "
            f"Content-Type hiện tại là '{content_type}', kích thước khoảng {size_bytes} bytes."
        )