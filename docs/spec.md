좋아, “비밀”은 **하나의 만능 전략**이 아니라, **시장 상태를 빠르게 판별해서 그때그때 가장 유리한 미세 엣지(edge)를 집요하게 활용**하는 구조야. 아래는 Bybit USDT-Perp 선물 1분 스캘핑을 전제로, **시드 100 USDT**에서 실전에 가까운 백테스트 → 반자동/자동 실행까지 한 번에 구현할 수 있는 \*\*구체 명세서(>5000자)\*\*야. 너는 이걸 그대로 Codex에 붙여 넣어 “개발 사양서”로 쓰면 된다. (현실적 안전장치와 거래/수수료/엔진 설계를 함께 포함했어. 수익은 보장할 수 없지만, “실전에 바로 가져다 얹어도 되는 수준”의 정확·안정성을 목표로 설계함.)

---

# Bybit 1분 스캘핑 자동매매 시스템: 개발 사양서 (v1.3 “Gumiho”)

## 0) 목적

* 급변하는 코인 시장에서 **유동성·변동성 상위 심볼만 선별**해, **단타 다회전**으로 “수수료 제외 순이익 +1%/일”을 노리는 **체계적 스캘핑 시스템**을 구축한다.
* \*\*시장 레짐(정상/비정상)\*\*을 **초저지연 지표로 판별**해, 급락/비정상 국면에서는 **즉시 트레이드 중단**, 정상화 신호 포착 시 **거래 재개**한다.
* \*\*전략은 단일이 아니라 ‘전략 팩(Strategy Pack)’\*\*으로 묶어 **레짐·유니버스(종목)별 다이나믹 라우팅**을 한다.
* **시드 100 USDT**, 레버리지 사용. **슬리피지/부분체결/수수료/펀딩/리스크 제한**까지 모두 시뮬레이션에 반영한다.
* 개발 언어: Python 3.11+, 비동기 I/O 기반.

> 참고: Bybit v5 API 기본 개요와 카테고리(spot/linear/inverse/option)는 공식 문서에 따름. **테스트넷/메인넷 베이스 URL**은 v5 가이드 기준 사용. ([Bybit Exchange][1])

---

## 1) 시스템 아키텍처

### 1.1 모듈 구성 (폴더 구조)

```
/bot
  /core
    data_feed.py          # WS 시세, 오더북, 티커, OI 구독
    market_state.py       # 레짐 감지(급락/정상화)
    universe.py           # 종목 유니버스 선정(유동성/스프레드/변동성)
    indicators.py         # 초단기 지표(EMA, ADX, Keltner, VWAP dev, OBI 등)
    strategies.py         # MIS/VRS/LSR 전략 신호
    risk.py               # 포지션 사이징/손절/익절/일손실컷/회복 규칙
    execution.py          # 주문 라우팅(메이커/테이커), postOnly/IOC/FOK
    fees.py               # 수수료/펀딩/슬리피지 모델
    backtest.py           # 실전형 백테스터(부분체결, 슬리피지, 딥스냅샷)
    walkforward.py        # 파라미터 탐색/검증 파이프라인
    reporting.py          # 성과·분배·DD·체결품질 리포트
    persistence.py        # 체결/주문/신호 로깅(SQLite/Parquet)
    api.py                # REST/WS 래퍼, 서명, 재연결, 레이트리밋
  /configs
    config.yaml           # 전역 설정
    params_gumiho.yaml    # 전략 파라미터 팩(기본값)
  /scripts
    run_live.py           # 실거래 실행 엔트리
    run_paper.py          # 페이퍼/백테스트 실행
    export_report.py      # 성과 리포터
  /tests
    test_backtest.py
    test_execution_sim.py
```

### 1.2 데이터 소스

* **WebSocket**: ticker, orderbook(단일 레벨+N레벨), 일부 스트림에서 **OI/펀딩/nextFundingTime 포함**. 시세 스냅샷/체결/스프레드/깊이 변화를 초저지연으로 받는다. ([Bybit Exchange][2])
* **REST**: 종목 스펙, 티커 스냅샷, 최근 체결, 펀딩 이력, OI, 서버시간 동기화, 주문/포지션 관리.

  * 테스트넷/메인넷 **베이스 URL**: `https://api-testnet.bybit.com`, `https://api.bybit.com`. ([Bybit Exchange][3])
  * **Place Order** 엔드포인트는 v5 기준을 사용. ([Bybit Exchange][4])
  * **Instruments Info**는 선형(USDT) 심볼이 500+ 개이므로 페이지네이션 필수. ([Bybit Exchange][5])
  * **Funding Rate History**: 심볼마다 주기 상이(일반적으로 8h 예시). ([Bybit Exchange][6])
  * **Open Interest** 조회로 레버리지 과열 여부 파악. ([Bybit Exchange][7])

### 1.3 수수료·펀딩 반영

* **Derivatives(Perp/Futures) 비VIP 일반 기준 예시**: Taker 0.055%, Maker 0.02% (계정·영역·프로모션·Innovation Zone 등에 따라 상이할 수 있음. 항상 계정별 실제 적용 요율을 조회해서 시뮬에 반영). ([Bybit][8])

---

## 2) 유니버스(종목) 선정

**초단타는 종목 선택이 절반**이다. 매 분기(혹은 30초\~1분 주기)마다 다음 필터로 **Top-N 후보**를 구성:

1. **유동성**: 24h 거래대금 상위 (티커 `turnover24h`, `volume24h`) + **베스트 1호가/스프레드**가 얇지 않을 것. ([Bybit Exchange][9])
2. **스프레드/깊이**: `bid1/ask1` 스프레드가 **중앙값 대비 1.5×** 이내, 상위 5레벨 누적 깊이가 **\$X 이상**. (오더북 REST/WS 혼합) ([Bybit Exchange][10])
3. **미세 추세성**: 최근 3–5분 **방향 일관성**(EMA(3/9) 기울기·연속 고저갱신).
4. **오버나잇/펀딩 리스크**: 펀딩 임박(±5분) 시 테이커 트레이드 지양, 메이커 진입 위주. ([Bybit Exchange][6])
5. **OI 과열도**: OI 급증 구간은 역추세 스윕 위험↑ → **돌파형만 허용** 등 레짐별 화이트리스트 전환. ([Bybit Exchange][7])

기본값: `TopN = 12`, 유니버스는 **회전 가능해야** 한다(틱당 시그널 품질이 계속 유지되는 종목으로 자동 교대).

---

## 3) 레짐 판별(“시장 정상/비정상” 스위치)

### 3.1 급락·이상치 감지 (Trade Pause)

아래 중 **2개 이상 동시 충족** 시 `PAUSE M` 분:

* **1초 수익률 Z-score ≥ 4.0** (최근 5분 기준)
* **스프레드**가 최근 10분 중앙값의 **≥ 3×**
* **최상위 호가 깊이**가 최근 10분 중앙값 대비 **≥ 70% 감소**
* **OI 급감**(최근 1분 OI 변화가 –Ppct 이상) + **체결폭주** 동시 발생 (청산 캐스케이드 위험)
* **WS 틱 드랍율** 증가(연결 품질 저하)

### 3.2 정상화 감지 (Trade Resume)

* 1초 RV(Z) ≤ 1.5 **AND** 스프레드 ≤ 1.3× 중앙값
* 상위 5레벨 누적 깊이 회복 ≥ 80%
* OI 변화율 안정화(±Q pct 이내), 펀딩 임박 아님

`M, P, Q`는 아래 \*\*“숨겨진 파라미터 팩”\*\*에서 기본값 제시.

---

## 4) 전략 팩(3종)과 진입·청산 로직

> **핵심**: 레짐/유니버스별로 **가장 유리한 미세 엣지 전략**만 활성화. 세 전략은 상호 베타를 낮게 설계.

### 4.1 MIS (Momentum Ignition Scalper) — **미세 돌파 추종**

* **진입(롱)**:

  * EMA(3) > EMA(9), ADX(7) ≥ 13
  * 직전 3분 고점 상향 돌파 **AND** 오더북 **순매수 불균형(OBI) ≥ 0.60** (최근 1.5초 누적)
  * 스프레드 ≤ 기준치(메이커 진입 우선, 실패시 테이커)
* **진입(숏)**: 위의 반대 신호
* **청산**:

  * 1차: **엔트리에서 +0.10%** 절반 익절(트레일링 0.08%)
  * 2차: **VWAP 터치** 또는 **Keltner 상단/하단** 접촉
  * **시간 손절**: 25–40초 내 추세 가속 없으면 탈출
* **회피**: 펀딩 5분 전후에는 테이커 금지(메이커만) ([Bybit Exchange][6])

### 4.2 VRS (VWAP Reversion Scalper) — **미세 과열 되돌림**

* **진입(롱)**:

  * 가격의 **VWAP 괴리 ≥ +0.35%** & Keltner 위편차, RSI(2) ≤ 4
  * 오더북 **역전 조짐**(최근 800ms 내 반대 방향 순유동성 유입)
* **진입(숏)**: 위의 반대 조건
* **청산**: VWAP 근접 시 전량/부분 청산, 시간 손절 20–30초

### 4.3 LSR (Liquidity Sweep Reversal) — **유동성 스윕 반전**

* **조건**: 1–2초 체결 폭주 + **롱/숏 스탑 스윕형 긴 윅** 발생 & OI 감소(청산 추정)
* **진입**: 스윕 반대 방향으로 VWAP까지 스캘프
* **청산**: +0.12\~0.25% 또는 VWAP 터치, 실패시 시간 손절 15–25초

> 세 전략은 **동시 진입을 금지**. 신호 충돌 시 **레짐 가중치**(추세성/평균회귀성 지표)로 가중 스코어 높은 전략만 실행.

---

## 5) “숨겨진 파라미터 팩” (v1.3 Gumiho: 시작값)

> 아래 값은 **시작점**이자 **레짐·종목별로 다르게 워크포워드 튜닝**해야 한다. 그래도 1분 스캘핑 실전에서 **‘바로 써먹을 수 있는’ 기본값**으로 선별했다.

```
[유니버스]
  topN: 12
  spread_max_mult: 1.5        # 최근10분 중앙값 대비
  depth_drop_pause: 0.70      # 70% 이상 깊이 증발 시 위험
  vwap_dev_for_vrs: 0.0035    # 0.35%

[레짐/이상치]
  crash_z: 4.0
  spread_mult_pause: 3.0
  pause_minutes: 3
  resume_rv_z: 1.5
  resume_spread_mult: 1.3
  resume_depth_recover: 0.80
  oi_drop_pct: 2.0            # 1분 OI -2% 이상 급감

[OBI(Order Book Imbalance)]
  window_ms: 1500
  threshold_mis: 0.60
  min_depth_usd: 15000

[지표]
  ema_fast: 3
  ema_slow: 9
  adx_len: 7
  keltner_len: 20
  keltner_mult: 1.25
  rsi2_low: 4
  rsi2_high: 96

[진입/청산]
  tp1: 0.0010          # +0.10%
  trail_after_tp1: 0.0008
  time_stop_mis: 30-40 # 초, 난수폭 부여
  time_stop_vrs: 20-30
  time_stop_lsr: 15-25

[주문 정책]
  prefer_maker_if_spread_bps<=4  # 스프레드 0.04% 이내 메이커 우선
  maker_post_only: true
  taker_on_strong_score: true
  fallback_ioc: true

[리스크]
  max_leverage: 10
  risk_per_trade: 0.003~0.006   # 0.3~0.6% of equity (시드 100USDT 고려)
  daily_max_loss: 0.02          # 2% 손실 시 일중 중지
  per_symbol_concentration: 0.40 # 동일심볼 익스포저 제한

[펀딩/시간]
  avoid_taker_within_min: 5     # 펀딩 전후 ±5분 테이커 금지
```

---

## 6) 포지션 사이징과 레버리지

* **변동성 기반 사이징**: 엔트리 직전 30–60초 **EWM 표준편차**로 1틱 기대 변동을 추정, 목표 **해당 변동 대비 손절폭**이 `k`틱이면 **위험금액 = equity × risk\_per\_trade**, **수량 = 위험금액 / (k틱 가격가치)**.
* **레버리지 자동 제한**: **MMR/IMR 변화**는 주문 전 **Pre-Check API**로 시뮬 후 제출(신규 v5 엔드포인트). ([Bybit Exchange][11])
* **최대 레버리지 10×** 권장. 급락/이상치 상태에서는 3–5×로 강제 하향.

---

## 7) 수수료·체결·슬리피지 모델링 (백테스트 필수 반영)

* **수수료**: 파라미터화(기본 Taker 0.055%, Maker 0.02%). 계정별 실제 요율로 덮어쓰기. **Innovation Zone/프리마켓은 요율 다름** → 심볼별 수수료 맵핑. ([Bybit][8])
* **슬리피지**: 오더북 L1\~L5 깊이 기반 **충전(fill) 시뮬**. 테이커는 **시장가 호가 스윕**으로 체결가 재현, 메이커는 **큐 포지션/취소율**로 fill 확률 모델.
* **부분체결/미체결**: IOC/FOK, postOnly 거절(reject) 재시도 정책 시뮬.
* **스톱/트레일링**: 마크프라이스 기준 트리거, 체결/피어싱 리스크 반영.
* **펀딩**: 정산 시점 보유 포지션에 펀딩 적용.

---

## 8) 백테스트 설계(실전형)

### 8.1 데이터

* **틱 체결** + **오더북 스냅샷(최소 L5)** + **티커/OI/펀딩**.
* 빈 구간은 **불활성 구간**으로 간주(거래 없음).
* **서버 시간 동기화**는 v5 서버타임 참고. ([Bybit Exchange][12])

### 8.2 엔진 요구사항

* 이벤트 드리븐(틱 & 북 업데이트 순서 보존)
* 매 주문마다 **수수료/슬리피지/부분체결** 재현
* **레짐 스위치** 즉시 반영(진입 차단, 보유 포지션은 규칙에 따라 청산)
* **멀티심볼 동시성** + **리스크 공유 제한**(총 델타·총 엑스포저 캡)
* **워크포워드 튜닝**:

  1. **기간 분할**(예: 60일): Train(20d)→Validate(10d) → Roll → OOS(나머지)
  2. Bayesian/Optuna로 파라미터 탐색(과최적화 방지: 단순화·규칙화 우선)
  3. 각 구간 **수익률/승률/EV/MaxDD/Profit Factor/Sharpe** 보고

### 8.3 성과 지표와 합격선(예시)

* **OOS Profit Factor ≥ 1.25**, **MaxDD ≤ 8%**, **Sharpe(일) ≥ 1.2**
* **체결 품질**: 테이커 평균 슬리피지 ≤ 0.8틱, 메이커 fill율 ≥ 55%
* **전략 간 상관**: 일수익 상관 |ρ| ≤ 0.5 유지

---

## 9) 실행(라이브) 설계

### 9.1 API/WS

* **REST**: 주문/포지션/자산 관리. Place Order v5 사용. ([Bybit Exchange][4])
* **WS**: `public.ticker`, `public.orderbook.<depth>`, 필요시 `trade` 구독. **Args 길이 제한/구독 갯수는 가이드 준수**. ([Bybit Exchange][13])
* **재연결**: 지수 백오프, 시퀀스 넘버 검증, 스냅샷 리싱크.

### 9.2 주문 정책(디테일)

* **메이커 우선**: 스프레드 얕고 OBI 우세 시 **postOnly**로 붙인다(거절 시 가격 한틱 재견적).
* **테이커 전환**: 신호 점수 강함 + 체결확률 낮을 때 **IOC**로 스윕.
* **부분청산**: 2회 이상 분할, 잔량은 트레일 스탑.
* **일손실컷**: 미실현 손익 포함 기준. 하회 시 **당일 종료**.

### 9.3 리스크 가드

* **연속 손실 3회**: 10분 쿨다운
* **평균 체결 레이턴시↑**: 테이커 금지·메이커만
* **펀딩 윈도우**: ±5분 테이커 금지(메이커 진입만 허용). ([Bybit Exchange][6])

---

## 10) 설정 예시 (config.yaml)

```yaml
exchange:
  base_url: https://api.bybit.com
  testnet_url: https://api-testnet.bybit.com
  category: linear   # USDT Perp
  ws_depth: 5
  symbols_refresh_secs: 60

universe:
  topN: 12
  min_turnover_24h_usd: 5_000_000
  max_spread_mult: 1.5
  vwap_dev_for_vrs: 0.0035

regime:
  crash_z: 4.0
  spread_mult_pause: 3.0
  depth_drop_pause: 0.70
  pause_minutes: 3
  resume_rv_z: 1.5
  resume_spread_mult: 1.3
  resume_depth_recover: 0.80
  oi_drop_pct: 2.0

strategy_pack:
  mis: {ema_fast:3, ema_slow:9, adx_len:7, obi_ms:1500, obi_th:0.60}
  vrs: {keltner_len:20, keltner_mult:1.25, rsi2_low:4, rsi2_high:96}
  lsr: {wick_ratio:2.2, oi_drop_pct:1.0}

execution:
  prefer_maker_bps: 4
  post_only: true
  taker_on_strong: true
  fallback_ioc: true
  tp1: 0.0010
  trail_after_tp1: 0.0008
  time_stop_sec: {mis:[30,40], vrs:[20,30], lsr:[15,25]}

risk:
  max_leverage: 10
  risk_per_trade_range: [0.003, 0.006]
  daily_max_loss: 0.02
  per_symbol_concentration: 0.40
```

---

## 11) 의사코드 (핵심 루프)

```python
while True:
    ticks, book, oi, funding = feed.poll()
    universe.update(ticker=ticks, book=book)  # 상위 N 선정
    regime_state = market_state.evaluate(ticks, book, oi)

    if regime_state == "PAUSE":
        executor.cancel_open_orders_all()
        if position.exists():
            risk.manage_in_pause()
        continue

    for sym in universe.topN():
        features = indicators.compute(sym, ticks, book)
        score_mis, score_vrs, score_lsr = strategies.score_all(sym, features, oi, funding)

        chosen = select_best([mis, vrs, lsr], [score_mis, score_vrs, score_lsr])
        if chosen.score < threshold: 
            continue

        side, qty, px = risk.size_and_price(sym, chosen, features)
        order = execution.route(sym, side, qty, px, prefer_maker=True)

        while order.alive():
            fills = execution.check_fills(order)
            if risk.should_time_stop(order, chosen):
                execution.flatten(order)
                break
            if risk.should_trail(order, fills, features):
                execution.move_trailing(order)
        reporting.log_trade_result(order, fills)
```

---

## 12) 100 USDT 시드 전용 가드

* **초기 2일**: `risk_per_trade = 0.003`(0.3%), **테이커 비중 최소화**(메이커 우선).
* **미니멈 오더수량**/틱가치/리스크 제한은 **Instruments Info**에서 실시간 조회 후 계산. 심볼별 규격이 다르다(티커 단위, 최소주문수량 등). ([Bybit Exchange][5])
* **일손실 2% 또는 연속손실 3회** 즉시 중단.
* **5일 롤링 EV** 음수면 파라미터 자동 하향(보수화), 유니버스 축소.

---

## 13) 보고서/모니터링

* **거래 요약**: 일/주/월 단위 손익, PF, 승률, 평균 R, MFE/MAE
* **체결 품질**: 메이커 fill율, 테이커 슬리피지 분포
* **전략별 기여도**: MIS/VRS/LSR 수익 분해, 상관도
* **레짐 타임라인**: Pause/Resume 구간, 원인(스프레드/깊이/OI/틱 Z)

---

## 14) 실전 투입 전 체크리스트 (Acceptance Criteria)

1. **백테스트/페이퍼**에서 최근 90일 OOS: PF≥1.25, MaxDD≤8%
2. **실시간 페이퍼 3일**: 체결 품질 목표 충족(테이커 슬리피지 ≤ 0.8틱, 메이커 fill ≥ 55%)
3. **위험 가드 작동 로그**: 급락 감지→Pause→Resume 정상
4. **심볼 회전**: 유니버스 교체가 손익에 악영향 X
5. **수수료 동적 반영**: 계정 실요율로 자동 업데이트(혁신존 예외 포함) ([Bybit][8])

---

## 15) API·엔드포인트 명세 (구현 참고)

* **Base URLs**: Testnet/Mainnet 명시(위 1.2 참조). ([Bybit Exchange][3])
* **Market**:

  * Get Tickers `/v5/market/tickers` (24h 거래대금/스프레드 필터) ([Bybit Exchange][9])
  * Orderbook `/v5/market/orderbook` (L1\~L50) ([Bybit Exchange][10])
  * Recent Trades `/v5/market/recent-trade` (틱 체결 레코드) ([Bybit Exchange][14])
  * Instruments Info `/v5/market/instruments-info`(심볼 스펙, 페이징 유의) ([Bybit Exchange][5])
  * Funding Rate History `/v5/market/history-fund-rate` (펀딩 주기/이력) ([Bybit Exchange][6])
  * Open Interest `/v5/market/open-interest` (과열도/레짐 보조) ([Bybit Exchange][7])
* **Trade**:

  * Create Order `/v5/order/create` (postOnly/IOC/FOK) ([Bybit Exchange][4])
  * *Pre-Check Order* (IMR/MMR 변화 사전계산) — 체결 전 리스크 확인에 활용. ([Bybit Exchange][11])
* **WebSocket**:

  * `public.ticker`(OI/funding 포함 필드 제공) + `public.orderbook` 구독. ([Bybit Exchange][2])

---

## 16) 코딩 가이드 (Codex용 세부 지시)

1. **언어/패키지**: Python 3.11+, `httpx`(REST, timeout/retry), `websockets` 또는 `aiohttp` WS, `pydantic` 설정 스키마, `numpy/pandas/numba`, `pyyaml`, `sqlite3` 또는 `duckdb`.
2. **서명/인증**: v5 인증 헤더, 타임스탬프는 **서버타임 동기화** 기반. ([Bybit Exchange][12])
3. **내결함성**: WS 재연결/리싱크, 시퀀스/크로스시퀀스 검증, 스냅샷-디프 동기화.
4. **백테스터**:

   * 입력: (틱 체결, 북 L5, 펀딩 타임스탬프, OI, 티커 스냅)
   * 이벤트 시뮬: 주문 제출 → 오더북 충전 → 부분/전량 체결 → 수수료/슬리피지 적용 → 포지션·PnL 업데이트
   * **Latency 모델**: 50–120ms 가우시안(테이커), 메이커는 체결확률 큐모델.
5. **지표**:

   * EMA(3/9), ADX(7), Keltner(20,1.25), VWAP(실시간), RSI(2)
   * **OBI**: `sum(bid_size) - sum(ask_size) / sum(bid+ask)` (최근 1.5s 누적)
6. **전략 스코어**: 각 전략별 0\~100 스코어 산출 → 최댓값 전략만 진입.
7. **리스크**:

   * 포지션 사이징: 변동성 기반(§6)
   * 스탑: 시간스탑 + 가격스탑 + 트레일
   * 일손실컷/연속손실 컷 구현
8. **로그/리포트**: 모든 이벤트를 시간순 로그(주문/체결/신호/레짐변화). `export_report.py`로 HTML 리포트 생성.
9. **설정/파라미터**: `params_gumiho.yaml`로 독립. 워크포워드 시 자동 오버라이드.
10. **테스트**:

* `test_execution_sim.py`에 단위 테스트(부분체결/거절재시도/트레일 이동)
* `test_backtest.py`에 수수료/슬리피지/펀딩 적용 검증

---

## 17) 실전 운영 지침

* **모드 전환**: Paper → Live 전환 전, **1\~3일 실시간 페이퍼**로 체결 품질 확인.
* **키·권한**: API Key는 주문/포지션/잔고 최소 권한. *절대* 하드코딩 금지.
* **릴리즈 정책**: 파라미터 변경은 장중 소형 실험(테이커 금지) → 장마감 반영.
* **모니터링**: 레짐 Pause 잦아지면 유니버스 스프레드/깊이 조건 상향.
* **컴플라이언스**: 각 지역 규정 준수, 파생상품 위험 고지.

---

## 18) 현실 체크(중요)

* \*\*승률 80%+\*\*는 **특정 레짐·종목·시간대**에서만 유효한 국소 엣지다. 이 설계는 **그 구간만 정교히 취사선택**해 EV(기대값)를 끌어올린다.
* 수익 목표(일 +1%)는 **벤치마크**일 뿐. 핵심은 **손실 억제와 체결 품질**이다.
* **백테스트 성과**가 좋더라도 라이브에서는 마켓 마이크로구조 차이가 존재한다. 반드시 **슬리피지·거절·부분체결**을 보수적으로 가정하라.

---

### 마무리

위 명세를 그대로 Codex에 던지면, **데이터 피드 → 레짐 판별 → 전략 팩 → 리스크·체결 → 실전형 백테스터**까지 한 번에 구현이 가능하다.
추가로, 다음 항목은 코딩 중 참고하라:

* **v5 소개/카테고리**: 레이어 정합 확인. ([Bybit Exchange][1])
* **Base URL/키 발급/테스트넷**: 통합 가이드. ([Bybit Exchange][3])
* **티커/24h 거래대금/스프레드 필드**: 유니버스 필터. ([Bybit Exchange][9])
* **오더북/WS 구독 한계**: 구독 정책·Args 제한. ([Bybit Exchange][13])
* **펀딩 주기/이력**: 이벤트 회피/반영. ([Bybit Exchange][6])
* **수수료**: 계정별 실요율 반영(파라미터화). ([Bybit][8])
* **OI**: 과열/디레버리징 감지. ([Bybit Exchange][7])
* **주문 생성**: v5 order/create. ([Bybit Exchange][4])

원하면, 위 `params_gumiho.yaml`을 네 계정/선호 심볼에 맞춰 \*\*맞춤 커브(유니버스·레짐·전략 가중)\*\*로 더 날카롭게 깎아줄게.

[1]: https://bybit-exchange.github.io/docs/v5/intro?utm_source=chatgpt.com "Introduction | Bybit API Documentation - GitHub Pages"
[2]: https://bybit-exchange.github.io/docs/v5/websocket/public/ticker?utm_source=chatgpt.com "Ticker | Bybit API Documentation - GitHub Pages"
[3]: https://bybit-exchange.github.io/docs/v5/guide?utm_source=chatgpt.com "Integration Guidance | Bybit API Documentation - GitHub Pages"
[4]: https://bybit-exchange.github.io/docs/v5/order/create-order?utm_source=chatgpt.com "Place Order | Bybit API Documentation - GitHub Pages"
[5]: https://bybit-exchange.github.io/docs/v5/market/instrument?utm_source=chatgpt.com "Get Instruments Info | Bybit API Documentation - GitHub Pages"
[6]: https://bybit-exchange.github.io/docs/v5/market/history-fund-rate?utm_source=chatgpt.com "Get Funding Rate History | Bybit API Documentation"
[7]: https://bybit-exchange.github.io/docs/v5/market/open-interest?utm_source=chatgpt.com "Get Open Interest | Bybit API Documentation - GitHub Pages"
[8]: https://www.bybit.com/en/help-center/article/Bybit-Fees-You-Need-to-Know?utm_source=chatgpt.com "Bybit's Fees That You Need to Know"
[9]: https://bybit-exchange.github.io/docs/v5/market/tickers?utm_source=chatgpt.com "Get Tickers | Bybit API Documentation - GitHub Pages"
[10]: https://bybit-exchange.github.io/docs/v5/market/orderbook?utm_source=chatgpt.com "Get Orderbook | Bybit API Documentation - GitHub Pages"
[11]: https://bybit-exchange.github.io/docs/changelog/v5?utm_source=chatgpt.com "V5 | Bybit API Documentation - GitHub Pages"
[12]: https://bybit-exchange.github.io/docs/api-explorer/v5/market/time?utm_source=chatgpt.com "Get Bybit Server Time | Bybit API Documentation"
[13]: https://bybit-exchange.github.io/docs/v5/ws/connect?utm_source=chatgpt.com "Connect | Bybit API Documentation - GitHub Pages"
[14]: https://bybit-exchange.github.io/docs/v5/market/recent-trade?utm_source=chatgpt.com "Get Recent Public Trades | Bybit API Documentation"



## A. Agent Checklist (실행 우선 순위)
1) 스캐폴드 생성 → 2) 더미 백테스트(run_paper.py) 가동 → 3) 테스트/CI 그린 → 4) PR 생성
모든 파일은 레포 상대경로/완전코드로 제시.

## B. Repository Conventions
- Python 3.11 고정, ruff/pytest 사용, line-length 100
- data/stubs/ 에 더미 CSV/JSON 생성 (틱/오더북 L5/펀딩/OI 최소 구조)
- 환경변수 이름 규약(라이브에서만 사용): BYBIT_API_KEY, BYBIT_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

## C. CI 상세
- .github/workflows/ci.yml
  - on: [push, pull_request]
  - steps: setup-python@v5 → pip install -r requirements.txt → ruff check → pytest -q
  - artifacts: html_report/**, logs/**
- 시크릿 없이도 CI는 그린이어야 한다(테스트는 더미 데이터 기반).

## D. Deliverables (PR 본문 체크리스트)
- [ ] 프로젝트 구조/설치방법/실행/테스트/리포트 README 반영
- [ ] run_paper.py 2분 내 실행/리포트 산출
- [ ] tests/* 통과, CI green
- [ ] 이후 작업 TODO (실 WS/REST, 레짐 실데이터 연결, Walk-forward 튜닝)
