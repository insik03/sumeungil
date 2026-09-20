# 스팟 파생 태그 (매칭도 세분화)

시드 스팟의 72%가 태그 1개(카테고리에서 파생)뿐이라 매칭도가 몇 가지 값에 몰렸다. 소개글에서 분위기·특성 태그를 더 뽑아 **한 번 만들고 캐시**한다.

## 흐름
1. `scripts/build_spot_tags.py`(배치) → TourAPI `detailCommon2` 소개글 → `app/ai/spot_tagger.py` 규칙 추출 → `<SUMMARY_STORE_DIR>/spot_tags.json`
2. 서버(`JsonSpotRepository`)가 이 파일을 시드 태그에 **더해** 태그벡터를 만든다. 파일이 바뀌면 재시작 없이 1분 안에 반영. 요청 처리 중엔 추출도 API 호출도 없다.
3. 매칭도는 희소한 태그가 맞을수록 높게(IDF 가중 코사인). 추천·비교·코스가 같은 가중치를 쓴다.
4. 화면은 %가 아니라 3단계(잘 맞아요/무난해요/참고용).

## 다시 만드는 조건 (그 외엔 캐시)
- 소개글 sha256 이 달라졌을 때
- `RULES_VERSION` 을 올렸을 때(규칙 수정 시 반드시 올린다)
- `--stale-days`(기본 60일) 지나 소개글을 다시 확인할 때 — 확인해서 같으면 추출은 생략

## 운영
```bash
docker compose exec -d backend python scripts/build_spot_tags.py --all   # 백그라운드, 429 나면 저장하고 멈춤 → 다음날 이어서
docker compose exec backend python scripts/build_spot_tags.py --report-only
```
분당 25건(요약 배치와 같은 잠금·쿼터). 우선순위는 트렌딩 → 테마 컬렉션 → 숨은 스팟 → 나머지.

## 규칙 튜닝
`spot_tagger._RULES` 의 (강한, 약한) 키워드. 강한 것은 1번, 약한 것은 2번 이상 나와야 인정. 바꾸면 `RULES_VERSION` 올리고 `verify_spot_tags.py` 통과 확인.
