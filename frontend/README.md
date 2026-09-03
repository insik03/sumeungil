# 숨은길 프론트엔드 (MVP-4)

Next.js 15(App Router) + TypeScript. 채택한 부티크 트래블 디자인을 실제 동작하는 React 컴포넌트로 이식했다.

**MVP-2**: 홈의 목적지 검색창 + 지역 칩(경주·전주·강릉·부산)이 실제로 `GET /api/v1/regions/search`로 지역 코드를 얻어 `GET /api/v1/congestion/board`를 재호출한다(01-interface-contract.md 부록 A).

**MVP-4(신규, `/recommend`)**: 온보딩(부록 B)에서 sessionStorage에 저장된 취향 프로필을 소비해 `POST /api/v1/places/recommend`(부록 C)로 프로필 맞춤 로컬 스팟 추천 카드를 보여준다. 아래 "MVP-4 — 추천 화면" 절 참고.

## MVP-4 — 추천 화면 (`/recommend`)

### 화면 목적·흐름

- 진입 경로: 온보딩 결과 화면("이 취향으로 계속하기" 버튼, `OnboardingContent.tsx`)에서 진입, 또는 URL 직접 접근.
- 진입 시 `sessionStorage["sumeungil:onboarding-result:v1"]`(§B.7 산출물)을 읽는다.
  - **프로필 있음**: `OnboardingResult`의 `tag_vector`/`vector_version`/`scoring_weights`/`tags`만 뽑아(§C.3 "부분집합" 규정) 그대로 재전송한다 — 조작·재계산 없음.
  - **프로필 없음**: `profile: null`로 호출해 비개인화 목록을 그대로 보여주고, 상단에 "취향을 알려주면 매칭 이유까지 붙은 맞춤 추천을 받을 수 있어요" 배너 + `/onboarding` 유도 버튼을 띄운다(화면을 막지 않음, §C.7-1·DoD).
  - 개인화 여부는 항상 백엔드 응답의 `personalized` 필드를 신뢰한다(로컬 프로필 유무로 재판정하지 않음 — 구조 위반으로 서버가 프로필을 버렸을 때도 정확히 반영됨).
- 지역 선택: Hero.tsx와 동일한 4개 지역 칩(경주·전주·강릉·부산)을 재사용, 기본값은 백엔드 기본 지역(`config.py` `DEFAULT_SIGUNGU_CD=26350`, 부산 해운대)과 동일하게 맞췄다. 칩 클릭 시 `/regions/search`(부록 A)로 얻은 코드로 재호출.
- 카테고리 필터: §C.2.1 enum 8종(관광지/음식점/카페/공방/산책로/자연경관/전통시장/그 외)을 `전체` + 칩으로 노출. 이 값은 계약이 고정한 enum이라 상수화했다(카테고리 스키마 엔드포인트가 계약에 없음).
- 카드: 이름·카테고리·혼잡도 배지(`congestion.level`만으로 판정, `null`이면 배지 생략)·테마 배지(`true`=색상 배지, `null`=회색 "정보없음", `false`는 카드에서 생략)·숨은 스팟 배지(`is_hidden_gem`)·(개인화 시) 매칭도 바 + "이래서 추천했어요" 이유 칩(`match_reasons.signals`→프론트 한국어 매핑, `matched_tags`→**사용자 본인의 OnboardingResult.tags 라벨로 치환**, 별도 tag-schema 재호출 없이 처리).
- 상태: 로딩(스켈레톤 6장) / 빈 결과("이 지역·취향에 맞는 스팟이 아직 없어요") / 에러(재시도 버튼, 404면 "추천 기능이 아직 준비 중" 문구) / stale·degraded 안내(`meta.notice`).

### 디자인 선택 근거 (B안 톤 유지, 신규 색 없음)

- 상단 히어로·섹션 헤더·에러/빈 상태 블록은 기존 `.onboard-hero`/`.section`/`.board-error` 클래스를 그대로 재사용했다 — 화면마다 톤이 흔들리지 않게, 그리고 신규 CSS를 최소화하기 위해.
- 지역 칩은 Hero.tsx와 동일한 색상 배정(경주=민트/전주=아주르/강릉=코랄/부산=샌드)을 그대로 써서 "이 앱에서 지역 = 이 색"이라는 사용자 학습을 재사용했다.
- 카테고리 필터는 지역 칩과 시각적으로 구분되도록 별도 `.filter-chip`(아주르 단색 토글)을 새로 정의했다 — 지역 선택과 카테고리 필터가 같은 색이면 "둘 다 지역 칩처럼" 오인될 수 있어서다.
- 테마 배지는 `true`/`null`만 카드에 노출하고 `false`는 생략했다 — "미확인(null)과 불가(false)를 구분"하라는 계약 요구를, "불가 사실을 굳이 부각하지 않는" UX 선택과 함께 만족시키기 위한 절충이다(접근성 정보 자체가 부정확한 경우가 많은 초기 데이터셋 특성 고려).
- 매칭 이유는 자연어 문장을 지어내지 않고(예시 "연인에게 어울리는 로컬 카페" 같은 완성 문장은 계약에 없는 필드라 임의 생성 금지) `signals`/`matched_tags` 각각을 칩으로 나열했다 — enum 재판정 금지 원칙을 문구 차원에서도 지키기 위함.

### 실제 검증 (2026-07-24)

**참고**: 검증 시점 기준 실제 backend(`projects/sumeungil-build/backend`)에는 `places/recommend` 엔드포인트가 아직 구현되어 있지 않다(`app/api/`에 `places.py` 부재 확인). 이번 검증은 01-interface-contract.md 부록 C 스키마를 그대로 흉내낸 임시 목 서버로 진행했다(격리 포트 8001/3001 사용, 실제 :8000/:3000에서 돌던 다른 세션 서버와 충돌 없이 검증 후 프로세스 종료함).

Playwright 헤드리스로 확인한 항목:

1. 프로필 없이 진입 → 비개인화 카드 4장 정상 렌더 + 온보딩 유도 배너 노출.
2. sessionStorage에 `OnboardingResult`를 심고 진입 → `personalized:true` 응답 반영, 매칭도 바 4개·추천 이유 블록 4개 정상 렌더, 온보딩 유도 배너는 숨김.
3. 카테고리 필터("음식점") 클릭 → 해당 카테고리 카드만 남도록 재호출·필터링 확인.
4. 지역 칩("경주") 클릭 → 헤딩이 "경상북도 경주시의 로컬 스팟"으로 갱신, 해당 지역으로 재호출 확인.
5. 응답 `items: []` 강제 → "이 지역·취향에 맞는 스팟이 아직 없어요" 안내 정상 노출(화면 안 죽음).
6. 요청 자체를 실패시켜(백엔드 다운 시뮬레이션) → 에러 카드 + 재시도 버튼 정상 노출.
7. 위 전체 시나리오에서 브라우저 콘솔/페이지 에러 0건.
8. `npx tsc --noEmit`, `npm run build` 모두 통과.

검증에 쓴 목 서버·스크립트·스크린샷은 프로젝트 산출물이 아니라 임시 검증 도구라 저장소에 커밋하지 않았다(세션 scratchpad에만 존재).

## 로컬 실행

```bash
cd projects/sumeungil-build/frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE=http://localhost:8000
npm run dev
```

브라우저에서 http://localhost:3000 접속. 백엔드(:8000, `projects/sumeungil-build/backend`)가 함께 떠 있어야 "실시간 전광판"에 실데이터가 뜬다. 백엔드가 꺼져 있으면 전광판 영역에 에러 상태(재시도 버튼)가 뜨고, 나머지 화면(히어로/축제 배너)은 정상 렌더된다.

## 구조

```
frontend/
  app/
    layout.tsx        # 루트 레이아웃, 메타데이터
    page.tsx           # 홈 (Header + HomeContent + FestivalBanner + Footer)
    onboarding/page.tsx # 취향 온보딩 (MVP-3)
    recommend/page.tsx  # 맞춤 스팟 추천 (MVP-4, 신규)
  components/
    Header.tsx          # GNB + 모바일 메뉴 (인터랙션 있음, client component)
    HomeContent.tsx      # Hero ↔ CongestionBoard 상태 연결 (선택 지역을 둘이 공유)
    Hero.tsx             # 히어로 + 목적지 검색/지역 칩 — GET /api/v1/regions/search 실호출
    CongestionBoard.tsx  # 실시간 전광판 — GET /api/v1/congestion/board 실호출(선택 지역 반영), 로딩/에러/stale/빈결과 처리
    BoardCard.tsx         # 카드 1개 + 혼잡도 배지 (congestion_level만으로 색 결정)
    FestivalBanner.tsx    # 지역 축제 배너 (정적, MVP-1)
    Footer.tsx
    OnboardingContent.tsx # 온보딩 오케스트레이터 (MVP-3) — 결과 확인 시 /recommend로 이동
    onboarding/           # 온보딩 하위 컴포넌트(폼/로딩/결과)
    RecommendContent.tsx  # 추천 화면 오케스트레이터 (MVP-4, 신규) — POST /api/v1/places/recommend 실호출
    recommend/
      RegionPicker.tsx     # 지역 전환 칩 (Hero.tsx와 동일 4개 지역 재사용)
      CategoryFilter.tsx   # §C.2.1 카테고리 enum 필터 칩
      SpotCard.tsx          # 스팟 카드 1개 + 혼잡도/테마 배지 + 매칭도 + 추천 이유
      constants.ts          # 기본 지역, 지역 칩 세트, 카테고리 enum, signals 한국어 매핑
  lib/
    api.ts               # 01-interface-contract.md §1.2/§2.1 + 부록 A/B/C 스키마와 1:1 타입 + fetch 래퍼
    onboardingStorage.ts  # OnboardingResult sessionStorage 저장/조회 (MVP-3, 추천 화면이 그대로 읽음)
  styles/
    tokens.css            # 디자인 토큰(색상/타이포/간격) — 디자인 방향 교체 시 이 파일만 갈아끼우면 됨
    globals.css            # 리셋 + 컴포넌트 스타일 (variant-B 클래스명 그대로 이식, 검색 드롭다운/활성 칩/추천 카드 포함)
```

## 백엔드 API 계약

`projects/sumeungil-build/01-interface-contract.md`(본문 + 부록 A/B/C)가 정본이다. `congestion_level`(enum: high/mid/low/unknown)만으로 배지 색·라벨을 결정하며, 프론트에서 `congestion_rate`로 재판정하지 않는다. 지역 코드(`area_cd`/`sigungu_cd`)도 항상 backend 응답에서 온다 — 프론트가 지명을 코드로 지어내지 않는다.

**MVP-4 참고**: `POST /api/v1/places/recommend`는 계약(부록 C)은 확정돼 있으나, 검증 시점 기준 backend에는 아직 구현되어 있지 않다(`backend/app/api/`에 `places.py` 없음). 백엔드 협의 필요 — 이 엔드포인트가 뜨기 전까지 `/recommend` 화면은 항상 에러 상태(재시도 버튼)로 보인다.

- `GET {NEXT_PUBLIC_API_BASE}/api/v1/congestion/board?area_cd=&sigungu_cd=` — 홈 진입 시 파라미터 없이 1회 호출(기본 지역). 지역 칩/검색 선택 시 선택된 코드로 재호출.
- `GET {NEXT_PUBLIC_API_BASE}/api/v1/regions/search?q=&limit=` — 지역 칩 4개는 초기 로드 시 이 엔드포인트로 코드를 미리 캐시하고, 검색창은 타이핑마다(디바운스 200ms) 호출한다. 매칭 0건은 `items: []` + 200(에러 아님) — 드롭다운에 "검색 결과 없음" 문구로 표시.
- 응답 `meta.is_stale === true`면 전광판 상단에 안내 배너.
- 2xx가 아니거나 네트워크 자체 실패 시 전광판 영역만 에러 상태(재시도 버튼)로 전환, 나머지 화면은 유지.
- `regions/search`가 없는(구 MVP-1) 백엔드에 붙으면(404/네트워크 실패) 검색창·지역 칩이 자동으로 비활성 안내("검색 기능 준비 중이에요")로 전환되고, 초기 기본 지역 전광판은 그대로 동작한다.

## 혼잡도 "예측치" 고지 (CS 리스크 방지)

전광판 데이터가 실시간 실측이 아니라 예측치임을 화면에 항상 명시한다(`CongestionBoard.tsx`의 `.board-source-note`):

> "KT 이동통신 데이터 기반 혼잡도 예측치 · 실시간 실측이 아니며 실제 상황과 다를 수 있어요"

근거: `projects/sumeungil/01-backend-design.md` §15.9.5 — 원천 데이터(D1, 한국관광공사 관광지 집중률)는 "KT 이동통신 집계를 ML 학습한 예측"이다. 과장 방지를 위해 라벨을 임의로 부풀리지 않았다.

## 디자인 토큰

`styles/tokens.css`에 색상(`--g-*`/`--n-*`/`--b-*`)·타이포·스페이싱을 CSS 변수로 분리했다. 대표 피드백으로 디자인 방향이 바뀌면 이 파일의 값만 교체하면 컴포넌트 코드(className)는 그대로 재사용된다.

## 알려진 이슈 / 후속 확인 필요

- 2026-08-31 `npm audit --omit=dev` 기준 알려진 운영 의존성 취약점 0건. PR과 main push마다 CI에서 lint·프로덕션 빌드를 실행한다.
- 축제 배너는 정적 데이터다. 축제 API는 01-interface-contract.md에 아직 없음 — 필요 시 백엔드 협의 후 계약에 추가해야 한다.
- MVP-2 지역 사전(`app/regions/seed.py`)은 데모용 정적 seed다. 검색창은 이 사전에 있는 지명만 매칭된다(예: "제주"는 되지만 임의 동네 이름은 0건).

## MVP-2 검증 기록 (2026-07-24)

백엔드(`py -m uvicorn app.main:app --port 8000`) + 프론트(`npm run dev`, :3000)를 로컬로 띄우고 Playwright 헤드리스로 아래를 확인했다 (검증 후 두 서버 모두 종료함):

1. 초기 진입 시 기본 지역(부산광역시 해운대구) 전광판 정상 표시.
2. 부산/경주 칩 클릭 → 해당 `area_cd`/`sigungu_cd`로 `congestion/board` 재호출 → 전광판 카드 내용이 실제로 바뀌고, 선택된 칩에 활성 표시(`aria-pressed="true"` + 테두리 강조) 적용됨.
3. 검색창에 "강릉" 입력(디바운스 200ms) → 드롭다운에 "강원특별자치도 강릉시" 표시 → 선택 시 전광판이 강릉 데이터로 갱신됨.
4. 검색어 0건("존재하지않는지역이름") → "검색 결과가 없어요" 안내가 드롭다운에 표시됨(빈 화면 아님).
5. 브라우저 콘솔/페이지 에러 0건.
