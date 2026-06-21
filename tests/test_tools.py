"""tools 계층 테스트.

네트워크 호출(yfinance/requests)은 모킹해 외부 의존성 없이 검증한다.
실행: pytest
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from tools.stock_data import get_recent_move
from tools.news import get_recent_news


def _fake_history() -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "Open": [100, 102, 101, 105, 110],
            "High": [103, 104, 106, 108, 112],
            "Low": [99, 100, 100, 104, 109],
            "Close": [102, 101, 105, 107, 110],
            "Volume": [1_000, 1_200, 900, 1_500, 2_000],
        },
        index=idx,
    )


@patch("tools.stock_data.yf.Ticker")
def test_get_recent_move_computes_pct_change(mock_ticker):
    mock_ticker.return_value.history.return_value = _fake_history()

    result = get_recent_move("TEST", lookback_days=5)

    assert result["ticker"] == "TEST"
    assert result["start_close"] == 102.0
    assert result["end_close"] == 110.0
    # (110 - 102) / 102 * 100 ≈ 7.84%
    assert result["pct_change"] == 7.84
    assert result["avg_volume"] == 1320


@patch("tools.stock_data.yf.Ticker")
def test_get_recent_move_handles_empty(mock_ticker):
    mock_ticker.return_value.history.return_value = pd.DataFrame()

    result = get_recent_move("EMPTY")

    assert result["error"] == "no_data"


@patch.dict("os.environ", {}, clear=True)
@patch("tools.news.yf.Ticker")
def test_get_recent_news_falls_back_to_yfinance(mock_ticker):
    mock_ticker.return_value.news = [
        {"title": "Big news", "publisher": "Reuters", "providerPublishTime": 1, "link": "http://x"}
    ]

    result = get_recent_news("AAPL", limit=5)

    assert result["source"] == "yfinance"
    assert result["articles"][0]["title"] == "Big news"
