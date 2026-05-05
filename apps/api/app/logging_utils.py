from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_mangadex_logger() -> logging.Logger:
    logger = logging.getLogger("mangaforge.mangadex")
    if logger.handlers:
        return logger

    log_dir = _project_root() / "logs" / "mangadex"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "mangadex.log"

    handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s")
    )
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
