#!/usr/bin/env python3
"""주가 변동 원인 분석 CLI.

크롬 등에서 선택한 티커를 단축키로 넘겨 빠르게 분석하기 위한 진입점.

사용법:
    python cli.py TSLA
    echo "TSLA" | python cli.py
    python cli.py TSLA --notify      # macOS 알림으로도 표시

기존 agents/analysis_agent.py 를 그대로 재사용한다.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv


def read_ticker(arg: str | None) -> str:
    """인자 또는 stdin 에서 티커를 추출한다 (공백/줄바꿈 제거, 대문자)."""
    raw = arg if arg is not None else sys.stdin.read()
    token = raw.strip().split()[0] if raw.strip() else ""
    return token.upper()


def summary_line(text: str, limit: int = 120) -> str:
    """분석 결과에서 알림에 쓸 핵심 한 줄 요약을 뽑는다 (첫 비어있지 않은 줄)."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s if len(s) <= limit else s[: limit - 1] + "…"
    return "분석 완료"


def notify_macos(title: str, message: str) -> None:
    """macOS 알림 센터에 한 줄 요약 알림을 띄운다. macOS 가 아니면 조용히 무시.

    문자열을 AppleScript 소스에 직접 끼워넣지 않고 argv 로 전달한다.
    이렇게 하면 따옴표·한글·특수문자 이스케이프 문제가 원천적으로 사라진다.
    (직접 끼워넣으면 한글이 \\uXXXX 로 바뀌어 osascript 가 파싱에 실패함.)
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
        help="macOS 알림(display notification)으로도 결과를 표시합니다.",
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
        analysis = StockInsightAgent().analyze(ticker, args.question)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 친절한 메시지로 종료
        print(f"❌ 분석 중 오류가 발생했습니다: {exc}", file=sys.stderr)
        return 1

    print(f"\n=== {ticker} 변동 원인 분석 ===\n")
    print(analysis)

    if args.notify:
        notify_macos(f"{ticker} 분석 완료", analysis)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
