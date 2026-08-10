"""부록 R 공통 에러 — 서비스가 던지고 라우터가 계약 §3 봉투로 변환한다.

`{"error":{"code","message","detail"}}` 형식을 유지하기 위해 서비스는 HTTPException 을
쓰지 않는다(기존 모든 라우터가 JSONResponse 로 직접 봉투를 만드는 방식과 동일 — 프론트가
새 파서를 만들 필요가 없다).
"""

from __future__ import annotations


class CommunityError(Exception):
    """status/code/message(/detail)를 그대로 응답으로 옮길 수 있는 업무 예외.

    `detail` 은 계약 §3 봉투의 `error.detail` 로 나간다(기본 `{}`). **기계가 읽는 값만**
    담는다 — 사람이 읽는 문구는 message 이고, detail 에 사용자 텍스트나 device_id 를
    넣지 않는다(그대로 응답에 실려 나간다).
    """

    def __init__(
        self, status: int, code: str, message: str, detail: dict[str, object] | None = None
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.detail: dict[str, object] = detail or {}


def not_found(message: str = "요청한 항목을 찾을 수 없습니다.") -> CommunityError:
    return CommunityError(404, "NOT_FOUND", message)


def not_owner() -> CommunityError:
    # 403 + NOT_OWNER. "존재는 하지만 당신 것이 아니다"를 알려주는 것이 데모 UX 에 낫다
    # (404 로 숨겨도 device_id 를 모르면 어차피 아무것도 할 수 없다).
    return CommunityError(403, "NOT_OWNER", "본인이 작성한 항목만 수정·삭제할 수 있어요.")


def review_exists(*, hidden: bool = False) -> CommunityError:
    """409 — 같은 기기 + 같은 대상에 이미 후기가 있음.

    QA M-3: `detail.hidden` 은 "그 기존 후기가 신고 누적으로 가려진 상태인가"다. 프론트는
    이 값으로 안내를 바꾼다(가려진 경우 "수정하거나 삭제할 수 있어요"로 자력 복구를 안내).
    """
    if hidden:
        message = (
            "이미 남긴 후기가 신고 누적으로 가려진 상태예요. 목록에서 수정하거나 삭제할 수 있어요."
        )
    else:
        message = "이미 이곳에 남긴 후기가 있어요. 기존 후기를 수정해 주세요."
    return CommunityError(409, "REVIEW_EXISTS", message, {"hidden": hidden})


def invalid_input(code: str, message: str) -> CommunityError:
    return CommunityError(400, code, message)


def device_id_required() -> CommunityError:
    return CommunityError(
        400, "DEVICE_ID_REQUIRED", "기기 식별자가 없어 요청을 처리할 수 없습니다."
    )


def storage_unavailable() -> CommunityError:
    return CommunityError(
        503, "STORAGE_UNAVAILABLE", "후기 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    )


def feature_disabled() -> CommunityError:
    return CommunityError(
        503, "FEATURE_DISABLED", "후기·코스 공유 기능이 현재 비활성화되어 있습니다."
    )


__all__ = (
    "CommunityError",
    "device_id_required",
    "feature_disabled",
    "invalid_input",
    "not_found",
    "not_owner",
    "review_exists",
    "storage_unavailable",
)
