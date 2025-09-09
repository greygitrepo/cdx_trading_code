# OB-Flow v2: 호가창+거래량 기반 초단타 봇

이 레포는 v2(OB-Flow) 전용 경량 구조를 제공합니다. v1의 다전략 구조(MIS/VRS/LSR 등)를 제거하고, 호가창+거래량 기반 단일 전략만 유지합니다.

## 프로젝트 구조
- `bot/core`: 핵심 모듈(타입, 수수료/슬리피지, 백테스터 등)
- `bot/configs`: 설정/파라미터 스키마(Pydantic)와 YAML 설정
- `bot/scripts`: 실행 스크립트(paper/live/report)
- `tests`: 유닛 테스트(수수료/슬리피지/부분청산 등)
- `docs/spec.md`: 단일 소스 명세

## 현재 기능 요약
- 이벤트 버스: 심볼별 비동기 큐 기반 팬아웃(`bot/core/event_bus.py`)
- 주문 라우터: 레이트리밋/타임아웃/재시도/idem 키 표준화(`bot/core/order_router.py`)
- 리스크 수학: 수수료·슬리피지·TP/SL 판단 순수함수(`bot/core/risk_math.py`)
- 마켓데이터 허브: 거래소 WS → 심볼별 이벤트 분배, 신선도(≤200ms) 체크(`bot/core/market_data_hub.py`)
- 심볼 액터(옵션): 심볼별 상태머신(Task-per-Symbol)으로 독립 의사결정/주문(`bot/actors/symbol_actor.py`)
- 실행 플래그: `--actor-mode`로 신규 경로 활성화, 기본값은 기존 모놀리식 루프 유지

## 빠른 시작(Quickstart)
1) 의존성 설치
```bash
pip install -r requirements.txt
```

2) 린트 & 테스트
```bash
ruff check .
pytest -q
```

3) 페이퍼 리포트 생성
```bash
python bot/scripts/run_paper.py
```
리포트는 `reports/paper.html`에 생성됩니다.

## 개발(Development)

- Python 3.10/3.11
- 의존성 설치: `pip install -r requirements.txt`
- 코드 스타일/린트: `ruff format . && ruff check .`
- 테스트 실행: `pytest -q -m "unit or strategy"`

### Pre-commit(권장)

커밋 전에 Ruff를 자동 실행하려면 pre-commit을 설치하세요:

```
pip install pre-commit
pre-commit install
```

훅은 변경 파일에 `ruff --fix`와 `ruff format`을 실행합니다.

## 빠른 시작(Live Testnet)
- 의존성 설치 후 `.env.sample`을 복사해 Bybit 테스트넷 API 키를 채운 `.env`를 준비합니다(비밀키 커밋 금지).
- 환경 토글 확인:
  - `STUB_MODE=false`, `PAPER_MODE=false`, `LIVE_MODE=true`, `TESTNET=true`
  - `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_SYMBOL=BTCUSDT`

실행 단계
```bash
pip install -r requirements.txt

# export envs (or use a .env loader in your shell)
export STUB_MODE=false PAPER_MODE=false LIVE_MODE=true TESTNET=true
export BYBIT_API_KEY=xxx BYBIT_API_SECRET=yyy BYBIT_SYMBOL=BTCUSDT

python bot/scripts/run_live_testnet.py
```

동작 개요
- `/v5/account/wallet-balance`로 API 키 검증 및 로그 출력
- 심볼 필터(tickSize/qtyStep/minQty) 로드 및 레버리지 설정
- 타이머 루프 시작: 레짐 체크 → 전략 스코어링(MIS/VRS/LSR) → 주문 라우팅(maker/taker) → 반영(주문/포지션) → 취소(smoke)
- `CONSENSUS_TICKS` 동안 전략 합의가 없으면 심볼 회전(유니버스/로테이션 환경변수 참조). 종료는 `EXIT_KEY`(기본 `q`).
- 정밀도 기반 사이징, 펀딩 회피, 트레일/TP/SL, 타임스탑 적용

주의/안전
- 비밀키: 환경변수에서만 읽습니다. `.env`는 커밋 금지.
- 레이트리밋: 429/일부 `retCode`에 대해 지수 백오프+재시도 내장.
- 복원력: 주문 생성 시 `orderLinkId`로 idem 보장.
- 로깅: `logs/run_*/events.jsonl`(JSONL)과 순환 `app.log` 기록.
- 선택적 WS: `ENABLE_PRIVATE_WS=true`와 `websocket-client` 설치 시 `order/execution/position` 프라이빗 이벤트를 JSONL로 수집.

### Actor 모드(옵션)
- 목적: 심볼별 비동기 Actor(Task)로 이벤트 기반 즉시 평가 및 주문 지연 감소
- 특징: 중복 주문 방지(idempotency), 레이트리밋 세마포어, 타임아웃/재시도 일원화, 허브 기반 팬아웃

실행 예시
```
python bot/scripts/run_live_testnet.py --actor-mode --symbols BTCUSDT,ETHUSDT
```

시작 로그 예시(1줄)
```
INFO ActorMode=on symbols=['BTCUSDT','ETHUSDT'] rate_limit=3
```

SLA 로그(주기 5초)
- avg_per_symbol_sla_ms: 심볼당 평균 SLA
- p95_decision_to_order_ms: 의사결정→주문 전송 p95 지연
- stale_events: 신선도 초과 이벤트 수(>200ms)
- dup_idem: 중복 idempotency 키 감지 수

#### Actor 모드 상세 사용 팁
- 심볼 선택: `--symbols BTCUSDT,ETHUSDT`처럼 화이트리스트로 시작하세요. 심볼이 늘수록 액터(Task) 수가 증가합니다.
- 레이트리밋: 거래소 제약에 맞춰 세마포어 크기를 설정합니다(예: 3). 버스트가 잦으면 2로 낮춰 p95를 안정화하세요.
- Idempotency 키: `f"{symbol}-{ts_ms}-{intent}"` 형태를 권장합니다. 재시도 시 반드시 동일 키를 사용하세요. 거래소가 `clientOrderId` 중복을 거절하는지 로그로 확인하세요.
- 신선도 게이트: `now_ms - event.ts <= 200` 조건을 통과한 이벤트만 진입/청산에 사용됩니다. 시스템 시간이 표준시와 어긋나면 NTP 동기화를 권장합니다.
- 재시도/백오프: `timeout` 또는 `429` 계열 오류 시 라우터가 상태를 반환합니다. 액터는 즉시 재평가(EVAL)로 돌아가고, 짧은 지터(예: 50–150ms) 후 재시도를 권장합니다.
- 모니터링: 5초 주기의 SLA 로그로 평균/분포를 확인하세요. 목표는 `avg≤30ms`, `p95≤40ms`, `stale=0`, `dup_idem=0`입니다.
- 격리/복구: 한 액터 예외는 Supervisor가 재시작합니다. 다른 심볼은 영향을 받지 않습니다. 장애 시 해당 심볼의 idem 키 충돌 여부를 먼저 점검하세요.
- 안전 모드: 실제 키로 실행 전 `TESTNET=true` 또는 `DRY_RUN=true`에서 먼저 검증하세요.

#### SLA 정의(측정 방법 포함)
- event_freshness_ms: `publish시각(now_ms) - event.ts`. 200ms 초과는 stale로 집계합니다.
- evaluation_latency_ms: 버스 구독자가 이벤트를 수신한 시점 → 액터 `step()` 시작 시점까지의 지연.
- decision_to_order_ms: 액터가 주문 결정을 내린 시점 → `OrderRouter.send()` 완료(거래소 응답 수신)까지. 세마포어 대기와 네트워크 왕복을 포함합니다.
- avg_per_symbol_sla_ms: 최근 60초 윈도우의 `decision_to_order_ms` 평균(심볼별).
- p95_decision_to_order_ms: 최근 60초 윈도우의 `decision_to_order_ms` 95퍼센타일(전체).
- stale_events: 최근 60초 동안 `event_freshness_ms>200`인 이벤트 개수.
- dup_idem: 최근 60초 동안 동일 idempotency 키로 주문 전송 시도 감지 횟수.

환경(운영용 하이라이트)
- 모드: `LIVE_MODE`, `TESTNET`, `STUB_MODE`, `PAPER_MODE`
- 비밀키: `BYBIT_API_KEY`, `BYBIT_API_SECRET`
- 운영 토글: `DRY_RUN`, `ENABLE_PRIVATE_WS`, `TIME_STOP_SEC`(override), 선택 `ORDER_SIZE_USDT`
전략/리스크/루프 파라미터는 YAML(config/profiles)에서 관리합니다.

## 데이터 레이어(Stub/Live)
- 환경변수로 모드 전환: `STUB_MODE`(기본 true), `PAPER_MODE`(기본 true), `LIVE_MODE`(기본 false)
- WS(스텁 재생): `bot/core/data_ws.py`가 `data/stubs/ws/*.jsonl`에서 ticker/orderbook(L1/L5) 읽기
- REST(스텁 픽스처): `STUB_MODE=true`일 때 `bot/core/data_rest.py`가 `data/stubs/rest/*.json` 읽기
- 라이브 전환: `STUB_MODE=false` 내보내기(CI에서는 라이브 WS 배선 비활성)

## 설정(Configuration)
### YAML 단일 소스(통합)
- 기본: `bot/configs/config.yaml`
- 프로파일(오버레이): `bot/configs/profiles/*.yaml`(예: `mainnet.yaml`, `testnet.yaml`, `quick_test.yaml`)
- 전략/리스크/레짐/라우팅/루프 파라미터는 YAML(ENV 아님)
- 운영 토글은 ENV로만 제어: `LIVE_MODE/TESTNET/STUB/PAPER`, `BYBIT_API_KEY/SECRET`, `DRY_RUN`, `ENABLE_PRIVATE_WS`

런너는 YAML을 직접 읽습니다:
- 리스크: `risk.max_leverage`, `risk.max_alloc_pct`, `risk.min_free_balance_usdt`
- 레짐: `params.regime.strictness`, `params.universe.spread_threshold_pct`, `params.regime.spread_mult_pause`
- 오더북: `params.orderbook.min_depth_usd`
- OB-Flow: `params.obflow.*`
- 라우팅: `params.execution.*`(강시그널 → taker 승격)
- 진입/청산: `params.entry_exit.tp1/sl/trail_after_tp1`
- 루프/디스커버리: `runtime.discover_symbols/consensus_ticks/no_trade_sleep_sec/loop_idle_sec/exit_key/refresh_universe_each_loop`
- 동작: `runtime.avoid_duplicate_symbol/allow_flip/invert_signals/attach_tpsl_on_create`

프로파일은 YAML 오버레이로 적용됩니다(ENV 매핑 없음):
```
python bot/scripts/run_live_testnet.py --profile mainnet
```
`bot.configs.schemas.load_app_config`로 로드/검사할 수 있습니다. 런너는 핵심 파라미터로 `config:resolved` 이벤트를 출력합니다.

### OB-Flow 임계값(YAML)
`bot/core/signals/obflow.py`는 `OBFlowConfig.from_params(app.params)`를 통해 YAML에서 임계값을 읽습니다.
조정 위치: `bot/configs/config.yaml` → `params.obflow`
- depth_imb_L5_min: 패턴 A/C의 L5 불균형 임계값
- spread_tight_mult_mid: 패턴 B의 타이트 스프레드 배수
- tps_min_breakout: 브레이크아웃 최소 ticks-per-second(placeholder)
- c_absorption_min: 흡수 강도 임계값
- d_wide_spread_mult_mid: 패턴 D의 와이드 스프레드 게이트
- d_micro_dev_mult_spread: 패턴 D의 스프레드 대비 미세 괴리

### 트레이드 상태 헬퍼
`bot/core/execution/trade_state.py`는 부분청산, TP1 이후 트레일, 타임스탑, 쿨다운(라이브/시뮬 공용)을 제공합니다.

### 퀵-테스트 프로파일(테스트넷 빠른 체결)

테스트넷에서 라이브 배선을 빠르게 검증하고 다수 체결을 유도하려면:

1) quick-test 프로파일로 실행

```
python bot/scripts/run_live_testnet.py --profile quick-test
```

완화된 필터와 테이커 친화 라우팅을 적용합니다:
- maker_post_only=false, taker_on_strong_score=true, fallback_ioc=true
- MIN_DEPTH_USD≈2000, SLIPPAGE_GUARD_PCT≈0.0015, CONSENSUS_TICKS≈2
- 시그널 증가: keltner_mult≈1.25, rsi2_low≈8, rsi2_high≈92, htf_bias.disabled
- RR: TP≈0.10%, SL≈0.12%, TIME_STOP≈8m

2) 리포트 생성

```
python bot/scripts/make_report.py --run_id <run_id>
```

HTML 리포트는 체결률/슬리피지 추정/요약과 함께 `reports/quick_test_<run_id>.html`에 저장됩니다.

주의: 실거래 전에는 보수 설정으로 되돌리거나 `--profile quick-test`를 생략하세요.

## Replay/Backtest (Stub LOB)
- OB-Flow 리플레이: `bot/scripts/run_replay_obflow.py`는 `data/stubs/ws/orderbook1_<SYMBOL>.jsonl`을 재생해 신호/부분청산/트레일/타임스탑/쿨다운 동작을 점검합니다.
```
python bot/scripts/run_replay_obflow.py --symbol BTCUSDT --max-sec 60 --qty-usdt 50
```
결과는 `logs/replay_obflow/<SYMBOL>.jsonl` 이벤트와 `reports/replay_obflow_<SYMBOL>.json` 요약으로 저장됩니다.

## 테스트(요약)
- risk_math: 수수료 반영 및 TP/SL 경계값 검증(`tests/test_risk_math.py`)
- order_router: 타임아웃/재시도/idem 동작 및 세마포어 레이트리밋 검증(`tests/test_order_router.py`)
- symbol_actor: 가짜 이벤트 스트림으로 IDLE→ENTERED→EXITED 전이 검증, stale 차단(`tests/test_symbol_actor.py`)
