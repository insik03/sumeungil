/** @type {import('tailwindcss').Config} */
// styles/tokens.css의 기존 디자인 토큰을 그대로 참조한다(값 중복 정의 금지).
// 색상/spacing/radius를 새로 만들지 않고 var(--x)로 연결해 두 시스템이 항상 동기화되게 한다.
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // shadcn/ui가 기대하는 시맨틱 이름 → tokens.css 브랜드 컬러 매핑
        background: "var(--white)",
        foreground: "var(--ink)",
        primary: {
          DEFAULT: "var(--g-500)",
          foreground: "var(--white)",
        },
        secondary: {
          DEFAULT: "var(--n-600)",
          foreground: "var(--white)",
        },
        muted: {
          DEFAULT: "var(--gray-100)",
          foreground: "var(--gray-500)",
        },
        accent: {
          DEFAULT: "var(--g-100)",
          foreground: "var(--g-700)",
        },
        destructive: {
          DEFAULT: "var(--b-500)",
          foreground: "var(--white)",
        },
        border: "var(--gray-300)",
        input: "var(--gray-300)",
        ring: "var(--g-500)",
        // tokens.css 원본 팔레트 전체도 유틸리티로 그대로 노출 (bg-brand-green-500 등)
        "brand-green": {
          900: "var(--g-900)",
          700: "var(--g-700)",
          600: "var(--g-600)",
          500: "var(--g-500)",
          400: "var(--g-400)",
          100: "var(--g-100)",
          50: "var(--g-50)",
        },
        "brand-navy": {
          900: "var(--n-900)",
          700: "var(--n-700)",
          600: "var(--n-600)",
          500: "var(--n-500)",
          400: "var(--n-400)",
          100: "var(--n-100)",
          50: "var(--n-50)",
        },
        "brand-brown": {
          900: "var(--b-900)",
          700: "var(--b-700)",
          600: "var(--b-600)",
          500: "var(--b-500)",
          400: "var(--b-400)",
          dark: "var(--b-dark)",
          100: "var(--b-100)",
          50: "var(--b-50)",
        },
        level: {
          high: "var(--level-high)",
          mid: "var(--level-mid)",
          low: "var(--level-low)",
          unknown: "var(--level-unknown)",
        },
      },
      borderRadius: {
        DEFAULT: "var(--r-md)",
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
        full: "var(--r-full)",
      },
      spacing: {
        1: "var(--sp-1)",
        2: "var(--sp-2)",
        3: "var(--sp-3)",
        4: "var(--sp-4)",
        5: "var(--sp-5)",
        6: "var(--sp-6)",
        8: "var(--sp-8)",
        10: "var(--sp-10)",
        12: "var(--sp-12)",
        16: "var(--sp-16)",
        20: "var(--sp-20)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
      fontFamily: {
        base: "var(--font-base)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
