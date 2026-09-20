/**
 * 01-interface-contract.md §1.2 / §2.1 스키마와 1:1로 유지한다.
 * 필드를 추측으로 추가/변형하지 않는다. 계약이 바뀌면 이 파일보다 문서를 먼저 고친다(§5).
 */
import { getDeviceId } from "./deviceId";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export type CongestionLevel = "high" | "mid" | "low" | "unknown";

export interface CongestionRegion {
  area_cd: string;
  sigungu_cd: string | null;
  area_name: string | null;
}

export interface CongestionItem {
  rank: number;
  spot_name: string;
  congestion_rate: number | null;
  congestion_level: CongestionLevel;
  base_date: string | null;
}

export interface CongestionMeta {
  source: string;
  fetched_at: string;
  cache: "hit" | "miss";
  is_stale: boolean;
  degraded: boolean;
  notice: string | null;
}

export interface CongestionBoardResponse {
  region: CongestionRegion;
  items: CongestionItem[];
  meta: CongestionMeta;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    detail?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  code: string;
  status: number;
  detail?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, detail?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/** 공통: 에러 응답 본문을 최대한 방어적으로 파싱해 ApiError로 변환한다. */
async function parseErrorResponse(res: Response, fallbackMessage: string): Promise<ApiError> {
  let body: Partial<ApiErrorBody> = {};
  try {
    body = await res.json();
  } catch {
    // 본문이 JSON이 아닐 수 있음(예: regions/search가 아직 없는 서버의 기본 404 HTML) — 무시하고 기본 메시지 사용
  }
  const err = body.error;
  return new ApiError(res.status, err?.code ?? "UNKNOWN", err?.message ?? fallbackMessage, err?.detail);
}

/**
 * 01-interface-contract.md 부록 R.1 — 리뷰·코스공유 요청에 붙이는 X-Device-Id 헤더.
 * 쓰기(POST/PATCH/DELETE)는 서버가 이 헤더를 필수로 요구하고(없으면 400 DEVICE_ID_REQUIRED),
 * 조회(GET)는 헤더가 없어도 동작하지만 없으면 `is_mine`이 전부 false로 온다(R.0) — 그래서
 * 이 파일의 리뷰·코스공유 GET 요청에도 동일하게 붙여 항상 정확한 is_mine을 받는다(부록 R 전용,
 * 다른 기존 엔드포인트에는 영향 없음 — 그쪽은 이 헤더를 아예 모른다).
 */
function deviceHeaders(): Record<string, string> {
  return { "X-Device-Id": getDeviceId() };
}

export interface CongestionBoardParams {
  areaCd?: string;
  sigunguCd?: string | null;
  limit?: number;
}

/**
 * §1.1 파라미터는 전부 선택. 미지정 시 백엔드 기본 지역 응답(§4.1 §1).
 * §A.3 칩/검색 선택 시 area_cd/sigungu_cd를 그대로 넘겨 재호출한다(프론트가 코드를 지어내지 않음).
 * 실패 시 ApiError를 던진다(호출부에서 로딩/에러 상태로 처리).
 */
export async function fetchCongestionBoard(
  params?: CongestionBoardParams,
  signal?: AbortSignal
): Promise<CongestionBoardResponse> {
  const qs = new URLSearchParams();
  if (params?.areaCd) qs.set("area_cd", params.areaCd);
  if (params?.sigunguCd) qs.set("sigungu_cd", params.sigunguCd);
  if (params?.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/congestion/board${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    // 네트워크 자체 실패(백엔드 미기동 등) — 계약에 없는 상황이므로 프론트가 자체 코드 부여
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "혼잡도 데이터를 불러오지 못했습니다.");
  }

  return (await res.json()) as CongestionBoardResponse;
}

/* =========================================================================
 * 부록 M(신규) — "한적한 날 예보". GET /api/v1/congestion/forecast. board(§1)와
 * 별도 계약이며 board 응답/캐시는 불변이다(additive). 원천에 있는 날짜만 daily에 담겨 온다 —
 * 빈 날짜를 보간·연결하지 않는다. meta.notice(예측치 고지)는 항상 온다 — 프론트는 이 문구를
 * 반드시 노출한다("실시간/실측" 표현 금지, "예상/예측/참고용"만 쓴다, §31 근거).
 * ========================================================================= */

/** §M — daily 1일치. index/level은 board의 congestion_rate/congestion_level과 동일 판정 방식(재판정 금지). */
export interface ForecastDay {
  date: string; // "YYYY-MM-DD"
  index: number; // 0~100
  level: CongestionLevel;
}

/** §M — 스팟 1개의 예보. best_day/worst_day는 daily 2개 미만이면 null(지어내지 않음). */
export interface SpotForecast {
  spot_name: string;
  daily: ForecastDay[];
  best_day: ForecastDay | null;
  worst_day: ForecastDay | null;
}

export interface ForecastRegion {
  region_code: string;
  region_name: string | null;
}

export interface ForecastMeta {
  source: string;
  fetched_at: string;
  cache: "hit" | "miss";
  is_stale: boolean;
  degraded: boolean;
  days: number;
  /** 예측치 고지 — 항상 존재. stale이면 앞에 폴백 문구가 붙는다. 텍스트 노드로만 렌더한다. */
  notice: string | null;
}

export interface ForecastResponse {
  region: ForecastRegion;
  /** 매칭 스팟 없음/원천 데이터 없음이면 [] (에러 아님, graceful). */
  spots: SpotForecast[];
  meta: ForecastMeta;
}

/**
 * §M — GET /api/v1/congestion/forecast?region_code=&spot_name=&days=. region_code는 필수(법정동
 * 시군구 코드). spot_name을 주면 그 스팟 하나만(대부분 spots.length<=1) 돌아온다 — 스팟 상세 카드가
 * 이 조합으로 호출한다(§31 방문 타이밍 카드). days 미지정 시 서버 기본값(14) 적용.
 * 실패해도 ApiError를 던진다 — 호출부(VisitTipCard)가 "차트만 생략"으로 조용히 처리한다(카드 유지).
 */
export async function fetchForecast(
  regionCode: string,
  spotName?: string,
  days?: number,
  signal?: AbortSignal
): Promise<ForecastResponse> {
  const qs = new URLSearchParams({ region_code: regionCode });
  if (spotName) qs.set("spot_name", spotName);
  if (days) qs.set("days", String(days));

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/congestion/forecast?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "혼잡도 예보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "혼잡도 예보를 불러오지 못했습니다.");
  }

  return (await res.json()) as ForecastResponse;
}

/**
 * 부록 A.1 — GET /api/v1/regions/search. 코드 값은 backend가 소유하므로
 * 프론트는 이 응답의 area_cd/sigungu_cd를 그대로 board 재호출에 넘기기만 한다.
 */
export interface RegionSearchItem {
  region_id: string;
  label: string;
  area_cd: string;
  sigungu_cd: string;
}

export interface RegionSearchResponse {
  query: string;
  items: RegionSearchItem[];
}

export async function fetchRegionSearch(
  q: string,
  limit = 8,
  signal?: AbortSignal
): Promise<RegionSearchResponse> {
  const qs = new URLSearchParams({ q, limit: String(limit) });

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/regions/search?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    // 백엔드가 아직 MVP-2 전이면(엔드포인트 없음) 404가 이 경로로 온다 — 호출부가 status로 구분한다.
    throw await parseErrorResponse(res, "지역 검색에 실패했습니다.");
  }

  return (await res.json()) as RegionSearchResponse;
}

/* =========================================================================
 * 부록 B — MVP-3 온보딩(취향 추출). §B.1/§B.2 스키마와 1:1로 유지한다.
 * tag_vector/scoring_weights는 서버 소유(§B.1 필드 계약) — 프론트는 재계산하지 않고
 * 표시에도 쓰지 않는다(§B.5-6). 타입에는 넣어두되(계약 그대로 보존) 렌더는 tags만 쓴다.
 * ========================================================================= */

/** §B.1 tags 객체의 key. flag는 파생값(칩 없음, §B.2)이라 tag-schema에는 없지만 analyze 응답에는 온다. */
export type OnboardingAxis =
  | "companion"
  | "flag"
  | "mobility"
  | "mood"
  | "spot_pref"
  | "accessibility"
  | "congestion_pref";

export interface TagValue {
  value: string;
  label: string;
  confidence: number;
}

export interface OnboardingScoringWeights {
  congestion: number;
  profile_fit: number;
  distance: number;
  local_exposure: number;
  trust: number;
}

export type ExtractedBy = "llm-v1" | "rule-v1" | "hybrid-v1";

/** §B.1 성공 응답 — OnboardingResult(08 §1.5 정본 승계) */
export interface OnboardingResult {
  tags: Partial<Record<OnboardingAxis, TagValue[]>>;
  tag_vector: number[];
  vector_version: number;
  scoring_weights: OnboardingScoringWeights;
  extraction_confidence: number;
  extracted_by: ExtractedBy;
  fallback_used: boolean;
}

export interface OnboardingAnalyzeRequest {
  /** 최대 300자. 초과분은 서버가 절단(§B.1). 프론트도 참고용으로 maxLength를 걸 수 있다. */
  text?: string;
  /** tag-schema가 준 value(영문 코드) 배열. 라벨을 보내지 않는다(§B.1). */
  chips?: string[];
  region_code?: string;
}

/** §B.2 tag-schema 응답 — 칩 UI는 이 응답으로만 구성한다(하드코딩 금지). */
export interface TagSchemaChip {
  value: string;
  label: string;
}

export interface TagSchemaAxis {
  /** registry 축 이름. flag/unspecified류는 서버가 애초에 내려주지 않는다(§B.2) */
  axis: string;
  label: string;
  /** UX 권고값(강제 아님) */
  select: "single" | "multi";
  chips: TagSchemaChip[];
}

export interface TagSchemaResponse {
  vector_version: number;
  axes: TagSchemaAxis[];
}

/** analyze는 로컬 LLM 추론(~24초)을 기다린다. backend 권장 타임아웃(~45초)보다 넉넉히 길게(§B.6). */
const ONBOARDING_ANALYZE_TIMEOUT_MS = 60_000;

/**
 * §B.2 — GET /api/v1/onboarding/tag-schema. 칩 축·값·라벨의 유일한 소스.
 * 백엔드가 MVP-3 전이면(엔드포인트 없음) 404/네트워크실패로 던진다 — 호출부가 "준비 중"으로 처리.
 */
export async function fetchOnboardingTagSchema(signal?: AbortSignal): Promise<TagSchemaResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/onboarding/tag-schema`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "취향 키워드를 불러오지 못했습니다.");
  }

  return (await res.json()) as TagSchemaResponse;
}

/**
 * §B.1 — POST /api/v1/onboarding/analyze. 로컬 LLM 추론이라 ~24초 걸릴 수 있어(§B.6)
 * 백엔드 권장 타임아웃보다 긴 프론트 타임아웃을 별도로 건다. `signal`은 사용자가 취소했을 때만 넘긴다.
 * fallback_used:true도 200 정상 응답이다(§B.3) — 에러로 취급하지 않는다.
 */
export async function analyzeOnboarding(
  payload: OnboardingAnalyzeRequest,
  signal?: AbortSignal
): Promise<OnboardingResult> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, ONBOARDING_ANALYZE_TIMEOUT_MS);
  const onExternalAbort = () => controller.abort();
  signal?.addEventListener("abort", onExternalAbort);

  try {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/v1/onboarding/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
        credentials: "include", // 2026-08-17: 온보딩 로그인 필수화 — 세션 쿠키를 실어 보내야 401이 안 난다.
      });
    } catch (e) {
      if (signal?.aborted && !timedOut) throw e; // 사용자가 직접 취소 — 호출부가 signal.aborted로 구분
      if (timedOut) {
        throw new ApiError(
          0,
          "TIMEOUT",
          "분석이 너무 오래 걸리고 있어요. 잠시 후 다시 시도해주세요."
        );
      }
      throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
    }

    if (!res.ok) {
      throw await parseErrorResponse(res, "취향 분석에 실패했습니다.");
    }

    return (await res.json()) as OnboardingResult;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onExternalAbort);
  }
}

/* =========================================================================
 * 부록 C — MVP-4 로컬 스팟(M5) + 프로필 맞춤 추천. §C.2/§C.3 스키마와 1:1로 유지한다.
 * SpotCard·recommend 응답은 backend가 소유(스코어링·정렬·enum 판정). 프론트는 표시만 한다(§C.7).
 * ========================================================================= */

/** §C.2.1 — 원천 분류를 backend가 매핑한 고정 enum. 한국어 라벨은 프론트가 붙인다. */
export type SpotCategory =
  | "attraction"
  | "restaurant"
  | "cafe"
  | "craft"
  | "trail"
  | "nature"
  | "market"
  | "etc";

/** §C.2 congestion — level 판정은 backend 소유. §1.4 congestion_level과 동일 enum 재사용. */
export interface SpotCongestion {
  index: number | null;
  level: CongestionLevel;
  tier: "A" | "B" | "C" | "none";
}

/** §C.2 themes — null은 "데이터 미확인"(false와 구분, 프론트가 회색 처리). */
export interface SpotThemes {
  pet_allowed: boolean | null;
  barrier_free: boolean | null;
  wellness: boolean | null;
}

/** §C.2.2 — backend가 스코어링 근거로 채우는 고정 enum. 한국어 매핑은 프론트 소유. */
export type MatchSignal = "low_congestion" | "hidden_gem" | "high_profile_fit" | "theme_match" | "near";

export interface SpotMatchReasons {
  /** registry 영문 코드. tag-schema label(또는 사용자 본인 OnboardingResult.tags 라벨)로 변환해 표시한다. */
  matched_tags: string[];
  signals: MatchSignal[];
}

/** §C.2 — 프론트↔backend 계약 정본. 원천 필드가 아니라 이 형태가 계약이다. */
export interface SpotCard {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  address: string | null;
  location: { lat: number; lng: number };
  congestion: SpotCongestion | null;
  themes: SpotThemes;
  is_hidden_gem: boolean;
  /** 0~1 | null. 프로필 소비 시에만 값. 프론트가 재계산하지 않는다(§C.7-4). */
  match_score: number | null;
  match_reasons: SpotMatchReasons | null;
}

/**
 * §C.3 profile 필드 — OnboardingResult의 "부분집합"(정본 문구). extraction_confidence 등
 * 진단 전용 필드는 요청 스키마에 없으므로 싣지 않는다. 프론트는 sessionStorage 값을 그대로 전송하고
 * 조작·재계산하지 않는다(§C.7-7) — 신뢰경계 재검증은 backend 소관(§C.4).
 */
export interface RecommendProfilePayload {
  tag_vector: number[];
  vector_version: number;
  scoring_weights: OnboardingScoringWeights;
  tags?: Partial<Record<OnboardingAxis, TagValue[]>>;
}

/**
 * 부록 F.1-3/F.4-3 — recommend 요청 additive 필드. 없거나 생략하면 기존 MVP-4~6 동작 그대로(하위호환).
 * balance=true면 파트1 혼잡 분산 rerank, weather=true면 파트4 날씨 rerank를 opt-in한다.
 */
export interface RerankRequestOptions {
  balance?: boolean;
  weather?: boolean;
}

export interface RecommendRequest {
  region_code: string;
  /** 선택. null이면 비개인화(§C.3) — 없으면 요청 자체에 null로 명시해 보낸다. */
  profile?: RecommendProfilePayload | null;
  category?: SpotCategory;
  /** 유형 필터(신규, additive) — is_hidden_gem 기준 all/hidden/popular. 기본 all. */
  spot_type?: "all" | "hidden" | "popular";
  /**
   * 정렬(신규). 이전 값("personalized"|"congestion"|"distance")은 어떤 호출부도 실제로 쓴 적 없는
   * 미구현 자리표시자였다(전 코드베이스 기준 sort 필드 미사용) — 지금 실제로 연동되는 backend 계약
   * (recommended|popular|calm, 기본 recommended)에 맞춰 값 자체를 바로잡는다. "거리순"은 클라이언트 전용이라
   * 여기 보내지 않는다(recommended로 요청 후 프론트가 재정렬, RecommendContent 참고).
   */
  sort?: "recommended" | "popular" | "calm";
  limit?: number;
  /** 부록 F.1-3. 없으면 기존 MVP-4 동작(재정렬 없음, 응답 바이트 동일). */
  rerank?: RerankRequestOptions;
}

/**
 * 부록 F.1-4 — 로드밸런싱 reason enum(MVP-7 build 부분집합). time_shift/region_expanded는
 * 경로 단위 개념이라 스팟 단위 rerank에는 존재하지 않는다(계약 밖, F.1-5).
 */
export type DistributionReason = "primary_over_threshold" | "primary_amber_distributed" | "no_alternative";

/** 부록 F.1-3 — rerank.distribution 블록. balance=false/미요청이면 null. */
export interface RerankDistribution {
  applied: boolean;
  reason: DistributionReason;
  /** 임계 초과로 강등된 스팟 id[](SpotCard.id). 이름은 여기서 찾지 않고 items에서 조회(F.1-6). */
  congested_spot_ids: number[];
  boosted_spot_ids: number[];
  threshold_high: number;
  /** 수치·정형문구만(F.1-6) — 스팟명 미포함. 그대로 텍스트 노드로 렌더한다. */
  notice: string | null;
}

/** 부록 F.4-3 — 날씨 band enum. unknown = 데이터 없음(provider_status:"unavailable"과 함께 온다). */
export type WeatherBand = "clear" | "soft" | "advise_indoor" | "unknown";

/** 부록 F.4-3 — rerank.weather 블록. weather=false/미요청이면 null. */
export interface RerankWeather {
  provider_status: "ok" | "unavailable";
  applied: boolean;
  band: WeatherBand;
  precip_probability: number | null;
  threshold_soft: number;
  threshold_advise: number;
  boosted_categories: SpotCategory[];
  /** 수치·정형문구만(F.4-6) — "날씨 정보 준비중" 또는 "강수확률 N%..." 정형 문구. */
  notice: string | null;
}

/** 부록 F.1-3 최상위 — rerank 미요청 응답이면 이 블록 자체가 없다(undefined). */
export interface RerankBlock {
  distribution: RerankDistribution | null;
  weather: RerankWeather | null;
}

export interface RecommendRegion {
  region_code: string;
  region_name: string | null;
}

export interface RecommendMeta {
  source: string;
  fetched_at: string;
  cache: "hit" | "miss";
  profile_applied: boolean;
  rejected_tag_count: number;
  notice: string | null;
}

export interface RecommendResponse {
  region: RecommendRegion;
  /** 프로필을 실제로 소비했는지 — backend 권위값. 프론트는 이 값으로만 개인화 여부를 판단한다(§C.7-1). */
  personalized: boolean;
  items: SpotCard[];
  meta: RecommendMeta;
  /** 부록 F.1-3. rerank 미요청/미지원 백엔드면 필드 자체가 없다(undefined) — 프론트는 존재 자체를 신뢰하지 않는다. */
  rerank?: RerankBlock | null;
}

/**
 * §C.3 — POST /api/v1/places/recommend. region_code는 필수(§C.3), 없으면 호출부가 기본 지역을 채워 보낸다.
 * profile은 sessionStorage의 OnboardingResult를 그대로 실어 보낸다(§C.7-7).
 */
export async function fetchRecommendedPlaces(
  payload: RecommendRequest,
  signal?: AbortSignal
): Promise<RecommendResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/places/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "추천 목록을 불러오지 못했습니다.");
  }

  return (await res.json()) as RecommendResponse;
}

/* =========================================================================
 * 부록 D — MVP-5 비교(핫플 vs 숨은길, M3). §D.2/§D.4 스키마와 1:1로 유지한다.
 * 이동거리·리뷰 축은 계약에 없다(meta.distance_axis/review_axis 고정 false, §D.3) —
 * 프론트는 이 두 필드를 지어내지 않고, 응답에 없는 축의 UI 자체를 만들지 않는다(§D.7-6).
 * ========================================================================= */

export type CompareRole = "hotspot" | "hidden";
export type CompareSource = "m2_board" | "local_store";

/** §D.2 CompareSpot — hotspot/hidden 완전히 같은 키 구조(대칭 렌더 전제). */
export interface CompareSpot {
  role: CompareRole;
  spot_id: number | null;
  name: string;
  category: SpotCategory | null;
  congestion: SpotCongestion | null;
  themes: SpotThemes | null;
  is_hidden_gem: boolean;
  match_score: number | null;
  match_reasons: SpotMatchReasons | null;
  /** 부록 D.8 — 관광 사진(한국관광공사). 시드 → detailImage2 → 포토갤러리 순으로 찾고 없으면 null. */
  image_url: string | null;
  photo_credit: string | null;
  source: CompareSource;
}

export interface CompareDeltas {
  /** hidden.index − hotspot.index. 한쪽 index null이면 null(지어내지 않음, §D.4). */
  congestion_diff: number | null;
  congestion_diff_pct: number | null;
  fit_diff: number | null;
  matched_count: number;
}

export interface CompareVerdict {
  /** backend 템플릿 조립(§D.4.1). 텍스트 노드로만 렌더 — HTML 주입 금지(§D.7-5). */
  headline: string;
  template_id: string;
}

export interface CompareRegion {
  region_code: string;
  region_name: string | null;
}

export interface CompareMeta {
  /** 부록 D.9 — 두 곳의 성격 유사도(0~1). null = 비슷함을 확인하지 못함(0과 다르다). */
  similarity?: number | null;
  source: string;
  fetched_at: string;
  personalized: boolean;
  hotspot_source: CompareSource;
  /** MVP-5는 항상 false(고정) — 거리 축 UI를 만들지 않는다(§D.7-6). */
  distance_axis: boolean;
  /** MVP-5는 항상 false(고정) — 리뷰 축 UI를 만들지 않는다(§D.7-6). */
  review_axis: boolean;
  notice: string | null;
}

/** §D.4 성공 응답 — POST /api/v1/compare. */
export interface CompareResponse {
  comparison_id: string;
  generated_at: string;
  region: CompareRegion;
  hotspot: CompareSpot;
  hidden: CompareSpot;
  deltas: CompareDeltas;
  verdict: CompareVerdict;
  meta: CompareMeta;
}

export interface CompareRequest {
  region_code: string;
  /** 부록 C.3 ProfileInput과 동일 형태 — sessionStorage OnboardingResult를 그대로 재사용(§D.4). */
  profile?: RecommendProfilePayload | null;
  hidden_id?: number | null;
  hotspot_id?: number | null;
  category?: SpotCategory | null;
}

/**
 * §D.4 — POST /api/v1/compare. region_code 필수, profile은 §C.7-7과 동일하게 조작·재계산 없이 재전송한다.
 * 404 COMPARE_UNAVAILABLE(핫플/숨은길 선정 실패)은 에러가 아니라 "이 지역은 비교 준비 중"으로
 * 호출부가 부드럽게 처리한다(§D.5) — 여기서는 그대로 ApiError로 던지고 상태 판단은 호출부 몫이다.
 */
export async function fetchCompare(
  payload: CompareRequest,
  signal?: AbortSignal
): Promise<CompareResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "비교 결과를 불러오지 못했습니다.");
  }

  return (await res.json()) as CompareResponse;
}

/* =========================================================================
 * 부록 G(신규) — 관광지 상세(스팟 상세 페이지). 추천 목록 카드 탭 시 진입한다.
 * congestion/themes/is_hidden_gem은 부록 C.2 SpotCard와 동일 계약(재판정 금지, 그대로 표시).
 * overview/recommended_for는 backend가 채운 자유 문구다 — 텍스트 노드로만 렌더한다(HTML 주입 금지).
 * ========================================================================= */

/**
 * §36(신규, 03-design-spec.md) — 사진 배열 공용 모델. SpotDetail.images와 FestivalDetailResponse.images가
 * 완전히 동일한 형태를 쓴다(재정의 아님, 단일 소스) — PhotoCarousel.tsx가 이 타입을 그대로 props로 받는다.
 * credit이 null이면 출처 표기를 하지 않는다(FeaturedSpot.photo_credit과 동일 원칙, 지어내지 않음).
 */
export interface MediaImage {
  url: string;
  credit: string | null;
}

/**
 * §31(신규, 부록 M 승계) — "한적한 날/붐비는 날". SpotDetail.visit_tip additive 필드.
 * best_day/worst_day는 부록 M ForecastDay와 동일 구조(재정의 아님, 재사용). 관광지·자연경관 카테고리
 * 이면서 혼잡도 원천에 이름이 매칭될 때만 값이 있다 — 그 외엔 SpotDetail.visit_tip 자체가 null이라
 * "방문 타이밍" 카드 자체를 렌더하지 않는다(지어내지 않음, §31 근거).
 */
export interface VisitTip {
  best_day: ForecastDay;
  worst_day: ForecastDay;
  /** 판단에 쓴 조회 윈도우(일). 각주("N일 예측 기준")에 그대로 쓴다. */
  days: number;
}

/** §G.1 — GET /api/v1/places/{content_id} 성공 응답. */
/**
 * 2026-09-20 — 그 **장소 좌표 기준** 지금 날씨(기상청 초단기실황 5km 격자).
 * FestivalWeather(관광코스 날씨 D18, 시도 해상도, 축제 기간 강수확률)와는 다른 원천·다른 질문이다.
 * 서버가 원천을 못 받으면 필드 자체가 null/없음 → 화면은 날씨 줄을 그리지 않는다(지어내지 않음).
 */
export interface LiveWeather {
  /** "맑음" / "구름많음" / "흐림" / "비" / "눈" … 서버가 코드표로 정한 고정 문구다. */
  condition: string;
  /** 지금 비·눈이 오는가. 문구를 파싱하지 말고 이 불리언을 쓴다. */
  precipitation: boolean;
  temperature_c: number | null;
  humidity_pct: number | null;
  rain_1h_mm: number | null;
  /** "YYYY-MM-DD HH:00"(KST). 언제 기준인지 화면에 함께 밝힌다. */
  observed_at: string;
  source: string;
}

export interface SpotDetail {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  region_name: string | null;
  address: string | null;
  location: { lat: number; lng: number };
  congestion: SpotCongestion | null;
  themes: SpotThemes;
  is_hidden_gem: boolean;
  /** null이면 "소개 준비 중"으로 표시한다(지어내지 않음). */
  overview: string | null;
  /** 빈 배열이면 "이런 분께 추천" 섹션 자체를 숨긴다. */
  recommended_for: string[];
  source: string;
  /**
   * Phase 2(신규) — overview를 로컬 LLM으로 3줄 요약한 문구. null이면 요약이 아직 없다는 뜻이라
   * "AI 3줄 요약" 블록 자체를 렌더하지 않고 overview만 기존과 동일하게 보여준다(지어내지 않음).
   */
  ai_summary: string | null;
  /** 요약을 만든 LLM("gemini"/"ollama"). null/미존재 = 출처 미상(사전 생성분·구버전 백엔드) → 일반 "AI" 마크. */
  ai_provider?: string | null;
  /** 2026-09-20 — 이 스팟 좌표 기준 지금 날씨. null/미존재면 표시하지 않는다(구버전 백엔드 하위호환). */
  live_weather?: LiveWeather | null;
  /** §31(신규) — "방문 타이밍" 카드 전용. null이면 카드 자체를 숨긴다(관광지·자연 외 카테고리는 항상 null). */
  visit_tip: VisitTip | null;
  /**
   * 부록 H.3(신규) — 저작권 출처 표기. FeaturedSpot.photo_credit과 동일 계약(optional, null/undefined
   * 둘 다 미표기). 현재 SpotDetailContent.tsx는 스팟 상세에서 사진 자체를 렌더하지 않아(§34 확인)
   * 이 필드는 타입 계약만 반영하고 실제 렌더는 없다 — 상세 화면에 사진이 추가되면 그때 캡션도 붙인다.
   */
  photo_credit?: string | null;
  /**
   * §36(신규) — 스팟 상세 사진 슬라이드(PhotoCarousel.tsx). 대표사진 포함 최대 8장(backend 계약).
   * optional인 이유는 ai_summary/visit_tip과 동일(하위호환) — 구버전 백엔드가 이 필드를 안 내려주면
   * undefined다. undefined/빈 배열 둘 다 "이미지 없음"으로 같이 취급하고, 이 경우 SpotDetailContent는
   * 사진 영역 자체를 렌더하지 않는다(§34에서 이미 확인된 "상세에는 원래 사진 렌더가 없었다"는 사실과
   * 픽셀 동일하게 유지하기 위한 선택 — PhotoCarousel 컴포넌트 자체는 0장일 때 플레이스홀더를 그릴 수
   * 있지만, 축제 상세처럼 "사진 섹션이 항상 있어야 하는" 화면이 아니므로 스팟 상세는 조건부 마운트로
   * 기존 무변화를 지킨다. 03-design-spec.md §36 참고).
   */
  images?: MediaImage[];
}

/**
 * §G.1 — GET /api/v1/places/{content_id}. 없는 id는 404(ApiError.status===404) — 호출부가
 * "스팟을 찾을 수 없어요"로 부드럽게 처리한다(§D.5의 COMPARE_UNAVAILABLE 처리 패턴과 동일 원칙).
 */
export async function fetchSpotDetail(
  contentId: number | string,
  signal?: AbortSignal
): Promise<SpotDetail> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/places/${encodeURIComponent(String(contentId))}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "스팟 정보를 불러오지 못했습니다.");
  }

  return (await res.json()) as SpotDetail;
}

/* =========================================================================
 * 부록 I(신규) — AI 추천 코스(/course). CourseSpot은 §C.2 SpotCard의 상위집합(필드 전부 동일 +
 * slot_label만 추가)이라 표시 컴포넌트(SpotCard.tsx)를 그대로 재사용한다. congestion/match_score
 * 등 판정과 코스 순서(slot_label)는 전부 backend 소유 — 프론트는 순서·값을 재판정하지 않고 그대로 표시한다.
 * legs[i]는 spots[i]→spots[i+1] 구간이라 legs.length === spots.length-1이다.
 * ========================================================================= */

/** §C.2 SpotCard + 코스 내 시간대 라벨(예: "아침 카페","오전 명소","점심","오후 산책","저녁 명소"). */
export interface CourseSpot extends SpotCard {
  slot_label: string;
  /** 2026-09-05 — AI 가 자유서술에 맞춰 고른 경우 그 이유 한 줄. 슬롯 휴리스틱 코스는 없음. 텍스트노드로만 렌더. */
  pick_reason?: string | null;
  /**
   * 부록 I.12(신규) — TourAPI detailCommon2.firstimage(https 승격). featured/스팟상세와 동일 값·
   * 동일 캐시. optional로 둔 이유는 ai_summary와 동일(구버전 백엔드가 이 필드를 안 내려줘도
   * 기존 CourseResponse 파싱이 깨지지 않아야 한다). null이면 원천에 사진이 없거나 호출 실패
   * — 프론트는 플레이스홀더로 대체한다(지어내지 않음).
   */
  image_url?: string | null;
  /**
   * 부록 I.12(신규) — overview 원문 첫 1~2문장 발췌(LLM 아님, 생성이 아니라 발췌). null이면
   * 원문이 없거나 호출 실패 — 이 경우 설명 줄 자체를 생략한다(빈 문자열로 지어내지 않음).
   */
  blurb?: string | null;
  /**
   * 부록 H.3(신규) — 저작권 출처 표기. image_url/blurb와 동일 이유로 optional. showImage(사진이
   * 실제로 뜨는 상태)일 때만 사진 아래 캡션으로 표시한다 — 사진 없이 출처만 남는 상태 방지.
   */
  photo_credit?: string | null;
}

export interface CourseLegMode {
  minutes: number;
  meters: number;
}

/**
 * 구간 이동 정보. Tmap(백엔드 경로탐색 API) 실패 구간은 walk/car/path가 전부 null —
 * "이동 정보 없음"으로 표시하고 지어내지 않는다. path 좌표는 WGS84 [lng, lat] 순서
 * (GeoJSON 관례)다 — naver.maps.LatLng은 (lat, lng) 순서를 받으므로 지도에 그릴 때
 * 반드시 뒤집는다(coord[1], coord[0]).
 */
export interface CourseLeg {
  walk: CourseLegMode | null;
  car: CourseLegMode | null;
  path: [number, number][] | null;
}

export interface CourseRegion {
  region_code: string;
  region_name: string | null;
}

/** POST /api/v1/courses/recommend 성공 응답. */
export interface CourseResponse {
  region: CourseRegion;
  spots: CourseSpot[];
  legs: CourseLeg[];
  notice: string | null;
  /**
   * §26(신규) — courses/arrange·courses/recommend 공통 additive 필드. 코스 전체를 2~3문장으로
   * 요약한 LLM 생성 문구. optional로 선언한 이유: 백엔드가 아직 이 필드를 안 내려주는 동안에도
   * 기존 CourseResponse 파싱이 깨지지 않아야 한다(undefined===생략, null===LLM 실패/미생성 —
   * 둘 다 "AI 코스 요약" 박스를 그리지 않는다, 지어내지 않음).
   */
  ai_summary?: string | null;
  /**
   * 부록 I.12(신규) — 코스 감성 제목 1줄(15자 내외, 서버 24자 하드 절단). null이면 프론트가
   * 지역명 기반 폴백 제목을 쓴다(§I.12-6). optional인 이유는 ai_summary와 동일(하위호환).
   */
  ai_title?: string | null;
  /**
   * 부록 I.12(신규) — legs[*].walk.meters 합(Tmap 실측, 부분합 아님). leg가 하나라도
   * walk:null이거나 leg가 0개면 null — 이때는 총거리 뱃지 자체를 숨긴다(0m 표기 금지, §I.12-2).
   */
  total_distance_m?: number | null;
}

export interface CourseRequest {
  region_code: string;
  /** §C.3/§C.7-7과 동일 원칙 — sessionStorage 프로필을 그대로 재전송, 조작·재계산 금지. */
  profile?: RecommendProfilePayload | null;
  /** 2026-09-05 — 자유서술 원문. 있으면 서버가 태그 대신 AI 로 실제 후보 스팟을 고른다. */
  wish?: string | null;
}

/**
 * POST /api/v1/courses/recommend. region_code 필수, profile은 sessionStorage의 OnboardingResult를
 * 그대로 실어 보낸다(없으면 null — 비개인화 코스, §C.7-7과 동일 원칙).
 */
export async function fetchCourse(
  regionCode: string,
  profile?: RecommendProfilePayload | null,
  signal?: AbortSignal,
  wish?: string | null
): Promise<CourseResponse> {
  const payload: CourseRequest = { region_code: regionCode, profile: profile ?? null, wish: wish || null };

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
      credentials: "include", // 2026-08-17: AI 코스짜기 로그인 필수화 — 세션 쿠키를 실어 보내야 401이 안 난다.
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "추천 코스를 불러오지 못했습니다.");
  }

  return (await res.json()) as CourseResponse;
}

/**
 * 부록 I §arrange(신규) — 사용자가 직접 고른 스팟들의 방문 순서만 짜주는 엔드포인트.
 * 응답 스키마는 CourseResponse와 완전히 동일하다(차이: slot_label이 "1번째"~"N번째",
 * match_score는 항상 null) — 그래서 별도 타입을 만들지 않고 CourseResponse를 그대로 재사용한다.
 * spot_ids는 2~8개여야 한다(MIN_CART_SIZE/MAX_CART_SIZE, courseCartStorage.ts와 동일 값).
 * 잘못된 id는 backend가 무시하고 notice로 알려준다 — 프론트는 재검증하지 않는다.
 */
export interface ArrangeCourseRequest {
  spot_ids: number[];
  region_code?: string;
}

export async function fetchArrangeCourse(
  spotIds: number[],
  regionCode?: string,
  signal?: AbortSignal
): Promise<CourseResponse> {
  const payload: ArrangeCourseRequest = { spot_ids: spotIds };
  if (regionCode) payload.region_code = regionCode;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/arrange`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
      credentials: "include", // 2026-08-17: AI 코스짜기 로그인 필수화 — 세션 쿠키를 실어 보내야 401이 안 난다.
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "코스 순서를 짜지 못했습니다.");
  }

  return (await res.json()) as CourseResponse;
}

/* =========================================================================
 * 부록 L(신규) — 스팟 검색(§26, "내 코스 만들기" 검색창). GET /api/v1/places/search.
 * 부록 A.1(지역 검색)과 동일 원칙 — id/region_code 등 코드 값은 backend가 소유하므로 프론트는
 * 이 응답을 그대로 arrange 요청(spot_ids)에 실어 보내기만 하고 값을 지어내지 않는다.
 * ========================================================================= */

/** §26 — 검색 결과 카드 1개. SpotCard(부록 C.2)의 부분집합 + region_name/address. */
export interface PlaceSearchItem {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  region_name: string | null;
  address: string | null;
  is_hidden_gem: boolean;
}

export interface PlaceSearchResponse {
  items: PlaceSearchItem[];
}

const PLACE_SEARCH_LIMIT = 8;

/**
 * §26 — GET /api/v1/places/search?q=&region_code=&limit=8. region_code는 선택(지금은 항상
 * 생략 — 전국 검색이 "내 코스 만들기" 흐름에 더 맞다, region_code 필터는 계약에 있으므로 향후
 * 지역 한정 검색이 필요해지면 인자를 그대로 붙이면 된다). 백엔드가 아직 미배포면 404/네트워크실패로
 * 온다 — 호출부(SpotSearchBox.tsx)가 RegionPicker.tsx와 동일 패턴으로 "준비 중"으로 처리한다.
 */
export async function fetchSpotSearch(
  q: string,
  regionCode?: string,
  signal?: AbortSignal
): Promise<PlaceSearchResponse> {
  const qs = new URLSearchParams({ q, limit: String(PLACE_SEARCH_LIMIT) });
  if (regionCode) qs.set("region_code", regionCode);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/places/search?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "스팟 검색에 실패했습니다.");
  }

  return (await res.json()) as PlaceSearchResponse;
}

/* =========================================================================
 * 부록 H(신규) — 홈 발견 섹션("숨은길 PICK"/"지금 뜨는 여행지" — 렌더 순서는 §46, FeaturedSpots.tsx).
 * 백엔드-프론트 병렬 작업 계약.
 * congestion/is_hidden_gem은 부록 C.2 SpotCard와 동일 계약(재판정 금지, 그대로 표시).
 * image_url이 null이거나 로드 실패하면 프론트가 플레이스홀더로 대체한다(FeaturedSpots.tsx).
 * ========================================================================= */

export interface FeaturedRegion {
  region_code: string;
  region_name: string;
}

/** GET /api/v1/places/featured 응답의 스팟 1개. SpotCard(부록 C.2)의 부분집합 + image_url. */
export interface FeaturedSpot {
  id: number;
  name: string;
  category: SpotCategory;
  region_name: string;
  address: string | null;
  /** SpotCard와 같은 원천 실좌표. 지도는 이 값이 유효한 스팟만 경로에 포함한다. */
  location: { lat: number; lng: number };
  congestion: SpotCongestion | null;
  is_hidden_gem: boolean;
  /** null이면 사진 없음 — 프론트가 카테고리 아이콘/색블록 플레이스홀더로 대체(재판정 아님, 표시 방식). */
  image_url: string | null;
  /**
   * 부록 H.3(신규) — 저작권 출처 표기(예: "한국관광공사", "한국관광공사 포토갤러리 / 촬영: OOO").
   * optional인 이유는 CourseSpot.image_url/blurb와 동일(구버전 백엔드가 이 필드를 안 내려줘도 파싱이
   * 깨지지 않게). null/undefined면 아무것도 렌더하지 않는다 — `image_url`이 있어도 출처가 없을 수
   * 있다(불변식은 역방향: `photo_credit`이 있으면 반드시 `image_url`도 있다). 텍스트 노드로만 렌더.
   */
  photo_credit?: string | null;
}

export interface FeaturedResponse {
  /** region_code가 매칭되지 않으면 null — 그래도 trending/hidden_picks는 백엔드 기본값으로 채워질 수 있다. */
  region: FeaturedRegion | null;
  trending: FeaturedSpot[];
  hidden_picks: FeaturedSpot[];
  /**
   * 부록 H.6(신규, 2026-08-01) — **"더보기"가 의미 있는지** 판단용 후보 총 수(노출 개수가 아니다).
   * `trending_total`은 board 이름매칭에 성공한 관광지 수(= 이 지역 trending의 실제 상한, 대개
   * limit보다 작다), `hidden_total`은 `is_hidden_gem` 자격을 통과한 후보 수.
   * optional인 이유는 photo_credit과 동일(구버전 백엔드 호환). **null/undefined면 "더보기 없음"**
   * 으로 읽는다 — diverse=true(홈)는 집계하지 않으므로 항상 null이다.
   * 권장 규칙: `trending.length < (trending_total ?? 0)`일 때만 그 섹션의 더보기 버튼을 띄운다
   * (limit 상한 50에 이미 닿았으면 어차피 더 늘지 않는다).
   */
  trending_total?: number | null;
  hidden_total?: number | null;
}

/**
 * 신규 — GET /api/v1/places/featured. 홈 발견 섹션 전용(§HomeContent). region_code/limit 모두 선택.
 * 백엔드가 아직 미배포면 404/네트워크실패로 온다 — 호출부(FeaturedSpots.tsx)가 섹션을 조용히 숨긴다.
 *
 * §37(신규, 03-design-spec.md, 2026-07-31) — `diverse`(5번째 인자, additive) 추가. 홈이 지역
 * 미선택 상태일 때만 true로 넘긴다("홈에 부산만 많다" 대표 피드백 대응) — true면 backend가 여러
 * 지역을 섞어 응답한다(§H 계약 확장, 프론트는 섞는 로직을 갖지 않는다). 기존 3-인자 호출부
 * (ThemeCollections·RegionsContent 등)는 그대로 두면 undefined로 전달돼 기존 동작 100% 유지.
 *
 * §47(신규, 지역 허브 A안, 오케스트레이터 지시서 2026-08-11) — `areaCd`(6번째 인자, additive).
 * 시도 전체 집계 조회용(GET .../featured?area_cd=41). regionCode가 있으면 그쪽이 우선이라고
 * 오케스트레이터 계약에 명시돼 있어(§확정 API 계약 2) 프론트도 둘을 동시에 보내지 않는다 —
 * RegionsContent.tsx가 "전체" 선택 시에만 areaCd를, 특정 시군구 선택 시엔 regionCode만 넘긴다.
 * 기존 5-인자 이하 호출부는 undefined로 전달돼 기존 동작 100% 유지.
 */
export async function fetchFeatured(
  regionCode?: string,
  limit?: number,
  signal?: AbortSignal,
  diverse?: boolean,
  areaCd?: string
): Promise<FeaturedResponse> {
  const qs = new URLSearchParams();
  if (regionCode) qs.set("region_code", regionCode);
  if (limit) qs.set("limit", String(limit));
  if (diverse) qs.set("diverse", "true");
  if (areaCd) qs.set("area_cd", areaCd);
  const query = qs.toString();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/places/featured${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "발견 콘텐츠를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "발견 콘텐츠를 불러오지 못했습니다.");
  }

  return (await res.json()) as FeaturedResponse;
}

/* =========================================================================
 * 부록 J(신규) — 테마 컬렉션(홈 "테마별로 골라보는 여행" 섹션, ThemeCollections.tsx).
 * FeaturedSpot(부록 H)을 그대로 재사용한다 — 카드 표시 계약이 이미 동일(id·name·category·
 * region_name·congestion·is_hidden_gem·image_url)하므로 새 카드 타입을 만들지 않는다.
 * congestion/is_hidden_gem은 재판정하지 않고 그대로 표시한다(부록 C.2와 동일 원칙).
 * ========================================================================= */

export interface CollectionRegion {
  region_code: string;
  region_name: string;
}

/** GET /api/v1/collections 응답의 테마 1개. title은 backend 소유 문구를 텍스트 노드로만 렌더한다.
 *  §44(신규, 03-design-spec.md — 대표 지시 "테마별 여행 더보기 + 전국→지역 선택") — `total`/
 *  `has_more`는 additive/optional(구버전 backend는 안 줄 수 있다). `total`이 없으면 프론트는
 *  "전체 N곳" 표기를 생략한다(지어내지 않음), `has_more`가 없거나 false면 더보기 버튼을 숨긴다. */
export interface SpotCollection {
  theme_key: string;
  title: string;
  spots: FeaturedSpot[];
  /** 이 테마 자격을 통과한 후보 총 수(더보기 UI의 "전체 N곳" 표기 근거). */
  total?: number;
  /** true면 이 테마에 더 불러올 스팟이 남아 있다. */
  has_more?: boolean;
}

export interface CollectionsResponse {
  /** FeaturedResponse.region과 동일 원칙 — region_code가 매칭되지 않으면 null일 수 있다(방어적 처리). */
  region: CollectionRegion | null;
  collections: SpotCollection[];
  /**
   * §44(신규) — 이번 응답을 만든 랜덤 시드. "더보기" 요청 시 이 값을 그대로 재사용해야
   * (offset만 늘려서) 같은 조합이 이어진다(중복·누락 방지). 새로고침하면 새 seed로 새 조합.
   * 구버전 backend는 이 필드를 안 줄 수 있어 optional — 없으면 더보기 요청에 seed를 싣지 않는다.
   */
  seed?: number;
}

/**
 * §44(신규) — fetchCollections 4번째 인자. 전부 additive/optional이라 기존 3-인자 호출부는
 * 영향 없다(RegionsContent.tsx 등).
 */
export interface FetchCollectionsOptions {
  /** 테마당 요청 개수(백엔드 상한 50). 초기 로딩엔 8, "더보기" 클릭 시 증분값으로 쓴다. */
  perTheme?: number;
  /** "더보기" 전용 — 이 theme_key 하나만 응답에 담아달라는 요청(다른 테마는 재조회하지 않기 위함). */
  theme?: string;
  /** "더보기" 전용 — 이미 받은 개수(그 지점부터 이어서). */
  offset?: number;
  /** "더보기" 전용 — 최초 응답의 CollectionsResponse.seed를 그대로 재사용(페이지네이션 규약). */
  seed?: number;
}

/**
 * 신규 — GET /api/v1/collections. 홈 "테마별로 골라보는 여행" 섹션 전용(§ThemeCollections).
 * region_code는 선택 — 미지정 시 backend 기본 지역(§fetchFeatured와 동일 관례)으로 응답한다.
 * 백엔드가 아직 미배포면 404/네트워크실패로 온다 — 호출부가 섹션을 조용히 숨긴다(홈이 깨지지 않게).
 *
 * §37.5(신규, 2026-08-01, 대표 피드백 "테마별 여행은 새로고침해도 같은 곳만·인생샷도 부산만") —
 * `diverse`(3번째 인자, additive). fetchFeatured와 **같은 규약**이다: 홈이 지역 미선택일 때만
 * true로 넘기면 backend가 9권역을 합친 후보 풀에서 뽑아 준다(시군구당 최대 2곳). 기존
 * 2-인자 호출부는 undefined로 전달돼 동작 100% 유지. region_code가 있으면 backend가 무시한다.
 *
 * §44(신규) — `options`(4번째 인자, additive)로 `per_theme`/`theme`/`offset`/`seed`를 실어
 * "테마별 더보기" 페이지네이션을 지원한다. 전부 optional이라 기존 호출부는 무영향.
 */
export async function fetchCollections(
  regionCode?: string,
  signal?: AbortSignal,
  diverse?: boolean,
  options?: FetchCollectionsOptions
): Promise<CollectionsResponse> {
  const qs = new URLSearchParams();
  if (regionCode) qs.set("region_code", regionCode);
  if (diverse) qs.set("diverse", "true");
  if (options?.perTheme) qs.set("per_theme", String(options.perTheme));
  if (options?.theme) qs.set("theme", options.theme);
  if (typeof options?.offset === "number") qs.set("offset", String(options.offset));
  if (typeof options?.seed === "number") qs.set("seed", String(options.seed));
  const query = qs.toString();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/collections${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "테마 컬렉션을 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "테마 컬렉션을 불러오지 못했습니다.");
  }

  return (await res.json()) as CollectionsResponse;
}

/* =========================================================================
 * 부록 K(신규, Phase 3) — 지역 축제(홈 "지금 이 지역 축제" 섹션, FestivalBanner.tsx).
 * 오케스트레이터 계약: GET /api/v1/festivals?region_code={code}&limit={n}
 *   → { region, festivals: [{ id, title, start_date, end_date, address, image_url|null, ongoing }] }
 * "접근 불가/빈 지역이면 festivals: []"은 정상 200 응답이다(에러 아님) — 호출부(FestivalBanner.tsx)가
 * 이 빈 배열과 "엔드포인트 미배포"(404/네트워크실패)를 서로 다른 상태로 구분해서 처리한다.
 * ========================================================================= */

export interface FestivalRegion {
  region_code: string;
  region_name: string | null;
}

/** GET /api/v1/festivals 응답의 축제 1개. */
export interface Festival {
  id: number;
  title: string;
  start_date: string;
  end_date: string;
  address: string | null;
  /** null이면 사진 없음 — 프론트가 플레이스홀더로 대체한다(FeaturedSpot.image_url과 동일 원칙). */
  image_url: string | null;
  ongoing: boolean;
}

export interface FestivalsResponse {
  /** region_code가 매칭되지 않으면 null일 수 있다(부록 H/J region과 동일 방어적 처리). */
  region: FestivalRegion | null;
  festivals: Festival[];
  /**
   * 신규(§27, /festivals 전국 축제 페이지) — 필터 통과 전체 건수. optional로 둔 이유: 이 필드는
   * 백엔드 병렬 확장 계약에만 있고 기존 홈 배너 계약(§K)엔 없었다 — 구버전 백엔드가 이 필드 없이
   * 응답해도(하위호환) 타입 에러가 나지 않게 하고, 호출부(FestivalsContent)는 값이 없으면
   * "전체 N건" 건수 표기를 생략한다(개수를 지어내지 않는다).
   */
  total?: number;
}

/**
 * 신규(Phase 3) — GET /api/v1/festivals. 홈 "지금 이 지역 축제" 섹션(§FestivalBanner) +
 * 전국 축제 페이지(§27, /festivals, FestivalsContent) 공용.
 * region_code/limit 모두 선택. 백엔드가 아직 미배포면 404/네트워크실패로 온다 — 호출부가
 * 섹션을 조용히 숨기거나(FeaturedSpots/ThemeCollections와 동일 원칙) 에러 카드로 안내한다.
 *
 * opts(신규, additive 4번째 인자) — 기존 3-인자 호출부(FestivalBanner.tsx)는 그대로 두고
 * month/window_days만 필요한 화면(FestivalsContent)이 opts로 넘긴다:
 * - month: "YYYY-MM" 형식, 서버 계약 그대로 전달(프론트가 가공하지 않는다).
 * - windowDays: 서버 기본값 90/최대 365. 월 필터를 쓸 때만 365로 넉넉히 요청한다(호출부 책임).
 * - areaCd(§47, 지역 허브 A안) — 시도 전체 축제 조회용(GET .../festivals?area_cd=41).
 *   regionCode와 동시에 쓰지 않는다(fetchFeatured의 areaCd와 동일 규약, RegionsContent.tsx가
 *   "전체" 선택 시에만 넘긴다).
 */
export async function fetchFestivals(
  regionCode?: string,
  limit?: number,
  signal?: AbortSignal,
  opts?: { month?: string; windowDays?: number; areaCd?: string; regionBlock?: string }
): Promise<FestivalsResponse> {
  const qs = new URLSearchParams();
  if (regionCode) qs.set("region_code", regionCode);
  if (limit) qs.set("limit", String(limit));
  if (opts?.month) qs.set("month", opts.month);
  if (opts?.windowDays) qs.set("window_days", String(opts.windowDays));
  if (opts?.areaCd) qs.set("area_cd", opts.areaCd);
  // 2026-09-20 — 9권역 필터. region_code 가 있으면 서버가 무시한다(더 좁은 지정이 이긴다).
  if (opts?.regionBlock) qs.set("region_block", opts.regionBlock);
  const query = qs.toString();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/festivals${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "축제 정보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "축제 정보를 불러오지 못했습니다.");
  }

  return (await res.json()) as FestivalsResponse;
}

/* =========================================================================
 * §47(신규) — 지역 허브 A안(RegionsContent.tsx) 시군구 드롭다운. 오케스트레이터 계약:
 *   GET /api/v1/regions/children?area_cd={2자리 시도코드}
 *   → { area_cd, label, items: [{ region_code, label, spot_count }] }
 * "스팟이 있는 시군구만, 가나다순"으로 이미 서버가 정렬해 준다 — 프론트가 재정렬하지 않는다.
 * 0건이면 items: []가 정상 200 응답(부록 K festivals와 동일 원칙, 에러 아님).
 * ========================================================================= */

/** GET /api/v1/regions/children 응답의 시군구 1개. */
export interface RegionChild {
  region_code: string;
  /** 서버가 내려주는 전체 명칭(예: "경기도 가평군") — 프론트는 지어내지 않고 문자열 가공만 한다. */
  label: string;
  spot_count: number;
}

export interface RegionChildrenResponse {
  area_cd: string;
  label: string;
  items: RegionChild[];
}

/**
 * 신규(§47) — GET /api/v1/regions/children. area_cd는 필수(2자리 시도 코드).
 * 백엔드가 아직 미배포/실패면 호출부(RegionsContent.tsx)가 "전체"만 남기고 드롭다운을
 * 비활성화한다 — children이 없어도 area_cd 기반 featured/festivals 조회 자체는 계속 동작한다.
 */
export async function fetchRegionChildren(
  areaCd: string,
  signal?: AbortSignal
): Promise<RegionChildrenResponse> {
  const qs = new URLSearchParams({ area_cd: areaCd });

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/regions/children?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "시군구 목록을 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "시군구 목록을 불러오지 못했습니다.");
  }

  return (await res.json()) as RegionChildrenResponse;
}

/* =========================================================================
 * §36(신규) — 축제 상세 페이지(`/festival/[id]`, FestivalDetailContent). 오케스트레이터 계약:
 *   GET /api/v1/festivals/{id}
 *   → { festival, region, images, timing, weather }
 * festival은 부록 K Festival과 동일 모델(재정의 없음). images는 부록 O MediaImage[] 재사용.
 * timing/weather는 이 화면 전용 신규 블록 — backend 권위값을 그대로 표시하고 재계산하지 않는다.
 * ========================================================================= */

export type FestivalTimingStatus = "ongoing" | "upcoming" | "ended";

/** "방문 타이밍" 카드 전용. d_day/days_left는 상태별로 의미가 달라질 수 있어 backend 값을 그대로 쓰고
 * 프론트가 재계산하지 않는다(visit_tip.best_day/worst_day와 동일 원칙 — 재판정 금지). tip은 항상
 * 채워지는 정형 안내 문구(예: "지금이 딱 방문하기 좋은 시기예요")로 텍스트 노드로만 렌더한다. */
export interface FestivalTiming {
  status: FestivalTimingStatus;
  d_day: number | null;
  days_left: number | null;
  tip: string;
}

/** 날씨 카드 전용. available:false면 summary는 참고하지 않고 notice만 그대로 노출한다(지어내지 않음,
 * "실시간/실측" 표현 금지 — 부록 M notice 원칙과 동일). */
export interface FestivalWeather {
  available: boolean;
  summary: string | null;
  notice: string | null;
}

export interface FestivalDetailResponse {
  festival: Festival;
  /** FestivalsResponse.region과 동일 형태(재정의 없음) — 매칭 실패 시 null(지역 스팟 더보기 CTA 숨김). */
  region: FestivalRegion | null;
  /** 대표사진 포함 최대 8장. 빈 배열이면 PhotoCarousel이 자체 플레이스홀더를 그린다. */
  images: MediaImage[];
  timing: FestivalTiming;
  weather: FestivalWeather;
  /** 2026-09-20 — 축제 지역 좌표 기준 지금 날씨. null/미존재면 표시하지 않는다. */
  live_weather?: LiveWeather | null;
  /**
   * §36.8(신규, 03-design-spec.md 대표 피드백 후속) — TourAPI overview 정제본 또는 표준데이터
   * 축제내용(최대 1200자). optional인 이유는 timing/weather와 동일(하위호환) — 구버전 백엔드가
   * 이 필드를 안 내려주면 undefined다. null/undefined 둘 다 "축제 소개" 섹션 자체를 렌더하지
   * 않는다(빈 껍데기 금지, 지어내지 않음).
   */
  description?: string | null;
  ai_summary?: string | null;
  ai_provider?: string | null;
}

/**
 * §36 — GET /api/v1/festivals/{id}. 없는 id는 404(ApiError.status===404, 기존 에러 봉투) — 호출부가
 * SpotDetailContent의 notfound 처리와 동일한 패턴으로 "축제를 찾을 수 없어요"를 보여준다.
 */
export async function fetchFestivalDetail(
  festivalId: number | string,
  signal?: AbortSignal
): Promise<FestivalDetailResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/festivals/${encodeURIComponent(String(festivalId))}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "축제 정보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "축제 정보를 불러오지 못했습니다.");
  }

  return (await res.json()) as FestivalDetailResponse;
}

/* =========================================================================
 * 부록 P(신규, §37 — 03-design-spec.md, 2026-07-31) — 전국 날씨 보드
 * (`/tips` 상단, WeatherBoard.tsx). GET /api/v1/weather/nationwide. 오케스트레이터
 * 병렬 계약 — 9권역 그룹핑은 backend 소유(프론트는 응답 개수·순서를 그대로 렌더하고
 * 지어내지 않는다). verdict는 backend 판정값을 배지로만 옮긴다(congestion_level과 동일
 * 원칙 — 재판정 금지).
 * ========================================================================= */

export type WeatherVerdict = "good" | "fair" | "poor";

/** §P — 권역 1개. available:false면 pop/temp_c/verdict/tip을 신뢰하지 않고 notice만 보여준다. */
export interface NationwideWeatherRegion {
  key: string;
  label: string;
  region_code: string;
  available: boolean;
  pop: number | null;
  temp_c: number | null;
  verdict: WeatherVerdict | null;
  tip: string | null;
  notice: string | null;
}

export interface NationwideWeatherResponse {
  as_of: string;
  regions: NationwideWeatherRegion[];
}

/**
 * §P — GET /api/v1/weather/nationwide. 파라미터 없음. 백엔드가 아직 미배포면 404/네트워크실패로
 * 온다 — 호출부(WeatherBoard.tsx)가 섹션을 조용히 숨긴다(FeaturedSpots.tsx와 동일 원칙).
 */
export async function fetchNationwideWeather(
  signal?: AbortSignal
): Promise<NationwideWeatherResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/weather/nationwide`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "전국 날씨 정보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "전국 날씨 정보를 불러오지 못했습니다.");
  }

  return (await res.json()) as NationwideWeatherResponse;
}

/* =========================================================================
 * 부록 Q(신규, §37) — 출발일 플래너(홈 DeparturePlanner.tsx). GET /api/v1/plan/outlook.
 *
 * 2026-07-31 대표 지시(작업 중 계약 축소) — `weather.basis`는 이제 "forecast"|"none"만
 * 존재한다("normal"/평년 기준 폐기, 03-design-spec.md §37.2 근거). 예보 커버 밖 날짜(대략
 * 사흘 초과)는 weather.available:false로 오고, 이때도 congestion은 계속 정상 응답한다
 * (180일까지 "forecast"|"last_year" basis로 커버) — 그래서 congestion을 카드 배치상 주인공으로
 * 둔다(DeparturePlanner.tsx 참고).
 * ========================================================================= */

export type PlanWeatherBasis = "forecast" | "none";
export type PlanCongestionBasis = "forecast" | "last_year" | "none";

export interface PlanOutlookWeather {
  available: boolean;
  basis: PlanWeatherBasis;
  pop: number | null;
  temp_c: number | null;
  summary: string | null;
  notice: string | null;
}

export interface PlanOutlookCongestion {
  available: boolean;
  basis: PlanCongestionBasis;
  level: CongestionLevel | null;
  index: number | null;
  summary: string | null;
  notice: string | null;
}

export interface PlanOutlookRegion {
  region_code: string;
  region_name: string | null;
}

export interface PlanOutlookMeta {
  notice: string | null;
}

export interface PlanOutlookResponse {
  region: PlanOutlookRegion;
  date: string;
  days_ahead: number;
  weather: PlanOutlookWeather;
  congestion: PlanOutlookCongestion;
  meta: PlanOutlookMeta;
}

/**
 * §Q — GET /api/v1/plan/outlook?region_code=&date=YYYY-MM-DD. 둘 다 필수(호출부가 채워 보낸다).
 * 400 DATE_OUT_OF_RANGE(오늘~+180일 밖)는 이 함수가 안내 문구로 바꿔 던진다 — 호출부는
 * ApiError.message를 그대로 보여주면 된다(재해석 불필요).
 */
export async function fetchPlanOutlook(
  regionCode: string,
  date: string,
  signal?: AbortSignal
): Promise<PlanOutlookResponse> {
  const qs = new URLSearchParams({ region_code: regionCode, date });

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/plan/outlook?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "여행 시기 정보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(
      res,
      res.status === 400
        ? "선택한 날짜는 확인할 수 없어요. 오늘부터 180일 이내로 골라주세요."
        : "여행 시기 정보를 불러오지 못했습니다."
    );
  }

  return (await res.json()) as PlanOutlookResponse;
}

/* =========================================================================
 * 부록 R(신규, §37) — 계절 여행 섹션(홈 SeasonalSection.tsx). GET /api/v1/places/seasonal.
 *
 * 지시서 원문 계약은 popular/hidden을 "SpotCard[]"로 표기했지만, 같은 지시서가 "기존
 * FeaturedSpotCard 재사용(신규 카드 컴포넌트 금지)"을 명시한다 — FeaturedSpotCard는
 * FeaturedSpot(부록 H, image_url/region_name/photo_credit 포함) 형태만 렌더할 수 있고
 * 부록 C.2 SpotCard(위치·테마 등 다른 필드 조합)로는 그릴 수 없다. 재사용 요구를 만족하는
 * 유일한 해석으로, 이 문서는 실제 응답 항목 형태를 FeaturedSpot으로 채택한다 — 값을 지어내는
 * 것이 아니라 두 요구사항(계약 문구 vs 컴포넌트 재사용 지시) 중 명시적 지시를 우선한 것이다.
 * 백엔드 실계약이 다르게 확정되면(예: 진짜 SpotCard 형태) 오케스트레이터 통합 검증 단계에서
 * 이 타입과 SeasonalSection.tsx를 함께 바로잡아야 한다(핸드오프 참고).
 * ========================================================================= */

export type Season = "spring" | "summer" | "autumn" | "winter";

export interface SeasonalPlacesMeta {
  notice: string | null;
  basis: string | null;
}

export interface SeasonalPlacesResponse {
  season: Season;
  label: string;
  popular: FeaturedSpot[];
  hidden: FeaturedSpot[];
  meta: SeasonalPlacesMeta;
}

/**
 * §R — GET /api/v1/places/seasonal?season=&region_code=&region_block=&limit=. season은 필수,
 * 나머지는 선택(미지정 시 backend 기본 = 전국 9권역·기본 limit). 백엔드가 아직 미배포면
 * 404/네트워크실패로 온다 — 호출부(SeasonalSection.tsx)가 섹션을 조용히 숨긴다.
 *
 * regionBlock(부록 Q.3.2, 2026-08-01): 9권역 key(`gyeonggi`…`jeju`). 시군구 코드가 아니라
 * **권역 key** 다 — 백엔드가 그 권역 안 시군구 여러 곳을 훑는다. regionCode와 함께 주면
 * 백엔드에서 regionCode(더 좁은 지정)가 이긴다.
 */
export async function fetchSeasonalPlaces(
  season: Season,
  regionCode?: string | null,
  limit?: number,
  signal?: AbortSignal,
  regionBlock?: string | null
): Promise<SeasonalPlacesResponse> {
  const qs = new URLSearchParams({ season });
  if (regionCode) qs.set("region_code", regionCode);
  if (regionBlock) qs.set("region_block", regionBlock);
  if (limit) qs.set("limit", String(limit));

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/places/seasonal?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "계절 여행지 정보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "계절 여행지 정보를 불러오지 못했습니다.");
  }

  return (await res.json()) as SeasonalPlacesResponse;
}

/* =========================================================================
 * §41(신규) — 후기(리뷰) · 코스 공유(데모). 01-interface-contract.md 부록 R과 1:1로 유지한다.
 * (주의: 이 파일 위쪽의 "부록 R" 계절 여행 블록과는 별개다 — 그건 이 프론트 문서 자체의 로컬
 * 표기 순서일 뿐이고, 여기서 말하는 "부록 R"은 01-interface-contract.md가 후기·코스공유에 붙인
 * 문서 전체의 부록 문자다. 두 "R"은 서로 다른 문서·다른 시점에 독립적으로 매겨져 우연히 겹쳤다.)
 *
 * 신원 모델은 인증이 아니다(R.0) — X-Device-Id(deviceId.ts)만으로 "내 글"을 구분하고, 서버는
 * device_id를 어떤 응답에도 싣지 않는다. 대신 서버가 계산한 is_mine만 내려준다. 사용자 텍스트
 * (닉네임·한줄평·코스 제목)는 서버가 정제하지만, 프론트도 전부 텍스트 노드로만 렌더해야 한다
 * (dangerouslySetInnerHTML 금지, R.8-2) — 이 계약을 소비하는 컴포넌트(ReviewSection 등)의 필수 규칙.
 * ========================================================================= */

export type ReviewTargetType = "spot" | "festival";

/** R.2 — 별점 1~5점 분포. 값이 0이어도 다섯 키가 항상 존재한다(지어내지 않음, 서버가 채워 보낸다). */
export interface ReviewDistribution {
  "1": number;
  "2": number;
  "3": number;
  "4": number;
  "5": number;
}

/** 리뷰 0건이면 average는 null(0.0이 아니다) — R.2. */
export interface ReviewSummary {
  average: number | null;
  count: number;
  distribution: ReviewDistribution;
}

export interface ReviewItem {
  id: number;
  nickname: string;
  rating: number;
  /** 별점만 남긴 경우 null(R.2) — 빈 문자열로 지어내지 않는다. */
  comment: string | null;
  created_at: string;
  updated_at: string;
  /** 서버가 device_id를 대조해 계산한 값(R.0) — 이 값으로만 수정·삭제 버튼 노출을 판단한다. */
  is_mine: boolean;
}

export interface ReviewListResponse {
  summary: ReviewSummary;
  items: ReviewItem[];
  total: number;
}

export interface ReviewListParams {
  limit?: number;
  offset?: number;
}

/**
 * R.2 — GET /api/v1/reviews?target_type=&target_id=&limit=&offset=. 최신순 정렬, hidden 리뷰는
 * 목록·요약 양쪽에서 이미 제외된 상태로 온다(재판정 없음). ReviewSection.tsx가 최초 로딩과
 * "더보기" 양쪽에 이 함수를 그대로 재사용한다.
 */
export async function fetchReviews(
  targetType: ReviewTargetType,
  targetId: number | string,
  params?: ReviewListParams,
  signal?: AbortSignal
): Promise<ReviewListResponse> {
  const qs = new URLSearchParams({ target_type: targetType, target_id: String(targetId) });
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/reviews?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json", ...deviceHeaders() },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "후기를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "후기를 불러오지 못했습니다.");
  }

  return (await res.json()) as ReviewListResponse;
}

/**
 * R.5 — GET /api/v1/reviews/summary?target_type=&ids=1,2,3 (N+1 방지, **카드 목록에서 반드시
 * 이 함수를 1회만 호출**할 것 — 카드마다 개별 GET 금지). 요청한 id는 후기가 0건이어도
 * count:0으로 항상 포함되므로(R.5) 호출부가 키 존재 여부를 따로 방어할 필요가 없다.
 * ids가 비어 있으면 네트워크 호출 없이 빈 객체를 즉시 반환한다(빈 목록 카드 렌더 시 불필요한
 * 요청 방지).
 */
export async function fetchReviewsSummaryBulk(
  targetType: ReviewTargetType,
  ids: Array<number | string>,
  signal?: AbortSignal
): Promise<Record<string, ReviewSummary>> {
  const uniqueIds = Array.from(new Set(ids.map((id) => String(id))));
  if (uniqueIds.length === 0) return {};

  const qs = new URLSearchParams({ target_type: targetType, ids: uniqueIds.join(",") });

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/reviews/summary?${qs.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json", ...deviceHeaders() },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "별점 정보를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "별점 정보를 불러오지 못했습니다.");
  }

  const body = (await res.json()) as { summaries: Record<string, ReviewSummary> };
  return body.summaries;
}

export interface CreateReviewResponse {
  review: ReviewItem;
  summary: ReviewSummary;
}

/**
 * R.3 — POST /api/v1/reviews → 201. 409 REVIEW_EXISTS(같은 기기·같은 대상 중복)는 여기서 삼키지
 * 않고 그대로 ApiError로 던진다 — 호출부(ReviewSection)가 `err.code === "REVIEW_EXISTS"`로 분기해
 * "이미 작성하셨어요 — 수정할까요?" 흐름으로 이어간다(R.12-4 요구사항).
 */
export async function createReview(
  targetType: ReviewTargetType,
  targetId: number | string,
  nickname: string,
  rating: number,
  comment?: string,
  signal?: AbortSignal
): Promise<CreateReviewResponse> {
  const payload: Record<string, unknown> = {
    target_type: targetType,
    target_id: String(targetId),
    nickname,
    rating,
  };
  if (comment && comment.length > 0) payload.comment = comment;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/reviews`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        Accept: "application/json",
        ...deviceHeaders(),
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "후기를 등록하지 못했습니다.");
  }

  return (await res.json()) as CreateReviewResponse;
}

export interface PatchReviewPayload {
  rating?: number;
  /** 명시적 null = 한줄평 삭제(필드 누락과 구분된다, R.4). undefined면 이 필드를 아예 보내지 않는다. */
  comment?: string | null;
}

/** R.4 — PATCH /api/v1/reviews/{id} → 200, ReviewItem 단독(summary는 오지 않는다 — 호출부가
 * 평균을 새로 반영하려면 fetchReviewsSummaryBulk를 별도로 호출해야 한다). */
export async function patchReview(
  id: number,
  payload: PatchReviewPayload,
  signal?: AbortSignal
): Promise<ReviewItem> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/reviews/${id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        Accept: "application/json",
        ...deviceHeaders(),
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "후기를 수정하지 못했습니다.");
  }

  return (await res.json()) as ReviewItem;
}

/** R.4 — DELETE /api/v1/reviews/{id} → {"deleted": true}. device_id 불일치는 403 NOT_OWNER. */
export async function deleteReview(
  id: number,
  signal?: AbortSignal
): Promise<{ deleted: boolean }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/reviews/${id}`, {
      method: "DELETE",
      headers: { Accept: "application/json", ...deviceHeaders() },
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "백엔드 서버에 연결할 수 없습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "후기를 삭제하지 못했습니다.");
  }

  return (await res.json()) as { deleted: boolean };
}

/**
 * R.6 — POST /api/v1/reviews/{id}/report → 202. hidden:true면 서로 다른 기기 3건 신고 임계에
 * 도달해 즉시 숨겨졌다는 뜻 — 호출부가 그 카드를 목록에서 즉시 제거한다(R.6 요구사항).
 */
export async function reportReview(
  id: number,
  reason: string,
  signal?: AbortSignal
): Promise<{ status: string; hidden: boolean }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/reviews/${id}/report`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        Accept: "application/json",
        ...deviceHeaders(),
      },
      body: JSON.stringify({ reason }),
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "신고를 접수하지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "신고를 접수하지 못했습니다.");
  }

  return (await res.json()) as { status: string; hidden: boolean };
}

/* --- R.7 코스 공유 --- */

export interface ShareCourseRequest {
  nickname: string;
  title: string;
  /** 부록 I CourseResponse를 그대로 담는다 — 서버는 이 값을 해석하지 않고 그대로 보관·반환한다(R.7). */
  course: CourseResponse;
}

export interface ShareCourseResponse {
  share_code: string;
  created_at: string;
}

/**
 * R.7 — POST /api/v1/courses/share → 201. 413 COURSE_TOO_LARGE(32KB 초과)·400 INVALID_COURSE
 * (중첩 16단계 초과)는 여기서 삼키지 않고 그대로 ApiError로 던진다 — 호출부(ShareCourseModal)가
 * err.message를 그대로 보여준다(실사용에서 코스 하나가 32KB를 넘는 경우는 거의 없다).
 */
export async function shareCourse(
  payload: ShareCourseRequest,
  signal?: AbortSignal
): Promise<ShareCourseResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/share`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        Accept: "application/json",
        ...deviceHeaders(),
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "코스를 공유하지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "코스를 공유하지 못했습니다.");
  }

  return (await res.json()) as ShareCourseResponse;
}

/** R.7 상세 응답 — course는 공유 당시 저장된 CourseResponse 원본 그대로(재계산 없음). */
export interface SharedCourseDetail {
  share_code: string;
  nickname: string;
  title: string;
  spot_count: number;
  created_at: string;
  view_count: number;
  course: CourseResponse;
  is_mine: boolean;
}

/**
 * R.7 — GET /api/v1/courses/shared/{code}. 조회할 때마다 view_count가 1 증가하는 트랜잭션이라
 * (R.7) 호출부는 "보여줄 때만" 불러야 한다(내가 만든 목록을 갱신하려고 반복 호출하지 않는다 —
 * sharedCoursesStorage.ts 주석 참고). 없거나 숨겨진/형식이 틀린 코드는 404.
 */
export async function fetchSharedCourse(
  code: string,
  signal?: AbortSignal
): Promise<SharedCourseDetail> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/shared/${encodeURIComponent(code)}`, {
      method: "GET",
      headers: { Accept: "application/json", ...deviceHeaders() },
      cache: "no-store",
      credentials: "include", // 2026-08-20(QA L-2) — 좋아요 호출과 통일. 세션 쿠키가 있어야 is_mine 등 로그인 종속 값이 정확하다.
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "공유 코스를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "공유 코스를 불러오지 못했습니다.");
  }

  return (await res.json()) as SharedCourseDetail;
}

/** R.7 피드 항목 — 목록에는 course payload를 싣지 않는다(R.7, 응답 폭발 방지).
 * R.14.4(2026-08-20, additive) — like_count/liked_by_me 신설. 항상 존재(비로그인이면 liked_by_me=false). */
export interface SharedCourseFeedItem {
  share_code: string;
  nickname: string;
  title: string;
  spot_count: number;
  created_at: string;
  view_count: number;
  like_count: number;
  liked_by_me: boolean;
}

export interface SharedCourseFeedResponse {
  items: SharedCourseFeedItem[];
  total: number;
}

/** R.14.4 — 정렬 키. 생략(undefined)이면 서버 기본값 latest(무회귀 계약, SQL까지 종전과 동일). */
export type SharedCoursesSort = "latest" | "popular";

/** R.7/R.14.4 — GET /api/v1/courses/shared?limit=&offset=&sort=. limit 기본 20 / 최대 50. */
export async function fetchSharedCoursesFeed(
  limit?: number,
  offset?: number,
  signal?: AbortSignal,
  sort?: SharedCoursesSort
): Promise<SharedCourseFeedResponse> {
  const qs = new URLSearchParams();
  if (limit) qs.set("limit", String(limit));
  if (offset) qs.set("offset", String(offset));
  if (sort) qs.set("sort", sort);
  const query = qs.toString();

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/shared${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json", ...deviceHeaders() },
      cache: "no-store",
      credentials: "include", // 2026-08-20(QA L-2) — 좋아요 호출과 통일. 빠지면 liked_by_me가 분리배포/로컬개발에서 항상 false로 보인다.
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "다른 사람 코스를 불러오지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "다른 사람 코스를 불러오지 못했습니다.");
  }

  return (await res.json()) as SharedCourseFeedResponse;
}

/** R.14.1/R.14.2 응답 — 멱등(이미 같은 상태여도 200, 409/404를 쓰지 않는다). */
export interface SharedCourseLikeResponse {
  liked: boolean;
  like_count: number;
}

/**
 * R.14.1 — POST /api/v1/courses/shared/{share_code}/like. 로그인 세션 쿠키 필수(device_id 아님,
 * R.14.0) — 비로그인이면 401(봉투 아닌 FastAPI 기본 {"detail":...}, 호출부가 status만 분기).
 */
export async function likeSharedCourse(shareCode: string): Promise<SharedCourseLikeResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/shared/${encodeURIComponent(shareCode)}/like`, {
      method: "POST",
      headers: { Accept: "application/json" },
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "좋아요를 반영하지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "좋아요를 반영하지 못했습니다.");
  }
  return (await res.json()) as SharedCourseLikeResponse;
}

/** R.14.2 — DELETE /api/v1/courses/shared/{share_code}/like. 규칙은 likeSharedCourse와 동일. */
export async function unlikeSharedCourse(shareCode: string): Promise<SharedCourseLikeResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/shared/${encodeURIComponent(shareCode)}/like`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "좋아요를 취소하지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "좋아요를 취소하지 못했습니다.");
  }
  return (await res.json()) as SharedCourseLikeResponse;
}

/** R.7 — DELETE /api/v1/courses/shared/{code}. device_id 불일치 403 NOT_OWNER, 없으면 404. */
export async function deleteSharedCourse(
  code: string,
  signal?: AbortSignal
): Promise<{ deleted: boolean }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/shared/${encodeURIComponent(code)}`, {
      method: "DELETE",
      headers: { Accept: "application/json", ...deviceHeaders() },
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "공유를 삭제하지 못했습니다.");
  }

  if (!res.ok) {
    throw await parseErrorResponse(res, "공유를 삭제하지 못했습니다.");
  }

  return (await res.json()) as { deleted: boolean };
}

/* ---------------- 2026-08-17 신설 — 내가 저장한 AI 코스 (Phase C, 로그인 필수) ----------------
 * course_share.py의 /share·/shared(device_id 기준, 공개 공유)와는 별개. 여기는 로그인 계정
 * 전용 개인 보관함이라 전부 credentials:"include"로 세션 쿠키를 실어 보낸다.
 */
export interface MyCourseSummary {
  id: number;
  region_code: string;
  mode: "ai" | "custom";
  created_at: string;
}

export interface MyCourseDetail extends MyCourseSummary {
  course: CourseResponse;
}

export async function saveMyCourse(
  regionCode: string,
  mode: "ai" | "custom",
  course: CourseResponse,
  signal?: AbortSignal
): Promise<MyCourseSummary> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/mine`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
      body: JSON.stringify({ region_code: regionCode, mode, course }),
      credentials: "include",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "코스를 저장하지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "코스를 저장하지 못했습니다.");
  }
  return (await res.json()) as MyCourseSummary;
}

export async function fetchMyCourses(signal?: AbortSignal): Promise<MyCourseSummary[]> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/mine`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "저장한 코스를 불러오지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "저장한 코스를 불러오지 못했습니다.");
  }
  const data = (await res.json()) as { items: MyCourseSummary[] };
  return data.items;
}

export async function fetchMyCourseDetail(
  id: number,
  signal?: AbortSignal
): Promise<MyCourseDetail> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/mine/${id}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "저장한 코스를 불러오지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "저장한 코스를 불러오지 못했습니다.");
  }
  return (await res.json()) as MyCourseDetail;
}

export async function deleteMyCourse(
  id: number,
  signal?: AbortSignal
): Promise<{ deleted: boolean }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/courses/mine/${id}`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
      credentials: "include",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "저장한 코스를 삭제하지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "저장한 코스를 삭제하지 못했습니다.");
  }
  return (await res.json()) as { deleted: boolean };
}

/* ---------------- 2026-08-18 신설 — 고객문의 (마이페이지, 로그인 필수) ----------------
 * MyCourseSummary 블록과 동일한 관례. "간단한 문의 폼 + DB 저장"까지만 — admin 콘솔 조회
 * 화면은 아직 없다(backend/app/api/inquiries.py 모듈 docstring 참고).
 */
export interface InquirySummary {
  id: number;
  status: "new" | "resolved";
  created_at: string;
  reply: string | null;
  replied_at: string | null;
}

export async function createInquiry(
  message: string,
  contactEmail: string | null,
  signal?: AbortSignal
): Promise<InquirySummary> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/inquiries`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
      body: JSON.stringify({ message, contact_email: contactEmail }),
      credentials: "include",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "문의를 접수하지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "문의를 접수하지 못했습니다.");
  }
  return (await res.json()) as InquirySummary;
}

export async function fetchMyInquiries(signal?: AbortSignal): Promise<InquirySummary[]> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/inquiries/mine`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "문의 내역을 불러오지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "문의 내역을 불러오지 못했습니다.");
  }
  const data = (await res.json()) as { items: InquirySummary[] };
  return data.items;
}

/** GET /api/v1/onboarding/me — 로그인 계정에 저장된 최신 취향 프로필(없으면 null). */
export async function fetchMyOnboardingProfile(
  signal?: AbortSignal
): Promise<OnboardingResult | null> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/onboarding/me`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "취향 프로필을 불러오지 못했습니다.");
  }
  if (!res.ok) {
    throw await parseErrorResponse(res, "취향 프로필을 불러오지 못했습니다.");
  }
  const data = (await res.json()) as { profile: OnboardingResult | null };
  return data.profile;
}

/* ---------------- 부록 U — 전국 시도 혼잡도 보드 (2026-08-01) ----------------
 * GET /api/v1/congestion/nationwide
 * 각 항목은 "그 시도의 **대표 시군구 1곳**" 기준값이다(basis_region_name 을 화면에 표기해야
 * 한다 — 숨기면 "서울 = 종로 기준"이라는 사실을 속이는 것이 된다).
 * available=false 면 index/level 이 **null** 이다(0 이 아니다) — 데이터 없음과 한산함을 섞지 않는다.
 */
export interface NationwideCongestionItem {
  sido_code: string;
  short_name: string;
  region_code: string;
  basis_region_name: string | null;
  available: boolean;
  index: number | null;
  level: "low" | "mid" | "high" | null;
  sample_count: number;
  /** 그 지역의 실제 관광 사진(한국관광공사 TourAPI). 없으면 null — 다른 지역 사진으로 채우지 않는다. */
  photo_url: string | null;
  /** 위 사진에 찍힌 곳의 실제 이름. 화면이 무엇을 보여주는지 밝히기 위해 함께 표기한다. */
  photo_spot_name: string | null;
}

export interface NationwideCongestionResponse {
  items: NationwideCongestionItem[];
  fetched_at: string;
  notice: string | null;
}

export async function fetchNationwideCongestion(
  signal?: AbortSignal
): Promise<NationwideCongestionResponse> {
  const res = await fetch(`${API_BASE}/api/v1/congestion/nationwide`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    throw new ApiError(res.status, "NATIONWIDE_CONGESTION_FAILED", "전국 혼잡도를 불러오지 못했습니다.");
  }
  return (await res.json()) as NationwideCongestionResponse;
}

/* =========================================================================
 * 부록 Z(신규, 01-interface-contract.md, 2026-08-20) — 개인화 여행 팁. POST
 * /api/v1/tips/personalized. 인터페이스·폴백 경계는 backend-engineer 소관(§Z.0~Z.6), 프롬프트
 * 본문은 02-ai-strategy.md(ai-optimization-engineer) 소관 — 여기서는 계약대로 타입/호출만 둔다.
 * §Z.0-2: 이 엔드포인트는 어떤 경우에도 5xx를 내지 않고 정적 5건을 200으로 폴백한다. 그래도
 * 이 화면(TipsContent.tsx)은 로그인+프로필이 있을 때만 호출한다(불필요한 호출/레이트리밋
 * 소모를 줄이기 위한 프론트 판단, §47.9 지시서 그대로) — 실패하면 기존 정적 5건을 그대로 둔다.
 * ========================================================================= */

/** §Z.2 tips[].category — 고정 enum(정적 5건과 동일 축). */
export type PersonalizedTipCategory = "혼잡" | "교통" | "날씨" | "반려동물" | "안전";

export interface PersonalizedTip {
  id: string;
  category: PersonalizedTipCategory;
  title: string;
  body: string;
  source: "ai" | "static";
}

export interface PersonalizedTipsResponse {
  tips: PersonalizedTip[];
  generated_by: "ai-v1" | "static-v2";
  /** ai일 때만 문자열, static이면 null(§Z.2). 화면은 이 문구를 그대로 노출해야 한다(정직 표기). */
  notice: string | null;
}

/** §Z.4: 서버 LLM 타임아웃은 20초(TIPS_TIMEOUT_SEC) 뒤 정적 폴백으로 흡수한다(5xx 없음).
 * 클라이언트가 무한정 매달리지 않도록 여유를 두고 끊는다(2026-08-20, QA m-3 — 삭제된
 * askConcierge/analyzeOnboarding과 동일한 AbortController 타임아웃 패턴). */
const PERSONALIZED_TIPS_TIMEOUT_MS = 30_000;

/**
 * §Z.1 — POST /api/v1/tips/personalized. region_code는 선택(형식 위반만 422, 미등록 코드는 무시).
 * 비로그인도 호출 가능하지만(§Z.1) 이 화면은 로그인+프로필 있을 때만 호출한다(위 파일 헤더 설명).
 */
export async function fetchPersonalizedTips(
  regionCode?: string | null,
  signal?: AbortSignal
): Promise<PersonalizedTipsResponse> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, PERSONALIZED_TIPS_TIMEOUT_MS);
  const onExternalAbort = () => controller.abort();
  signal?.addEventListener("abort", onExternalAbort);

  try {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/v1/tips/personalized`, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8", Accept: "application/json" },
        body: JSON.stringify({ region_code: regionCode ?? null }),
        credentials: "include",
        signal: controller.signal,
      });
    } catch (e) {
      if (signal?.aborted && !timedOut) throw e; // 사용자/호출부가 직접 취소
      if (timedOut) {
        throw new ApiError(0, "TIMEOUT", "맞춤 팁을 불러오는 데 시간이 오래 걸리고 있어요.");
      }
      throw new ApiError(0, "NETWORK_UNAVAILABLE", "맞춤 팁을 불러오지 못했습니다.");
    }
    if (!res.ok) {
      throw await parseErrorResponse(res, "맞춤 팁을 불러오지 못했습니다.");
    }
    return (await res.json()) as PersonalizedTipsResponse;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onExternalAbort);
  }
}

// ---------------------------------------------------------------------------
// 저장한 스팟 계정 보관함 — 2026-09-16(대표 지시 "기기가 아닌 계정의 데이터로"). 로그인 필수.
// 스팟 본문은 서버가 id 로 재구성하고, 프론트는 혼잡도 스냅샷만 올린다(savedSpotsStorage.ts 참고).
// ---------------------------------------------------------------------------
export interface SavedSpotRemote {
  id: number;
  name: string;
  category: SpotCategory;
  region_code: string;
  location: { lat: number; lng: number } | null;
  congestion: { index: number | null; level: CongestionLevel; tier: "A" | "B" | "C" | "none" } | null;
  is_hidden_gem: boolean;
  saved_at: string;
}

async function savedSpotsRequest(path: string, init: RequestInit, failMsg: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/saved-spots${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init.headers ?? {}) },
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", failMsg);
  }
  if (!res.ok) {
    let code = "UNKNOWN";
    let message = failMsg;
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } };
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, code, message);
  }
  return res;
}

export async function fetchSavedSpots(): Promise<SavedSpotRemote[]> {
  const res = await savedSpotsRequest("", { method: "GET" }, "저장한 스팟을 불러오지 못했습니다.");
  const body = (await res.json()) as { items?: SavedSpotRemote[] };
  return body.items ?? [];
}

export async function putSavedSpotRemote(
  spotId: number,
  congestion: SavedSpotRemote["congestion"]
): Promise<SavedSpotRemote> {
  const res = await savedSpotsRequest(
    `/${spotId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ congestion }),
    },
    "스팟을 저장하지 못했습니다."
  );
  return (await res.json()) as SavedSpotRemote;
}

export async function deleteSavedSpotRemote(spotId: number): Promise<void> {
  await savedSpotsRequest(`/${spotId}`, { method: "DELETE" }, "저장을 해제하지 못했습니다.");
}
