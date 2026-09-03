# 지역 지도 스케치 — 작업 재료 (2026-08-29, 대표 지시)

목표: 홈 데모(`frontend/components/demo-home/DemoHome.tsx`)의 히어로 우측 상단 지도
자리(`.routeStage`)가 지금은 부산/기장으로 고정된 손그림 SVG인데, **도시 선택 버튼을 누를
때마다 그 도시의 진짜 경계 지도가 뜨고, 그 안에 실제 코스 스팟을 선으로 잇는** 걸로 바꾼다.
대표 지시: "구의 경계도 나눠야 좀 볼 만할 거 같다" — 시/도 외곽선만이 아니라 그 안의
구/군 경계도 같이 보여야 한다.

## 이 폴더에 있는 것

- **`kr-sido-boundaries.json`** — 시/도 17곳 외곽 경계(진짜 좌표, 지어낸 값 아님).
  출처: [southkorea/southkorea-maps](https://github.com/southkorea/southkorea-maps)
  (통계청 2018년 경계, 공개 데이터). Douglas-Peucker로 단순화(epsilon 0.001).
  형식: `{ "<우리 앱 sido_code>": { "name_ko", "name_eng", "ring": [[lng,lat], ...] } }`.
  **키는 원본 데이터셋의 code가 아니라 우리 앱 코드로 이미 리매핑해놨다** —
  `frontend/public/landmarks/{code}.png`(부산=26, 서울=11 등)와 같은 체계.
- **`kr-sigungu-boundaries.json`** — 시/군/구 250곳 경계(같은 출처, epsilon 0.0006,
  섬 등 멀티폴리곤은 링 전부 보존). 형식: `{ "<원본 code>": { "name_ko", "name_eng", "rings": [[[lng,lat],...], ...] } }`.
  **주의: 이 파일의 code는 우리 앱 region_code와 다른 체계다**(예: 종로구가 여기선
  "11010", 우리 앱(`backend/app/regions/seed.py`, `REGIONS`)에선 "11110"). 매칭은
  `name_ko`/`name_eng`로 해야 한다 — 두 데이터셋 다 사람이 만든 지명 표기라 완전 일치가
  아닐 수 있으니(예: "-시"/"-군"/"-구" 접미사 차이) 접미사 제거 후 비교하는 걸 권장.
  seed.py의 `_strip_suffix` 함수가 이미 그 로직을 갖고 있다(참고용으로 재사용해도 됨).
- **`seoul-course-mockup-sketch.html`** — 오케스트레이터가 미리 만든 러프 스케치.
  서울 시/도 경계만(구 경계 없음) + 실제 스팟 4곳(난지한강공원/경복궁/남산팔각정/서울숲,
  `backend/app/spots/data/spots_seed.json`에서 뽑은 실좌표) 좌표투영 + route선. 브라우저로
  열어서 톤(종이색/먹색/시그널 코랄)과 좌표투영 방식 참고용 — 최종 디자인은 아니다.

## 좌표 투영 방법(스케치에 이미 구현, 재사용 가능)

1. 지역 경계의 위경도 bounding box를 구한다.
2. 위도에 따른 경도 왜곡을 보정한다(`lng_scale = cos(중위도)`) — 안 하면 위쪽 지역일수록
   가로로 퍼져 보인다.
3. bbox를 SVG viewBox에 맞게 scale+offset, **위도는 뒤집는다**(북=위, SVG Y는 아래로 증가).
4. 스팟의 실제 lat/lng를 같은 transform으로 투영하면 지도 위 정확한 위치가 나온다.

## 만들어줬으면 하는 것 (Codex에게)

1. **재사용 가능한 지역 지도 컴포넌트** — 현재 선택된 도시(대표가 이미 만든 도시 선택
   버튼들, `Hero.tsx`/`HomeContent.tsx`의 지역 선택 상태와 같은 패턴)에 따라 해당 시/도
   외곽선 + 그 안의 구/군 경계선을 그린다. 부산 하나로 고정된 지금 `.routeStage`/`.mapHeading`/
   `.regionMap` 등(DemoHome.module.css)을 대체하거나 일반화한다.
2. **디자인 완성도** — 지금 부산/기장 손그림 버전의 톤(종이 배경, 격자 패턴, 먹색 해안선,
   코랄 점선 경로, 원형 핀+번호)을 기준으로 삼되, 17개 지역 어디를 골라도 어색하지 않게
   다듬어라(예: 내륙 지역은 바다가 없으니 해안선 대신 다른 시각 장치가 필요할 수 있음).
3. **실코스 데이터 연결 — 선행 이슈 있음.** `DemoHome.tsx`가 지금 쓰는
   `fetchFeatured`(`/api/v1/places/featured`) 응답 타입 `FeaturedSpot`(`lib/api.ts:1012`
   부근)은 **사진(image_url)은 있는데 좌표(location)가 없다.** 좌표가 있는 쪽은
   `SpotCard`(`/recommend` 응답, `location: {lat,lng}`)인데 그쪽엔 사진이 없다. 즉
   지금 API 어느 쪽도 "사진 있는 실스팟의 좌표"를 한 번에 안 준다 — 지도 위에 실제
   코스선을 그리려면 백엔드 쪽에서 `FeaturedSpot`(또는 `/featured` 응답)에 `location`을
   추가해야 한다(스팟 레코드 자체엔 이미 lat/lng가 있음, `backend/app/spots/data/
   spots_seed.json` 참고 — 그냥 응답 스키마에 안 실려 있을 뿐). 이 백엔드 스키마 확장이
   먼저 필요하다는 걸 인지하고 작업 순서를 잡아라. (오케스트레이터의 스케치 HTML은
   `spots_seed.json`을 파이썬으로 직접 읽어 우회한 것 — 프로덕션 컴포넌트는 이렇게 하면
   안 되고 정식 API를 통해야 한다.)
   좌표를 확보했으면 위 좌표투영 방식으로 지도 위에 찍고 순서대로 선으로 잇는다.
   **좌표를 지어내지 않는다** — 스팟에 좌표가 없으면 그 지점은 생략.
4. 성능: 시/도 17개+시군구 250개 경계를 전부 한 번에 클라이언트로 보내지 말고, 선택된
   지역(또는 인접 몇 곳)만 필요한 만큼 로드하는 방식을 고려해라(정적 JSON split이든
   API든 판단은 맡긴다).
5. 산출물은 `frontend/components/demo-home/` 또는 새 `frontend/components/region-map/`
   등 적절한 위치에 실제 컴포넌트 코드로. 이 폴더(`design-docs/region-map-scratch/`)는
   작업 재료일 뿐 최종 위치가 아니다 — 완성 후 이 폴더의 원본 데이터 그대로 재사용해도
   되고, 다듬어서 옮겨도 된다.
