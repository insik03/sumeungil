/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 2026-08-18(외부 보안감사 2차) — 기본값은 응답마다 `X-Powered-By: Next.js` 를 붙인다.
  // 프레임워크와 대략의 계열을 광고하는 헤더라 스캐너가 표적을 좁히는 데 쓴다.
  // 끈다고 취약점이 사라지지는 않지만, 알려줄 이유도 없다.
  poweredByHeader: false,
};

module.exports = nextConfig;
