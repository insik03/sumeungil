/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 2026-08-18(외부 보안감사 2차) — 기본값은 응답마다 `X-Powered-By: Next.js` 를 붙인다.
  // 프레임워크와 대략의 계열을 광고하는 헤더라 스캐너가 표적을 좁히는 데 쓴다.
  // 끈다고 취약점이 사라지지는 않지만, 알려줄 이유도 없다.
  poweredByHeader: false,
  // 2026-08-20(QA M-2) — /ask는 삭제된 AI 문답(컨시어지) 화면의 옛 경로다. 예전엔
  // app/ask/page.tsx의 next/navigation redirect()로 처리했는데, 이 라우트가 정적
  // 프리렌더 대상이라 실제 응답이 Location 헤더 없는 307이 되어 JS 비활성/크롤러에는
  // 404 화면이 최종 결과였다. redirects()는 파일시스템 라우트보다 먼저 평가되는
  // 라우팅 설정 계층이라 실제 Location 헤더가 붙는 308을 보장한다 — 외부에 공유된
  // /ask 링크를 영구적으로 /course로 보내는 것이 목적이므로 permanent:true(308).
  async redirects() {
    return [
      {
        source: "/ask",
        destination: "/course",
        permanent: true,
      },
    ];
  },
};

module.exports = nextConfig;
