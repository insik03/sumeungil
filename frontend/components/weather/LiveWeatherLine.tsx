import { LiveWeather } from "../../lib/api";

/**
 * 2026-09-20 대표 지시 "시 별로 지금 비가 오는지 안오는지 어떤지" — 스팟 상세·축제 상세 공용
 * 한 줄 날씨. 기상청 초단기실황(5km 격자)이라 시도 단위가 아니라 **그 장소 기준**이다.
 *
 * 정직성 규칙(이 컴포넌트의 핵심):
 *  - 서버가 null 을 주면 **아무것도 그리지 않는다.** "날씨 정보 없음" 같은 빈 껍데기도 안 만든다.
 *  - 값은 서버가 준 그대로만 쓴다. 기온으로 체감온도를 계산하거나 "나들이 좋아요" 같은 판단을
 *    덧붙이지 않는다 — 원천에 없는 값이다.
 *  - 관측 시각을 함께 밝힌다. 실황은 정시 관측이라 최대 1시간 전 값일 수 있다.
 */
export default function LiveWeatherLine({ weather }: { weather: LiveWeather | null | undefined }) {
  if (!weather) return null;

  const time = weather.observed_at.slice(11, 16); // "YYYY-MM-DD HH:MM" → "HH:MM"
  const parts: string[] = [weather.condition];
  if (weather.temperature_c != null) parts.push(`${weather.temperature_c}°C`);
  if (weather.humidity_pct != null) parts.push(`습도 ${weather.humidity_pct}%`);
  // 강수량은 실제로 오고 있을 때만 의미가 있다(안 올 땐 항상 0이라 줄만 길어진다).
  if (weather.precipitation && weather.rain_1h_mm != null && weather.rain_1h_mm > 0) {
    parts.push(`시간당 ${weather.rain_1h_mm}mm`);
  }

  // 아이콘은 세 갈래다. 문구를 파싱하는 대신 precipitation 불리언을 먼저 보고, 비가 아닐 때만
  // 하늘상태 문구로 해/구름을 가른다(서버가 정한 고정 문구라 이 비교는 안전하다).
  const cloudy = !weather.precipitation && weather.condition !== "맑음";

  return (
    <p className={`live-weather${weather.precipitation ? " live-weather--rain" : ""}`}>
      <span className="live-weather__icon" aria-hidden="true">
        {weather.precipitation ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M17 14a4 4 0 0 0-1-7.9A5.5 5.5 0 0 0 5.5 8 3.5 3.5 0 0 0 6 15h11z" />
            <path d="M8 18l-1 2M12 18l-1 2M16 18l-1 2" />
          </svg>
        ) : cloudy ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 18a4 4 0 0 0-1-7.9A5.5 5.5 0 0 0 5.5 12 3.5 3.5 0 0 0 6 19h11z" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
          </svg>
        )}
      </span>
      <span>
        지금 {parts.join(" · ")}
      </span>
      <span className="live-weather__meta">{time} 기준 · 기상청</span>
    </p>
  );
}
