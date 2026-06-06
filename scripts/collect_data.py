"""
bubble_canary 데이터 수집기
수집 지표:
  - VIX        : Yahoo Finance (^VIX)
  - HY OAS     : FRED BAMLH0A0HYM2 (basis points)
  - ON RRP     : FRED RRPONTSYD (Billions → T$)
  - TGA        : FRED WTREGEN (Millions → T$)
  - Fed BS     : FRED WALCL (Millions → T$)
  - 10Y-2Y     : FRED T10Y2Y (% → bp)
  - DXY        : Yahoo Finance (DX-Y.NYB)
  - Nasdaq Top7: Yahoo Finance (시가총액 비율 계산)
"""

import os
import json
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

        # 메타
        "updated_at": datetime.now().isoformat(),
        "data_source": "FRED + Yahoo Finance",
    }

    # 수집 결과 요약
    success = sum(1 for v in data.values() if isinstance(v, (int, float)))
    total = 8
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
