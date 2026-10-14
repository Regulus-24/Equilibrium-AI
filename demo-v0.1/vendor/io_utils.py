from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Replace a text file atomically without exposing a partially written receipt."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding=encoding, newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    return atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
