"""MVP-3 온보딩 취향 추출 (AI) 모듈.

정본:
  - projects/sumeungil-build/01-interface-contract.md 부록 B (프론트↔backend 계약)
  - projects/sumeungil/08-interface-contract.md §1.4~1.8 (tag_axis_registry, OnboardingResult)
  - projects/sumeungil/02-ai-strategy.md §1 (프롬프트/스키마/폴백/injection 방어 설계)

backend가 호출할 단일 진입점은 `onboarding_service.extract_onboarding_tags()`.
"""
