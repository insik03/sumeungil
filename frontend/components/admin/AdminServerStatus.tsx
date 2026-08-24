"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { AdminServerStatus as ServerStatus, fetchAdminServerStatus } from "../../lib/adminApi";

/**
 * 서버 상태 탭 (2026-08-23, 대표 지시 "그라파나랑 운영대시보드랑 붙여야 한다").
 *
 * 그라파나 자체를 iframe으로 임베드하지 않는다 — 외부 인스턴스(grafana.aitestbed.kr)라
 * 임베드 허용 여부·로그인 상태가 우리가 못 고치는 그쪽 설정에 달려 있다. 대신 백엔드가
 * Prometheus에서 직접 읽은 핵심 지표(응답시간·에러율·요청수)를 여기 숫자로 보여주고,
 * 더 자세히 보고 싶을 때만 그라파나로 링크한다 — 콘솔 안에서 "지금 괜찮은지"는 바로 알 수
 * 있고, 과거 추이·상세 그래프는 그라파나에서 본다.
 */
export default function AdminServerStatusTab({ onSessionLost }: { onSessionLost: () => void }) {
  const [data, setData] = useState<ServerStatus | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setData(null);
    try {
      setData(await fetchAdminServerStatus());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSessionLost();
      else setFailed(true);
    }
  }, [onSessionLost]);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <div className="admin-empty">
        <p>서버 상태를 불러오지 못했어요.</p>
        <button type="button" className="admin-btn admin-btn--primary" onClick={() => void load()}>
          다시 시도
        </button>
      </div>
    );
  }
  if (!data) return <div className="admin-row admin-row--skeleton" />;

  if (!data.reachable) {
    return (
      <div className="admin-traffic">
        <div className="admin-empty">
          <p>운영 지표 서버(Prometheus)에 연결할 수 없어요.</p>
          <p className="admin-traffic__none">서버가 다운된 것과는 달라요 — 지표 수집 경로만 확인이 필요할 수 있어요.</p>
        </div>
        <a className="admin-btn admin-btn--ghost" href={data.grafana_url} target="_blank" rel="noopener noreferrer">
          그라파나에서 확인하기 →
        </a>
      </div>
    );
  }

  const noTraffic = data.requests_24h === 0 || data.requests_24h === null;

  return (
    <div className="admin-traffic">
      <div className="admin-traffic__kpis">
        <div className="admin-kpi">
          <span className="admin-kpi__num">
            {data.backend_up === null ? "?" : data.backend_up ? "🟢" : "🔴"}
          </span>
          <span className="admin-kpi__label">백엔드 상태</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">{data.requests_24h ?? "—"}</span>
          <span className="admin-kpi__label">최근 24h 요청수</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">
            {data.avg_response_ms != null ? `${Math.round(data.avg_response_ms)}ms` : "—"}
          </span>
          <span className="admin-kpi__label">평균 응답시간</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">
            {data.p95_response_ms != null ? `${Math.round(data.p95_response_ms)}ms` : "—"}
          </span>
          <span className="admin-kpi__label">p95 응답시간</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">
            {data.error_rate_pct != null ? `${data.error_rate_pct.toFixed(1)}%` : "—"}
          </span>
          <span className="admin-kpi__label">5xx 에러율</span>
        </div>
      </div>

      {noTraffic && (
        <p className="admin-traffic__caveat">최근 24시간 동안 요청이 없어서 응답시간·에러율은 표시되지 않아요.</p>
      )}

      <p className="admin-traffic__caveat">
        이 숫자는 최근 24시간 누적입니다. 과거 추이·상세 그래프는 그라파나에서 볼 수 있어요.
      </p>

      <a
        className="admin-btn admin-btn--ghost"
        href={data.grafana_url}
        target="_blank"
        rel="noopener noreferrer"
      >
        그라파나에서 자세히 보기 →
      </a>
    </div>
  );
}
