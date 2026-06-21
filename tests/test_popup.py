"""HTML 팝업 카드 생성 테스트 (API 키 불필요).

대표적인 구조화 데이터로 render/write 를 검증한다. 실제 브라우저는 열지 않는다.
"""

from __future__ import annotations

import os

from cli import render_popup_html, write_popup_html

SAMPLE = {
    "headline": "Pulled down by self-driving regulation concerns",
    "ticker": "TSLA",
    "pct_change": -4.7,
    "direction": "down",
    "sources_count": 5,
    "price_window": "6/12–6/18",
    "bullets": [
        {"type": "price", "text": "Fell 4.7% over the week to about $184."},
        {"type": "news", "text": 'Reuters reported a new "self-driving" safety probe.'},
    ],
    "tags": ["self-driving", "regulation", "valuation concerns"],
    "full_analysis": "📊 Price Move\n- ...\n\n⚠️ Caveats\n- not investment advice",
}


def test_render_contains_all_sections():
    out = render_popup_html(SAMPLE)
    # 1) 헤드라인
    assert "Pulled down by self-driving regulation concerns" in out
    # 2) 티커 + % + 색상 (하락 = 파랑)
    assert "TSLA" in out
    assert "-4.7%" in out
    assert "#4d8dff" in out
    # 3) 메타 라인
    assert "Based on 5 news sources" in out
    assert "price data 6/12–6/18" in out
    # 4) "Why did it move?" 섹션
    assert "Why did it move?" in out
    # 5) 불릿 (price/news 아이콘)
    assert "📊" in out and "📰" in out
    assert "Fell 4.7% over the week" in out
    # 6) 태그 칩
    for tag in ("self-driving", "regulation", "valuation concerns"):
        assert tag in out
    # 푸터 + 닫기 버튼
    assert "Not investment advice." in out
    assert "window.close()" in out
    # 카드는 마크다운 표/헤더가 아니라 HTML
    assert "<table" not in out and "|---" not in out


def test_up_is_red_with_plus_sign():
    out = render_popup_html({**SAMPLE, "direction": "up", "pct_change": 3.2})
    assert "#ff5b5b" in out  # 상승 = 빨강
    assert "+3.2%" in out


def test_html_escaping_prevents_breakage():
    # 따옴표/꺾쇠가 들어가도 안전하게 이스케이프되어야 한다.
    out = render_popup_html(SAMPLE)
    assert "&quot;self-driving&quot;" in out  # 본문의 " 가 이스케이프됨
    assert "<script>alert" not in out  # 주입 위험 없음


def test_write_creates_html_file():
    path = write_popup_html(SAMPLE)
    try:
        assert os.path.exists(path)
        assert path.endswith(".html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert 'class="card"' in content
        assert "TSLA" in content
    finally:
        os.remove(path)
