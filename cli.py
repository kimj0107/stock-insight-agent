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
import json
import os
import subprocess
import sys

from dotenv import load_dotenv


def read_ticker(arg: str | None) -> str:
    """인자 또는 stdin 에서 티커를 추출한다 (공백/줄바꿈 제거, 대문자)."""
    raw = arg if arg is not None else sys.stdin.read()
    token = raw.strip().split()[0] if raw.strip() else ""
    return token.upper()


def notify_macos(title: str, message: str) -> None:
    """macOS 알림 센터에 알림을 띄운다. macOS 가 아니면 조용히 무시."""
    if sys.platform != "darwin":
        return
    # 알림 본문은 길면 잘리므로 앞부분만, AppleScript 문자열은 json.dumps 로 안전하게 이스케이프.
    body = message.strip().replace("\n", " ")
    if len(body) > 240:
        body = body[:237] + "..."
    script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
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
