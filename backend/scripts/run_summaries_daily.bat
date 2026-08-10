@echo off
REM ============================================================================
REM  숨은길 — AI 요약 사전생성 이어받기 (하루 1회 실행)
REM
REM  공공데이터(detailCommon2)는 일일 호출 쿼터가 있어 한 번에 다 못 만든다.
REM  이 파일을 하루 한 번 더블클릭하면, 이미 만든 것은 건너뛰고 그날 쿼터만큼
REM  이어서 채운다(재개 가능). 쿼터가 떨어지면 스스로 깔끔하게 멈춘다.
REM
REM  전제: Ollama 가 켜져 있어야 한다(작업 표시줄 아이콘 확인, 없으면 `ollama serve`).
REM  결과: backend/app/spots/data/spot_summaries.json 에 누적 저장된다.
REM ============================================================================
setlocal
cd /d "%~dp0\.."
echo [숨은길] AI 요약 이어받기를 시작합니다. 창을 닫지 마세요.
echo.

REM Ollama 응답 확인 (없으면 요약 생성이 전부 실패하므로 미리 중단)
curl -s -o nul -m 8 http://127.0.0.1:11434/api/tags
if errorlevel 1 (
  echo [중단] Ollama 가 응답하지 않습니다. Ollama 를 먼저 실행한 뒤 다시 시도하세요.
  pause
  exit /b 1
)

py -u scripts\build_spot_summaries.py --limit 400

echo.
echo [숨은길] 종료되었습니다. 위 "커버리지 리포트" 수치를 확인하세요.
echo          쿼터 소진으로 멈췄다면 내일 이 파일을 다시 실행하면 이어집니다.
pause
