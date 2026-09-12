# 숨은 길 — 보안 보완 요청서

[Unverified] 운영 환경에서 공격 성공 여부는 확인하지 않았습니다. 결과는 커밋 545ae9d7f5c10a0b5c4cec0b3be8755103b94e66 코드와 로컬 실험에 한정합니다.

## 우선 수정

- F-01 의존성: Next.js 14.2.35, Starlette/python-dotenv를 공식 권고에 따라 갱신하고 lockfile·CI·npm audit·pip-audit 결과를 남깁니다.
- F-02 공유 상한: 조회 유예가 전체 저장 상한을 넘지 않도록 쓰기 트랜잭션에서 강제하고 동시 생성 후 행 수를 검증합니다. 현재 SQLite/BEGIN IMMEDIATE 기준입니다.
- F-03 신고 조작: 같은 IP에서 X-Device-Id를 바꾼 익명 신고 3회만으로 정상 리뷰가 자동 숨김되지 않도록 관리자 검토 정책으로 수정합니다.
- F-04 payload 검증: course/spots/legs/region 중첩 스키마와 프론트 응답 검증을 추가합니다. object가 문자열 자리에 들어간 입력은 4xx로 거부합니다.
- F-05 캐시: MemoryCache와 last_good에 항목 수·바이트 상한, 만료 정리, 지역 코드 허용목록을 적용합니다.
- F-06 방문 통계: 비콘 경로를 허용 패턴으로 정규화하고 visit_repo.prune()을 주기 작업에 연결해 90일 보존을 실제로 지킵니다.

## 재현 결과

F-02 최근 조회 5,000행 준비 후 API 생성·조회 3회 뒤 5,003행 잔존. F-03 동일 IP 장치 ID 3개 신고가 모두 202이고 세 번째에 타인 리뷰 자동 숨김. F-04 malformed nested course가 201 저장·반환되고 React에서 Objects are not valid as a React child 오류. F-05 TTL 0 키 1,000개 잔존. F-06 존재하지 않는 경로 10개가 모두 저장되고 prune 호출부 미확인.

## 운영 재검증

XFF 신뢰, malformed Host, 관리자 리미터 동시성, 로그아웃 후 기존 토큰 재사용을 실제 프록시 환경에서 재검증합니다. 공개 배포의 RATE_LIMIT_ENABLED, 통계 해시 비밀값, CSP/HSTS, 관리자 프레임 차단, 3000·8000·11434 외부 노출도 확인합니다.

수정 커밋 SHA, 변경 파일, 수정 전·후 재현 결과, 회귀 검사, 설정 변경(비밀값 제외), 배포 여부를 항목별로 회신해 주세요. 수정 완료와 배포 완료를 구분합니다.

