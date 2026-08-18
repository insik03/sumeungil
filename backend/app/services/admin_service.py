"""관리자 운영 업무 로직 — 부록 T.

## 이 파일이 지키는 4가지
1. **인증은 여기서 하지 않는다.** 라우터가 세션을 검증한 뒤에만 이 함수들을 부른다
   (인증 판정 지점을 한 곳으로 몰아 "인증 없이 도달 가능한 경로"를 만들지 않는다).
2. **device_id 비노출.** 저장소가 돌려준 row 에서 `device_id` 를 읽는 곳은 `_actor` 하나뿐이고,
   그 결과는 8자 HMAC 지문이다. 원본은 응답 모델에 필드조차 없다.
3. **감사 로그와 변경은 한 트랜잭션.** 숨김/복구/삭제가 성공했는데 기록이 없거나, 기록만
   남고 변경이 롤백되는 상태가 존재하지 않는다.
4. **LLM 미주입.** 부록 R.8-1 과 동일 — 관리자 화면에 보이는 사용자 텍스트도 어떤 프롬프트에도
   들어가지 않는다(이 모듈은 `app/ai/*` 를 import 하지 않는다).

## 로깅 규칙
리뷰 원문·닉네임·device_id·비밀번호·세션 토큰을 남기지 않는다. 남기는 것은 동작 이름·대상 종류·
대상 id·`ip_hash` 뿐이다.
"""

from __future__ import annotations

import logging
import psycopg

from ..config import settings
from ..db.postgres import Database
from ..repositories import admin_repo, visit_repo
from ..schemas.admin import (
    AdminTrafficResponse,
    AdminCourseItem,
    AdminCourseListResponse,
    AdminInquiryItem,
    AdminInquiryListResponse,
    AdminModerationResponse,
    AdminReviewItem,
    AdminReviewListResponse,
    AdminStatsResponse,
)
from ..security.admin_auth import AdminAuth
from ..util.time import now_kst, to_iso_kst
from . import community_errors as errors

logger = logging.getLogger("sumeungil.services.admin")

TARGET_REVIEW = "review"
TARGET_COURSE = "course"
TARGET_INQUIRY = "inquiry"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _actor(auth: AdminAuth, row: dict) -> str:
    """DB row 의 device_id → 8자 지문. **원본이 밖으로 나가는 유일한 통로를 여기로 좁힌다.**"""
    return auth.actor_hash(row.get("device_id"))


def _review_item(auth: AdminAuth, row: dict) -> AdminReviewItem:
    return AdminReviewItem(
        id=int(row["id"]),
        target_type=str(row["target_type"]),
        target_id=str(row["target_id"]),
        nickname=row["nickname"],
        rating=int(row["rating"]),
        comment=row["comment"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        hidden=bool(row["hidden"]),
        report_count=int(row.get("report_count") or 0),
        author_hash=_actor(auth, row),
    )


def _course_item(auth: AdminAuth, row: dict) -> AdminCourseItem:
    return AdminCourseItem(
        share_code=row["share_code"],
        nickname=row["nickname"],
        title=row["title"],
        spot_count=int(row["spot_count"]),
        created_at=row["created_at"],
        view_count=int(row["view_count"]),
        hidden=bool(row["hidden"]),
        author_hash=_actor(auth, row),
    )


def _inquiry_item(row: dict) -> AdminInquiryItem:
    """리뷰/코스와 달리 device_id 지문화가 없다 — 로그인 계정의 실제 닉네임을 그대로 쓴다
    (admin_repo.list_inquiries 주석 참고)."""
    return AdminInquiryItem(
        id=int(row["id"]),
        nickname=row["nickname"],
        contact_email=row.get("contact_email"),
        message=row["message"],
        status=row["status"],
        created_at=row["created_at"],
        reply=row.get("reply"),
        replied_at=row.get("replied_at"),
        replied_by=row.get("replied_by"),
    )


# --- 조회 ---------------------------------------------------------------------


async def list_reviews(
    db: Database, *, auth: AdminAuth, status: str, sort: str, limit: int, offset: int
) -> AdminReviewListResponse:
    limit = _clamp(limit, 1, admin_repo.MAX_LIMIT)
    offset = max(0, offset)

    def _tx(conn: psycopg.Connection):
        rows = admin_repo.list_reviews(
            conn, status=status, sort=sort, limit=limit, offset=offset
        )
        total = admin_repo.count_reviews(conn, status=status)
        return rows, total

    rows, total = await db.aread(_tx)
    return AdminReviewListResponse(
        items=[_review_item(auth, r) for r in rows], total=total, limit=limit, offset=offset
    )


async def list_courses(
    db: Database, *, auth: AdminAuth, status: str, limit: int, offset: int
) -> AdminCourseListResponse:
    limit = _clamp(limit, 1, admin_repo.MAX_LIMIT)
    offset = max(0, offset)

    def _tx(conn: psycopg.Connection):
        rows = admin_repo.list_courses(conn, status=status, limit=limit, offset=offset)
        total = admin_repo.count_courses(conn, status=status)
        return rows, total

    rows, total = await db.aread(_tx)
    return AdminCourseListResponse(
        items=[_course_item(auth, r) for r in rows], total=total, limit=limit, offset=offset
    )


async def list_inquiries(
    db: Database, *, status: str, limit: int, offset: int
) -> AdminInquiryListResponse:
    limit = _clamp(limit, 1, admin_repo.MAX_LIMIT)
    offset = max(0, offset)

    def _tx(conn: psycopg.Connection):
        rows = admin_repo.list_inquiries(conn, status=status, limit=limit, offset=offset)
        total = admin_repo.count_inquiries(conn, status=status)
        return rows, total

    rows, total = await db.aread(_tx)
    return AdminInquiryListResponse(
        items=[_inquiry_item(r) for r in rows], total=total, limit=limit, offset=offset
    )


async def stats(db: Database) -> AdminStatsResponse:
    now = now_kst()
    today_prefix = now.strftime("%Y-%m-%d")

    def _tx(conn: psycopg.Connection):
        return admin_repo.stats(conn, today_prefix=today_prefix)

    counts = await db.aread(_tx)
    # 임계값은 화면이 "자동 숨김/운영자 숨김"을 구분하는 데 쓴다. 프론트에 숫자를 박지
    # 않도록 서버가 현재 설정값을 그대로 실어 보낸다(env 로 바꿔도 화면이 따라온다).
    return AdminStatsResponse(
        **counts,
        review_hide_report_threshold=settings.review_hide_report_threshold,
        generated_at=to_iso_kst(now),
    )


async def traffic(db: Database, *, days: int = 14) -> AdminTrafficResponse:
    """운영 트래픽 집계(부록 X). 원본 IP 는 어디에도 없다 — 해시만 다룬다."""
    now = now_kst()
    today = now.strftime("%Y-%m-%d")

    def _tx(conn):
        return visit_repo.summary(conn, today=today, days=days)

    data = await db.aread(_tx)
    return AdminTrafficResponse(**data, generated_at=to_iso_kst(now))

# --- 변경 (전부 감사 로그 동반) -----------------------------------------------------


async def set_review_hidden(
    db: Database, *, review_id: int, hidden: bool, ip_hash: str, operator: str = ""
) -> AdminModerationResponse:
    action = "review_hide" if hidden else "review_unhide"
    at = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection) -> None:
        changed = admin_repo.set_review_hidden(conn, review_id=review_id, hidden=hidden)
        if changed == 0:
            # 트랜잭션 안에서 예외 → 감사 로그도 함께 롤백된다(없는 대상은 기록하지 않는다).
            raise errors.not_found("후기를 찾을 수 없습니다.")
        admin_repo.insert_action(
            conn,
            action=action,
            target_type=TARGET_REVIEW,
            target_id=str(review_id),
            at=at,
            ip_hash=ip_hash,
        )

    await db.awrite(_tx)
    logger.info("admin %s id=%s by=%s ip_hash=%s", action, review_id, operator or "?", ip_hash)
    return AdminModerationResponse(
        action=action, target_type=TARGET_REVIEW, target_id=str(review_id), hidden=hidden
    )


async def delete_review(
    db: Database, *, review_id: int, ip_hash: str, operator: str = ""
) -> AdminModerationResponse:
    at = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection) -> None:
        changed = admin_repo.delete_review(conn, review_id=review_id)
        if changed == 0:
            raise errors.not_found("후기를 찾을 수 없습니다.")
        admin_repo.insert_action(
            conn,
            action="review_delete",
            target_type=TARGET_REVIEW,
            target_id=str(review_id),
            at=at,
            ip_hash=ip_hash,
        )

    await db.awrite(_tx)
    logger.info("admin review_delete id=%s by=%s ip_hash=%s", review_id, operator or "?", ip_hash)
    return AdminModerationResponse(
        action="review_delete", target_type=TARGET_REVIEW, target_id=str(review_id), deleted=True
    )


async def set_course_hidden(
    db: Database, *, share_code: str, hidden: bool, ip_hash: str, operator: str = ""
) -> AdminModerationResponse:
    action = "course_hide" if hidden else "course_unhide"
    at = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection) -> None:
        changed = admin_repo.set_course_hidden(conn, share_code=share_code, hidden=hidden)
        if changed == 0:
            raise errors.not_found("공유된 코스를 찾을 수 없습니다.")
        admin_repo.insert_action(
            conn,
            action=action,
            target_type=TARGET_COURSE,
            target_id=share_code,
            at=at,
            ip_hash=ip_hash,
        )

    await db.awrite(_tx)
    logger.info("admin %s code=%s by=%s ip_hash=%s", action, share_code, operator or "?", ip_hash)
    return AdminModerationResponse(
        action=action, target_type=TARGET_COURSE, target_id=share_code, hidden=hidden
    )


async def delete_course(
    db: Database, *, share_code: str, ip_hash: str, operator: str = ""
) -> AdminModerationResponse:
    at = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection) -> None:
        changed = admin_repo.delete_course(conn, share_code=share_code)
        if changed == 0:
            raise errors.not_found("공유된 코스를 찾을 수 없습니다.")
        admin_repo.insert_action(
            conn,
            action="course_delete",
            target_type=TARGET_COURSE,
            target_id=share_code,
            at=at,
            ip_hash=ip_hash,
        )

    await db.awrite(_tx)
    logger.info("admin course_delete code=%s by=%s ip_hash=%s", share_code, operator or "?", ip_hash)
    return AdminModerationResponse(
        action="course_delete", target_type=TARGET_COURSE, target_id=share_code, deleted=True
    )


async def reply_inquiry(
    db: Database, *, inquiry_id: int, reply: str, ip_hash: str, operator: str = ""
) -> AdminInquiryItem:
    at = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection):
        changed = admin_repo.set_inquiry_reply(
            conn, inquiry_id=inquiry_id, reply=reply, replied_by=operator, replied_at=at
        )
        if changed == 0:
            raise errors.not_found("문의를 찾을 수 없습니다.")
        admin_repo.insert_action(
            conn,
            action="inquiry_reply",
            target_type=TARGET_INQUIRY,
            target_id=str(inquiry_id),
            at=at,
            ip_hash=ip_hash,
        )
        # 응답에 최신 상태를 실어 보내기 위해 방금 답변한 행을 다시 읽는다(list_inquiries와
        # 같은 조인이지만 단건 전용 쿼리가 없어 여기서 직접 짠다).
        return conn.execute(
            """
            SELECT i.id, i.user_id, i.contact_email, i.message, i.status,
                   i.created_at, i.reply, i.replied_at, i.replied_by,
                   u.display_name AS nickname
              FROM inquiries i
              JOIN users u ON u.id = i.user_id
             WHERE i.id = %s
            """,
            (inquiry_id,),
        ).fetchone()

    row = await db.awrite(_tx)
    logger.info("admin inquiry_reply id=%s by=%s ip_hash=%s", inquiry_id, operator or "?", ip_hash)
    return _inquiry_item(dict(row))


__all__ = (
    "delete_course",
    "delete_review",
    "list_courses",
    "list_inquiries",
    "list_reviews",
    "reply_inquiry",
    "set_course_hidden",
    "set_review_hidden",
    "stats",
)
