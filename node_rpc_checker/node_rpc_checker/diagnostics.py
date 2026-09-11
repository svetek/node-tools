"""Internal diagnostics without exception values, source text or frame locals."""

import logging
import traceback
from pathlib import Path


def log_internal_error(node: str, check: str, error: Exception) -> None:
    frames = traceback.extract_tb(error.__traceback__)
    stack = "\n".join(f"  {Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames)
    logging.error(
        "internal checker error node=%s check=%s type=%s\nTraceback (sanitized):\n%s",
        node,
        check,
        type(error).__name__,
        stack,
    )
