from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER_NAME = "pennyparse"
_CONFIGURED_LOG_PATH: Path | None = None


def configure_logging(*, cwd: Path | None = None, level: int = logging.INFO) -> Path:
    global _CONFIGURED_LOG_PATH

    log_path = (cwd or Path.cwd()) / "pennyparse.log"
    logger = logging.getLogger(_LOGGER_NAME)
    if _CONFIGURED_LOG_PATH == log_path and logger.handlers:
        return log_path

    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    _CONFIGURED_LOG_PATH = log_path
    return log_path


def get_logger(name: str | None = None) -> logging.Logger:
    configure_logging()
    if not name or name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    full_name = name if name.startswith(f"{_LOGGER_NAME}.") else f"{_LOGGER_NAME}.{name}"
    return logging.getLogger(full_name)
