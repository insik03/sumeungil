"""검증 스크립트 — 상세 사진 슬라이드(부록 P.1) + 축제 상세(부록 P.2). 서버·원천 호출 0.

TourAPI 클라이언트를 스텁으로 바꿔치기해 조립 규칙·graceful·문구만 확인한다.
(실제 데이터 확인은 서버를 띄운 뒤 /api/v1/places/{id} · /api/v1/festivals/{id} 로 별도 확인)

검증 항목:
  (a) images 조립: 대표 첫 번째 + 중복 URL 제거 + 총 8장 상한 + 7일 캐시(호출 1회)
  (b) detailImage2 429 → [대표사진 1장] (빈 배열 아님), 실패는 짧게만 캐시
  (c) 표준데이터 축제(id >= 900,000,000) → images [] + detailImage2 미호출
  (d) timing 판정 5케이스(ongoing 말일 / D-3 / 종료 지남 / 장기 진행 / 오늘 시작)
  (e) weather 예보 범위 밖 → available=false + notice, 범위 안 → 실측 POP 문구

실행:
    cd projects/sumeungil-build/backend
    py scripts/verify_detail_images.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cache.memory import MemoryCache  # noqa: E402
from app.clients import tourapi_detail_client  # noqa: E402
from app.clients.tourapi_detail_client import TourApiDetailError  # noqa: E402
from app.schemas.places import Festival  # noqa: E402
from app.services import festival_detail_service as fds  # noqa: E402
from app.services import photo_service, spot_detail_service  # noqa: E402
from app.services.photo_service import Photo  # noqa: E402
from app.services.weather_provider import WeatherProvider, WeatherSnapshot  # noqa: E402

FAILS: list[str] = []
CALLS: dict[str, int] = {"detail_image": 0}


def check(label: str, cond: bool, got=None) -> None:
    print(f"[{'OK  ' if cond else 'FAIL'}] {label}" + ("" if cond else f"  <- got={got!r}"))
    if not cond:
        FAILS.append(label)


HOST = "http://tong.visitkorea.or.kr/cms/resource"


def _img(n: int) -> dict:
    return {"originimgurl": f"{HOST}/{n}.jpg", "smallimageurl": ""}


def stub_images(items: list[dict]):
    async def _fetch(content_id: int, num_of_rows: int = 5) -> list[dict]:
        CALLS["detail_image"] += 1
        return items
    return _fetch


async def stub_429(content_id: int, num_of_rows: int = 5) -> list[dict]:
    CALLS["detail_image"] += 1
    raise TourApiDetailError("upstream status 429")


class StubWeather(WeatherProvider):
    def __init__(self, pop: int | None) -> None:
        self.pop = pop

    async def get_region_forecast(self, region_code: str):
        if self.pop is None:
            return None
        return WeatherSnapshot(region_code=region_code, precip_probability=self.pop, source="stub")


# ---------- (a) images 조립 ----------

async def test_assembly() -> None:
    print("\n--- (a) images 조립: 대표 우선 / 중복 제거 / 8장 상한 / 캐시 ---")
    cache = MemoryCache()
    # 대표사진과 겹치는 URL 1건 + 그 외 9건 → 중복 제거 후 상한 8
    items = [{"originimgurl": f"{HOST}/rep.jpg"}] + [_img(i) for i in range(1, 10)]
    tourapi_detail_client.fetch_detail_images = stub_images(items)
    CALLS["detail_image"] = 0

    photo = Photo(url="https://tong.visitkorea.or.kr/cms/resource/rep.jpg",
                  credit="한국관광공사", source="firstimage")
    images = await spot_detail_service.build_images(1234, photo, cache)

    urls = [i.url for i in images]
    check("대표사진이 첫 번째", urls[0] == photo.url, urls[:1])
    check("총 8장 상한", len(images) == 8, len(images))
    check("중복 URL 제거(대표와 같은 사진 1회만)", len(set(urls)) == len(urls), urls)
    check("전부 https 승격", all(u.startswith("https://") for u in urls), urls)
    check("추가사진 credit=한국관광공사",
          all(i.credit == "한국관광공사" for i in images), [i.credit for i in images])

    await spot_detail_service.build_images(1234, photo, cache)
    check("7일 캐시 — 재조회 시 원천 호출 없음", CALLS["detail_image"] == 1, CALLS["detail_image"])

    # 대표사진이 없어도 추가사진만으로 목록을 만든다
    CALLS["detail_image"] = 0
    only_extra = await spot_detail_service.build_images(5678, Photo(url=None), MemoryCache())
    check("대표 없음 → 추가사진만", len(only_extra) == 8 and only_extra[0].url.endswith("rep.jpg"),
          [i.url for i in only_extra[:1]])


# ---------- (b) 429 graceful ----------

async def test_429() -> None:
    print("\n--- (b) detailImage2 429 → [대표사진 1장] ---")
    cache = MemoryCache()
    tourapi_detail_client.fetch_detail_images = stub_429
    CALLS["detail_image"] = 0

    photo = Photo(url="https://tong.visitkorea.or.kr/cms/resource/rep.jpg", credit="한국관광공사")
    images = await spot_detail_service.build_images(999, photo, cache)
    check("429여도 대표사진 1장 유지", [i.url for i in images] == [photo.url], images)
    check("예외 전파 없음(위에서 도달)", True)

    none_photo = await spot_detail_service.build_images(998, Photo(url=None), cache)
    check("대표사진도 없으면 빈 배열", none_photo == [], none_photo)

    hit = await cache.get("spot_images:999")
    check("실패는 빈 목록으로 짧게만 캐시(다음 날 재시도)", hit == {"urls": []}, hit)


# ---------- (c) 표준데이터 축제 ----------

async def test_synthetic() -> None:
    print("\n--- (c) 표준데이터 축제(id>=900M) → images [] + 원천 미호출 ---")
    tourapi_detail_client.fetch_detail_images = stub_images([_img(1), _img(2)])
    CALLS["detail_image"] = 0
    cache = MemoryCache()

    std = Festival(id=923_456_789, title="표준데이터축제", start_date="2026-08-01",
                   end_date="2026-08-03", address="부산광역시 해운대구", image_url=None)
    images = await fds.build_images(std, cache)
    check("표준데이터 → images []", images == [], images)
    check("표준데이터 → detailImage2 호출 0", CALLS["detail_image"] == 0, CALLS["detail_image"])

    tour = Festival(id=2_736_033, title="투어API축제", start_date="2026-08-01",
                    end_date="2026-08-03", address=None,
                    image_url="https://tong.visitkorea.or.kr/cms/resource/rep.jpg")
    t_images = await fds.build_images(tour, cache)
    check("TourAPI 축제 → 대표 + 추가 사진", [i.url for i in t_images] == [
        "https://tong.visitkorea.or.kr/cms/resource/rep.jpg",
        "https://tong.visitkorea.or.kr/cms/resource/1.jpg",
        "https://tong.visitkorea.or.kr/cms/resource/2.jpg",
    ], [i.url for i in t_images])
    check("TourAPI 축제 → detailImage2 1회", CALLS["detail_image"] == 1, CALLS["detail_image"])


# ---------- (d) timing 5케이스 ----------

def _f(start: str, end: str) -> Festival:
    return Festival(id=1, title="t", start_date=start, end_date=end)


def test_timing() -> None:
    print("\n--- (d) timing 판정 5케이스 ---")
    today = date(2026, 8, 5)  # 수요일

    t1 = fds.build_timing(_f("2026-08-01", "2026-08-05"), today)
    check("ongoing 말일 → days_left=1 / '오늘이 마지막 날이에요'",
          (t1.status, t1.days_left, t1.tip) == ("ongoing", 1, "오늘이 마지막 날이에요"), t1)

    t2 = fds.build_timing(_f("2026-08-08", "2026-08-10"), today)
    check("시작 D-3 → upcoming / d_day=3 / '곧 시작해요'",
          (t2.status, t2.d_day, t2.tip) == ("upcoming", 3, "D-3, 곧 시작해요"), t2)

    t3 = fds.build_timing(_f("2026-07-01", "2026-08-04"), today)
    check("종료 지남 → ended / d_day·days_left null",
          (t3.status, t3.d_day, t3.days_left, t3.tip)
          == ("ended", None, None, "이미 종료된 축제예요"), t3)

    t4 = fds.build_timing(_f("2026-01-01", "2026-12-31"), today)
    check("장기 진행 → '장기 진행 중인 축제예요'",
          (t4.status, t4.tip) == ("ongoing", "장기 진행 중인 축제예요"), t4)

    t5 = fds.build_timing(_f("2026-08-05", "2026-08-09"), today)
    check("오늘 시작 → '오늘 시작한 축제예요'",
          (t5.status, t5.days_left, t5.tip) == ("ongoing", 5, "오늘 시작한 축제예요"), t5)

    # 보조 케이스 — 주말 종료 / 하루짜리
    t6 = fds.build_timing(_f("2026-08-01", "2026-08-09"), today)  # 8/9 = 일요일
    check("(보조) 주말 종료 임박 → '이번 주말이 마지막이에요'",
          t6.tip == "이번 주말이 마지막이에요", t6)
    t7 = fds.build_timing(_f("2026-08-05", "2026-08-05"), today)
    check("(보조) 오늘 하루만 → '오늘 하루만 열리는 축제예요'",
          t7.tip == "오늘 하루만 열리는 축제예요", t7)


# ---------- (e) weather ----------

async def test_weather() -> None:
    print("\n--- (e) weather 범위/사유 ---")
    today = date(2026, 8, 5)

    out = await fds.build_weather(_f("2026-08-20", "2026-08-22"), "26350", today, StubWeather(10))
    check("예보 범위 밖 → available=false + notice",
          out.available is False and out.summary is None
          and out.notice == "축제 기간이 예보 범위 밖이에요", out)

    no_region = await fds.build_weather(_f("2026-08-01", "2026-08-09"), None, today, StubWeather(10))
    check("지역 미매칭 → available=false + 지역 notice",
          no_region.available is False and "지역" in (no_region.notice or ""), no_region)

    no_data = await fds.build_weather(_f("2026-08-01", "2026-08-09"), "26350", today,
                                      StubWeather(None))
    check("원천 미확보 → available=false + notice(수치 없음)",
          no_data.available is False and no_data.summary is None and no_data.notice, no_data)

    ok = await fds.build_weather(_f("2026-08-01", "2026-08-09"), "26350", today, StubWeather(70))
    check("범위 안 + POP 70 → available=true / 실측 수치 문구",
          ok.available is True and ok.summary is not None and "70%" in ok.summary, ok)

    ok2 = await fds.build_weather(_f("2026-08-05", "2026-08-05"), "26350", today, StubWeather(10))
    check("당일 축제 + POP 10 → 야외 문구", ok2.available and "10%" in (ok2.summary or ""), ok2)


# ---------- OpenAPI 프로퍼티 확인 ----------

def test_openapi() -> None:
    print("\n--- OpenAPI 스키마 노출 확인 ---")
    from app.main import app  # noqa: PLC0415

    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    check("SpotDetail.images 존재", "images" in schemas["SpotDetail"]["properties"])
    check("SpotImage 스키마(url/credit)",
          set(schemas["SpotImage"]["properties"]) == {"url", "credit"})
    detail = spec["paths"].get("/api/v1/festivals/{festival_id}", {}).get("get")
    check("GET /api/v1/festivals/{festival_id} 라우트 존재", detail is not None)
    props = schemas["FestivalDetailResponse"]["properties"]
    check("FestivalDetailResponse 기존 6필드 + 요약/제공자",
          set(props) == {"festival", "region", "description", "images", "timing", "weather", "ai_summary", "ai_provider"}, set(props))
    check("Festival(부록 K) 필드 불변(7개)",
          set(schemas["Festival"]["properties"])
          == {"id", "title", "start_date", "end_date", "address", "image_url", "ongoing"})

    # 부록 O 레이트 리밋: 새 GET 은 화이트리스트가 아니라 폴백이라 자동으로 default 버킷.
    from app.middleware.rate_limit import BUCKET_DEFAULT, resolve_bucket  # noqa: PLC0415

    check("신규 라우트 = default 버킷(추가 등록 불필요)",
          resolve_bucket("GET", "/api/v1/festivals/2736033") == BUCKET_DEFAULT)


async def main() -> int:
    await test_assembly()
    await test_429()
    await test_synthetic()
    test_timing()
    await test_weather()
    test_openapi()
    print("\n" + ("전부 통과" if not FAILS else f"실패 {len(FAILS)}건: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
