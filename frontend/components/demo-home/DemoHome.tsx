"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { fetchFeatured, FeaturedSpot, SpotCategory } from "../../lib/api";
import { CATEGORY_META } from "../recommend/constants";
import styles from "./DemoHome.module.css";

const moods = ["아이와 천천히", "둘이서 조용히", "혼자 오래 걷기"] as const;
type Mood = (typeof moods)[number];

// 무드별로 실제 category 필드를 다르게 걸러 보여준다(대표 지시 2026-08-28 — "모드에 따라
// 추천 코스도 달라야 함"). 스팟명·사진 어느 것도 지어내지 않고, 이미 받아온 실데이터를
// 재정렬만 한다 — 매칭이 부족하면 나머지 카테고리로 채워 카드가 비지 않게 한다.
const MOOD_CATEGORIES: Record<Mood, SpotCategory[]> = {
  "아이와 천천히": ["attraction", "nature", "market"],
  "둘이서 조용히": ["cafe", "craft", "trail"],
  "혼자 오래 걷기": ["trail", "nature"],
};

// 배경 사진 자동전환 주기(ms). prefers-reduced-motion이면 아예 돌리지 않는다.
const BG_ROTATE_MS = 4000;

// 해운대구(부산) — 이 데모의 히어로 카피("해운대를 지나 기장 안쪽으로")와 맞는, 실제로
// 시드 데이터가 있는 지역. 기장군은 별도 시드가 없어 쓸 수 없다.
const DEMO_REGION_CODE = "26350";

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  CATEGORY_META.map((c) => [c.value, c.label])
);

// 사진 있는 실스팟을 못 받아왔을 때(네트워크 실패 등)만 쓰는 자리표시 이미지. 대체 문구가 아니라
// 카드 자체가 비지 않게 하는 최후 폴백이다 — 실사진이 오면 전부 즉시 교체된다.
const FALLBACK_IMAGES = ["/landmarks/47940.png", "/landmarks/43.png", "/landmarks/52.png"];

function crowdLabel(spot: FeaturedSpot): string {
  if (!spot.congestion) return "정보없음";
  const idx = spot.congestion.index;
  const levelLabel: Record<string, string> = { low: "여유", mid: "보통", high: "혼잡", unknown: "정보없음" };
  return idx != null ? `${Math.round(idx)}%` : levelLabel[spot.congestion.level] ?? "정보없음";
}

export default function DemoHome() {
  const [mood, setMood] = useState<Mood>(moods[1]);
  // 그림 자리를 실제 관광지 사진으로 채운다(대표 지시 2026-08-27). null=로딩 중.
  const [spots, setSpots] = useState<FeaturedSpot[] | null>(null);
  // 통계·마무리 섹션 배경 사진 자동전환 인덱스(대표 지시 2026-08-28).
  const [bgIndex, setBgIndex] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchFeatured(DEMO_REGION_CODE, 12, controller.signal)
      .then((res) => {
        const withPhoto = [...res.hidden_picks, ...res.trending].filter((s) => s.image_url);
        setSpots(withPhoto);
      })
      .catch(() => {
        if (!controller.signal.aborted) setSpots([]); // 실패해도 조용히 폴백 이미지로
      });
    return () => controller.abort();
  }, []);

  const heroSpots = spots ?? [];
  // 히어로 원형 사진 2장은 장식용 — 카드와 안 겹치게 앞 2곳은 항상 이 자리로 예약한다.
  const heroImg = (i: number) => heroSpots[i]?.image_url ?? FALLBACK_IMAGES[i] ?? FALLBACK_IMAGES[0];
  const heroAlt = (i: number, fallback: string) => (heroSpots[i] ? `${heroSpots[i].name} 사진` : fallback);

  // 무드가 바뀌면 그 무드의 카테고리를 우선 보여주고(히어로가 예약한 앞 2곳은 제외), 부족하면
  // 나머지 실스팟으로 채운다(빈 카드 방지 — 카테고리 매칭 없어도 섹션 자체는 항상 채워짐).
  const routeSpots = useMemo(() => {
    const pool = heroSpots.slice(2);
    const wanted = new Set(MOOD_CATEGORIES[mood]);
    const matched = pool.filter((s) => wanted.has(s.category));
    const rest = pool.filter((s) => !wanted.has(s.category));
    return [...matched, ...rest].slice(0, 3);
  }, [heroSpots, mood]);

  const routes = routeSpots.map((s) => ({
    type: CATEGORY_LABEL[s.category] ?? s.category,
    title: s.name,
    note: s.address ?? s.region_name,
    crowd: crowdLabel(s),
    image: s.image_url as string,
    alt: `${s.name} 사진`,
  }));

  // 배경 로테이션: 사진 2장 이상 있고, 움직임을 줄여달라는 설정이 아닐 때만 돈다.
  useEffect(() => {
    if (heroSpots.length < 2) return;
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setBgIndex((i) => (i + 1) % heroSpots.length), BG_ROTATE_MS);
    return () => window.clearInterval(id);
  }, [heroSpots.length]);

  const bgImg = heroSpots[bgIndex % Math.max(heroSpots.length, 1)]?.image_url ?? null;

  return (
    <main className={styles.demo}>
      <a className={styles.skipLink} href="#demo-main">
        본문으로 바로가기
      </a>

      <div className={styles.compareBar} aria-label="홈 디자인 비교">
        <span>홈 디자인 비교</span>
        <Link href="/">현재 홈</Link>
        <Link className={styles.compareActive} href="/demo-home" aria-current="page">
          새 데모
        </Link>
      </div>

      <section className={styles.hero} id="demo-main">
        <div className={styles.topline}>
          <p>관광객을 줄이는 여행이 아니라, 여행지를 넓히는 방법</p>
          <span>BUSAN · 오늘 09:40 기준</span>
        </div>

        <div className={styles.heroGrid}>
          <div className={styles.heroCopy}>
            <p className={styles.kicker}>AI 혼잡 분산 여행</p>
            <h1>
              붐비는 길 옆에,
              <br />
              <em>당신의 길</em>이 있습니다.
            </h1>
            <p className={styles.lead}>
              가고 싶은 곳과 여행 기분을 말해주세요. 관광 데이터와 취향을 함께 읽어 더 한적하고,
              더 오래 기억될 하루를 만듭니다.
            </p>

            <div className={styles.promptBox}>
              <span className={styles.promptLabel}>오늘은 어떤 여행을 원하세요?</span>
              <p>부산에서 둘이 걷기 좋고, 바다가 보이는 조용한 곳</p>
              <div className={styles.promptActions}>
                <span>부산 · 2명 · 도보 중심</span>
                <Link href="/course">이 문장으로 코스 만들기 <b aria-hidden="true">↗</b></Link>
              </div>
            </div>

            <div className={styles.moods} aria-label="여행 기분 선택">
              {moods.map((item) => (
                <button
                  key={item}
                  className={mood === item ? styles.moodActive : undefined}
                  type="button"
                  aria-pressed={mood === item}
                  onClick={() => setMood(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className={styles.routeStage} aria-label="추천 경로 미리보기">
            <div className={styles.hotspot}>
              <span>지금 해운대</span>
              <strong>예상 혼잡 82%</strong>
              <small>매우 붐빔</small>
            </div>
            <svg className={styles.routeLine} viewBox="0 0 520 620" aria-hidden="true">
              <path d="M394 25C466 120 239 111 310 218C382 327 99 330 183 445C226 504 153 558 91 590" />
            </svg>
            <div className={`${styles.routePin} ${styles.pinOne}`}><i>1</i><span>숲의 입구</span></div>
            <div className={`${styles.routePin} ${styles.pinTwo}`}><i>2</i><span>동네의 점심</span></div>
            <div className={`${styles.routePin} ${styles.pinThree}`}><i>3</i><span>조용한 바다</span></div>
            <div className={styles.artOne}><img src={heroImg(0)} alt={heroAlt(0, "산과 숲길이 그려진 숨은 명소")} /></div>
            <div className={styles.artTwo}><img src={heroImg(1)} alt={heroAlt(1, "바닷길이 그려진 숨은 명소")} /></div>
            <p className={styles.routeCaption}><b>{mood}</b>에 맞춘<br />분산 경로가 열렸어요.</p>
          </div>
        </div>
      </section>

      <section className={styles.proof} aria-labelledby="proof-title">
        {bgImg && (
          <div className={styles.sectionBg} aria-hidden="true">
            <img key={bgImg} src={bgImg} alt="" />
          </div>
        )}
        <div className={styles.proofIntro}>
          <p className={styles.kicker}>왜 이 길인가요</p>
          <h2 id="proof-title">추천의 이유를<br />숫자로 숨기지 않습니다.</h2>
        </div>
        <dl>
          <div><dt>예상 혼잡</dt><dd><strong>82</strong><span>→</span><strong>18%</strong></dd></div>
          <div><dt>당신과의 취향 일치</dt><dd><strong>91%</strong><small>조용함 · 산책 · 로컬</small></dd></div>
          <div><dt>지역 안에서 머무는 시간</dt><dd><strong>+2.4h</strong><small>명소 한 곳보다 동네 세 곳</small></dd></div>
        </dl>
      </section>

      <section className={styles.itinerary} aria-labelledby="route-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>오늘의 숨은 경로 · 5시간 10분</p>
            <h2 id="route-title">해운대를 지나, 기장 안쪽으로</h2>
          </div>
          <Link href="/course">내 취향으로 다시 짜기 <span aria-hidden="true">↗</span></Link>
        </div>

        <ol className={styles.routeCards}>
          {spots === null
            ? [0, 1, 2].map((i) => (
                <li key={i}>
                  <div className={styles.routeMeta}><i>{String(i + 1).padStart(2, "0")}</i></div>
                  <div className={`${styles.routeArt} skeleton-bar`} />
                  <div className={styles.routeCardBody}>
                    <div className="skeleton-bar" style={{ width: "60px", height: "10px" }} />
                    <h3 className="skeleton-bar" style={{ width: "70%", height: "24px", marginTop: 12 }} />
                  </div>
                </li>
              ))
            : routes.map((route, index) => (
                <li key={route.title}>
                  <div className={styles.routeMeta}><i>{String(index + 1).padStart(2, "0")}</i></div>
                  <div className={styles.routeArt}><img src={route.image} alt={route.alt} loading="lazy" /></div>
                  <div className={styles.routeCardBody}>
                    <div><span>{route.type}</span><b>예상 혼잡 {route.crowd}</b></div>
                    <h3>{route.title}</h3>
                    <p>{route.note}</p>
                  </div>
                </li>
              ))}
        </ol>
      </section>

      <section className={styles.closing}>
        {bgImg && (
          <div className={styles.sectionBg} aria-hidden="true">
            <img key={bgImg} src={bgImg} alt="" />
          </div>
        )}
        <div>
          <p>사람이 몰린 곳을 피하는 데서 끝나지 않도록.</p>
          <h2>한 사람의 발걸음이<br />한 동네의 내일이 됩니다.</h2>
        </div>
        <div className={styles.closingActions}>
          <Link href="/onboarding">내 숨은길 시작하기</Link>
          <Link href="/congestion">전국 혼잡도 먼저 보기</Link>
        </div>
      </section>
    </main>
  );
}
