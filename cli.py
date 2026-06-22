#!/usr/bin/env python3
"""주가 변동 원인 분석 CLI.

크롬 등에서 선택한 티커를 단축키로 넘겨 빠르게 분석하기 위한 진입점.

사용법:
    python cli.py TSLA
    echo "TSLA" | python cli.py
    python cli.py TSLA --notify      # 한 줄 요약 알림
    python cli.py TSLA --popup       # 토스 스타일 HTML 카드 팝업

기존 agents/analysis_agent.py 를 그대로 재사용한다.
"""

from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
import tempfile

from dotenv import load_dotenv

# 가격 방향별 색상 (한국식: 상승=빨강, 하락=파랑, 보합=회색).
DIRECTION_COLOR = {"up": "#ff5b5b", "down": "#4d8dff", "flat": "#9aa0a6"}
BULLET_ICON = {"price": "📊", "news": "📰"}

# frameless 팝업 창 크기/여백. 카드(약 400px + body 패딩)에 맞춘다.
POPUP_WIN_W = 440
POPUP_WIN_H = 680
POPUP_MARGIN = 40
POPUP_BG = "#0b0b0c"  # body 배경과 동일 (흰 테두리 방지)


def read_ticker(arg: str | None) -> str:
    """인자 또는 stdin 에서 티커를 추출한다 (공백/줄바꿈 제거, 대문자)."""
    raw = arg if arg is not None else sys.stdin.read()
    token = raw.strip().split()[0] if raw.strip() else ""
    return token.upper()


def summary_line(text: str, limit: int = 120) -> str:
    """분석 텍스트에서 알림에 쓸 한 줄 요약을 뽑는다 (첫 비어있지 않은 줄)."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s if len(s) <= limit else s[: limit - 1] + "…"
    return "분석 완료"


def notify_macos(title: str, message: str) -> None:
    """macOS 알림 센터에 한 줄 요약 알림을 띄운다. macOS 가 아니면 조용히 무시.

    문자열을 AppleScript 소스에 직접 끼워넣지 않고 argv 로 전달해
    따옴표·한글·특수문자 이스케이프 문제(-2741)를 원천 차단한다.
    """
    if sys.platform != "darwin":
        return
    body = summary_line(message)
    script = (
        "on run argv\n"
        "    display notification (item 1 of argv) with title (item 2 of argv)\n"
        "end run"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script, body, title], check=False, timeout=10
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 본 분석을 막지 않도록
        pass


# ── HTML 팝업 카드 (토스 증권 "왜 움직였나" 카드 스타일) ────────────────
POPUP_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TICKER__ — why it moved</title>
<style>
  :root { color-scheme: dark; }
  html, body { margin: 0; height: 100%; background: #0b0b0c; }
  body {
    display: flex; align-items: center; justify-content: center; padding: 16px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, "Apple SD Gothic Neo", sans-serif;
  }
  .card {
    position: relative; width: 400px; max-width: 92vw; box-sizing: border-box;
    background: #1c1c1e; color: #f5f5f7; border-radius: 20px;
    padding: 26px 22px 18px; box-shadow: 0 24px 60px rgba(0, 0, 0, .55);
  }
  .close {
    position: absolute; top: 14px; right: 14px; width: 28px; height: 28px;
    border: none; border-radius: 50%; background: #2c2c2e; color: #aeaeb2;
    font-size: 17px; line-height: 28px; text-align: center; cursor: pointer;
  }
  .close:hover { background: #3a3a3c; color: #fff; }
  .headline { font-size: 19px; font-weight: 700; line-height: 1.35; margin: 2px 30px 16px 0; }
  .price { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
  .ticker { font-size: 24px; font-weight: 800; letter-spacing: .4px; }
  .pct { font-size: 24px; font-weight: 800; color: __COLOR__; }
  .meta { font-size: 12px; color: #8e8e93; margin-bottom: 20px; }
  .why { font-size: 13px; font-weight: 700; color: #c7c7cc; margin: 0 0 10px; }
  ul { list-style: none; margin: 0 0 18px; padding: 0; }
  li {
    display: flex; gap: 10px; align-items: flex-start; font-size: 14px;
    line-height: 1.5; padding: 6px 0; color: #e5e5ea;
  }
  li .ic { flex: 0 0 auto; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .chip {
    background: #2c2c2e; color: #c7c7cc; font-size: 12px; font-weight: 600;
    padding: 6px 12px; border-radius: 999px;
  }
  .foot { font-size: 11px; color: #636366; margin: 0; }
</style>
</head>
<body>
  <div class="card">
    <button class="close" onclick="closeCard()" aria-label="Close">&times;</button>
    <div class="headline">__HEADLINE__</div>
    <div class="price"><span class="ticker">__TICKER__</span><span class="pct">__PCT__</span></div>
    <div class="meta">__META__</div>
    <div class="why">Why did it move?</div>
    <ul>__BULLETS__</ul>
    <div class="chips">__CHIPS__</div>
    <p class="foot">Not investment advice.</p>
  </div>
  <script>
    // X 버튼: pywebview 창이면 Python 닫기 훅을, 아니면(브라우저 폴백) window.close().
    function closeCard() {
      try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.close) {
          window.pywebview.api.close();
          return;
        }
      } catch (e) {}
      window.close();
    }
    try { window.resizeTo(440, 660); } catch (e) {}
  </script>
</body>
</html>"""


def _format_pct(value, direction: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    sign = "+" if v > 0 else ""  # 음수는 자체 부호 포함
    return f"{sign}{v:.1f}%"


def _meta_line(data: dict) -> str:
    bits = []
    n = data.get("sources_count")
    if isinstance(n, int) and n > 0:
        bits.append(f"Based on {n} news source" + ("s" if n != 1 else ""))
    window = str(data.get("price_window") or "").strip()
    if window:
        bits.append(f"price data {window}")
    return " · ".join(bits)


def render_popup_html(data: dict) -> str:
    """구조화된 분석 dict 를 토스 스타일 HTML 카드 문자열로 렌더링한다."""
    direction = str(data.get("direction") or "flat").lower()
    color = DIRECTION_COLOR.get(direction, DIRECTION_COLOR["flat"])

    bullets = data.get("bullets") or []
    if bullets:
        rows = "".join(
            '<li><span class="ic">{ic}</span><span>{txt}</span></li>'.format(
                ic=BULLET_ICON.get(str(b.get("type")), "•"),
                txt=html.escape(str(b.get("text", ""))),
            )
            for b in bullets
        )
    else:
        rows = '<li><span class="ic">•</span><span>No detail available.</span></li>'

    chips = "".join(
        f'<span class="chip">{html.escape(str(t))}</span>'
        for t in (data.get("tags") or [])
        if str(t).strip()
    )

    replacements = {
        "__TICKER__": html.escape(str(data.get("ticker", ""))),
        "__HEADLINE__": html.escape(str(data.get("headline", "")) or "Why it moved"),
        "__PCT__": html.escape(_format_pct(data.get("pct_change"), direction)),
        "__COLOR__": color,
        "__META__": html.escape(_meta_line(data)),
        "__BULLETS__": rows,
        "__CHIPS__": chips,
    }
    out = POPUP_HTML_TEMPLATE
    for token, value in replacements.items():
        out = out.replace(token, value)
    return out


def write_popup_html(data: dict) -> str:
    """HTML 카드를 임시 .html 파일로 쓰고 경로를 반환한다."""
    ticker = "".join(c for c in str(data.get("ticker", "")) if c.isalnum()) or "stock"
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=f"stockcard_{ticker}_",
        suffix=".html",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(render_popup_html(data))
        return f.name


def open_popup(path: str) -> None:
    """생성된 HTML 파일을 브라우저로 연다 (pywebview 폴백 경로)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False, timeout=10)
        else:
            import webbrowser

            webbrowser.open("file://" + os.path.abspath(path))
    except Exception:  # noqa: BLE001 - 팝업 열기 실패가 본 분석을 막지 않도록
        pass


def _screen_width(default: int = 1440) -> int:
    """주 화면 너비(px). 실패하면 default."""
    if sys.platform != "darwin":
        return default
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True, text=True, timeout=5,
        )
        parts = [p.strip() for p in out.stdout.strip().split(",")]
        if len(parts) == 4 and parts[2].isdigit():
            return int(parts[2])
    except Exception:  # noqa: BLE001
        pass
    return default


class _PopupApi:
    """JS -> Python 닫기 훅. HTML 의 X 버튼이 window.pywebview.api.close() 를 호출."""

    def __init__(self) -> None:
        self.window = None

    def close(self) -> None:
        if self.window is not None:
            self.window.destroy()


def show_popup_window(html_str: str, title: str) -> bool:
    """frameless pywebview 창으로 카드를 화면 우상단에 띄운다.

    성공하면 True. pywebview 미설치/임포트 실패나 창 생성 실패 시 False 를
    돌려 호출부가 브라우저 폴백을 쓰도록 한다.

    주의: macOS 에서 webview.start() 는 반드시 메인 스레드에서 호출해야 하므로
    이 함수는 분석/HTTP 가 모두 끝난 뒤 main() 마지막에 호출되어야 한다.
    (start() 는 창이 닫힐 때까지 블로킹된다.)
    """
    try:
        import webview
    except Exception:  # noqa: BLE001 - 미설치/임포트 실패 -> 폴백
        return False

    try:
        x = max(0, _screen_width() - POPUP_WIN_W - POPUP_MARGIN)  # 우측에 붙임
        y = 60
        api = _PopupApi()
        window = webview.create_window(
            title,
            html=html_str,
            js_api=api,
            frameless=True,
            easy_drag=True,
            width=POPUP_WIN_W,
            height=POPUP_WIN_H,
            x=x,
            y=y,
            on_top=True,
            background_color=POPUP_BG,
        )
        api.window = window
        webview.start()  # 창이 닫힐 때까지 블로킹 (메인 스레드)
        return True
    except Exception:  # noqa: BLE001 - 창 생성/표시 실패 -> 폴백
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="주가 변동 원인을 분석합니다 (투자 권유 아님)."
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help="종목 코드 (예: TSLA). 생략 시 stdin 에서 읽습니다.",
    )
    parser.add_argument(
        "-q",
        "--question",
        help="티커에 대한 추가 질문 (선택).",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="macOS 알림(display notification)으로 한 줄 요약을 표시합니다.",
    )
    parser.add_argument(
        "--popup",
        action="store_true",
        help="토스 스타일 카드를 frameless 플로팅 창으로 띄웁니다 (pywebview).",
    )
    args = parser.parse_args()

    load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "❌ ANTHROPIC_API_KEY 가 설정되지 않았습니다.\n"
            "   .env 파일에 키를 넣어주세요:  ANTHROPIC_API_KEY=sk-ant-...\n"
            "   (.env.example 을 복사해서 사용하세요)",
            file=sys.stderr,
        )
        return 1

    ticker = read_ticker(args.ticker)
    if not ticker:
        print("❌ 티커가 비어 있습니다. 예) python cli.py TSLA", file=sys.stderr)
        return 1

    # agents 모듈은 키 확인 이후에 import (import 시점의 부작용 회피).
    from agents import StockInsightAgent

    print(f"📊 {ticker} 분석 중...", file=sys.stderr)
    try:
        data = StockInsightAgent().analyze_structured(ticker, args.question)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 친절한 메시지로 종료
        print(f"❌ 분석 중 오류가 발생했습니다: {exc}", file=sys.stderr)
        return 1

    # 전체 분석은 지금처럼 stdout 에 그대로 출력.
    print(f"\n=== {ticker} 변동 원인 분석 ===\n")
    print(data.get("full_analysis", ""))

    # --notify 와 --popup 은 독립적으로 동작.
    if args.notify:
        body = data.get("headline") or summary_line(data.get("full_analysis", ""))
        notify_macos(f"{ticker} 분석 완료", body)
    if args.popup:
        # frameless pywebview 창을 우선 시도하고, 실패하면 브라우저로 폴백.
        # (webview.start() 는 메인 스레드에서 블로킹되므로 가장 마지막에 호출)
        if not show_popup_window(render_popup_html(data), f"{ticker} — why it moved"):
            path = write_popup_html(data)
            print(f"🪟 팝업(브라우저 폴백): {path}", file=sys.stderr)
            open_popup(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
