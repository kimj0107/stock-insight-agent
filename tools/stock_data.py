"""yfinance 기반 주가 데이터 조회 도구.

에이전트는 여기 정의된 함수를 tool로 호출해 실제 시세를 가져온다.
순수한 데이터 계층 — LLM 호출이나 해석 로직은 포함하지 않는다.
"""

from __future__ import annotations

import yfinance as yf


def get_price_history(ticker: str, period: str = "1mo", interval: str = "1d") -> dict:
    """티커의 과거 시세(OHLCV)를 조회한다.

    Args:
        ticker: 종목 코드 (예: "AAPL", "005930.KS").
        period: 조회 기간 ("1d", "5d", "1mo", "3mo", "6mo", "1y", "ytd", "max").
        interval: 캔들 간격 ("1d", "1h", "5m" 등).

    Returns:
        {"ticker", "period", "interval", "rows": [{date, open, high, low, close, volume}, ...]}
    """
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    rows = [
        {
            "date": idx.isoformat(),
            "open": round(float(r.Open), 4),
            "high": round(float(r.High), 4),
            "low": round(float(r.Low), 4),
            "close": round(float(r.Close), 4),
            "volume": int(r.Volume),
        }
        for idx, r in zip(df.index, df.itertuples())
    ]
    return {"ticker": ticker, "period": period, "interval": interval, "rows": rows}


def get_recent_move(ticker: str, lookback_days: int = 5) -> dict:
    """최근 N 거래일간의 가격 변동률을 요약한다.

    Args:
        ticker: 종목 코드.
        lookback_days: 변동을 계산할 거래일 수.

    Returns:
        {"ticker", "start_date", "end_date", "start_close", "end_close",
         "pct_change", "max_drawdown_pct", "avg_volume"}
    """
    df = yf.Ticker(ticker).history(period=f"{max(lookback_days * 2, 10)}d", interval="1d")
    if df.empty:
        return {"ticker": ticker, "error": "no_data"}

    window = df.tail(lookback_days)
    start_close = float(window["Close"].iloc[0])
    end_close = float(window["Close"].iloc[-1])
    pct_change = (end_close - start_close) / start_close * 100.0

    running_max = window["Close"].cummax()
    drawdown = (window["Close"] - running_max) / running_max
    max_drawdown_pct = float(drawdown.min()) * 100.0

    return {
        "ticker": ticker,
        "start_date": window.index[0].isoformat(),
        "end_date": window.index[-1].isoformat(),
        "start_close": round(start_close, 4),
        "end_close": round(end_close, 4),
        "pct_change": round(pct_change, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "avg_volume": int(window["Volume"].mean()),
    }
