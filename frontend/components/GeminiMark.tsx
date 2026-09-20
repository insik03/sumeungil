/**
 * Gemini 표시 마크 (2026-09-03, 대표: "제미나이가 추천해준 코스나 알림들은 제미나이 아이콘이 앞에
 * 보이도록"). LLM 이 만든 텍스트(코스 제목·요약, 스팟 3줄 요약, 맞춤 팁, 온보딩 취향 정리) 앞에
 * 붙인다 — "AI가 만든 콘텐츠"라는 정직 표시를 어느 모델이 만들었는지까지 구체화한 것.
 *
 * 4각 별은 Gemini 로고 형태를 단순화한 자체 드로잉(상표 이미지를 그대로 쓰지 않는다). 색은
 * Google 블루 한 가지.
 *
 * provider(QA 2026-09-05 P2): 응답에 `ai_provider` 가 있는 곳(스팟 상세)은 그 값으로 분기한다 —
 * "gemini" 가 아니면(ollama 배치 산출물·출처 미상) Gemini 별 대신 일반 "AI" 마크. prop 을 안 주는
 * 호출부 중 코스만 기본 Gemini를 쓰며, 팁·온보딩은 provider="ollama"를 명시한다.
 */
export default function GeminiMark({
  label = "Gemini",
  provider = "gemini",
}: {
  label?: string;
  provider?: string | null;
}) {
  if (provider !== "gemini") {
    return (
      <span className="gemini-mark gemini-mark--generic" aria-label="AI가 생성">
        ✦ AI
      </span>
    );
  }
  return (
    <span className="gemini-mark" aria-label="Gemini가 생성">
      <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 1.5c.6 5.7 4.8 9.9 10.5 10.5C16.8 12.6 12.6 16.8 12 22.5 11.4 16.8 7.2 12.6 1.5 12 7.2 11.4 11.4 7.2 12 1.5z"
          fill="currentColor"
        />
      </svg>
      {label}
    </span>
  );
}
