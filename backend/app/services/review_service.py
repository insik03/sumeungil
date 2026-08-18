"""리뷰(별점+한줄평) 업무 로직 — 부록 R.

## 이 파일이 지키는 3가지
1. **소유권**: 수정·삭제는 `device_id` 가 일치할 때만. 판정은 조회와 **같은 트랜잭션 안**에서
   한다(읽고 나서 따로 쓰면 그 사이에 삭제/변경이 끼어들 수 있다).
2. **비노출**: `device_id` 는 어떤 응답에도 나가지 않는다. 서버가 `is_mine` 만 계산해 준다.
3. **LLM 미주입**: 이 모듈이 만들어내는 어떤 문자열도 LLM 프롬프트로 흘러가지 않는다.
   (요약/컨시어지/코스 AI 는 이 모듈을 import 하지 않는다 — 그 불변식이 인젝션 방어선이다.)

## 로깅 규칙
리뷰 원문·닉네임·device_id 를 로그에 남기지 않는다. 남기는 것은 대상 종류·건수·길이뿐이다.
"""

from __future__ import annotations

import logging
import psycopg
from typing import Any

from ..db.postgres import Database
from ..repositories import review_repo
from ..schemas.community import (
    COMMENT_MAX,
    NICKNAME_MAX,
    REASON_MAX,
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewItem,
    ReviewListResponse,
    ReviewSummary,
    ReviewSummaryMapResponse,
    ReviewUpdateRequest,
)
from ..util.time import now_kst, to_iso_kst
from ..util.user_text import clean_user_text, is_impersonating_staff, is_valid_target_id
from . import community_errors as errors

logger = logging.getLogger("sumeungil.services.review")

DEFAULT_LIMIT = 20


# --- 공통 헬퍼 -----------------------------------------------------------------


def _summary_from_hist(hist: dict[int, int]) -> ReviewSummary:
    """히스토그램 → {average, count, distribution}. 0건이면 average 는 null."""
    distribution = {str(star): int(hist.get(star, 0)) for star in (1, 2, 3, 4, 5)}
    count = sum(distribution.values())
    if count == 0:
        return ReviewSummary(average=None, count=0, distribution=distribution)
    total = sum(int(star) * n for star, n in distribution.items())
    return ReviewSummary(average=round(total / count, 2), count=count, distribution=distribution)


def _to_item(row: dict[str, Any], device_id: str | None) -> ReviewItem:
    """DB row → 응답 모델. **여기서 device_id 를 떨어뜨린다**(응답 비노출 지점)."""
    is_mine = bool(device_id) and row.get("device_id") == device_id
    return ReviewItem(
        id=int(row["id"]),
        nickname=row["nickname"],
        rating=int(row["rating"]),
        comment=row["comment"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_mine=is_mine,
        # QA M-3: 숨김 플래그는 **본인 글에만** 실어 보낸다. 남의 글은 애초에 숨김이면
        # 목록에 없지만, 혹시 다른 경로로 흘러도 "누가 신고당했는지"가 새지 않게 한다.
        hidden=bool(is_mine and int(row.get("hidden") or 0) == 1),
    )


def _clean_nickname(raw: str) -> str:
    nickname = clean_user_text(raw, max_chars=NICKNAME_MAX)
    if not nickname:
        raise errors.invalid_input("INVALID_NICKNAME", "닉네임을 1~20자로 입력해 주세요.")
    # 사칭 차단은 **정제 뒤**에 본다. 정제 전에 보면 제로폭 문자를 끼워 넣어
    # ("관​리자") 검사만 피하고 저장은 "관리자"로 되는 우회가 생긴다.
    if is_impersonating_staff(nickname):
        raise errors.invalid_input("NICKNAME_RESERVED", "이 닉네임은 사용할 수 없어요. 운영자로 오해될 수 있는 이름은 피해 주세요.")
    return nickname


def _clean_comment(raw: str | None) -> str | None:
    """빈 문자열/공백만 남는 한줄평은 null 로 저장한다(별점만 남기는 것은 정상 사용)."""
    if raw is None:
        return None
    comment = clean_user_text(raw, max_chars=COMMENT_MAX)
    return comment or None


def _require_target_id(target_id: str) -> str:
    if not is_valid_target_id(target_id):
        raise errors.invalid_input("INVALID_TARGET", "잘못된 대상입니다.")
    return target_id


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# --- 조회 ---------------------------------------------------------------------


async def list_reviews(
    db: Database,
    *,
    target_type: str,
    target_id: str,
    limit: int,
    offset: int,
    device_id: str | None,
) -> ReviewListResponse:
    target_id = _require_target_id(target_id)
    limit = _clamp(limit, 1, review_repo.MAX_LIMIT)
    offset = max(0, offset)

    def _tx(conn: psycopg.Connection):
        rows = review_repo.list_reviews(
            conn,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            offset=offset,
            # QA M-3: 본인이 쓴 글은 숨김이어도 목록에 포함된다(자력 복구 경로).
            # 타인에게는 종전 그대로 보이지 않는다.
            viewer_device_id=device_id,
        )
        hist = review_repo.rating_histogram(conn, target_type=target_type, target_id=target_id)
        return rows, hist

    rows, hist = await db.aread(_tx)
    # summary/total 은 **hidden 제외 집계 그대로**다(평균·분포·건수 무회귀). 본인에게만 보이는
    # 숨김 글 때문에 `len(items) > total` 이 될 수 있다 — 의도된 것이며, total 은 "공개 중인
    # 후기 수"라는 기존 의미를 유지한다.
    summary = _summary_from_hist(hist)
    return ReviewListResponse(
        summary=summary,
        items=[_to_item(r, device_id) for r in rows],
        total=summary.count,
    )


async def summary_map(
    db: Database, *, target_type: str, target_ids: list[str]
) -> ReviewSummaryMapResponse:
    """카드 목록용 일괄 요약(N+1 방지). **DB 쿼리는 정확히 1회**다.

    요청한 id 는 리뷰가 없어도 `count:0` 으로 전부 포함한다 — 프론트가 키 유무로 분기하지
    않게 하기 위해서(계약 부록 R.4).
    """
    ids = [t for t in (x.strip() for x in target_ids) if is_valid_target_id(t)]
    # 중복 제거(순서 유지) 후 상한 절삭.
    seen: dict[str, None] = {}
    for t in ids:
        seen.setdefault(t, None)
    ids = list(seen)[: review_repo.MAX_SUMMARY_IDS]
    if not ids:
        return ReviewSummaryMapResponse(summaries={})

    def _tx(conn: psycopg.Connection):
        return review_repo.bulk_rating_histogram(conn, target_type=target_type, target_ids=ids)

    hists = await db.aread(_tx)
    return ReviewSummaryMapResponse(
        summaries={t: _summary_from_hist(hists.get(t, {})) for t in ids}
    )


# --- 쓰기 ---------------------------------------------------------------------


async def create_review(
    db: Database, *, req: ReviewCreateRequest, device_id: str
) -> ReviewCreateResponse:
    target_id = _require_target_id(req.target_id)
    nickname = _clean_nickname(req.nickname)
    comment = _clean_comment(req.comment)
    now_iso = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection):
        # 사전 조회 + 유니크 인덱스 **이중 방어**. 사전 조회는 친절한 409 를 위해서,
        # 유니크 인덱스는 동시 요청 두 건이 동시에 통과하는 경우를 막기 위해서다.
        existing = review_repo.find_by_device_target(
            conn, device_id=device_id, target_type=req.target_type, target_id=target_id
        )
        if existing:
            # QA M-3: 기존 글이 숨김 상태인지를 detail 로 알려준다 — 프론트가 "가려진 상태이니
            # 수정·삭제할 수 있어요"로 안내를 바꿀 수 있어야 dead-end 가 풀린다.
            raise errors.review_exists(hidden=int(existing.get("hidden") or 0) == 1)
        review_id = review_repo.insert_review(
            conn,
            target_type=req.target_type,
            target_id=target_id,
            device_id=device_id,
            nickname=nickname,
            rating=req.rating,
            comment=comment,
            now_iso=now_iso,
        )
        row = review_repo.get_review(conn, review_id)
        hist = review_repo.rating_histogram(
            conn, target_type=req.target_type, target_id=target_id
        )
        return row, hist

    try:
        row, hist = await db.awrite(_tx)
    except psycopg.errors.UniqueViolation:
        # 유니크 인덱스 위반(동시 요청 경합) — 사전 조회와 동일한 사용자 메시지로 수렴시킨다.
        # detail.hidden 을 맞추기 위해 이 드문 경로에서만 한 번 더 읽는다(읽기 실패해도
        # 409 자체는 그대로 나가야 하므로 실패 시 false 로 둔다).
        try:
            def _read(conn: psycopg.Connection):
                return review_repo.find_by_device_target(
                    conn, device_id=device_id, target_type=req.target_type, target_id=target_id
                )

            existing = await db.aread(_read)
            hidden_flag = bool(existing) and int(existing.get("hidden") or 0) == 1
        except psycopg.Error:
            hidden_flag = False
        raise errors.review_exists(hidden=hidden_flag) from None

    logger.info(
        "review created target_type=%s rating=%d comment_len=%d",
        req.target_type, req.rating, len(comment or ""),
    )
    assert row is not None  # 방금 INSERT 한 행 — 같은 트랜잭션에서 반드시 읽힌다
    return ReviewCreateResponse(
        review=_to_item(row, device_id), summary=_summary_from_hist(hist)
    )


async def update_review(
    db: Database, *, review_id: int, req: ReviewUpdateRequest, device_id: str
) -> ReviewItem:
    fields = req.model_fields_set
    if not fields:
        raise errors.invalid_input("NOTHING_TO_UPDATE", "수정할 내용이 없습니다.")

    nickname = _clean_nickname(req.nickname) if req.nickname is not None else None
    # comment 를 명시적으로 null 로 보내면 "한줄평 삭제"로 해석한다(누락과 구분).
    clear_comment = "comment" in fields and req.comment is None
    comment = _clean_comment(req.comment) if req.comment is not None else None
    now_iso = to_iso_kst(now_kst())

    def _tx(conn: psycopg.Connection):
        row = review_repo.get_review(conn, review_id)
        if row is None:
            raise errors.not_found("후기를 찾을 수 없습니다.")
        if row["device_id"] != device_id:
            raise errors.not_owner()
        review_repo.update_review(
            conn,
            review_id=review_id,
            nickname=nickname,
            rating=req.rating,
            comment=comment,
            clear_comment=clear_comment,
            now_iso=now_iso,
        )
        return review_repo.get_review(conn, review_id)

    row = await db.awrite(_tx)
    assert row is not None
    return _to_item(row, device_id)


async def delete_review(db: Database, *, review_id: int, device_id: str) -> None:
    def _tx(conn: psycopg.Connection) -> None:
        row = review_repo.get_review(conn, review_id)
        if row is None:
            raise errors.not_found("후기를 찾을 수 없습니다.")
        if row["device_id"] != device_id:
            raise errors.not_owner()
        review_repo.delete_review(conn, review_id=review_id)

    await db.awrite(_tx)
    logger.info("review deleted id=%d", review_id)


async def report_review(
    db: Database, *, review_id: int, reason: str, device_id: str, hide_threshold: int
) -> dict[str, Any]:
    """신고 접수. 고유 신고자 수가 임계 이상이면 **즉시 hidden=1**.

    운영자가 상주하지 않는 데모의 최소 안전장치다(계약 부록 R.6). 오탐 가능성이 있으므로
    삭제가 아니라 플래그이며, DB 에서 `hidden=0` 으로 되돌리면 즉시 복구된다.
    """
    clean_reason = clean_user_text(reason, max_chars=REASON_MAX)
    if not clean_reason:
        raise errors.invalid_input("INVALID_REASON", "신고 사유를 입력해 주세요.")
    now_iso = to_iso_kst(now_kst())
    threshold = max(1, hide_threshold)

    def _tx(conn: psycopg.Connection):
        row = review_repo.get_review(conn, review_id)
        if row is None or int(row["hidden"]) == 1:
            # 이미 숨겨진 리뷰는 목록에 없다 → 존재를 알려줄 이유가 없다(404 로 수렴).
            raise errors.not_found("후기를 찾을 수 없습니다.")
        count = review_repo.insert_report_and_count(
            conn, review_id=review_id, device_id=device_id, reason=clean_reason, now_iso=now_iso
        )
        hidden = count >= threshold
        if hidden:
            review_repo.hide_review(conn, review_id=review_id)
        return count, hidden

    count, hidden = await db.awrite(_tx)
    logger.info("review reported id=%d unique_reports=%d hidden=%s", review_id, count, hidden)
    return {"status": "accepted", "hidden": hidden}


__all__ = (
    "DEFAULT_LIMIT",
    "create_review",
    "delete_review",
    "list_reviews",
    "report_review",
    "summary_map",
    "update_review",
)
