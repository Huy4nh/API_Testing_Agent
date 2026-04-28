from __future__ import annotations

import uuid

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from api_testing_agent.tasks.orchestrator import ReviewWorkflowResult, TestOrchestrator


class TelegramBotApp:
    def __init__(self, token: str, orchestrator: TestOrchestrator) -> None:
        self._token = token
        self._orchestrator = orchestrator
        self._active_threads: dict[int, str] = {}

    def build(self) -> Application:
        app = Application.builder().token(self._token).build()

        app.add_handler(CommandHandler("start", self._start))
        app.add_handler(CommandHandler("targets", self._targets))
        app.add_handler(CommandHandler("mode", self._mode))
        app.add_handler(CommandHandler("setmode", self._setmode))
        app.add_handler(CommandHandler("model", self._model))
        app.add_handler(CommandHandler("setmodel", self._setmodel))

        app.add_handler(CommandHandler("approve", self._approve))
        app.add_handler(CommandHandler("feedback", self._feedback))
        app.add_handler(CommandHandler("showdraft", self._showdraft))
        app.add_handler(CommandHandler("cancelreview", self._cancelreview))

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        return app

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = (
            "Chào bạn.\n\n"
            "Lệnh test ví dụ:\n"
            "- test target cms_local module posts GET\n"
            "- test target cms_local module posts POST\n"
            "- test target cms_local module auth negative\n\n"
            "Lệnh mode/model:\n"
            "- /mode\n"
            "- /setmode ai\n"
            "- /setmode rule\n"
            "- /model\n"
            "- /setmodel openai:gpt-5.2\n"
            "- /setmodel openai:gpt-5.4\n\n"
            "Lệnh review flow:\n"
            "- Gửi lệnh test khi mode=ai để sinh testcase draft\n"
            "- /showdraft\n"
            "- /feedback <nội dung feedback>\n"
            "- /approve\n"
            "- /cancelreview\n"
        )
        await update.message.reply_text(message)

    async def _targets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        names = self._orchestrator.list_targets()
        await update.message.reply_text("Available targets:\n- " + "\n- ".join(names))

    async def _mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        mode = self._orchestrator.get_generator_mode()
        model = self._orchestrator.get_ai_model()
        await update.message.reply_text(
            f"Current generator mode: {mode}\nCurrent AI model: {model}"
        )

    async def _setmode(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /setmode ai  hoặc  /setmode rule")
            return

        try:
            self._orchestrator.set_generator_mode(context.args[0])
            mode = self._orchestrator.get_generator_mode()
            await update.message.reply_text(f"Generator mode updated to: {mode}")
        except Exception as exc:
            await update.message.reply_text(f"Failed to set mode: {exc}")

    async def _model(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        model = self._orchestrator.get_ai_model()
        await update.message.reply_text(f"Current AI model: {model}")

    async def _setmodel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text(
                "Usage: /setmodel openai:gpt-5.2\nVí dụ khác: /setmodel anthropic:claude-sonnet-4-6"
            )
            return

        try:
            self._orchestrator.set_ai_model(context.args[0])
            await update.message.reply_text(f"AI model updated to: {self._orchestrator.get_ai_model()}")
        except Exception as exc:
            await update.message.reply_text(f"Failed to set model: {exc}")

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not update.message.text:
            return

        text = update.message.text.strip()

        try:
            if self._orchestrator.get_generator_mode() == "ai":
                chat_id = update.effective_chat.id if update.effective_chat else 0
                thread_id = uuid.uuid4().hex
                self._active_threads[chat_id] = thread_id

                review_result = self._orchestrator.start_review_from_text(
                    text,
                    thread_id=thread_id,
                )
                await update.message.reply_text(self._format_review_result(review_result))
                return

            summary, _results = self._orchestrator.run_from_text(text)
            response = (
                f"Đã chạy test xong.\n"
                f"- Target: {summary.target_name}\n"
                f"- Generator mode: {self._orchestrator.get_generator_mode()}\n"
                f"- AI model: {self._orchestrator.get_ai_model()}\n"
                f"- Total: {summary.total}\n"
                f"- Passed: {summary.passed}\n"
                f"- Failed: {summary.failed}\n"
                f"- JSON report: {summary.report_json_path}\n"
                f"- Markdown report: {summary.report_md_path}"
            )
            await update.message.reply_text(response)
        except Exception as exc:
            await update.message.reply_text(f"Có lỗi khi chạy test: {exc}")

    async def _showdraft(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        thread_id = self._active_threads.get(chat_id)

        if not thread_id:
            await update.message.reply_text("Không có review draft nào đang chờ trong chat này.")
            return

        try:
            review_result = self._orchestrator.get_review_preview(thread_id)
            await update.message.reply_text(self._format_review_result(review_result))
        except Exception as exc:
            await update.message.reply_text(f"Không lấy được draft hiện tại: {exc}")

    async def _feedback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        thread_id = self._active_threads.get(chat_id)

        if not thread_id:
            await update.message.reply_text("Không có review draft nào đang chờ để feedback.")
            return

        feedback_text = " ".join(context.args).strip()
        if not feedback_text:
            await update.message.reply_text("Usage: /feedback <nội dung phản hồi>")
            return

        try:
            review_result = self._orchestrator.resume_review(
                thread_id,
                action="revise",
                feedback=feedback_text,
            )

            if review_result.status in {"completed", "cancelled"}:
                self._active_threads.pop(chat_id, None)

            await update.message.reply_text(self._format_review_result(review_result))
        except Exception as exc:
            await update.message.reply_text(f"Không feedback được: {exc}")

    async def _approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        thread_id = self._active_threads.get(chat_id)

        if not thread_id:
            await update.message.reply_text("Không có review draft nào đang chờ để approve.")
            return

        try:
            review_result = self._orchestrator.resume_review(
                thread_id,
                action="approve",
                feedback="",
            )

            if review_result.status in {"completed", "cancelled"}:
                self._active_threads.pop(chat_id, None)

            await update.message.reply_text(self._format_review_result(review_result))
        except Exception as exc:
            await update.message.reply_text(f"Không approve được: {exc}")

    async def _cancelreview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        thread_id = self._active_threads.get(chat_id)

        if not thread_id:
            await update.message.reply_text("Không có review draft nào đang chờ để hủy.")
            return

        try:
            review_result = self._orchestrator.resume_review(
                thread_id,
                action="cancel",
                feedback="",
            )
            self._active_threads.pop(chat_id, None)
            await update.message.reply_text(self._format_review_result(review_result))
        except Exception as exc:
            await update.message.reply_text(f"Không hủy review được: {exc}")


    def _format_review_result(self, result: ReviewWorkflowResult) -> str:
        if result.status == "pending_review":
            extra = ""
            if result.draft_report_json_path:
                extra += f"\n- Draft JSON report: {result.draft_report_json_path}"
            if result.draft_report_md_path:
                extra += f"\n- Draft Markdown report: {result.draft_report_md_path}"

            return (
                f"Draft review đang chờ phản hồi.\n"
                f"- Thread ID: {result.thread_id}\n"
                f"- Round: {result.round_number}"
                f"{extra}\n\n"
                f"{result.preview_text or 'Không có preview.'}"
            )

        if result.status == "completed" and result.summary is not None:
            extra = ""
            if result.draft_report_json_path:
                extra += f"\n- Last Draft JSON report: {result.draft_report_json_path}"
            if result.draft_report_md_path:
                extra += f"\n- Last Draft Markdown report: {result.draft_report_md_path}"

            return (
                f"Đã approve và chạy test xong.\n"
                f"- Thread ID: {result.thread_id}\n"
                f"- Round cuối: {result.round_number}"
                f"{extra}\n"
                f"- Total: {result.summary.total}\n"
                f"- Passed: {result.summary.passed}\n"
                f"- Failed: {result.summary.failed}\n"
                f"- JSON report: {result.summary.report_json_path}\n"
                f"- Markdown report: {result.summary.report_md_path}"
            )

        if result.status == "cancelled":
            extra = ""
            if result.draft_report_json_path:
                extra += f"\n- Draft JSON report: {result.draft_report_json_path}"
            if result.draft_report_md_path:
                extra += f"\n- Draft Markdown report: {result.draft_report_md_path}"

            return f"Review đã bị hủy.\n- Thread ID: {result.thread_id}{extra}"

        return result.message or "Không có kết quả."