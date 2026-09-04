/**
 * Gemini 표시 마크 (2026-09-03, 대표: "제미나이가 추천해준 코스나 알림들은 제미나이 아이콘이 앞에
 * 보이도록"). LLM 이 만든 텍스트(코스 제목·요약, 스팟 3줄 요약, 맞춤 팁, 온보딩 취향 정리) 앞에
 * 붙인다 — "AI가 만든 콘텐츠"라는 정직 표시를 어느 모델이 만들었는지까지 구체화한 것.
 *
 * 4각 별은 Gemini 로고 형태를 단순화한 자체 드로잉(상표 이미지를 그대로 쓰지 않는다). 색은
 * Google 블루 한 가지.
 *
 * ponytail: 백엔드가 `LLM_PROVIDER=ollama` 로 되돌아가도 이 마크는 그대로 "Gemini" 로 보인다 —
 * 응답에 provider 필드가 없기 때문. 되돌릴 일이 생기면 그때 응답에 `ai_provider` 를 추가하고
 * 여기서 분기한다(지금은 전 경로 Gemini 라 분기가 없다).
 */
export default function GeminiMark({ label = "Gemini" }: { label?: string }) {
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
