"""스팟 파생 태그의 영구 캐시 — 한 번 만들면 저장해 두고, 소개글이 바뀔 때만 다시 만든다 (2026-09-20).

배치(scripts/build_spot_tags.py)가 소개글(TourAPI detailCommon2 overview)에서 태그를 뽑아 이 파일에
쌓는다. 서버는 읽기만 한다 — 요청 처리 중에 추출·API 호출을 하지 않는다.

파일 하나(`<SUMMARY_STORE_DIR>/spot_tags.json`)를 원자적으로 교체한다:
    {"version": 1, "rules": "<RULES_VERSION>",
     "spots": {"<id>": {"h": "<소개글 sha256>", "t": [["mood","calm"], ...], "at": "<ISO>"}}}

재생성 조건은 딱 두 가지다 — 소개글 해시가 다르거나, 규칙 버전(RULES_VERSION)이 올랐을 때.
그 외에는 API 를 다시 부르지도(stale_days 이내), 다시 추출하지도 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..ai.spot_tagger import RULES_VERSION

logger = logging.getLogger("sumeungil.spot_tag_cache")

FILE_NAME = "spot_tags.json"
SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SpotTagCache:
    def __init__(self, directory: str | Path) -> None:
        self.path = Path(directory) / FILE_NAME
        self._spots: dict[str, dict] = {}

    # --- 읽기 -----------------------------------------------------------------

    def load(self) -> "SpotTagCache":
        """파일이 없거나 깨졌으면 빈 캐시(서버는 시드 태그만으로 동작). 규칙 버전이 다르면 낡은 것으로 본다."""
        self._spots = {}
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self
        except (OSError, ValueError):
            logger.warning("spot_tags 캐시를 읽지 못했다(무시): %s", self.path)
            return self
        if isinstance(doc, dict) and doc.get("version") == SCHEMA_VERSION and isinstance(doc.get("spots"), dict):
            self._spots = doc["spots"]
        return self

    def mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def tags(self, spot_id: int) -> list[list[str]]:
        """이 스팟에 붙일 파생 태그. 현재 규칙 버전으로 만든 것만 쓴다(낡은 규칙의 결과는 버린다)."""
        entry = self._spots.get(str(spot_id))
        if not entry or entry.get("v", RULES_VERSION) != RULES_VERSION:
            return []
        t = entry.get("t")
        return t if isinstance(t, list) else []

    def __len__(self) -> int:
        return len(self._spots)

    # --- 재생성 판단 -----------------------------------------------------------

    def is_fresh(self, spot_id: int, stale_days: int) -> bool:
        """최근에 확인했고 규칙 버전도 같으면 소개글을 다시 받아올 필요가 없다(API 호출 절약)."""
        entry = self._spots.get(str(spot_id))
        if not entry or entry.get("v") != RULES_VERSION:
            return False
        try:
            checked = datetime.fromisoformat(entry["at"])
        except (KeyError, ValueError, TypeError):
            return False
        return _now() - checked < timedelta(days=stale_days)

    def needs_extract(self, spot_id: int, source_hash: str) -> bool:
        """소개글이 바뀌었거나 규칙 버전이 올랐을 때만 다시 추출한다."""
        entry = self._spots.get(str(spot_id))
        return not entry or entry.get("h") != source_hash or entry.get("v") != RULES_VERSION

    # --- 쓰기(배치 전용) ---------------------------------------------------------

    def put(self, spot_id: int, source_hash: str, tags: list[tuple[str, str]]) -> None:
        self._spots[str(spot_id)] = {
            "h": source_hash,
            "v": RULES_VERSION,
            "t": [[a, v] for a, v in tags],
            "at": _now().isoformat(),
        }

    def touch(self, spot_id: int) -> None:
        """소개글이 그대로임을 확인했다 — 태그는 두고 확인 시각만 갱신."""
        entry = self._spots.get(str(spot_id))
        if entry:
            entry["at"] = _now().isoformat()

    def save(self) -> None:
        """원자적 교체 — 도중에 죽어도 기존 파일이 온전하다."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"version": SCHEMA_VERSION, "rules": RULES_VERSION, "spots": self._spots}
        fd, tmp = tempfile.mkstemp(prefix=FILE_NAME + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(doc, out, ensure_ascii=False, separators=(",", ":"))
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
