"""Structured logging and run metadata utilities for the credit-strategy pipeline.

Each pipeline run gets:
- A unique run_id (timestamp + short hash of input path + mode).
- A JSON run-metadata record persisted alongside outputs.
- A logger that emits to stderr and to `pipeline.log` inside the output dir.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class RunMetadata:
    """Metadata captured for every pipeline run."""
    run_id: str
    mode: str
    input_path: str
    output_dir: str
    config_path: str | None
    started_at: str
    finished_at: str | None = None
    status: str = "running"  # "running", "success", "failed"
    error_message: str | None = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "input_path": self.input_path,
            "output_dir": self.output_dir,
            "config_path": self.config_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "error_message": self.error_message,
            "extras": self.extras,
        }


def make_run_id(mode: str, input_path: str) -> str:
    """Deterministic-ish run id: timestamp + 6-char hash of input path."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    short_hash = hashlib.sha256(input_path.encode("utf-8")).hexdigest()[:6]
    return f"{timestamp}_{mode}_{short_hash}"


def setup_logger(name: str, output_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """Create a logger that writes both to stderr and to `<output_dir>/pipeline.log`."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Clean any prior handlers (helpful when run inside test loops)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    output_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(output_dir / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def write_run_metadata(output_dir: Path, metadata: RunMetadata) -> None:
    """Persist run metadata as JSON inside the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
