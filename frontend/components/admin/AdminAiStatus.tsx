"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { AdminAiStatus as AiStatus, fetchAdminAiStatus } from "../../lib/adminApi";

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("ko-KR", { hour12: false });
}

/**
 * 2026-09-20 — "AI 사용량" 탭. 무료 Gemini 한도(#99)와 코스 LLM 일일 상한이 운영의 가장 큰 변수라
 * 관리자가 한 화면에서 보게 한다. 값은 백엔드 프로세스 메모리 카운터(재시작하면 0)라 "천장 확인용"이지
 * 회계가 아니다 — 그 한계를 화면에 같이 적는다. CSP 보고는 보고 전용 정책 → 강제 전환 판단용.
 */
export default function AdminAiStatusTab({ onSessionLost }: { onSessionLost: () => void }) {
  const [data, setData] = useState<AiStatus | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setData(null);
    try {
      setData(await fetchAdminAiStatus());
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
        <p>AI 사용 현황을 불러오지 못했어요.</p>
        <button type="button" className="admin-btn admin-btn--primary" onClick={() => void load()}>
          다시 시도
        </button>
      </div>
    );
  }
  if (!data) return <div className="admin-row admin-row--skeleton" />;

  const usedPct = data.course_llm_cap_global > 0
    ? Math.min(100, Math.round((data.course_llm_used_today / data.course_llm_cap_global) * 100))
    : 0;
  const summaryPct = data.spots_total > 0 ? Math.round((data.summaries_pregenerated / data.spots_total) * 100) : 0;

  return (
    <div className="admin-traffic">
      <div className="admin-traffic__kpis">
        <div className="admin-kpi">
          <span className="admin-kpi__num">{data.provider === "gemini" ? "Gemini" : data.provider === "ollama" ? "Ollama" : data.provider}</span>
          <span className="admin-kpi__label">LLM 제공자 · {data.model}</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">
            {data.course_llm_used_today}
            <small style={{ fontSize: 13, fontWeight: 500, color: "var(--admin-faint)" }}> / {data.course_llm_cap_global}</small>
          </span>
          <span className="admin-kpi__label">오늘 코스 LLM 호출(전체 상한)</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num" style={{ color: data.quota_429_last_24h > 0 ? "var(--admin-danger)" : undefined }}>
            {data.quota_429_last_24h}
          </span>
          <span className="admin-kpi__label">한도 초과(429) 최근 24h · 1h {data.quota_429_last_hour}</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">{data.summaries_pregenerated}</span>
          <span className="admin-kpi__label">사전 생성 요약 · 전체 {data.spots_total}곳의 {summaryPct}%</span>
        </div>
      </div>

      <div className="admin-traffic__block">
        <h3 className="admin-traffic__title">오늘 코스 LLM 사용량</h3>
        <ul className="admin-bars">
          <li className="admin-bar">
            <span className="admin-bar__label">전체</span>
            <span className="admin-bar__track">
              <span className="admin-bar__fill" style={{ width: `${usedPct}%` }} />
            </span>
            <span className="admin-bar__value">
              {data.course_llm_used_today} / {data.course_llm_cap_global} · 계정당 {data.course_llm_cap_per_user}
            </span>
          </li>
        </ul>
        <p className="admin-traffic__caption">
          마지막 성공 {fmt(data.last_success_at)} · 마지막 429 {fmt(data.last_429_at)}
          {data.fallback_suspected && " · 지금은 한도 초과로 규칙 기반 폴백 중일 수 있어요"}
        </p>
        <p className="admin-traffic__caveat">
          카운터는 백엔드 프로세스 메모리에 있어 재배포하면 0부터 다시 셉니다. 무료 티어(하루 20회)는 이 화면과
          별개로 Google 쪽에서 세므로, 429가 보이면 그날은 이미 한도를 넘긴 것입니다.
        </p>
      </div>

      <div className="admin-traffic__block">
        <h3 className="admin-traffic__title">CSP 위반 보고(보고 전용 정책)</h3>
        {data.csp_total === 0 ? (
          <p className="admin-traffic__none">재시작 이후 보고가 없어요. 며칠 비어 있으면 강제 정책으로 바꿔도 됩니다.</p>
        ) : (
          <div className="admin-table__wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>지시자 @ 호스트</th>
                  <th>건수</th>
                </tr>
              </thead>
              <tbody>
                {data.csp_top.map(([key, n]) => (
                  <tr key={key}>
                    <td className="admin-table__mono">{key}</td>
                    <td className="admin-table__num">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="admin-traffic__caption">총 {data.csp_total}건 · 종류 {data.csp_distinct}</p>
      </div>
    </div>
  );
}
