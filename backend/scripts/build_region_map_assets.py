"""Split the verified Korea boundary sources into one lazy-loadable asset per sido.

Input files are the design handoff sources. Sigungu source codes use the legacy
dataset code system, so matching to the app's current legal-dong region codes is
done by area + verified names/aliases from app.regions.seed.REGIONS. A boundary
is still preserved when there is no unique app-code match; its regionCode is
then null rather than guessed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SOURCE_DIR = ROOT / "design-docs" / "region-map-scratch"
OUTPUT_DIR = ROOT / "frontend" / "public" / "data" / "region-maps"

sys.path.insert(0, str(BACKEND))

from app.regions.seed import REGIONS  # noqa: E402


# southkorea-maps sigungu prefixes (2018 dataset) -> app sido_code.
SOURCE_AREA_TO_APP_AREA = {
    "11": "11",  # Seoul
    "21": "26",  # Busan
    "22": "27",  # Daegu
    "23": "28",  # Incheon
    "24": "29",  # Gwangju
    "25": "30",  # Daejeon
    "26": "31",  # Ulsan
    "29": "36",  # Sejong
    "31": "41",  # Gyeonggi
    "32": "51",  # Gangwon
    "33": "43",  # Chungbuk
    "34": "44",  # Chungnam
    "35": "52",  # Jeonbuk
    "36": "46",  # Jeonnam
    "37": "47",  # Gyeongbuk
    "38": "48",  # Gyeongnam
    "39": "50",  # Jeju
}

SUFFIXES = ("특별자치시", "특별자치도", "광역시", "특별시", "시", "군", "구")


def _compact(name: str) -> str:
    return re.sub(r"[\s\-·]", "", name).casefold()


def _strip_suffix(name: str) -> str:
    for suffix in SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _keys(name: str) -> set[str]:
    compact = _compact(name)
    stripped = _compact(_strip_suffix(name))
    return {value for value in (compact, stripped) if value}


def _match_region_code(area_cd: str, name_ko: str) -> str | None:
    source_keys = _keys(name_ko)
    matches: list[str] = []
    for region in REGIONS:
        if region.area_cd != area_cd:
            continue
        names = (region.label, *region.aliases)
        if any(source_keys & _keys(name) for name in names if name):
            matches.append(region.region_id)
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _bounds(ring: list[list[float]]) -> dict[str, float]:
    lngs = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return {
        "minLng": min(lngs),
        "minLat": min(lats),
        "maxLng": max(lngs),
        "maxLat": max(lats),
    }


def build() -> None:
    sido: dict[str, dict[str, Any]] = json.loads(
        (SOURCE_DIR / "kr-sido-boundaries.json").read_text(encoding="utf-8")
    )
    sigungu: dict[str, dict[str, Any]] = json.loads(
        (SOURCE_DIR / "kr-sigungu-boundaries.json").read_text(encoding="utf-8")
    )

    grouped: dict[str, list[dict[str, Any]]] = {code: [] for code in sido}
    for source_code, boundary in sigungu.items():
        area_cd = SOURCE_AREA_TO_APP_AREA.get(source_code[:2])
        if area_cd not in grouped:
            raise ValueError(f"Unknown sigungu source prefix: {source_code}")
        grouped[area_cd].append(
            {
                "sourceCode": source_code,
                "regionCode": _match_region_code(area_cd, boundary["name_ko"]),
                "nameKo": boundary["name_ko"],
                "nameEng": boundary["name_eng"],
                "rings": boundary["rings"],
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    matched_total = 0
    for area_cd, boundary in sido.items():
        districts = sorted(grouped[area_cd], key=lambda item: item["sourceCode"])
        matched_total += sum(item["regionCode"] is not None for item in districts)
        payload = {
            "version": 1,
            "source": "southkorea/southkorea-maps (Statistics Korea 2018, simplified)",
            "sidoCode": area_cd,
            "nameKo": boundary["name_ko"],
            "nameEng": boundary["name_eng"],
            "bounds": _bounds(boundary["ring"]),
            "outerRing": boundary["ring"],
            "districts": districts,
        }
        (OUTPUT_DIR / f"{area_cd}.json").write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    print(
        f"Wrote {len(sido)} sido assets with {len(sigungu)} sigungu boundaries "
        f"({matched_total} uniquely matched app region codes) to {OUTPUT_DIR}"
    )


if __name__ == "__main__":
    build()
