OB-Flow v2 Spec
================

개요
----
v2는 호가창+거래량 기반 초단타(OB-Flow) 전용 봇으로, v1의 다전략 구조를 제거하고 경량화된 실행·테스트·리포트 파이프라인을 제공합니다.

핵심 컴포넌트
-------------
- feed: WS 기반 L2 오더북, ticker
- book: 스냅샷+증분 동기화(L2Book)
- features: microprice, depth imbalance, OFI 등 저지연 피처
- signals.obflow: A/B/C/D 패턴 평가 (단일 전략 라우팅)
- exec: 브로커(IOC/PostOnly), 리스크(TP/SL/time stop)
- state: 포지션 FSM
- recorder: JSONL 이벤트 기록
- replay: LOB 리플레이

전략(요약)
---------
- A 매수벽 반등: wall_bid_mult>=Wmin, depth_imb_L5>=Imin, micro>mid
- B 매도벽 돌파: ask벽 소거, tps/vps 급증, micro가 ask측
- C 흡수 후 반전: 체결 우위 지속, 가격 정체, 반대편 재보충
- D 스윕 후 평균회귀: 급등락 후 스프레드 축소, 첫 보합 캔들

리스크/실행(요약)
-----------------
- 기본 TP/SL, time stop, 슬리피지 가드(bps)
- 테스트넷 quicktest 프로필 제공

테스트/CI
---------
- pytest 단위/경량 통합 테스트, 1분 내 완료
- GitHub Actions: ruff + pytest(unit/strategy)

