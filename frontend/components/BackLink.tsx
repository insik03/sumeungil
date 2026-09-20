"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

/**
 * "← 목록으로" 링크. 브라우저 뒤로가기와 똑같이 **이전 화면**으로 돌아간다(2026-09-20 대표 지시 —
 * 고정 href 로 가면 보던 페이지·필터가 초기화돼 목록 첫 화면으로 떨어졌다).
 * 이전 화면이 없으면(새 탭·주소 직접 입력) href 로 이동한다. 새 탭 열기(Ctrl/⌘/Shift-클릭·가운데 버튼)는
 * 기본 동작 그대로 href 를 연다.
 */
export default function BackLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  const router = useRouter();
  return (
    <Link
      href={href}
      className={className}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        if (window.history.length > 1) {
          e.preventDefault();
          router.back();
        }
      }}
    >
      {children}
    </Link>
  );
}
