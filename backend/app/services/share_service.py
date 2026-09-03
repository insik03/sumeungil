"""코스 공유(데모) 업무 로직 — 부록 R.

## share_code 설계
`secrets.choice` 로 만든 **8자 base32 계열**(혼동 문자 I/L/O/0/1 제외, 31자 알파벳)이다.
31^8 ≈ 8.5×10^11 (약 40비트) — 순차 id 와 달리 남의 코스를 훑을 수 없다. 인증이 없으므로
"추측 불가능한 URL" 자체가 접근 제어다. 그래도 **비밀 URL 은 비밀번호가 아니다** — 공유
코스에는 개인정보를 담지 않는다는 전제(닉네임+제목+스팟 목록)가 계약에 명시돼 있다.

## payload 를 재구성하는 이유 (2026-08-18 변경 — 외부 보안감사 3차 최우선 지적)
**예전에는** `course` JSON 을 크기·깊이만 검사하고 그대로 보관·반환했다. 그 결과 공개 피드
(`/shared`)에 클라이언트가 지어낸 장소명·"여유" 혼잡도 배지·임의 이미지·"공식 인증" 류 문구를
API 한 번으로 올릴 수 있었다(XSS 가 아니라 **콘텐츠 위조** — 텍스트 노드 렌더로는 못 막는다).

이제 `course_payload.rebuild_course_for_store` 가 **스팟 id 만 신뢰**하고 나머지 표시값을
`spot_repo`(+ 서버 사진/설명 캐시)에서 다시 채운다. 혼잡도는 아예 저장하지 않고 상세 조회
시점에 서버가 붙인다(시점 데이터). 크기(32KB)·중첩 깊이(16) 상한은 그대로 유지한다 —
재구성 **전에** 파서를 보호해야 하기 때문이다.

## 보존정책 (QA M-2, 2026-08-01)
크기 상한만으로는 부족하다. 건수 상한이 없으면 32KB × 무제한 = 디스크가 찬다(= SQLite 쓰기
실패 = 커뮤니티 전체 503). 그래서 3중 상한을 둔다.
  ① 기기당 보유 상한 — 생성 시 같은 트랜잭션에서 오래된 내 공유부터 자동 삭제(사용자 무영향)
  ② 전체 row 상한   — 생성 시 소량 트림 + 주기 정리에서 조회수 0·오래된 것부터
  ③ 보존 기간       — 주기 정리(기동 1회 + 하루 1회)
①②는 쓰기 경로 안에 있으므로 **소량(batch)** 만 지운다. 정리가 길어지면 그 시간만큼 다른
쓰기가 락 뒤에서 기다린다 — 정리 때문에 서비스가 느려지면 본말전도다.
"""

from __future__ import annotations

import json
import logging
import secrets
import psycopg
from datetime import timedelta
from typing import Any

from ..cache.base import Cache
from ..config import settings
from ..db.postgres import Database
from ..repositories import shared_course_repo
from ..repositories.congestion_repo import CongestionRepository
from ..repositories.spot_repo import SpotRepository
from ..schemas.community import (
    NICKNAME_MAX,
    TITLE_MAX,
    LikeResponse,
    ShareCreateRequest,
    ShareCreateResponse,
    SharedCourseDetail,
    SharedCourseItem,
    SharedCourseListResponse,
)
from ..util.time import now_kst, to_iso_kst
from ..util.user_text import clean_user_text, is_impersonating_staff
from . import community_errors as errors
from . import course_payload

logger = logging.getLogger("sumeungil.services.share")

# 주기 정리 1회가 지울 수 있는 최대 배치 수(= batch × 이 값). 폭주 상황에서도 정리가
# 무한히 돌지 않게 하는 상한이며, 남은 초과분은 다음 주기(또는 다음 쓰기)에서 처리된다.
_CLEANUP_MAX_ROUNDS = 40

# 혼동되는 글자(I, L, O, 0, 1)를 뺀 31자 — 사람이 URL 을 받아적을 수 있게.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
_CODE_MAX_TRIES = 5

DEFAULT_LIMIT = 20
MAX_DEPTH = 16


def generate_share_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_share_code(raw: str) -> str:
    """대소문자·공백 관용(사용자가 URL 을 손으로 옮겨 적는 경우). 형식이 틀리면 404 대상."""
    code = (raw or "").strip().upper()
    if len(code) != CODE_LENGTH or any(c not in _CODE_ALPHABET for c in code):
        raise errors.not_found("공유된 코스를 찾을 수 없습니다.")
    return code


def _json_depth_ok(value: Any, limit: int = MAX_DEPTH) -> bool:
    """재귀 없이(스택으로) 중첩 깊이를 검사한다.

    재귀로 짜면 이 검사 자체가 RecursionError 를 내며 500 이 된다 — 깊게 중첩된 JSON 을
    막으려는 함수가 그 JSON 에 당하면 안 된다.
    """
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(node, dict):
            for v in node.values():
                stack.append((v, depth + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, depth + 1))
    return True


def _spot_count(course: dict[str, Any]) -> int:
    """목록 카드에 쓸 스팟 수. 구조가 다르면 0(추측하지 않는다)."""
    for key in ("spots", "spot_ids"):
        value = course.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _encode_payload(course: dict[str, Any], max_bytes: int) -> str:
    if not course:
        raise errors.invalid_input("INVALID_COURSE", "공유할 코스 내용이 비어 있습니다.")
    if not _json_depth_ok(course):
        raise errors.invalid_input("INVALID_COURSE", "코스 데이터 구조가 올바르지 않습니다.")
    try:
        encoded = json.dumps(course, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        raise errors.invalid_input("INVALID_COURSE", "코스 데이터를 저장할 수 없습니다.") from None
    size = len(encoded.encode("utf-8"))
    if size > max_bytes:
        raise errors.CommunityError(
            413, "COURSE_TOO_LARGE", "코스 데이터가 너무 큽니다. 스팟 수를 줄여 주세요."
        )
    return encoded


def guard_payload_limits(course: Any, max_bytes: int) -> None:
    """크기(32KB)·중첩 깊이(16) **사전 검사만** 한다(재구성 전에 파서를 보호하는 단계).

    2026-08-18(보안 L-4): `/courses/share` 만 이 검사를 하고 `/courses/mine` 은 하지 않아,
    같은 성격의 쓰기인데 한쪽만 무제한 JSON 을 파싱하고 있었다. 두 경로가 같은 함수를 부르게
    해 규칙이 갈리지 않도록 한다. 위반 시 `CommunityError`(413/400) — 라우터가 봉투로 변환한다.
    """
    _encode_payload(course, max_bytes)


def _decode_payload(raw: str) -> dict[str, Any]:
    """저장 시 검증을 통과한 JSON 이므로 실패는 곧 데이터 손상이다 → 빈 dict 로 graceful."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("shared course payload 파싱 실패(손상 가능) len=%d", len(raw or ""))
        return {}
    return value if isinstance(value, dict) else {}


def _to_item(row: dict[str, Any]) -> SharedCourseItem:
    return SharedCourseItem(
        share_code=row["share_code"],
        nickname=row["nickname"],
        title=row["title"],
        spot_count=int(row["spot_count"]),
        created_at=row["created_at"],
        view_count=int(row["view_count"]),
        # 부록 R.14: 좋아요는 payload 밖 컬럼이라 여기서만 읽는다. 값이 없는 행(구 데이터)도
        # 0/False 로 안전하게 접힌다.
        like_count=int(row.get("like_count") or 0),
        liked_by_me=bool(row.get("liked_by_me")),
    )


# --- 보존정책 (QA M-2) ---------------------------------------------------------


def _grace_since_iso(now: Any = None) -> str:
    """"최근 조회된 것은 지우지 않는다"의 기준 시각(now - grace days)."""
    base = now or now_kst()
    return to_iso_kst(base - timedelta(days=max(0, settings.share_recent_view_grace_days)))


def _retention_cutoff_iso(now: Any = None) -> str | None:
    """보존 기간 경계. 0 이하로 설정하면 기간 정리를 끈다(None)."""
    days = settings.share_retention_days
    if days <= 0:
        return None
    base = now or now_kst()
    return to_iso_kst(base - timedelta(days=days))


def _enforce_caps_in_tx(conn: psycopg.Connection, *, device_id: str, now: Any) -> None:
    """생성 트랜잭션 안에서 도는 **소량** 정리. 예외를 밖으로 내보내지 않는다.

    여기서 실패해도 공유 생성 자체는 성공해야 한다 — 정리는 부가 작업이고, 사용자는
    "정리 실패" 때문에 자기 코스를 못 올리는 상황을 이해할 수 없다. 다만 트랜잭션이
    깨지는 종류의 오류(psycopg.Error)는 삼키면 INSERT 까지 함께 롤백되므로 그대로 올린다.

    ## 동시성 (5차 보안감사 #53, 2026-09-03)
    "같은 트랜잭션 안"이라는 것만으로는 기기당 상한이 지켜지지 않는다 — 그 원자성은
    **이 트랜잭션 자신**에게만 적용되고, 동시에 도는 다른 커넥션(같은 device_id로 온
    또 다른 요청)과의 격리는 PostgreSQL 기본 격리수준(READ COMMITTED)에서 보장되지
    않는다. 여러 요청이 동시에 "정리 불필요"로 판단하고 전부 INSERT에 성공할 수 있다
    (그레이박스 재현: 19건 상태에서 10건 동시 삽입 → 상한 20건인데 최종 29건).
    device_id 기준 트랜잭션 advisory lock으로 같은 기기의 요청들을 실제로 직렬화한다
    — 다른 기기의 요청과는 경합하지 않으므로 전체 처리량에는 영향이 없다. 트랜잭션
    종료(커밋/롤백) 시 자동 해제되므로 별도 unlock이 필요 없다.
    """
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (device_id,))
    batch = max(1, settings.share_cleanup_batch)
    # ① 기기당 상한 — 새로 들어올 1건의 자리를 미리 비운다(keep = 상한 - 1).
    removed = shared_course_repo.delete_oldest_by_device(
        conn, device_id=device_id, keep=max(0, settings.share_max_per_device - 1), batch=batch
    )
    if removed:
        # device_id 는 로그에 남기지 않는다(부록 R.8 로그 규칙).
        logger.info("share retention: 기기 보유 상한 초과분 정리 removed=%d", removed)
    # ② 전체 상한 — 한 번에 batch 만큼만(긴 잠금 금지). 남은 초과분은 주기 정리가 마저 한다.
    overflow = shared_course_repo.delete_overflow(
        conn,
        max_total=max(1, settings.share_max_total),
        batch=batch,
        grace_since_iso=_grace_since_iso(now),
        reserve=1,  # 지금 INSERT 될 1건의 자리를 미리 비운다(상한 초과 상태로 머물지 않게)
    )
    if overflow:
        logger.info("share retention: 전체 상한 초과분 정리 removed=%d", overflow)


async def run_cleanup(db: Database) -> dict[str, int]:
    """보존 기간 + 전체 상한 정리. **기동 시 1회 + 하루 1회** 호출(fire-and-forget).

    한 트랜잭션에 몰지 않고 batch 단위로 여러 번 쓴다 — 트랜잭션 사이에 다른 요청이 락을
    가져갈 수 있어야 정리 중에도 조회·쓰기가 정상 동작한다(QA 검증 항목 c).
    """
    batch = max(1, settings.share_cleanup_batch)
    grace_iso = _grace_since_iso()
    cutoff_iso = _retention_cutoff_iso()
    expired = 0
    overflow = 0

    if cutoff_iso is not None:
        for _ in range(_CLEANUP_MAX_ROUNDS):
            def _tx(conn: psycopg.Connection) -> int:
                return shared_course_repo.delete_expired(
                    conn, cutoff_iso=cutoff_iso, batch=batch, grace_since_iso=grace_iso
                )

            n = await db.awrite(_tx)
            expired += n
            if n < batch:
                break

    max_total = max(1, settings.share_max_total)
    for _ in range(_CLEANUP_MAX_ROUNDS):
        def _tx_overflow(conn: psycopg.Connection) -> int:
            return shared_course_repo.delete_overflow(
                conn, max_total=max_total, batch=batch, grace_since_iso=grace_iso
            )

        n = await db.awrite(_tx_overflow)
        overflow += n
        if n < batch:
            break

    def _count(conn: psycopg.Connection) -> int:
        return shared_course_repo.count_all_shares(conn)

    remaining = await db.aread(_count)
    if expired or overflow:
        logger.info(
            "share retention 정리 완료 expired=%d overflow=%d remaining=%d",
            expired, overflow, remaining,
        )
    # 부록 R.14.5 잔여 위험: 전체가 "최근 + 반응 있음"이면 유예에 걸려 정리가 0건이 되어
    # 상한을 못 지킬 수 있다(좋아요 이전부터 view_count 로 존재하던 성질). 조용히 넘어가면
    # 운영이 알 방법이 없으므로 관측되면 경고를 남긴다(SHARE_MAX_TOTAL 상향 또는 유예일 하향).
    if overflow == 0 and remaining > max_total:
        logger.warning(
            "share retention: 정리 0건인데 전체 상한 초과 remaining=%d max_total=%d "
            "(유예 대상이 상한을 채웠을 수 있음 — SHARE_MAX_TOTAL 상향 또는 유예일 하향 검토)",
            remaining, max_total,
        )
    return {"expired": expired, "overflow": overflow, "remaining": remaining}


# --- 쓰기 ---------------------------------------------------------------------


async def create_share(
    db: Database,
    *,
    req: ShareCreateRequest,
    device_id: str,
    max_bytes: int,
    spot_repo: SpotRepository,
    cache: Cache,
) -> ShareCreateResponse:
    nickname = clean_user_text(req.nickname, max_chars=NICKNAME_MAX)
    if not nickname:
        raise errors.invalid_input("INVALID_NICKNAME", "닉네임을 1~20자로 입력해 주세요.")
    if is_impersonating_staff(nickname):
        raise errors.invalid_input("NICKNAME_RESERVED", "이 닉네임은 사용할 수 없어요. 운영자로 오해될 수 있는 이름은 피해 주세요.")
    title = clean_user_text(req.title, max_chars=TITLE_MAX)
    if not title:
        raise errors.invalid_input("INVALID_TITLE", "코스 제목을 입력해 주세요.")

    # ① 먼저 크기·깊이 상한으로 파서를 보호하고(재구성은 입력을 순회하므로 그 전에 잘라야 한다),
    # ② 그 다음 스팟 id 만 신뢰해 서버 값으로 재구성한다(2026-08-18 보안감사).
    guard_payload_limits(req.course, max_bytes)
    try:
        course = course_payload.rebuild_course_for_store(req.course, spot_repo=spot_repo)
    except course_payload.InvalidCoursePayload as exc:
        raise errors.invalid_input("INVALID_COURSE", "코스 내용을 확인할 수 없습니다.") from exc
    # 사진·설명은 서버 캐시에서 채운다(클라이언트가 준 값은 위에서 이미 버렸다).
    await course_payload.enrich_stored_course(course, cache=cache, spot_repo=spot_repo)

    payload_json = _encode_payload(course, max_bytes)
    spot_count = _spot_count(course)
    now = now_kst()
    now_iso = to_iso_kst(now)

    # PK 충돌은 40비트 공간에서 사실상 없지만, 생겨도 조용히 500 이 되지 않게 재시도한다.
    for _ in range(_CODE_MAX_TRIES):
        code = generate_share_code()

        def _tx(conn: psycopg.Connection, _code: str = code) -> None:
            # 보존정책(QA M-2): 상한 정리와 INSERT 를 **같은 트랜잭션**에 둔다.
            # 나누면 "자리를 비웠는데 INSERT 가 실패해 데이터만 사라진" 상태가 생긴다.
            _enforce_caps_in_tx(conn, device_id=device_id, now=now)
            shared_course_repo.insert_share(
                conn,
                share_code=_code,
                device_id=device_id,
                nickname=nickname,
                title=title,
                payload_json=payload_json,
                spot_count=spot_count,
                now_iso=now_iso,
            )

        try:
            await db.awrite(_tx)
        except psycopg.errors.UniqueViolation:
            continue
        logger.info(
            "course shared spot_count=%d payload_bytes=%d",
            spot_count, len(payload_json.encode("utf-8")),
        )
        return ShareCreateResponse(share_code=code, created_at=now_iso)

    raise errors.CommunityError(
        500, "SHARE_CODE_CONFLICT", "공유 코드를 만들지 못했습니다. 다시 시도해 주세요."
    )


async def delete_share(db: Database, *, share_code: str, device_id: str) -> None:
    code = normalize_share_code(share_code)

    def _tx(conn: psycopg.Connection) -> None:
        row = shared_course_repo.get_share(conn, share_code=code)
        if row is None:
            raise errors.not_found("공유된 코스를 찾을 수 없습니다.")
        if row["device_id"] != device_id:
            raise errors.not_owner()
        shared_course_repo.delete_share(conn, share_code=code)

    await db.awrite(_tx)
    logger.info("shared course deleted")


# --- 조회 ---------------------------------------------------------------------


async def get_share(
    db: Database,
    *,
    share_code: str,
    device_id: str | None,
    spot_repo: SpotRepository,
    congestion_repo: CongestionRepository,
    user_id: int | None = None,
) -> SharedCourseDetail:
    """상세 조회 + view_count 증가를 **한 트랜잭션**으로 처리한다.

    조회와 증가를 나누면 두 번의 락 획득이 필요하고, 그 사이에 삭제되면 유령 카운트가 남는다.

    저장된 payload 도 **읽을 때 한 번 더** allowlist 를 통과시킨다(2026-08-18 보안감사) —
    이 코드 배포 전에 이미 조작돼 들어간 공유가 화면에 뜨지 않게 하기 위해서다. 혼잡도는
    저장돼 있지 않으므로 여기서 **지금 값**을 붙인다(옛 라벨을 현재처럼 보여주지 않는다).
    """
    code = normalize_share_code(share_code)

    def _tx(conn: psycopg.Connection):
        row = shared_course_repo.get_share(conn, share_code=code)
        if row is None or int(row["hidden"]) == 1:
            raise errors.not_found("공유된 코스를 찾을 수 없습니다.")
        shared_course_repo.bump_view_count(conn, share_code=code)
        # U-6 결론: 상세에 하트를 붙일지는 designer 판단이고, 서버는 그 판단과 무관하게
        # 값을 **항상** 제공한다(나중에 라우트를 다시 고치지 않기 위해서다).
        liked, like_count = shared_course_repo.get_like_state(
            conn, share_code=code, user_id=user_id
        )
        return row, liked, like_count

    row, liked, like_count = await db.awrite(_tx)
    item = _to_item(row | {"like_count": like_count, "liked_by_me": liked})
    course = course_payload.filter_stored_course(
        _decode_payload(row["payload"]), spot_repo=spot_repo
    )
    await course_payload.attach_congestion(course, congestion_repo)
    return SharedCourseDetail(
        share_code=item.share_code,
        nickname=item.nickname,
        title=item.title,
        spot_count=item.spot_count,
        created_at=item.created_at,
        # 방금 +1 한 값을 돌려준다(응답과 DB 가 어긋나 보이지 않게).
        view_count=item.view_count + 1,
        like_count=item.like_count,
        liked_by_me=item.liked_by_me,
        course=course,
        is_mine=bool(device_id) and row["device_id"] == device_id,
    )


async def list_shares(
    db: Database,
    *,
    limit: int,
    offset: int,
    sort: str = "latest",
    user_id: int | None = None,
) -> SharedCourseListResponse:
    limit = max(1, min(shared_course_repo.MAX_LIMIT, limit))
    offset = max(0, offset)
    # 화이트리스트 밖 값은 라우터가 이미 422 로 막지만, 서비스도 스스로를 지킨다(기본 latest).
    if sort not in shared_course_repo.SORT_VALUES:
        sort = "latest"

    def _tx(conn: psycopg.Connection):
        rows = shared_course_repo.list_shares(
            conn, limit=limit, offset=offset, sort=sort, user_id=user_id
        )
        total = shared_course_repo.count_shares(conn)
        return rows, total

    rows, total = await db.aread(_tx)
    return SharedCourseListResponse(items=[_to_item(r) for r in rows], total=total)


# --- 좋아요 (부록 R.14) --------------------------------------------------------


def _assert_likeable_in_tx(conn: psycopg.Connection, code: str) -> None:
    """없는 코드 · hidden=1 이면 404. 가려진 글에 좋아요가 붙지 않게 한다.

    payload 를 읽지 않는 전용 조회를 쓴다 — 하트는 목록에서 연달아 눌리는 동작이라
    한 번에 32KB 를 읽으면 그 비용이 그대로 쌓인다.
    """
    if shared_course_repo.get_share_visibility(conn, share_code=code) is not True:
        raise errors.not_found("공유된 코스를 찾을 수 없습니다.")


async def like_share(db: Database, *, share_code: str, user_id: int) -> LikeResponse:
    """멱등 — 이미 눌린 상태에서 다시 호출해도 200(liked=true). 409 를 쓰지 않는다."""
    code = normalize_share_code(share_code)

    def _tx(conn: psycopg.Connection) -> tuple[bool, int]:
        _assert_likeable_in_tx(conn, code)
        return shared_course_repo.toggle_like(
            conn, share_code=code, user_id=user_id, now_iso=to_iso_kst(now_kst())
        )

    try:
        liked, like_count = await db.awrite(_tx)
    except psycopg.errors.ForeignKeyViolation:
        # 조회와 INSERT 사이에 보존정책이 그 코스를 지운 경우 — 500 이 아니라 404 가 맞다.
        raise errors.not_found("공유된 코스를 찾을 수 없습니다.") from None
    # 로그에 user_id·share_code 를 남기지 않는다(부록 R.8-4/R.14.6-8 승계).
    logger.info("shared course liked")
    return LikeResponse(liked=liked, like_count=like_count)


async def unlike_share(db: Database, *, share_code: str, user_id: int) -> LikeResponse:
    """멱등 — 누른 적 없어도 200(liked=false). 404 를 쓰지 않는다(취소의 결과 상태가 같다)."""
    code = normalize_share_code(share_code)

    def _tx(conn: psycopg.Connection) -> tuple[bool, int]:
        _assert_likeable_in_tx(conn, code)
        return shared_course_repo.untoggle_like(conn, share_code=code, user_id=user_id)

    liked, like_count = await db.awrite(_tx)
    logger.info("shared course unliked")
    return LikeResponse(liked=liked, like_count=like_count)


__all__ = (
    "CODE_LENGTH",
    "DEFAULT_LIMIT",
    "create_share",
    "delete_share",
    "generate_share_code",
    "get_share",
    "guard_payload_limits",
    "like_share",
    "list_shares",
    "normalize_share_code",
    "run_cleanup",
    "unlike_share",
)
