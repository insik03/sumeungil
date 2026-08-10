"use client";

import { Fragment, ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, CourseLeg, SharedCourseDetail, fetchSharedCourse } from "../../lib/api";
import CourseStepCard from "./CourseStepCard";
import CourseMap from "./CourseMap";

type Status = "loading" | "success" | "notfound" | "error";

interface SharedCourseDetailContentProps {
  code: string;
}

/** 미터를 사람이 읽기 쉬운 거리 문구로. CourseContent.tsx의 formatMeters와 동일 로직 —
 * LEVEL_META가 여러 파일에 의도적으로 3중 복제돼 있는 것과 같은 관례(CourseStepCard.tsx 주석
 * 근거)를 따라, 이 작은 헬퍼도 CourseContent.tsx를 export로 열지 않고 여기 다시 둔다. */
function formatMeters(meters: number): string {
  if (meters < 1000) return `${Math.round(meters)}m`;
  return `${(meters / 1000).toFixed(1)}km`;
}

function WalkIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <ellipse cx="8" cy="7" rx="2.2" ry="3" fill="currentColor" transform="rotate(-15 8 7)" />
      <ellipse cx="16" cy="16" rx="2.2" ry="3" fill="currentColor" transform="rotate(15 16 16)" />
      <circle cx="8" cy="3" r="1.1" fill="currentColor" />
      <circle cx="16" cy="12" r="1.1" fill="currentColor" />
    </svg>
  );
}

function CarIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1a2 2 0 1 1-4 0H8a2 2 0 1 1-4 0H3a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h2Z"
        fill="currentColor"
      />
      <circle cx="7" cy="16" r="1.6" fill="#ffffff" />
      <circle cx="17" cy="16" r="1.6" fill="#ffffff" />
    </svg>
  );
}

/** 구간 이동 정보 한 줄 — CourseContent.tsx의 CourseLegInfo와 동일 로직(재구현 사유는 위 주석 참고). */
function CourseLegInfo({ leg }: { leg: CourseLeg }) {
  const parts: { key: string; node: ReactNode }[] = [];
  if (leg.walk) {
    parts.push({
      key: "walk",
      node: (
        <span className="course-leg__part">
          <WalkIcon />
          도보 {leg.walk.minutes}분({formatMeters(leg.walk.meters)})
        </span>
      ),
    });
  }
  if (leg.car) {
    parts.push({
      key: "car",
      node: (
        <span className="course-leg__part">
          <CarIcon />차 {leg.car.minutes}분
        </span>
      ),
    });
  }
  if (parts.length === 0) {
    return (
      <div className="course-leg course-leg--unknown" role="status">
        이동 정보 없음
      </div>
    );
  }
  return (
    <div className="course-leg">
      {parts.map((p, i) => (
        <Fragment key={p.key}>
          {i > 0 && <span className="course-leg__sep">·</span>}
          {p.node}
        </Fragment>
      ))}
    </div>
  );
}

export function SharedCourseDetailSkeleton() {
  return (
    <section className="section spot-detail" aria-label="공유 코스 불러오는 중" aria-busy="true">
      <div className="skeleton-bar" style={{ width: "120px", height: "16px" }} />
      <div className="skeleton-bar" style={{ width: "70%", height: "30px", marginTop: "16px" }} />
      <div className="skeleton-bar" style={{ width: "50%", height: "16px", marginTop: "10px" }} />
      <div className="skeleton-bar" style={{ width: "100%", height: "100px", marginTop: "var(--sp-6)" }} />
    </section>
  );
}

/**
 * §41(신규) — 공유된 코스 상세(`/course/shared/[code]`). 01-interface-contract.md 부록 R.7
 * `GET /courses/shared/{code}`를 소비한다. 이 화면을 열 때마다 서버 조회수가 1 증가하는 트랜잭션
 * (R.7)이므로 — 즉 "보여줄 목적으로만" 불러야 한다(더보기/새로고침 목적 재호출 자제).
 *
 * spot.match_reasons.matched_tags는 코스를 만든 사람의 프로필 라벨이라, 지금 이 링크를 보는
 * 사람(다른 방문자)의 프로필로는 한글 라벨을 되찾을 수 없다 — RecommendSpotCard가 이미 라벨이
 * 없으면 registry 코드 원문으로 폴백하도록 짜여 있어(tagLabelMap[v] ?? v) 빈 맵({})을 그대로
 * 넘긴다(값을 지어내지 않음, CourseStepCard.tsx 재사용 그대로).
 */
export default function SharedCourseDetailContent({ code }: SharedCourseDetailContentProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<SharedCourseDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const [mapOpen, setMapOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    fetchSharedCourse(code, controller.signal)
      .then((res) => {
        setData(res);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const apiErr =
          err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "공유 코스를 불러오지 못했습니다.");
        if (apiErr.status === 404) {
          setError(apiErr);
          setStatus("notfound");
          return;
        }
        setError(apiErr);
        setStatus("error");
      });
    return () => controller.abort();
  }, [code, retryTick]);

  const retry = () => setRetryTick((t) => t + 1);

  if (status === "loading") return <SharedCourseDetailSkeleton />;

  if (status === "notfound") {
    return (
      <section className="section spot-detail" aria-labelledby="sharedCourseHeading">
        <Link href="/courses" className="compare-back">
          ← 다른 사람 코스로
        </Link>
        <h1 className="section__title" id="sharedCourseHeading">
          공유 코스
        </h1>
        <div className="board-error" role="status">
          <p className="board-error__msg">이 공유 코스를 찾을 수 없어요.</p>
          <p className="board-error__hint">링크가 잘못됐거나, 만든 사람이 삭제했을 수 있어요.</p>
          <Link className="btn btn--mint" href="/courses">
            다른 코스 구경하기
          </Link>
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="section spot-detail" aria-labelledby="sharedCourseHeading">
        <Link href="/courses" className="compare-back">
          ← 다른 사람 코스로
        </Link>
        <h1 className="section__title" id="sharedCourseHeading">
          공유 코스
        </h1>
        <div className="board-error" role="alert">
          <p className="board-error__msg">{error?.message ?? "공유 코스를 불러오지 못했습니다."}</p>
          <p className="board-error__hint">
            {error?.status === 0
              ? "백엔드 서버가 켜져 있는지 확인해주세요 (localhost:8000). 잠시 후 다시 시도해주세요."
              : "잠시 후 다시 시도해주세요."}
          </p>
          <button className="btn btn--coral" type="button" onClick={retry}>
            다시 시도
          </button>
        </div>
      </section>
    );
  }

  if (!data) return null;

  const { title, nickname, spot_count, view_count, course } = data;
  // 공유 payload 는 **누구나 API 로 만들 수 있는 임의 JSON** 이다(공개 URL). 형식이 다른 값이
  // 섞이면 카드 렌더에서 크래시해 보는 사람 화면이 통째로 죽는다(실측). 최소 형태(객체 + id +
  // name)를 갖춘 항목만 남기고, 하나도 없으면 아래에서 "읽을 수 없는 코스" 안내로 대체한다.
  const rawSpots = Array.isArray(course?.spots) ? course.spots : [];
  const spots = rawSpots.filter(
    (s): s is (typeof rawSpots)[number] =>
      !!s && typeof s === "object" && typeof (s as { id?: unknown }).id === "number" &&
      typeof (s as { name?: unknown }).name === "string"
  );
  const payloadBroken = rawSpots.length > 0 && spots.length === 0;
  const legs = Array.isArray(course?.legs) ? course.legs : [];

  return (
    <section className="section spot-detail" aria-labelledby="sharedCourseHeading">
      <Link href="/courses" className="compare-back">
        ← 다른 사람 코스로
      </Link>

      <h1 className="spot-detail__title" id="sharedCourseHeading" style={{ marginTop: "var(--sp-4)" }}>
        {title}
      </h1>
      <div className="course-result-head__meta" style={{ marginTop: "var(--sp-2)" }}>
        <span className="course-result-head__meta-item">{nickname}</span>
        <span className="course-result-head__meta-item">{spot_count}곳</span>
        <span className="course-result-head__meta-item">조회 {view_count}</span>
      </div>

      {spots.length > 0 && (
        <button
          type="button"
          className="recommend-map-toggle"
          aria-expanded={mapOpen}
          onClick={() => setMapOpen((v) => !v)}
        >
          {mapOpen ? "지도 접기" : "지도로 보기"}
        </button>
      )}

      {mapOpen && spots.length > 0 && (
        <CourseMap spots={spots} legs={legs} regionLabel={course.region?.region_name ?? ""} />
      )}

      {payloadBroken && (
        <p className="board-error__msg" role="status">
          이 코스의 정보를 읽을 수 없어요. 공유한 분에게 다시 공유를 부탁해 주세요.
        </p>
      )}
      {spots.length > 0 ? (
        <ol className="course-timeline">
          {spots.map((spot, i) => {
            const leg = legs[i];
            return (
              <li key={`${spot.id}-${i}`} className="course-timeline__item">
                <div className="course-timeline__rail">
                  <span className="course-timeline__node">{i + 1}</span>
                  {i < spots.length - 1 && <span className="course-timeline__rail-line" />}
                </div>
                <div className="course-timeline__content">
                  <span className="course-timeline__slot-badge">{spot.slot_label}</span>
                  <CourseStepCard spot={spot} tagLabelMap={{}} />
                  {leg && <CourseLegInfo leg={leg} />}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="board-error" role="status">
          <p className="board-error__msg">이 코스에는 표시할 스팟 정보가 없어요.</p>
        </div>
      )}
    </section>
  );
}
