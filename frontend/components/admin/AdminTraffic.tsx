"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { AdminTraffic as Traffic, fetchAdminTraffic } from "../../lib/adminApi";

/**
 * 운영 트래픽 탭 (부록 X, 2026-08-10, 대표 지시)
 *
 * ## 화면이 지켜야 할 정직성 두 가지
 *
 * **1. 방문자 수는 추정치다.** 고유 `ip_hash` 수를 센 값인데, 이동통신 IP 는 수시로 바뀌고
 * 사무실·학교·카페는 여러 사람이 한 IP 를 쓴다. 실제보다 많게도 적게도 나온다.
 * 화면에 "명"이라고만 쓰면 정확한 사람 수로 읽히므로 **"추정"을 함께 적는다.**
 *
 * **2. `ip_hash` 는 IP 가 아니다.** 원본 IP 를 저장하지 않기로 한 결정(2026-08-10) 때문에
 * 되돌릴 수 없는 해시만 있다. 어느 나라인지도, 누구인지도 알 수 없다.
 * 이걸 "접속 IP" 라고 표기하면 운영자가 없는 정보를 있다고 착각한다 —
 * 그래서 라벨을 "요청 지문"으로 쓰고 한계를 캡션으로 붙인다.
 */
export default function AdminTrafficTab({ onSessionLost }: { onSessionLost: () => void }) {
  const [data, setData] = useState<Traffic | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setData(null);
    try {
      setData(await fetchAdminTraffic(14));
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
        <p>트래픽 집계를 불러오지 못했어요.</p>
        <button type="button" className="admin-btn admin-btn--primary" onClick={() => void load()}>
          다시 시도
        </button>
      </div>
    );
  }
  if (!data) return <div className="admin-row admin-row--skeleton" />;

  const peak = Math.max(1, ...data.hourly.map((h) => h.hits));
  const maxDay = Math.max(1, ...data.daily.map((d) => d.hits));

  return (
    <div className="admin-traffic">
      <div className="admin-traffic__kpis">
        <div className="admin-kpi">
          <span className="admin-kpi__num">{data.today_visitors}</span>
          <span className="admin-kpi__label">오늘 방문자 (추정)</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">{data.today_hits}</span>
          <span className="admin-kpi__label">오늘 요청 수</span>
        </div>
        <div className="admin-kpi">
          <span className="admin-kpi__num">{data.today_top_hits}</span>
          <span className="admin-kpi__label">한 곳에서 최다 요청</span>
        </div>
      </div>

      <p className="admin-traffic__caveat">
        방문자 수는 <b>요청 지문(해시)의 개수</b>라 정확한 사람 수가 아닙니다. 같은 사람이
        휴대폰과 PC 로 오면 2로, 같은 사무실 여러 명은 1로 셀 수 있어요. 추세를 보는 용도입니다.
      </p>

      <section className="admin-traffic__block">
        <h3 className="admin-traffic__title">최근 {data.daily.length}일</h3>
        {data.daily.length === 0 ? (
          <p className="admin-traffic__none">아직 쌓인 기록이 없어요.</p>
        ) : (
          <ul className="admin-bars">
            {data.daily.map((d) => (
              <li key={d.day} className="admin-bar">
                <span className="admin-bar__label">{d.day.slice(5)}</span>
                <span className="admin-bar__track">
                  <span className="admin-bar__fill" style={{ width: `${(d.hits / maxDay) * 100}%` }} />
                </span>
                <span className="admin-bar__value">
                  방문 {d.visitors} · 요청 {d.hits}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="admin-traffic__block">
        <h3 className="admin-traffic__title">오늘 시간대별</h3>
        <ul className="admin-hours">
          {data.hourly.map((h) => (
            <li key={h.hour} className="admin-hour" title={`${h.hour}시 · ${h.hits}건`}>
              <span className="admin-hour__fill" style={{ height: `${(h.hits / peak) * 100}%` }} />
              <span className="admin-hour__label">{h.hour % 6 === 0 ? h.hour : ""}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="admin-traffic__block">
        <h3 className="admin-traffic__title">오늘 많이 열린 경로</h3>
        {data.top_paths.length === 0 ? (
          <p className="admin-traffic__none">아직 기록이 없어요.</p>
        ) : (
          <ul className="admin-paths">
            {data.top_paths.map((p) => (
              <li key={p.path} className="admin-path">
                <code>{p.path}</code>
                <b>{p.hits}</b>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="admin-traffic__block">
        <h3 className="admin-traffic__title">오늘 요청이 많은 곳</h3>
        <p className="admin-traffic__caption">
          아래는 <b>IP 가 아니라 되돌릴 수 없는 지문</b>입니다. 원본 IP 를 저장하지 않기로 했기
          때문에 누구인지·어느 나라인지는 알 수 없어요. <b>한 곳에서 비정상적으로 많이
          두드리는지</b>를 보는 용도입니다.
        </p>
        {data.heavy_clients.length === 0 ? (
          <p className="admin-traffic__none">아직 기록이 없어요.</p>
        ) : (
          <ul className="admin-paths">
            {data.heavy_clients.map((c) => (
              <li key={c.ip_hash} className="admin-path">
                <code>{c.ip_hash}</code>
                <span className="admin-path__meta">
                  {c.first_seen.slice(11, 16)} ~ {c.last_seen.slice(11, 16)}
                </span>
                <b>{c.hits}</b>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="admin-traffic__caveat">
        집계는 {data.retention_days}일간 보관하고 자동으로 지웁니다. 정적 파일·헬스체크·관리자
        화면은 세지 않아요.
      </p>
    </div>
  );
}
