from __future__ import annotations

import re
from typing import cast

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from api_testing_agent.logging_config import bind_logger, get_logger
from api_testing_agent.tasks.language_support import SupportedLanguage


class WorkflowTextLocalizer:
    def __init__(
        self,
        *,
        model_name: str,
        model_provider: str | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._model_name = model_name.strip()
        self._model_provider = (model_provider or "").strip() or None
        self._translation_model = None
        self._enabled = False

        try:
            self._translation_model = init_chat_model(
                model=self._model_name,
                model_provider=self._model_provider,
                temperature=0,
            )
            self._enabled = True
            self._logger.info(
                "Initialized WorkflowTextLocalizer with translation model.",
                extra={"payload_source": "workflow_text_localizer_init"},
            )
        except Exception as exc:
            self._translation_model = None
            self._enabled = False
            self._logger.warning(
                f"WorkflowTextLocalizer will use rule-based fallback only: {exc}",
                extra={"payload_source": "workflow_text_localizer_init_failed"},
            )

    def localize_text(
        self,
        *,
        text: str | None,
        target_language: SupportedLanguage,
        text_kind: str = "generic",
        thread_id: str | None = None,
        target_name: str | None = None,
    ) -> str | None:
        if text is None:
            return None

        cleaned = text.strip()
        if not cleaned:
            return text

        if target_language == "vi":
            return text

        deterministic = self._rule_based_to_english(cleaned)

        # If deterministic rewrite already looks good enough, keep it.
        if not self._still_looks_vietnamese(deterministic):
            return deterministic

        model = self._translation_model
        if not self._enabled or model is None:
            return deterministic

        logger = bind_logger(
            self._logger,
            thread_id=thread_id or "-",
            target_name=str(target_name or "-"),
            payload_source="workflow_text_localizer_translate",
        )

        try:
            translated = self._translate_with_model(
                model=model,
                text=cleaned,
                text_kind=text_kind,
            )
            if translated and translated.strip():
                return translated.strip()
        except Exception as exc:
            logger.warning(f"Translation via model failed, fallback to rule-based English: {exc}")

        return deterministic

    def _translate_with_model(
        self,
        *,
        model,
        text: str,
        text_kind: str,
    ) -> str:
        system_prompt = (
            "You translate workflow text for a REST API testing assistant.\n"
            "Translate the input into clear natural English.\n"
            "Preserve markdown structure, bullet lists, numbering, code-like paths, operation_id, status codes, and backticks.\n"
            "Do not omit details.\n"
            "Do not add explanations.\n"
            f"Text kind: {text_kind}\n"
        )
        human_prompt = f"Translate this text to English exactly while preserving structure:\n\n{text}"

        raw_result = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]
        )

        if isinstance(raw_result, BaseModel):
            dumped = cast(dict[str, object], raw_result.model_dump())
            content = dumped.get("content")
            return str(content or "")

        content = getattr(raw_result, "content", None)
        if content is not None:
            return str(content)

        if isinstance(raw_result, dict):
            return str(raw_result.get("content", ""))

        return str(raw_result)

    def _still_looks_vietnamese(self, text: str) -> bool:
        lower = text.lower()
        if re.search(r"[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", lower):
            return True

        common_vi_markers = [
            "đã ",
            "không ",
            "trường ",
            "bắt buộc",
            "không có",
            "xác định",
            "gửi request",
            "thiếu field",
            "không yêu cầu",
            "môi trường",
            "chức năng",
            "hiện tại",
            "kiểm tra",
            "phù hợp",
        ]
        return any(marker in lower for marker in common_vi_markers)

    def _rule_based_to_english(self, text: str) -> str:
        result = text

        replacements = [
            ("Đây là phạm vi review hiện tại:", "Here is the current review scope:"),
            ("Các chức năng hiện có của target", "Available functions in target"),
            ("Preview draft hiện tại:", "Current draft preview:"),
            ("Đã xác định target là", "The system identified the target as"),
            ("và đã match đúng chức năng cụ thể:", "and matched the intended function:"),
            ("Bạn muốn test image generation trên môi trường nào? Local, Staging hay Production?", "Which environment would you like to test image generation on? Local, Staging, or Production?"),
            ("Bạn muốn test sinh ảnh trên môi trường nào của img: local (img_local), staging (img_api_staging), hay production (img_api_prod)?", "Which environment do you want to test image generation for img on: local (img_local), staging (img_api_staging), or production (img_api_prod)?"),
            ("Bạn muốn test sinh ảnh của img trên môi trường nào? staging (img_api_staging) hay local (img_local)?", "Which environment do you want to test img image generation on? staging (img_api_staging) or local (img_local)?"),
            ("Operation không yêu cầu authentication", "The operation does not require authentication"),
            ("Operation không yêu cầu xác thực", "The operation does not require authentication"),
            ("Không có path parameter đại diện resource identifier", "There is no path parameter representing a resource identifier"),
            ("không thể sinh not found case", "cannot generate a meaningful not-found case"),
            ("không thể sinh resource_not_found case có ý nghĩa", "cannot generate a meaningful resource_not_found case"),
            ("Trường", "Field"),
            ("trường", "field"),
            ("bắt buộc", "required"),
            ("thiếu trường", "missing field"),
            ("thiếu field", "missing field"),
            ("Gửi request", "Send a request"),
            ("gửi request", "send a request"),
            ("hợp lệ", "valid"),
            ("kèm", "with"),
            ("để kiểm tra", "to verify"),
            ("kiểm tra", "verify"),
            ("thành công", "success"),
            ("response thành công", "a successful response"),
            ("không yêu cầu auth", "does not require auth"),
            ("không có cơ chế auth", "there is no auth mechanism"),
            ("không có path parameter", "there is no path parameter"),
            ("không thể", "cannot"),
            ("với content hợp lệ", "with valid content"),
            ("với content là một URL hợp lệ", "with content as a valid URL"),
            ("với content là URL hợp lệ", "with content as a valid URL"),
            ("prompt và quality tùy chọn", "prompt, and optional quality"),
            ("sai kiểu", "with an invalid type"),
            ("không đúng kiểu", "with an invalid type"),
            ("truyền string thay vì integer", "passing a string instead of an integer"),
            ("skip test này", "skip this test"),
            ("không phù hợp", "is not applicable"),
            ("môi trường", "environment"),
            ("chức năng", "function"),
            ("Tôi đã chốt final report.", "I finalized the final report."),
            ("File chính thức nằm tại", "The official files are located at"),
            ("Workflow đã ở phase kết thúc. Nếu muốn test mới, hãy nhập yêu cầu mới.", "The workflow has finished. If you want to run a new test, enter a new request."),
            ("Workflow đã bị hủy.", "The workflow was cancelled."),
            ("Không có dữ liệu nào được finalize/persist.", "No data was finalized or persisted."),
            ("Bạn có thể hỏi giải thích report, yêu cầu tôi viết lại report, yêu cầu sửa scope để chạy lại, hoặc nói `lưu` / `done` / `hủy`.", "You can ask me to explain the report, rewrite it, change the scope and rerun, or say `save` / `done` / `cancel`."),
        ]
        for source, target in replacements:
            result = result.replace(source, target)

        # Structured / frequent line rewrites
        line_patterns: list[tuple[re.Pattern[str], str]] = [
            (
                re.compile(r"^Original request:\s*(.+)$", re.MULTILINE),
                r"Original request: \1",
            ),
            (
                re.compile(r"^Canonical command:\s*(.+)$", re.MULTILINE),
                r"Canonical command: \1",
            ),
            (
                re.compile(r"^Understanding:\s*(.+)$", re.MULTILINE),
                r"Understanding: \1",
            ),
            (
                re.compile(r"^Active operations:\s*(.+)$", re.MULTILINE),
                r"Active operations: \1",
            ),
            (
                re.compile(r"^\s*why:\s*(.+)$", re.MULTILINE),
                r"      why: \1",
            ),
            (
                re.compile(r"^\s*expect:\s*(.+)$", re.MULTILINE),
                r"      expect: \1",
            ),
            (
                re.compile(r"^\s*skip_reason:\s*(.+)$", re.MULTILINE),
                r"      skip_reason: \1",
            ),
        ]

        for pattern, replacement in line_patterns:
            result = pattern.sub(replacement, result)
            
        # High-priority full-sentence rewrites for review preview lines
        result = re.sub(
            r"POST /img với content hợp lệ \(URL\), prompt và quality tùy chọn",
            "POST /img with valid content (URL), prompt, and optional quality",
            result,
            flags=re.IGNORECASE,
        )

        result = re.sub(
            r"why:\s*Gửi request hợp lệ với trường required 'content' là URL, kèm prompt và quality để kiểm tra response thành công\.",
            "why: Send a valid request where the required field 'content' is a URL, with prompt and quality to verify a successful response.",
            result,
            flags=re.IGNORECASE,
        )

        result = re.sub(
            r"why:\s*Gửi request hợp lệ với trường required 'content' là URL, kèm prompt và quality để kiểm tra response thành công",
            "why: Send a valid request where the required field 'content' is a URL, with prompt and quality to verify a successful response.",
            result,
            flags=re.IGNORECASE,
        )

        # Repair mixed-language fragments after generic word replacements
        result = result.replace("với content valid", "with valid content")
        result = result.replace("với content hợp lệ", "with valid content")
        result = result.replace("prompt và quality", "prompt and quality")
        result = result.replace("with prompt và quality", "with prompt and quality")
        result = result.replace("trường required", "required field")
        result = result.replace("field required", "required field")
        result = result.replace("là URL", "is a URL")
        result = result.replace("kèm", "with")
        result = result.replace("để kiểm tra", "to verify")
        result = result.replace("response success", "a successful response")
        result = result.replace("response thành công", "a successful response")
        # Common testcase sentence rewrites
        result = re.sub(
            r"POST /img với content hợp lệ \(URL\), prompt và quality tùy chọn",
            "POST /img with valid content (URL), prompt, and optional quality",
            result,
        )
        result = re.sub(
            r"POST /img thiếu trường required 'content'",
            "POST /img with the required field 'content' missing",
            result,
        )
        result = re.sub(
            r"POST /img với 'quality' sai kiểu \(string thay vì integer\)",
            "POST /img with 'quality' using the wrong type (string instead of integer)",
            result,
        )
        result = re.sub(
            r"POST /img - operation không yêu cầu auth",
            "POST /img - the operation does not require auth",
            result,
        )
        result = re.sub(
            r"POST /img - không có path parameter resource identifier",
            "POST /img - there is no path parameter resource identifier",
            result,
        )
        result = re.sub(
            r"POST /img với content hợp lệ \(URL\), prompt và quality tùy chọn",
            "POST /img with valid content (URL), prompt, and optional quality",
            result,
        )
        result = re.sub(
            r"POST /img với content hợp lệ \(url\), prompt và quality tùy chọn",
            "POST /img with valid content (URL), prompt, and optional quality",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"POST /img thiếu trường required 'content'",
            "POST /img with the required field 'content' missing",
            result,
        )
        result = re.sub(
            r"POST /img với 'quality' sai kiểu \(string thay vì integer\)",
            "POST /img with 'quality' using the wrong type (string instead of an integer)",
            result,
        )
        result = re.sub(
            r"why:\s*Send a request valid với field required 'content' là URL, with prompt and quality to verify a successful response\.",
            "why: Send a valid request where the required field 'content' is a URL, with prompt and quality to verify a successful response.",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"why:\s*Send a request hợp lệ với trường required 'content' là URL, kèm prompt và quality để verify response thành công\.",
            "why: Send a valid request where the required field 'content' is a URL, with prompt and quality to verify a successful response.",
            result,
            flags=re.IGNORECASE,
        )
        # Understanding sentence normalization
        result = re.sub(
            r"The system identified the target as '([^']+)' and matched the intended function:\s*(.+)",
            r"The system identified the target as '\1' and matched the intended function: \2",
            result,
        )

        # Final cleanup
        result = re.sub(r"\s+\n", "\n", result)
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = result.replace("prompt and quality as optional fields", "prompt, and optional quality")
        result = result.replace("prompt and quality as optional fields", "prompt, and optional quality")
        result = result.replace("Send a request valid", "Send a valid request")
        result = result.replace("with required field", "where the required field")
        result = result.replace("I finalized the final report. The official files are located at", "I finalized the report. The official files are located at")
        return result