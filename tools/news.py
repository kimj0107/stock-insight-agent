"""뉴스 수집 도구 (requests 기반).

가격 변동의 '원인'을 찾기 위해 종목 관련 최신 뉴스 헤드라인을 가져온다.
NEWS_API_KEY 가 없으면 yfinance 가 제공하는 뉴스로 폴백한다.
"""

from __future__ import annotations

import os

import requests
import yfinance as yf

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


def get_recent_news(query: str, limit: int = 8) -> dict:
    """종목/키워드 관련 최신 뉴스 헤드라인을 조회한다.

    Args:
        query: 검색어 (회사명 또는 티커, 예: "Apple" 또는 "AAPL").
        limit: 가져올 기사 수.

    Returns:
        {"query", "source", "articles": [{title, source, published_at, url, summary}, ...]}
    """
    api_key = os.getenv("NEWS_API_KEY")
    if api_key:
        return _fetch_newsapi(query, limit, api_key)
    return _fetch_yfinance_news(query, limit)


def _fetch_newsapi(query: str, limit: int, api_key: str) -> dict:
    resp = requests.get(
        NEWSAPI_ENDPOINT,
        params={
            "q": query,
            "pageSize": limit,
            "sortBy": "publishedAt",
            "language": "en",
            "apiKey": api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    articles = [
        {
            "title": a.get("title"),
            "source": (a.get("source") or {}).get("name"),
            "published_at": a.get("publishedAt"),
            "url": a.get("url"),
            "summary": a.get("description"),
        }
        for a in data.get("articles", [])[:limit]
    ]
    return {"query": query, "source": "newsapi", "articles": articles}


def _fetch_yfinance_news(query: str, limit: int) -> dict:
    items = yf.Ticker(query).news or []
    articles = [
        {
            "title": i.get("title"),
            "source": i.get("publisher"),
            "published_at": i.get("providerPublishTime"),
            "url": i.get("link"),
            "summary": None,
        }
        for i in items[:limit]
    ]
    return {"query": query, "source": "yfinance", "articles": articles}
