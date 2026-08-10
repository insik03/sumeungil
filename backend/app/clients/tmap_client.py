"""Tmap 경로안내 클라이언트 (부록 I) — 보행자경로 + 자동차경로.

원천(2026-07-24 backend-engineer 실호출 확정, 기존 TMAP_APP_KEY 로 성공):
  - 보행자: POST https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1
  - 자동차: POST https://apis.openapi.sk.com/tmap/routes?version=1
  헤더 appKey, body JSON: startX(lng)/startY(lat)/endX/endY + reqCoordType/resCoordType=WGS84GEO.

실호출로 확인한 응답(둘 다 GeoJSON FeatureCollection):
  - features[0].properties.totalTime(초), totalDistance(m)
  - features 는 Point(경유점)+LineString(경로선) 혼합 → LineString.coordinates 를 순서대로
    이어붙이면 경로선. 좌표는 [lng, lat](WGS84GEO). (예 해운대 마린시티→해수욕장:
    보행 2024초/2628m, 차 850초/4674m — 실측)

정직 규칙: 호출/파싱 실패·거리초과·좌표이상이면 None 반환(지어내지 않음). appKey 는
헤더로만 전달하고 로그·URL 에 남기지 않는다(httpx 로거는 main.py 에서 WARNING 억제).
"""

from __future__ import annotations

import logging
import math

import httpx

from ..config import settings

logger = logging.getLogger("sumeungil.tmap")

_PEDESTRIAN_PATH = "/tmap/routes/pedestrian?version=1"
_CAR_PATH = "/tmap/routes?version=1"

# 한국 대략 bbox — 좌표 이상(해외/0,0) 방어. 벗어나면 Tmap 호출 자체를 생략(graceful null).
_KR_LAT = (33.0, 39.6)
_KR_LNG = (124.0, 132.0)


def valid_coord(lat: float | None, lng: float | None) -> bool:
    """스팟 좌표가 한국 bbox 안이면 True. 좌표 없음/해외/0,0 은 False(코스 leg 는 null 처리)."""
    if lat is None or lng is None:
        return False
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    return _KR_LAT[0] <= lat <= _KR_LAT[1] and _KR_LNG[0] <= lng <= _KR_LNG[1]


def _extract_line(features: list[dict]) -> list[list[float]]:
    """features 의 LineString 좌표를 순서대로 이어붙여 경로선([[lng,lat],...])을 만든다."""
    path: list[list[float]] = []
    for feat in features:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        for coord in geom.get("coordinates") or []:
            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                path.append([float(coord[0]), float(coord[1])])  # [lng, lat] 그대로
    return path


def _summary(features: list[dict]) -> tuple[int, int] | None:
    """features[0].properties 에서 (totalTime 초, totalDistance m) 정수 추출. 없으면 None."""
    if not features:
        return None
    props = features[0].get("properties") or {}
    tt = props.get("totalTime")
    td = props.get("totalDistance")
    if tt is None or td is None:
        return None
    try:
        return int(tt), int(td)
    except (TypeError, ValueError):
        return None


async def _fetch(url_path: str, body: dict) -> dict | None:
    """Tmap 경로 1건 호출 → {minutes, meters, path} 또는 None(실패·키없음·응답이상)."""
    key = settings.tmap_app_key
    if not key:
        return None  # 키 미설정 → graceful(코스는 유지, leg 만 null)

    headers = {"appKey": key, "Content-Type": "application/json"}
    url = settings.tmap_base_url.rstrip("/") + url_path
    try:
        async with httpx.AsyncClient(timeout=settings.tmap_timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        logger.info("Tmap 호출 실패 → leg null: %s", exc)
        return None

    if resp.status_code != 200:
        # 거리초과/좌표이상 등은 여기로 온다 → 지어내지 않고 null. 본문에 appKey 없음.
        logger.info("Tmap 비정상 상태 %s → leg null", resp.status_code)
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.info("Tmap 응답 JSON 파싱 실패 → leg null")
        return None

    features = data.get("features") or []
    summ = _summary(features)
    if summ is None:
        return None
    seconds, meters = summ
    return {
        "minutes": max(1, round(seconds / 60)),  # 0분 표기 방지(최소 1분)
        "meters": meters,
        "path": _extract_line(features),
    }


async def fetch_pedestrian_route(sx: float, sy: float, ex: float, ey: float) -> dict | None:
    """보행자경로. sx/ex=lng, sy/ey=lat. 실패 시 None."""
    body = {
        "startX": sx, "startY": sy, "endX": ex, "endY": ey,
        "startName": "출발", "endName": "도착",
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
    }
    return await _fetch(_PEDESTRIAN_PATH, body)


async def fetch_car_route(sx: float, sy: float, ex: float, ey: float) -> dict | None:
    """자동차경로. sx/ex=lng, sy/ey=lat. 실패 시 None."""
    body = {
        "startX": sx, "startY": sy, "endX": ex, "endY": ey,
        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        "searchOption": "0", "trafficInfo": "N",
    }
    return await _fetch(_CAR_PATH, body)
