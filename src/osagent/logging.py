"""基于 loguru 的统一日志。"""
from __future__ import annotations

import sys

from loguru import logger

from .config import settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
    )
    _configured = True


setup_logging()

__all__ = ["logger"]
