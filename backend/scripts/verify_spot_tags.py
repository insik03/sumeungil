# -*- coding: utf-8 -*-
"""스팟 파생 태그(소개글 → 태그 → 영구 캐시 → 매칭도) 회귀 검증 — DB·네트워크 불필요.

    py scripts/verify_spot_tags.py

검증 항목
  (a) 추출기: 근거 키워드가 있을 때만 붙고, 약한 키워드는 2번 이상, 부정 표현은 제외, 상한·결정론
  (b) 캐시: 저장/읽기, 소개글 해시가 같으면 재추출 없음, 바뀌면 재생성, 규칙 버전이 다르면 무효
  (c) 배치: 첫 실행은 생성, 재실행은 API 도 안 부름(stale_days 이내), 소개글 불변이면 추출 생략, 429 로 멈춰도 저장
  (d) 저장소 overlay: 시드 태그는 유지하고 파생 태그를 더한다, 캐시가 바뀌면 재시작 없이 반영
  (e) 가중 코사인: weights 없으면 종전 이진 코사인과 같고, 희소 태그 일치가 흔한 태그 일치보다 높다
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.ai import spot_fit, tag_registry  # noqa: E402
from app.ai.spot_tagger import RULES_VERSION, derive_tags  # noqa: E402
from app.repositories.spot_repo import JsonSpotRepository  # noqa: E402
from app.repositories.spot_tag_cache import SpotTagCache  # noqa: E402
from app.repositories.summary_repo import source_hash  # noqa: E402
from build_spot_summaries import QuotaExhausted  # noqa: E402
from build_spot_tags import run_batch  # noqa: E402

FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAIL.append(name)


def vals(tags) -> set[str]:
    return {v for _a, v in tags}


print("\n[a] 추출기")
check("빈 소개글 → 태그 없음", derive_tags("") == [] and derive_tags(None) == [] and derive_tags("   ") == [])
check("근거 없는 소개글 → 태그 없음", derive_tags("1990년에 개업한 식당이다. 주차 가능.") == [])
check("강한 키워드 1개 → 태그", "calm" in vals(derive_tags("숲속에 자리한 한적한 마을이다.")))
check("약한 키워드 1개는 부족", "romantic" not in vals(derive_tags("가족, 연인, 친구와 함께 즐기기 좋다.")))
check("약한 키워드 2개 겹치면 인정", "romantic" in vals(derive_tags("연인과 커플이 많이 찾는 곳이다.")))
check("부정 표현은 활기 근거가 아님", "lively" not in vals(derive_tags("북적이지 않는 조용한 골목이다.")))
check("소개글에 없는 성격은 안 붙임", not (vals(derive_tags("산책로를 따라 걷는 길이다.")) & {"romantic", "family_friendly", "unique"}))
many = "한적 힐링 로맨틱 사색 이색 카페 산책로 포토존 폭포 축제 공방"
out = derive_tags(many)
check("mood 최대 2·spot_pref 최대 2", sum(a == "mood" for a, _ in out) <= 2 and sum(a == "spot_pref" for a, _ in out) <= 2, str(out))
check("결정론(같은 입력 = 같은 출력)", derive_tags(many) == derive_tags(many))
check("결과 태그는 전부 레지스트리에 실재", all(tag_registry.is_valid(a, v) for a, v in out))

print("\n[b] 캐시")
with tempfile.TemporaryDirectory() as d:
    c = SpotTagCache(d)
    h1 = source_hash("한적한 숲길")
    c.put(1, h1, [("mood", "calm")])
    c.save()
    c2 = SpotTagCache(d).load()
    check("저장 후 읽기", c2.tags(1) == [["mood", "calm"]])
    check("같은 해시 → 재추출 불필요", c2.needs_extract(1, h1) is False)
    check("소개글이 바뀌면 재생성 필요", c2.needs_extract(1, source_hash("완전히 다른 소개글")) is True)
    check("처음 보는 스팟은 필요", c2.needs_extract(2, h1) is True)
    check("방금 확인 → fresh", c2.is_fresh(1, 30) is True and c2.is_fresh(1, 0) is False)
    # 규칙 버전이 다르면 무효
    doc = json.loads(c2.path.read_text(encoding="utf-8"))
    doc["spots"]["1"]["v"] = "0-old"
    c2.path.write_text(json.dumps(doc), encoding="utf-8")
    c3 = SpotTagCache(d).load()
    check("낡은 규칙 결과는 태그로 안 쓴다", c3.tags(1) == [])
    check("낡은 규칙이면 재생성 필요·fresh 아님", c3.needs_extract(1, h1) is True and c3.is_fresh(1, 30) is False)
    # 깨진 파일은 빈 캐시
    c3.path.write_text("{ not json", encoding="utf-8")
    check("깨진 파일 → 빈 캐시(예외 없음)", len(SpotTagCache(d).load()) == 0)

print("\n[c] 배치")
overviews = {10: "한적한 숲속 산책로. 조용하다.", 11: "전통시장이다. 오일장이 열린다.", 12: None}
calls: list[int] = []


async def fake_fetch(sid, limiter):
    calls.append(sid)
    return overviews[sid]


with tempfile.TemporaryDirectory() as d:
    cache = SpotTagCache(d)
    s1 = asyncio.run(run_batch([10, 11, 12], {10, 11, 12}, cache, None, 60, fetch=fake_fetch))
    check("첫 실행: 2곳 생성·소개글 없음 1곳", s1.generated == 2 and s1.no_overview == 1, str(s1))
    check("파일에 저장됨", SpotTagCache(d).load().tags(10) != [] and "traditional_market" in {v for _a, v in SpotTagCache(d).load().tags(11)})
    calls.clear()
    s2 = asyncio.run(run_batch([10, 11, 12], {10, 11, 12}, SpotTagCache(d).load(), None, 60, fetch=fake_fetch))
    check("재실행: 전부 fresh 라 API 호출 0", s2.fresh_skipped == 3 and not calls, f"{s2} calls={calls}")
    s3 = asyncio.run(run_batch([10, 11], {10, 11}, SpotTagCache(d).load(), None, 0, fetch=fake_fetch))
    check("stale_days=0: 다시 받아도 소개글 같으면 추출 생략", s3.unchanged == 2 and s3.generated == 0, str(s3))
    overviews[10] = "번화가에 자리한 활기 넘치는 곳이다."
    s4 = asyncio.run(run_batch([10, 11], {10, 11}, SpotTagCache(d).load(), None, 0, fetch=fake_fetch))
    check("소개글이 바뀐 스팟만 재생성", s4.generated == 1 and s4.unchanged == 1, str(s4))
    check("바뀐 내용이 반영됨", "lively" in {v for _a, v in SpotTagCache(d).load().tags(10)})

with tempfile.TemporaryDirectory() as d:
    n = {"i": 0}

    async def quota_fetch(sid, limiter):
        n["i"] += 1
        if n["i"] > 2:
            raise QuotaExhausted("429")
        return "한적한 곳"

    st = asyncio.run(run_batch([20, 21, 22, 23], {20, 21, 22, 23}, SpotTagCache(d), None, 60, fetch=quota_fetch))
    saved = SpotTagCache(d).load()
    check("429 로 멈추면 quota_aborted, 그때까지 만든 것은 저장", st.quota_aborted and st.generated == 2 and saved.tags(20) and saved.tags(21), str(st))

print("\n[d] 저장소 overlay")
with tempfile.TemporaryDirectory() as d:
    seed = {"spots": [
        {"id": 1, "name": "A카페", "category": "cafe", "region_code": "11", "lat": 37.5, "lng": 127.0,
         "tag_values": [["spot_pref", "local_cafe"]]},
        {"id": 2, "name": "B산책로", "category": "trail", "region_code": "11", "lat": 37.6, "lng": 127.1,
         "tag_values": [["spot_pref", "walking_trail"]]},
    ]}
    seed_path = Path(d) / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    cache = SpotTagCache(d)
    repo = JsonSpotRepository(seed_path, tag_cache=cache)
    repo.TAG_CACHE_CHECK_SEC = 0.0
    a = repo.by_id(1)
    check("캐시 없으면 시드 태그만", a.tags == [("spot_pref", "local_cafe")])
    cache.put(1, source_hash("x"), [("mood", "calm"), ("spot_pref", "local_cafe")])
    cache.save()
    a = repo.by_region("11")[0]
    check("캐시가 생기면 재시작 없이 태그 추가", ("mood", "calm") in a.tags and a.tags[0] == ("spot_pref", "local_cafe"), str(a.tags))
    check("중복 태그는 한 번만", a.tags.count(("spot_pref", "local_cafe")) == 1)
    check("벡터에도 반영", a.tag_vector[tag_registry.vector_index("mood", "calm")] == 1.0)
    check("캐시 없는 스팟은 그대로", repo.by_id(2).tags == [("spot_pref", "walking_trail")])

print("\n[e] 가중 코사인")
lo, _hi = tag_registry.MOOD_SPOT_SLICE
u = [0.0] * tag_registry.VECTOR_DIM
for i in (lo, lo + 7, lo + 12):  # calm + local_cafe + walking_trail 쯤(축 무관, 값만 필요)
    u[i] = 1.0
common, rare = [0.0] * tag_registry.VECTOR_DIM, [0.0] * tag_registry.VECTOR_DIM
common[lo + 7] = 1.0
rare[lo] = 1.0
check("weights 없으면 종전 이진 코사인과 같다", spot_fit.cosine_spot_fit(u, common) == spot_fit.cosine_spot_fit(u, common, None))
w = [1.0] * tag_registry.VECTOR_DIM
w[lo + 7] = 1.0
w[lo] = 8.0
check("희소 태그 일치가 흔한 태그 일치보다 높다", spot_fit.cosine_spot_fit(u, rare, w) > spot_fit.cosine_spot_fit(u, common, w))
check("점수는 [0,1] 안", 0.0 <= spot_fit.cosine_spot_fit(u, rare, w) <= 1.0)
check("한쪽이 0벡터면 0", spot_fit.cosine_spot_fit(u, [0.0] * tag_registry.VECTOR_DIM, w) == 0.0)
uniq = {round(spot_fit.cosine_spot_fit(u, v), 4) for v in (common, rare)}
uniq_w = {round(spot_fit.cosine_spot_fit(u, v, w), 4) for v in (common, rare)}
check("가중치를 쓰면 같은 점수로 뭉치던 두 스팟이 갈린다", len(uniq) == 1 and len(uniq_w) == 2, f"{uniq} {uniq_w}")

print(f"\n== {'ALL PASS' if not FAIL else 'FAIL'} ==", FAIL or "")
sys.exit(1 if FAIL else 0)
