import { RerankBlock, SpotCard } from "../../lib/api";

interface RerankBannersProps {
  /** RecommendResponse.rerank. rerank 미요청/미지원 백엔드면 undefined — 그대로 아무것도 렌더하지 않는다(graceful). */
  rerank: RerankBlock | null | undefined;
  /** congested_spot_ids/boosted_spot_ids로 이름을 찾을 items(서버가 준 순서 그대로). */
  items: SpotCard[];
}

/**
 * 부록 F 파트1(F.1-7)·파트4(F.4-7) 배너/배지.
 * - congestion.level·match_score·reason·순서는 절대 재계산하지 않는다. notice는 텍스트 노드로만 렌더.
 * - notice에는 스팟명이 없다(F.1-6/F.4-6, 인젝션 방지 설계) — 이름이 필요하면 congested/boosted id로
 *   items에서 찾아 프론트가 조합한다.
 * - backend가 아직 rerank 블록을 내려주지 않아도(백엔드 미구현) 이 컴포넌트는 조용히 아무것도 그리지 않는다.
 */
export default function RerankBanners({ rerank, items }: RerankBannersProps) {
  if (!rerank) return null;

  const nameOf = (id: number): string | null => items.find((s) => s.id === id)?.name ?? null;

  const dist = rerank.distribution;
  const showDistBanner = !!dist && (dist.applied || dist.reason === "no_alternative");
  const congestedNames = dist?.applied
    ? dist.congested_spot_ids.map(nameOf).filter((n): n is string => !!n)
    : [];
  const boostedNames = dist?.applied
    ? dist.boosted_spot_ids.map(nameOf).filter((n): n is string => !!n)
    : [];

  const weather = rerank.weather;
  const weatherUnavailable = !!weather && (weather.provider_status === "unavailable" || weather.band === "unknown");
  const weatherApplied = !!weather && weather.applied;

  return (
    <>
      {showDistBanner && dist && (
        <div
          className={`rerank-banner${dist.applied ? " rerank-banner--balance" : " rerank-banner--warn"}`}
          role="status"
        >
          <span>
            {dist.notice}
            {(congestedNames.length > 0 || boostedNames.length > 0) && (
              <span className="rerank-banner__detail">
                {congestedNames.length > 0 && `혼잡: ${congestedNames.join(", ")}`}
                {congestedNames.length > 0 && boostedNames.length > 0 && " · "}
                {boostedNames.length > 0 && `대안: ${boostedNames.join(", ")}`}
              </span>
            )}
          </span>
        </div>
      )}

      {weatherUnavailable && <span className="weather-status-badge">날씨 정보 준비중</span>}

      {weatherApplied && weather && (
        <div className="rerank-banner rerank-banner--weather" role="status">
          <span>{weather.notice}</span>
        </div>
      )}
    </>
  );
}
