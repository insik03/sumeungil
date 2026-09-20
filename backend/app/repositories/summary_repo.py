"""Persistent preprocessing cache on the existing backend data volume.

One atomically replaced document per source; readers never write or invoke an LLM.
Writers must hold batch_lock. Failed generations cannot overwrite a valid result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..ai.injection_guard import normalize_unicode
from ..ai.summarizer import SUMMARY_PROMPT_VERSION
from ..util.text import strip_html_to_plain, truncate_text

logger = logging.getLogger("sumeungil.summary_repo")


def source_text(raw: str | None) -> str:
    return strip_html_to_plain(normalize_unicode(raw)) if isinstance(raw, str) else ""


def source_hash(raw: str) -> str:
    return hashlib.sha256(source_text(raw).encode("utf-8")).hexdigest()


def fallback_summary(raw: str | None) -> str | None:
    return truncate_text(source_text(raw), 360) or None


class SummaryRepository:
    def __init__(self, directory: str | Path, model: str, prompt_version: str = SUMMARY_PROMPT_VERSION):
        self.directory = Path(directory)
        self.model = model
        self.prompt_version = prompt_version

    def _path(self, kind: str, content_id: int) -> Path:
        if kind not in {"spot", "festival"} or type(content_id) is not int or content_id <= 0:
            raise ValueError("invalid tourism source key")
        return self.directory / kind / f"{content_id}.json"

    def load(self, kind: str, content_id: int) -> dict:
        try:
            value = json.loads(self._path(kind, content_id).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("summary_cache unreadable kind=%s id=%s", kind, content_id)
            return {}

    def current(self, record: dict, raw: str | None = None) -> str | None:
        result = record.get("result")
        if not isinstance(result, dict):
            return None
        summary = result.get("summary")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 360:
            return None
        if result.get("modelName") != self.model or result.get("promptVersion") != self.prompt_version:
            return None
        expected = source_hash(raw) if raw is not None else record.get("sourceHash")
        if not isinstance(expected, str) or len(expected) != 64:
            return None
        return summary if result.get("sourceHash") == expected else None

    def display(self, kind: str, content_id: int, raw: str | None) -> tuple[str | None, str | None]:
        record = self.load(kind, content_id)
        summary = self.current(record, raw)
        if summary:
            return summary, "ollama"
        logger.info("summary fallback=source kind=%s id=%s", kind, content_id)
        return fallback_summary(raw if raw is not None else record.get("source")), None

    def write(self, kind: str, content_id: int, record: dict) -> None:
        path = self._path(kind, content_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(record, out, ensure_ascii=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @contextmanager
    def batch_lock(self):
        """Cross-process lock, released by the OS even after a worker crash."""
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "batch.lock").open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("another summary batch is running") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
