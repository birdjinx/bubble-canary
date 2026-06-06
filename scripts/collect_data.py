"""
bubble_canary 데이터 수집기
수집 지표:
  - VIX          : Yahoo Finance (^VIX)
  - HY OAS       : FRED BAMLH0A0HYM2 (basis points)
  - ON RRP       : FRED RRPONTSYD (Billions → T$)
  - TGA          : FRED WTREGEN (Millions → T$)
  - Fed BS       : FRED WALCL (Millions → T$)
  - 10Y-2Y       : FRED T10Y2Y (% → bp)
  - DXY          : Yahoo Finance (DX-Y.NYB)
  - Nasdaq Top7  : Yahoo Finance (시가총액 비율 계산)
  - S&P 500 RSI  : Yahoo Finance ^GSPC RSI(14)
  - Fed Gap      : FRED DGS2 - FEDFUNDS (정책 기대 갭)
"""

import os
import json
import numpy as np
from datetime import datetime, timedelta

import yfinance as yf
from fredapi import Fred

# ──────────────────────────────────────────
# FRED 초기화
# ──────────────────────────────────────────
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
fred = Fred(api_key=FRED_API_KEY) if FRED_API_KEY else None

START = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")


def get_fred(series_id, divisor=1.0, multiplier=1.0, decimals=3):
    """FRED 시리즈 최신값 반환 (단위 변환 포함)"""
    if not fred:
        print(f"  [{series_id}] FRED API key 없음")
        return None
    try:
        s = fred.get_series(series_id, observation_start=START).dropna()
        if s.empty:
            return None
        val = float(s.iloc[-1]) / divisor * multiplier
        result = round(val, decimals)
        print(f"  [{series_id}] {result}")
        return result
    except Exception as e:
        print(f"  [{series_id}] 오류: {e}")
        return None


def get_yahoo(ticker, decimals=2):
    """Yahoo Finance 최신 종가 반환"""
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty:
            return None
        val = round(float(hist["Close"].dropna().iloc[-1]), decimals)
        print(f"  [{ticker}] {val}")
        return val
    except Exception as e:
        print(f"  [{ticker}] 오류: {e}")
        return None


def calculate_rsi(prices, period=14):
    """RSI(14) Wilder 방식 계산"""
    prices = np.array(prices, dtype=float)
    if len(prices) < period + 2:
        return None
    deltas = np.diff(prices)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs  = avg_gain / avg_loss
    rsi = round(100 - (100 / (1 + rs)), 1)
    print(f"  [S&P RSI] {rsi}")
    return rsi


def get_sp500_rsi():
    """S&P 500 RSI(14) + 200일 이동평균 대비 거리(%) 수집"""
    try:
        hist = yf.Ticker("^GSPC").history(period="1y")
        if hist.empty or len(hist) < 20:
            print("  [S&P500] 데이터 부족")
            return None, None
        closes = hist["Close"].dropna().tolist()

        rsi = calculate_rsi(closes)

        # 200일 MA 대비 거리 (데이터가 200개 이상일 때)
        if len(closes) >= 200:
            ma200    = float(np.mean(closes[-200:]))
            ma_dist  = round((closes[-1] - ma200) / ma200 * 100, 1)
        else:
            ma_dist  = round((closes[-1] - float(np.mean(closes))) / float(np.mean(closes)) * 100, 1)

        print(f"  [S&P 200MA 거리] {ma_dist}%")
        return rsi, ma_dist
    except Exception as e:
        print(f"  [S&P500] 오류: {e}")
        return None, None


def get_fed_gap():
    """
    Fed Policy Gap = 2년물 국채금리 - Fed Funds Rate
    양수(+) : 시장이 추가 인상 기대 → 금리 충격 리스크
    음수(-) : 시장이 인하 기대 → 경기 둔화/침체 시그널
    """
    try:
        fed_funds = get_fred("FEDFUNDS", decimals=2)  # 실효 Fed Funds Rate
        t2y       = get_fred("DGS2",     decimals=2)  # 2년물 국채 수익률
        if fed_funds is None or t2y is None:
            return None, None
        gap = round(t2y - fed_funds, 2)
        print(f"  [Fed Gap] 2Y={t2y}% - FEDFUNDS={fed_funds}% = {gap}%")
        return gap, fed_funds
    except Exception as e:
        print(f"  [Fed Gap] 오류: {e}")
        return None, None



def get_nasdaq_concentration():
    """
    나스닥 100 상위 7개 종목의 시가총액 비중 계산
    QQQ ETF의 totalAssets(AUM)을 나스닥100 전체 시총 근사치로 사용
    """
    TOP7 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
    try:
        top7_cap = 0.0
        for t in TOP7:
            cap = yf.Ticker(t).info.get("marketCap", 0) or 0
            top7_cap += cap

        # QQQ AUM: 나스닥100 전체 시총의 약 1/300 수준
        # → 나스닥100 시총 직접 추정: 구성종목 상위20개 시총 합 / 0.6 (상위20개가 약 60%)
        TOP20 = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
                 "AVGO","COST","NFLX","AMD","ADBE","QCOM","INTC",
                 "INTU","AMAT","MU","LRCX","KLAC","PANW"]
        top20_cap = sum(
            (yf.Ticker(t).info.get("marketCap", 0) or 0) for t in TOP20
        )
        if top20_cap == 0:
            return None

        # 나스닥100 전체 시총 추정 (상위 20개가 약 60% 차지)
        ndx_total_est = top20_cap / 0.60

        pct = round(top7_cap / ndx_total_est * 100, 1)
        print(f"  [Nasdaq Conc] top7={top7_cap/1e12:.1f}T, ndx_est={ndx_total_est/1e12:.1f}T → {pct}%")

        # 비현실적 값 방지 (0~100% 범위)
        if pct <= 0 or pct > 100:
            return None
        return pct
    except Exception as e:
        print(f"  [Nasdaq Conc] 오류: {e}")
        return None


# ──────────────────────────────────────────
# 메인 수집
# ──────────────────────────────────────────
def collect():
    print(f"\n🔍 데이터 수집 시작: {datetime.now().isoformat()}\n")

    # S&P RSI + 200MA (한 번에 수집)
    sp500_rsi, sp500_ma200_dist = get_sp500_rsi()
    # Fed Gap (한 번에 수집)
    fed_gap, fed_funds_rate = get_fed_gap()

    data = {
        # VIX: 변동성 지수
        "vix": get_yahoo("^VIX"),

        # HY OAS: FRED는 % 단위 → ×100 해서 bp로 변환
        "hy_oas": get_fred("BAMLH0A0HYM2", multiplier=100, decimals=1),

        # ON RRP: 연준 역레포 (Billions → Trillions)
        "on_rrp": get_fred("RRPONTSYD", divisor=1_000),

        # TGA: 재무부 일반계정 (Millions → Trillions)
        "tga": get_fred("WTREGEN", divisor=1_000_000),

        # Fed Balance Sheet (Millions → Trillions)
        "fed_balance_sheet": get_fred("WALCL", divisor=1_000_000),

        # 10Y-2Y Yield Curve (% → basis points)
        "yield_curve_10y2y": get_fred("T10Y2Y", multiplier=100, decimals=1),

        # DXY: 달러 인덱스
        "dxy": get_yahoo("DX-Y.NYB"),

        # Nasdaq 상위 7개 집중도 (%)
        "nasdaq_concentration": get_nasdaq_concentration(),

        # S&P 500 RSI(14)
        "sp500_rsi": sp500_rsi,

        # S&P 500 200일 MA 대비 거리 (%)
        "sp500_ma200_dist": sp500_ma200_dist,

        # Fed Policy Gap: 2Y Treasury - Fed Funds Rate (%)
        "fed_gap": fed_gap,

        # 현재 Fed Funds Rate (%)
        "fed_funds_rate": fed_funds_rate,

        # 메타
        "updated_at": datetime.now().isoformat(),
        "data_source": "FRED + Yahoo Finance",
    }

    # 수집 결과 요약
    success = sum(1 for v in data.values() if isinstance(v, (int, float)))
    total = 12
    print(f"\n✅ 수집 완료: {success}/{total} 지표")

    # 저장
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"📁 docs/data.json 저장 완료\n")
    print(json.dumps(data, indent=2))
    return data


if __name__ == "__main__":
    collect()
