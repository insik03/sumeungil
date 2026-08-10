"""발견형 목록의 **무작위 표본 추출** 공용 유틸 (2026-08-01, backend-engineer).

대표 지시(2026-08-01): "홈에 뜨는 관광지가 너무 고정이라 항상 같은 곳만 보인다.
**'가장 ~한' 수식어가 붙는 순위성 추천만 빼고** 나머지는 랜덤으로 돌려라."

그래서 이 모듈은 **순위가 곧 정보인 섹션(trending, seasonal.popular, 혼잡도 보드)에는
쓰지 않는다.** 쓰는 곳은 "아직 붐비지 않는 곳"·"테마별"처럼 순서가 정보가 아닌 목록뿐이다.

설계 원칙 3가지
  1. **품질 하한 불변**: 표본은 항상 *기존 자격 조건을 통과한 후보*(is_hidden_gem / 테마 매칭 /
     예측 데이터 보유 …) 안에서만 뽑는다. 자격 미달 스팟을 끌어올려 자리를 채우지 않는다.
  2. **풀 상한**: 후보를 무제한으로 열지 않는다. 선호 순으로 정렬된 앞쪽 `pool_cap(need)`
     (= 필요 개수의 6배, 최대 60)만 풀로 삼는다 → 저혼잡·숨은 우선이라는 선호가 유지된다.
  3. **표시 순서는 선호 순 복원**: 뽑고 나서 원래 정렬 순서로 되돌린다(무작위는 "누가 뽑히나"
     에만 작용하고 "어떤 순서로 보이나"는 기존 규칙 그대로).

시드
  - `seed=None`(기본) → 요청마다 다른 결과(새로고침하면 바뀐다 = 대표 요구).
  - `seed=<int>`      → **결정적**. 검증·재현 용도로 쿼리 파라미터로 받는다(부록 S.3).
  - `random.seed()` 같은 전역 오염은 하지 않는다. 항상 `random.Random` 인스턴스다.
  - `salt` 는 같은 요청 안에서 병렬로 도는 단위(권역·테마)별로 **독립적이면서도 결정적인**
    난수열을 주기 위한 것이다. asyncio 완료 순서에 따라 rng 소비 순서가 달라지면 같은 seed
    로도 결과가 흔들리므로, 단위마다 별도 rng 를 만든다. 문자열 시드는 CPython 이 sha512
    로 처리하므로 프로세스가 달라도(PYTHONHASHSEED 무관) 같은 값이 나온다.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")

# 후보 풀 = 필요 개수의 몇 배까지 열 것인가(넉넉하되 무제한 금지).
POOL_FACTOR = 6
POOL_MAX = 60
# 사진 조회 상한 배수 — "선택 개수의 1.5배만 조회해 사진 있는 것 우선" 기존 정책(부록 H.3).
PHOTO_FACTOR = 1.5
# --- 부록 S.8.6(2026-08-01 수정) 결정적 순열(sequence) 상수 ---
# 순열은 **요청의 per_theme(페이지 크기)와 무관하게** 고정 청크로 만든다. 이게 이번 수정의 핵심:
# 청크 크기가 요청마다 달라지면 페이지 경계가 달라져 같은 시드인데도 중복/누락이 생긴다.
SEQ_CHUNK = 8
# 청크당 같은 그룹(시군구) 최대 개수 — 연속 구간 어디를 잘라도 지역 쏠림이 억제된다.
SEQ_GROUP_CAP = 2
# 순열 생성 청크 수 상한(무한 루프 방어). OFFSET_MAX(2000) + PER_THEME_MAX(50) 를 덮는다.
SEQ_MAX_CHUNKS = 512
# 시드 상한(쿼리 파라미터 `seed` 범위와 동일).
SEED_MAX = 2_147_483_647


def make_rng(seed: int | None, salt: str = "") -> random.Random:
    """요청 1건(+단위)용 난수 발생기. seed 가 None 이면 매번 다르다."""
    if seed is None:
        return random.Random()
    return random.Random(f"{seed}:{salt}")


def new_seed() -> int:
    """이번 요청의 시드를 새로 만든다(응답에 실어 더보기에서 재사용하게 하려고).

    부록 S.8(2026-08-01): 더보기(offset)는 **같은 시드로 만든 같은 순열의 다음 구간**이어야
    중복·누락이 없다. 그래서 seed 미지정 요청도 서버가 시드를 하나 뽑아 그걸로 표본을 만들고
    응답에 되돌려준다 — "새로고침하면 새 조합(매 요청 새 시드), 더보기는 이어짐(시드 재사용)".
    """
    return random.SystemRandom().randrange(0, SEED_MAX + 1)


def pool_cap(need: int) -> int:
    """표본을 뽑을 후보 풀의 상한."""
    if need <= 0:
        return 0
    return max(need, min(POOL_MAX, need * POOL_FACTOR))


# 청크 1개를 뽑을 때 여는 후보 풀. 선호(숨은·저혼잡·사진 보유) 순서 유지의 근거이자,
# offset=0/per_theme=8 요청이 종전과 **완전히 같은 결과**를 내는 근거다(pool_cap(8) = 48).
SEQ_POOL_CAP = pool_cap(SEQ_CHUNK)


def photo_budget(need: int) -> int:
    """사진을 조회할 최대 개수(= 선택 개수의 1.5배). 풀 전체 조회 금지의 근거 수치."""
    if need <= 0:
        return 0
    return max(need, math.ceil(need * PHOTO_FACTOR))


# 참고(2026-08-01, 결정 2): 옛 `trim_photo_candidates()` 는 **삭제**했다. 그 함수는
# "앞 need 개가 확정 후보, 뒤가 여유분"인 목록을 전제로 여유분을 잘라내는 도우미였는데,
# 그 전제를 만들려면 `take=photo_budget(need)` 로 넉넉히 뽑아야 했고 **풀이 그 예산 이하이면
# 표본이 결정적으로 퇴화**했다(풀 전체를 뽑아 선호순 복원 → 앞 need 개 절삭 = 매번 같은 결과).
# 같은 절약 규칙(여유분 = 확정 후보 중 시드 사진이 없는 개수만큼)은 `sample_with_spares()`
# 안에 그대로 살아 있다 — 조회 수는 여전히 노출 개수의 1.5배 이하다.


def sample_preferred(
    candidates: Sequence[T],
    need: int,
    rng: random.Random,
    take: int | None = None,
    group_key: Callable[[T], object] | None = None,
    group_cap: int = 1,
    group_counts: dict[object, int] | None = None,
) -> list[T]:
    """선호 순으로 정렬된 자격 통과 후보에서 무작위 표본을 뽑는다.

    - `candidates`: **이미 자격 필터 + 선호 정렬이 끝난** 목록(저혼잡 우선 등).
    - `need`: 최종 노출 개수. 풀 상한 계산의 기준이다.
    - `take`: 실제로 뽑을 개수(기본 `need`). 사진 있는 것 우선 채우기용 여유분을 뽑을 때
      `photo_budget(need)` 를 넘긴다.
    - `group_key`: 주면 같은 그룹(예: 시군구)에서 `group_cap` 개까지만 뽑는다(지역 다양성).
    - `group_cap`(2026-08-01 additive): 그룹당 상한. 기본 1 = 종전 동작(그룹당 1개).
    - `group_counts`(2026-08-01 additive): 그룹별 사용 수 카운터를 **호출자가 소유**해
      여러 번의 추출(등급별·여유분)에 걸쳐 상한을 이어서 적용한다. None 이면 이 호출 안에서만.
    - 반환 순서는 `candidates` 의 원래 순서다(선호 순 유지).
    """
    if need <= 0 or not candidates:
        return []
    pool = list(candidates[: pool_cap(need)])
    want = min(take if take is not None else need, len(pool))

    order = list(range(len(pool)))
    rng.shuffle(order)

    picked: list[int] = []
    counts: dict[object, int] = group_counts if group_counts is not None else {}
    for i in order:
        if group_key is not None:
            k = group_key(pool[i])
            if counts.get(k, 0) >= max(1, group_cap):
                continue
            counts[k] = counts.get(k, 0) + 1
        picked.append(i)
        if len(picked) >= want:
            break

    picked.sort()  # 표시 순서는 선호 순으로 복원
    return [pool[i] for i in picked]


def sample_tiered(
    tiers: Sequence[Sequence[T]],
    need: int,
    rng: random.Random,
    take: int | None = None,
    group_key: Callable[[T], object] | None = None,
    group_cap: int = 1,
    group_counts: dict[object, int] | None = None,
) -> list[T]:
    """등급(tier)이 있는 후보에서 표본을 뽑는다 — **상위 등급을 먼저 채운다**.

    컬렉션이 대표적이다: 숨은 스팟(tier0)을 먼저 무작위로 채우고, 모자랄 때만
    일반 스팟(tier1)으로 넘어간다. 이렇게 해야 "숨은길" 컨셉(숨은·저혼잡 우선)이라는
    품질 하한을 유지하면서 그 안에서만 무작위가 된다.

    group_* 인자(2026-08-01 additive)는 `sample_preferred` 와 같고, 카운터는 **등급을 가로질러
    공유**된다(등급마다 초기화되면 "시군구당 2곳" 같은 상한이 무너진다).
    """
    want = min(take if take is not None else need, sum(len(t) for t in tiers))
    counts: dict[object, int] = group_counts if group_counts is not None else {}
    out: list[T] = []
    for idx, tier in enumerate(tiers):
        if len(out) >= want:
            break
        remain = want - len(out)
        # 풀 상한은 항상 `need`(최종 노출 개수) 기준이다 — remain(여유분 포함)으로 잡으면
        # 등급별 풀이 의도보다 넓어져 선호(저혼잡·숨은 우선)가 옅어진다.
        out.extend(
            sample_preferred(
                tier,
                need,
                make_rng_child(rng, idx),
                take=remain,
                group_key=group_key,
                group_cap=group_cap,
                group_counts=counts if group_key is not None else None,
            )
        )
    return out[:want]


def sample_with_spares(
    tiers: Sequence[Sequence[T]],
    need: int,
    rng: random.Random,
    has_seed_photo: Callable[[T], bool],
    group_key: Callable[[T], object] | None = None,
    group_cap: int = 1,
) -> tuple[list[T], list[T]]:
    """확정 후보(primary)를 **먼저 무작위로** 뽑고, 사진 대체용 여유분(spare)을 나머지에서 뽑는다.

    왜 `sample_tiered(take=photo_budget(need))` + `trim_photo_candidates` 대신 이게 필요한가
    (2026-08-01 실측): 후보 풀이 `photo_budget(need)` 이하로 작으면 그 조합은 **풀 전체를 뽑아
    선호 순으로 되돌린 뒤 앞 need 개를 자르게 되어 결과가 완전히 결정적이 된다**(무작위성 0).
    실제로 컬렉션 "조용히 힐링"(숨은 후보 11개, need 8, 예산 12)이 10회 호출 내내 같은 8곳만
    내려줬다. 여기서는 primary 를 먼저 `need` 개만 무작위로 뽑으므로 풀이 작아도 섞인다.

    반환: `(primary, spares)`.
      - primary: 실제로 노출할 후보(그룹 상한 때문에 need 보다 적을 수 있다).
      - spares : primary 중 사진이 불확실한 개수만큼만, **primary 기준** 예산
        (`photo_budget(len(primary)) - len(primary)`) 안에서. 사진 조회 총량은 항상
        노출 개수의 1.5배 이하다(부록 H.3 정책 유지).
    그룹 상한 카운터는 primary→spares 로 이어져, 어떤 부분집합을 노출해도 상한이 지켜진다.
    """
    counts: dict[object, int] = {}
    primary = sample_tiered(
        tiers, need, rng, group_key=group_key, group_cap=group_cap, group_counts=counts
    )
    if not primary:
        return [], []
    # 이미 뽑힌 객체 제외. 같은 리스트에서 온 동일 객체라 identity 비교로 충분하다
    # (SpotRecord 는 비동결 dataclass 라 set 에 담을 수 없다).
    chosen = {id(x) for x in primary}
    remaining = [[x for x in tier if id(x) not in chosen] for tier in tiers]
    spares = _pick_spares(
        remaining,
        primary,
        # primary 와 다른 난수열(같은 rng 재사용 시 순서 의존)
        lambda: make_rng_child(rng, 977),
        has_seed_photo,
        group_key=group_key,
        group_cap=group_cap,
        group_counts=counts,
    )
    return primary, spares


def _pick_spares(
    remaining: Sequence[Sequence[T]],
    primary: Sequence[T],
    rng_factory: Callable[[], random.Random],
    has_seed_photo: Callable[[T], bool],
    group_key: Callable[[T], object] | None = None,
    group_cap: int = 1,
    group_counts: dict[object, int] | None = None,
) -> list[T]:
    """노출분(primary)의 "사진 없는 자리"를 대신할 여유분을 남은 후보에서 뽑는다.

    개수는 항상 **primary 기준 예산**(`photo_budget(len(primary)) - len(primary)`) 안이고,
    실제로는 primary 중 시드 사진이 없는 개수만큼만 뽑는다 → 사진 조회 총량은 노출 개수의
    1.5배 이하(부록 H.3 정책 유지).

    여유분의 존재 이유는 **사진 없는 자리를 대신 채우는 것** 하나뿐이다. 그래서 여유분만은
    시드 사진 보유 후보를 먼저 본다(등급 내 순서는 그대로). 이렇게 하지 않으면 상위 등급이
    통째로 사진 없는 테마("인생샷 스팟"의 숨은 후보 75곳이 전부 원천 사진 없음)에서
    여유분까지 사진 없는 후보로 채워져 대체가 무의미해진다(2026-08-01 실측).

    `rng_factory` 는 "여유분이 실제로 필요할 때만" 난수를 소비하기 위한 것이다(호출 순서에
    따라 부모 rng 상태가 달라지면 재현성이 헷갈린다 — 종전 동작을 그대로 보존한다).
    """
    if not primary:
        return []
    spare_cap = max(0, photo_budget(len(primary)) - len(primary))
    spare_need = min(spare_cap, sum(1 for c in primary if not has_seed_photo(c)))
    if spare_need <= 0:
        return []
    spare_tiers = [[x for x in t if has_seed_photo(x)] for t in remaining]
    spare_tiers += [[x for x in t if not has_seed_photo(x)] for t in remaining]
    return sample_tiered(
        spare_tiers,
        spare_need,
        rng_factory(),
        group_key=group_key,
        group_cap=group_cap,
        group_counts=group_counts,
    )


def _head(tier: Sequence[T], used: set[int], cap: int) -> list[T]:
    """아직 안 쓴 후보를 선호 순으로 앞에서 `cap` 개까지. (전체 리스트 재구성 없이 앞부분만 훑는다)"""
    out: list[T] = []
    for x in tier:
        if id(x) in used:
            continue
        out.append(x)
        if len(out) >= cap:
            break
    return out


def build_sequence(
    tiers: Sequence[Sequence[T]],
    seed: int | None,
    salt: str,
    limit: int,
    group_key: Callable[[T], object] | None = None,
    group_cap: int = SEQ_GROUP_CAP,
) -> list[T]:
    """(seed, salt) 만으로 정해지는 **결정적 순열**을 앞에서 `limit` 개까지 만든다 (S.8.6).

    2026-08-01 수정(운영 중복 재현 후): 종전 `sample_paged` 는 "요청의 page_size 로 페이지를
    이어서 계산"했다. 그래서 **같은 시드라도 페이지 크기가 달라지면 경계가 달라져** 앞 요청이
    이미 보여준 아이템이 다음 페이지에 다시 실렸다(실측: per_theme 8→50 조합에서 quiet_cafe
    64%, nature 24.5%, healing 5% 의 시드에서 중복 1건). 여기서는 순열 자체를 page_size 와
    무관하게 만들고, 페이지는 그 순열의 **슬라이스**로만 정의한다 → 어떤 크기·순서로 잘라도
    중복·누락이 원천적으로 불가능하다.

    순열 생성 규칙(품질 하한은 종전 그대로):
      - 고정 크기 청크(`SEQ_CHUNK`=8)를 반복해서 이어 붙인다. 각 청크는 종전 페이지 1장과
        같은 규칙(등급 우선 → 풀 상한 안에서 무작위 → 그룹 상한)으로 뽑는다.
      - 그래서 `seed` 고정 + `SEQ_CHUNK` 크기 페이지의 첫 장은 종전과 **완전히 동일**하다.
      - 그룹 상한(시군구당 2곳)에 걸린 후보는 **버리지 않고 다음 청크로 넘긴다**(그 청크가
        8개보다 짧아질 뿐이다). 종전에는 상한에 걸린 후보를 그 페이지에서 영구히 떨어뜨려
        "끝까지 페이징해도 안 나오는 스팟"(누락)이 생겼다.
      - 후보를 소비만 하고 버리는 경로가 없다 → 순열은 결국 **모든 후보**를 담는다(회수율 100%).
      - 청크마다 상한 카운터가 초기화되므로 후보가 남아 있는 한 최소 1개는 뽑힌다(진행 보장).
    """
    limit = max(0, limit)
    if limit <= 0:
        return []
    used: set[int] = set()
    seq: list[T] = []
    for chunk in range(SEQ_MAX_CHUNKS):
        if len(seq) >= limit:
            break
        heads = [_head(t, used, SEQ_POOL_CAP) for t in tiers]
        if not any(heads):
            break  # 후보 소진 — 지어내지 않는다
        # 청크 0 은 offset 미지정 요청과 **같은 난수열**이어야 한다(무회귀의 근거).
        rng = make_rng(seed, salt if chunk == 0 else f"{salt}:page{chunk}")
        picked = sample_tiered(heads, SEQ_CHUNK, rng, group_key=group_key, group_cap=group_cap)
        if not picked:
            break
        seq.extend(picked)
        used.update(id(x) for x in picked)
    return seq[:limit]


def sample_paged(
    tiers: Sequence[Sequence[T]],
    page_size: int,
    offset: int,
    seed: int | None,
    salt: str,
    group_key: Callable[[T], object] | None = None,
    group_cap: int = SEQ_GROUP_CAP,
) -> tuple[list[T], list[T], bool]:
    """"더보기"용 — 결정적 순열의 `[offset, offset+page_size)` 구간을 돌려준다 (S.8.6).

    **offset 은 "페이지 번호"가 아니라 "순열의 아이템 인덱스"다.** 그래서 호출부가 페이지
    크기를 도중에 바꿔도(8 → 50 → 20 …) 중복도 누락도 생기지 않는다. 프론트는 첫 응답의
    `seed` 를 유지한 채 `offset += 받은 개수` 만 하면 된다.

    여유분(spare) 개념은 **없앴다**. 여유분은 "사진 없는 자리를 대체할 후보"였는데, 노출될
    수도 있는 후보라 다음 페이지 풀에서 빼야 했고(중복 방지), 그러면 그 후보들이 순열에서
    영구히 사라져 회수율이 떨어졌다(실측: 고정 per=8 healing 97%, 혼합 8/50 market 33%).
    대신 **사진 보유 여부를 등급(tier)에 넣어** 앞쪽 아이템이 사진을 갖도록 한다 — 사진 조회는
    노출 개수와 정확히 같아져(≤ 노출×1.5 정책 유지) 원천 비용도 줄어든다.

    반환: `(window, prefix, has_next)`
      - window  : 이번에 노출할 구간(순열이 짧으면 그만큼만)
      - prefix  : 순열의 앞 `SEQ_CHUNK` 개. 호출부가 "테마 간 중복 회피" 등급을 **요청
                  파라미터와 무관하게** 계산하는 데 쓴다(이게 page_size 에 의존하면 등급이
                  흔들려 순열 자체가 달라진다 — 이번 중복 결함의 두 번째 원인이었다).
      - has_next: 순열에 다음 아이템이 남아 있는가(한 개만 더 만들어 보고 판단 — 순수 CPU).
    """
    limit = max(SEQ_CHUNK, offset + max(0, page_size) + 1)
    seq = build_sequence(tiers, seed, salt, limit, group_key=group_key, group_cap=group_cap)
    window = seq[offset : offset + page_size] if page_size > 0 else []
    return window, seq[:SEQ_CHUNK], len(seq) > offset + max(0, page_size)


def make_rng_child(rng: random.Random, idx: int) -> random.Random:
    """tier 마다 독립 난수열(같은 rng 를 연속 소비하면 tier 경계에서 재현성이 헷갈린다)."""
    return random.Random(f"{rng.random()}:{idx}")
