"use client";

import { useEffect, useState } from "react";
import { fetchNationwideCongestion } from "./api";

/** 순위가 매겨진 시도 1건. 화면이 쓰는 값만 추린다(원본 응답은 필드가 더 많다). */
export interface HotRegion {
  /** 법정동 시도 2자리 — SIDO_REGIONS.sidoCode 와 같은 체계. */
  sidoCode: string;
  /** 대표 시군구 코드 — SIDO_REGIONS.regionCode / QUICK_REGIONS.sigunguCd 와 매칭용. */
  regionCode: string;
  shortName: string;
  /** "서울특별시 종로구" — 이 값이 사실 어디 기준인지 밝히는 데 쓴다. */
  basisLabel: string | null;
  /** 방문 집중률(0~100). 클수록 붐빈다. */
  index: number;
}

/** 칩으로 보여줄 상한. 17개를 다 보여주면 "많이 찾는 곳"이라는 신호가 사라진다. */
export const HOT_REGION_LIMIT = 8;
/** 이보다 적게 잡히면 순위라고 부를 만하지 않아 고정 목록으로 되돌린다. */
const MIN_USABLE = 4;

/**
 * "지금 많이 찾는 지역" — 전국 시도를 **방문 집중도 높은 순**으로 돌려준다.
 * 원천 실패·표본 부족이면 `null` → 호출부는 종전 고정 목록(SIDO_REGIONS / QUICK_REGIONS)을 쓴다.
 *
 * 값의 정체(중요): GET /api/v1/congestion/nationwide 의 `index` 는 그 시도 **대표 시군구 board 에
 * 잡힌 관광지들의 집중률 중앙값**이다. 한 곳의 값이 아니라 그 지역 관광지 전체를 모은 값이고,
 * 평균이 아니라 중앙값인 건 백엔드가 실측으로 정한 것이다(nationwide_congestion_service.py):
 * 평균·최대값을 쓰면 한 곳이 튀어 17개 시도 중 13곳이 high 로 붙어버려 지역 간 차이가 사라졌다.
 * 그래서 여기서 다시 평균을 내지 않고 서버 값을 그대로 순위에만 쓴다.
 *
 * 호출은 화면당 1회다. 응답은 서버에서 12시간 캐시되므로 원천 쿼터를 더 태우지 않는다.
 */
export function useHotRegions(limit: number = HOT_REGION_LIMIT): HotRegion[] | null {
  const [hot, setHot] = useState<HotRegion[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchNationwideCongestion(controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        const ranked = (res.items ?? [])
          // available=false 는 원천 실패·데이터 없음이다. 0으로 치환하면 "한적한 곳"이라고
          // 거짓말하게 되므로 순위에서 아예 뺀다(지어내지 않는다).
          .filter((i) => i.available && i.index != null)
          .sort((a, b) => (b.index ?? 0) - (a.index ?? 0))
          .slice(0, limit)
          .map((i) => ({
            sidoCode: i.sido_code,
            regionCode: i.region_code,
            shortName: i.short_name,
            basisLabel: i.basis_region_name,
            index: i.index as number,
          }));
        if (ranked.length >= MIN_USABLE) setHot(ranked);
      })
      // 혼잡도는 부가 신호다. 실패해도 지역 선택 자체는 고정 목록으로 계속 돼야 한다.
      .catch(() => undefined);
    return () => controller.abort();
  }, [limit]);

  return hot;
}
