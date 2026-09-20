# -*- coding: utf-8 -*-
"""기상청 초단기실황·초단기예보 클라이언트 — **지점 단위** "지금 날씨" (2026-09-20).

기존 `kma_weather_client`(D18 관광코스별 날씨)와 **다른 원천이고 다른 해상도**다.

  - D18(TourStnInfoService1): 관광코스 단위 → 해상도가 **시도**다. 경주와 다른 경북 시를
    구분하지 못한다(그 모듈 docstring 참고). 값은 POP(강수확률) 하나만 rerank 에 쓴다.
  - 이 모듈(VilageFcstInfoService_2.0): 기상청 **5km 격자(nx, ny)** 단위다. 스팟·축제의
    위경도를 격자로 바꿔 부르면 "이 장소에 지금 비가 오는지"를 그 장소 기준으로 답할 수 있다.

두 오퍼레이션을 쓴다(둘 다 실호출로 확인, 2026-09-20):
  - getUltraSrtNcst(초단기실황) : **관측값**. PTY(강수형태)·T1H(기온)·REH(습도)·RN1(1시간 강수량).
    매시 정시 관측을 40분쯤에 공개한다 → 안전하게 45분 전 시각을 base_time 으로 쓴다.
    SKY(하늘상태)가 **없다** — 실황에는 구름 관측이 포함되지 않는다.
  - getUltraSrtFcst(초단기예보) : SKY 를 여기서만 얻는다. 매시 30분에 발표한다.

그래서 "비/눈"은 실황(PTY)으로, "맑음/구름/흐림"은 예보(SKY)로 판정한다. 비가 오는 중이면
SKY 는 보지 않으므로 두 번째 호출을 생략한다 — 쿼터를 아끼는 지점이다.

정직성: 원천이 실패하거나 값이 없으면 **None 을 돌려준다**. 날씨를 지어내지 않는다.
serviceKey 는 params 로만 전달하고 로그에 남기지 않는다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from ..config import settings
from ..util.redact import redact_secrets
from ..util.time import now_kst

logger = logging.getLogger("sumeungil.kma_ncst")

_BASE = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
NCST_URL = f"{_BASE}/getUltraSrtNcst"
FCST_URL = f"{_BASE}/getUltraSrtFcst"

DEFAULT_TIMEOUT_SEC = 6.0

# 실황은 정시 관측이 40분경 공개된다. 45분을 빼면 "가장 최근에 확실히 공개된 정시"가 나온다.
_NCST_PUBLISH_LAG_MIN = 45
# 초단기예보는 매시 30분 발표. 45분을 빼면 직전 발표분을 안전하게 가리킨다.
_FCST_PUBLISH_LAG_MIN = 45


class KmaNcstError(RuntimeError):
    """원천 호출·파싱 실패. 호출부는 날씨 없음(None)으로 강등한다."""


# ---------- 위경도 → 기상청 격자(nx, ny) ----------
# 기상청이 공개한 Lambert Conformal Conic 파라미터. 상수는 기상청 배포 코드와 동일하다
# (임의로 고른 값이 아니다 — 바꾸면 격자가 통째로 어긋난다).
_RE = 6371.00877     # 지구 반경(km)
_GRID = 5.0          # 격자 간격(km)
_SLAT1 = 30.0        # 표준 위도 1
_SLAT2 = 60.0        # 표준 위도 2
_OLON = 126.0        # 기준점 경도
_OLAT = 38.0         # 기준점 위도
_XO = 210 / _GRID    # 기준점 X 격자
_YO = 675 / _GRID    # 기준점 Y 격자


@dataclass(frozen=True)
class Grid:
    nx: int
    ny: int


def to_grid(lat: float, lng: float) -> Grid:
    """위경도 → 기상청 5km 격자. 기상청 배포 변환식 그대로다."""
    degrad = math.pi / 180.0
    re = _RE / _GRID
    slat1 = _SLAT1 * degrad
    slat2 = _SLAT2 * degrad
    olon = _OLON * degrad
    olat = _OLAT * degrad

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)

    ra = math.tan(math.pi * 0.25 + lat * degrad * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lng * degrad - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    return Grid(
        nx=int(math.floor(ra * math.sin(theta) + _XO + 1.5)),
        ny=int(math.floor(ro - ra * math.cos(theta) + _YO + 1.5)),
    )


# ---------- 코드 → 한국어 ----------
# PTY(강수형태) 실황 코드표. 초단기예보도 같은 코드를 쓴다.
PTY_LABEL: dict[str, str] = {
    "0": "",          # 없음 — SKY 로 판정한다
    "1": "비",
    "2": "비/눈",
    "3": "눈",
    "5": "빗방울",
    "6": "빗방울·눈날림",
    "7": "눈날림",
}
# SKY(하늘상태). 4는 원천 코드표에 없지만 과거 값이 섞여 들어오는 경우가 있어 흐림으로 본다.
SKY_LABEL: dict[str, str] = {"1": "맑음", "3": "구름많음", "4": "흐림"}


@dataclass(frozen=True)
class LiveWeather:
    """한 격자의 "지금" 날씨. 값이 없는 필드는 None 이고, 지어내지 않는다."""

    nx: int
    ny: int
    condition: str            # "비" / "맑음" 등. PTY 우선, 없으면 SKY.
    precipitation: bool       # 지금 비·눈이 오는가(PTY != 0)
    temperature_c: float | None
    humidity_pct: int | None
    rain_1h_mm: float | None
    observed_at: str          # "YYYY-MM-DD HH:MM" (KST) — 언제 기준인지 밝힌다


def _items(payload: dict) -> list[dict]:
    body = (payload or {}).get("response", {}).get("body", {})
    items = (body.get("items") or {}).get("item")
    if isinstance(items, list):
        return items
    return [items] if isinstance(items, dict) else []


def _result_code(payload: dict) -> str | None:
    return ((payload or {}).get("response", {}).get("header", {}) or {}).get("resultCode")


async def _get(url: str, params: dict, timeout: float) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise KmaNcstError(f"요청 실패: {redact_secrets(str(exc))}") from exc
    if resp.status_code != 200:
        raise KmaNcstError(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:  # 한도 초과 등은 XML 로 온다
        raise KmaNcstError(f"JSON 아님: {redact_secrets(resp.text[:160])}") from exc
    code = _result_code(payload)
    if code not in ("00", None):
        raise KmaNcstError(f"resultCode={code}")
    return payload


async def fetch_live_weather(
    lat: float, lng: float, *, timeout: float = DEFAULT_TIMEOUT_SEC
) -> LiveWeather | None:
    """위경도의 "지금" 날씨. 실패·값없음이면 None(호출부가 graceful 처리)."""
    key = (settings.public_data_api_key or "").strip()
    if not key:
        return None
    grid = to_grid(lat, lng)

    now = now_kst()
    base = now - timedelta(minutes=_NCST_PUBLISH_LAG_MIN)
    try:
        payload = await _get(
            NCST_URL,
            {
                "serviceKey": key,
                "pageNo": 1,
                "numOfRows": 20,
                "dataType": "JSON",
                "base_date": base.strftime("%Y%m%d"),
                "base_time": base.strftime("%H00"),
                "nx": grid.nx,
                "ny": grid.ny,
            },
            timeout,
        )
    except KmaNcstError as exc:
        logger.info("초단기실황 실패(날씨 없음으로 강등) nx=%s ny=%s: %s", grid.nx, grid.ny, exc)
        return None

    values = {i.get("category"): i.get("obsrValue") for i in _items(payload) if i.get("category")}
    if not values:
        return None

    def _num(key_: str) -> float | None:
        raw = values.get(key_)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    pty = str(values.get("PTY") or "0")
    condition = PTY_LABEL.get(pty, "")
    precipitation = bool(condition)

    # 비가 안 오는 중일 때만 하늘상태를 따로 받아 온다 — 비가 오면 SKY 는 화면에 쓸 일이 없다.
    if not condition:
        condition = await _fetch_sky(key, grid, timeout) or "정보없음"

    temp = _num("T1H")
    humid = _num("REH")
    rain = _num("RN1")
    return LiveWeather(
        nx=grid.nx,
        ny=grid.ny,
        condition=condition,
        precipitation=precipitation,
        temperature_c=round(temp, 1) if temp is not None else None,
        humidity_pct=int(humid) if humid is not None else None,
        rain_1h_mm=round(rain, 1) if rain is not None else None,
        observed_at=base.strftime("%Y-%m-%d %H:00"),
    )


async def _fetch_sky(key: str, grid: Grid, timeout: float) -> str | None:
    """SKY(하늘상태)는 초단기**예보**에만 있다. 실패하면 None → 호출부가 "정보없음"."""
    base = now_kst() - timedelta(minutes=_FCST_PUBLISH_LAG_MIN)
    try:
        payload = await _get(
            FCST_URL,
            {
                "serviceKey": key,
                "pageNo": 1,
                "numOfRows": 60,
                "dataType": "JSON",
                "base_date": base.strftime("%Y%m%d"),
                "base_time": base.strftime("%H30"),
                "nx": grid.nx,
                "ny": grid.ny,
            },
            timeout,
        )
    except KmaNcstError as exc:
        logger.info("초단기예보(SKY) 실패 nx=%s ny=%s: %s", grid.nx, grid.ny, exc)
        return None
    # 가장 이른 예보시각의 SKY 를 쓴다(응답은 시각 오름차순이 아닐 수 있어 직접 고른다).
    skies = [i for i in _items(payload) if i.get("category") == "SKY"]
    if not skies:
        return None
    first = min(skies, key=lambda i: f"{i.get('fcstDate','')}{i.get('fcstTime','')}")
    return SKY_LABEL.get(str(first.get("fcstValue")))


__all__ = ("LiveWeather", "fetch_live_weather", "to_grid", "Grid", "KmaNcstError",
           "PTY_LABEL", "SKY_LABEL")
