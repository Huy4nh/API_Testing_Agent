from __future__ import annotations

import logging
import os
from collections.abc import Mapping, MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class SafeExtraFormatter(logging.Formatter):
    DEFAULT_EXTRA_FIELDS = {
        "thread_id": "-",
        "target_name": "-",
        "operation_id": "-",
        "testcase_id": "-",
        "payload_source": "-",
    }

    def format(self, record: logging.LogRecord) -> str:
        for field_name, default_value in self.DEFAULT_EXTRA_FIELDS.items():
            if not hasattr(record, field_name):
                setattr(record, field_name, default_value)

        return super().format(record)


class ContextLoggerAdapter(logging.LoggerAdapter):
    """
    LoggerAdapter có typing sạch:
    - extra luôn là Mapping[str, object]
    - process nhận kwargs là MutableMapping đúng với base class
    - không dùng dict(self.extra) để tránh lỗi overload typing
    """

    def __init__(
        self,
        logger: logging.Logger,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(logger, extra or {})

    def process(
        self,
        msg: object,
        kwargs: MutableMapping[str, object],
    ) -> tuple[object, MutableMapping[str, object]]:
        merged_extra: dict[str, object] = {}

        if isinstance(self.extra, Mapping):
            for key, value in self.extra.items():
                if isinstance(key, str):
                    merged_extra[key] = value

        raw_extra = kwargs.get("extra")
        if isinstance(raw_extra, Mapping):
            for key, value in raw_extra.items():
                if isinstance(key, str):
                    merged_extra[key] = value

        kwargs["extra"] = merged_extra
        return msg, kwargs


_LOGGING_CONFIGURED = False


def setup_logging(
    *,
    level: str | int | None = None,
    log_dir: str | None = None,
    force: bool = False,
    enable_console: bool | None = None,
) -> None:
    """
    Cấu hình root logger cho toàn project.

    Env hỗ trợ:
    - LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
    - LOG_DIR=./logs
    - LOG_MAX_BYTES=10485760
    - LOG_BACKUP_COUNT=5
    - LOG_ENABLE_CONSOLE=true|false
    """
    global _LOGGING_CONFIGURED

    if _LOGGING_CONFIGURED and not force:
        return

    resolved_level = _resolve_log_level(level or os.getenv("LOG_LEVEL", "INFO"))
    resolved_log_dir = Path(log_dir or os.getenv("LOG_DIR", "./logs"))
    resolved_log_dir.mkdir(parents=True, exist_ok=True)

    if enable_console is None:
        enable_console = _safe_bool_from_env("LOG_ENABLE_CONSOLE", True)

    max_bytes = _safe_int_from_env("LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _safe_int_from_env("LOG_BACKUP_COUNT", 5)

    root_logger = logging.getLogger()

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    root_logger.setLevel(resolved_level)

    formatter = SafeExtraFormatter(
        fmt=(
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "thread=%(thread_id)s | target=%(target_name)s | "
            "op=%(operation_id)s | case=%(testcase_id)s | "
            "source=%(payload_source)s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(resolved_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    app_file_handler = RotatingFileHandler(
        filename=resolved_log_dir / "app.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    app_file_handler.setLevel(resolved_level)
    app_file_handler.setFormatter(formatter)

    error_file_handler = RotatingFileHandler(
        filename=resolved_log_dir / "error.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.WARNING)
    error_file_handler.setFormatter(formatter)

    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(error_file_handler)

    for noisy_logger_name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy_logger_name).setLevel(logging.WARNING)

    _LOGGING_CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or "api_testing_agent")


def bind_logger(logger: logging.Logger, **context: Any) -> ContextLoggerAdapter:
    normalized_context: dict[str, object] = {}

    for key, value in context.items():
        normalized_context[str(key)] = value

    return ContextLoggerAdapter(logger, normalized_context)


def _resolve_log_level(level: str | int) -> int:
    if isinstance(level, int):
        return level

    normalized = str(level).strip().upper()
    return getattr(logging, normalized, logging.INFO)


def _safe_int_from_env(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def _safe_bool_from_env(env_name: str, default: bool) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default