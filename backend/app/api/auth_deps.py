"""로그인 필수 엔드포인트용 공유 의존성 (2026-08-17, 대표 지시).

`api/auth.py`의 `_require_session`(세션 쿠키 검증, 실패 시 401)과 정확히 같은 로직이다 —
그 함수는 `auth.py` 안에서만 쓰던 모듈 비공개 헬퍼라 이름 그대로 재사용할 수 없었고,
이제 온보딩·AI 문답·AI 코스짜기·고객문의 라우터가 똑같은 검증을 필요로 하게 돼 별도
모듈로 분리했다(다른 라우터가 `api/auth.py` 내부 함수를 직접 import 하는 것보다, 공유
목적의 전용 모듈을 두는 편이 의존 방향이 명확하다).

`community_common.session_display_name`과의 차이: 그쪽은 "로그인했으면 값을, 아니면
None을"(선택적 신원 — 비로그인도 계속 진행) 패턴이고, 이 모듈은 "로그인 안 했으면 401"
(필수 신원 — 온보딩/AI문답/AI코스짜기/고객문의는 이제 로그인 없이는 아예 못 씀) 패턴이다.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..deps import get_database, get_user_auth
from ..repositories import user_repo
from ..security.user_auth import UserIdentity


async def require_login(request: Request) -> UserIdentity:
    """로그인 세션이 없으면 401. `Depends(require_login)`으로 라우터에 붙인다.

    2026-08-18(QA M-2) — 서명·만료만 보고 끝내던 걸, **DB에 그 계정이 실제로 아직
    있는지**까지 확인하도록 고쳤다. 세션 토큰은 서버가 강제로 무효화할 수단이 없는
    자체서명 방식이라(로그아웃은 쿠키만 지울 뿐), 계정을 삭제(탈퇴)한 뒤에도 만료 전까지는
    서명 자체는 여전히 유효하다. 그 상태로 쓰기 요청(예: 고객문의 작성)이 들어오면
    `ai_courses`/`inquiries`처럼 `user_id REFERENCES users(id)`인 테이블에 INSERT가
    시도되면서 존재하지 않는 user_id 때문에 외래키 위반으로 500이 났다(qa-reviewer
    실행 재현). DB 조회가 매 요청 하나 더 붙긴 하지만, "삭제된 계정" 요청은 500 대신
    깔끔하게 401(로그인이 필요합니다)로 떨어지는 게 맞다 — /me 엔드포인트가 이미 같은
    패턴(get_by_id 결과 없으면 비로그인 취급)을 쓰고 있어 그대로 재사용했다.
    """
    auth = get_user_auth()
    identity = auth.verify_token(request.cookies.get(auth.cookie_name)) if auth.enabled else None
    if identity is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    db = get_database()
    user = await db.aread(lambda conn: user_repo.get_by_id(conn, identity.user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return identity


__all__ = ("require_login",)
