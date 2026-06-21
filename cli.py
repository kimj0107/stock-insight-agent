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
import re
import subprocess
import sys

# 팝업에 우선적으로 보여줄 섹션 마커(이모지). 분석 출력의 섹션 헤더와 맞춘다:
#   📊 가격 변동 / 📰 뉴스·촉매 / ⚠️ 주의사항·면책
POPUP_SECTION_KEYWORDS = ("📊", "📰", "⚠️")

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


def popup_excerpt(text: str, limit: int = 1500) -> str:
    """팝업에 보여줄 핵심 발췌를 만든다.

    "핵심 요약" / "뉴스와의 연결" 같은 섹션이 있으면 그 부분을 우선 추출하고,
    없으면 전체 분석을 사용한다. 마지막에 limit(기본 1500자) 이내로 자른다.
    """
    text = text.strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chosen: list[str] = []
    i = 0
    while i < len(paras):
        first_line = paras[i].splitlines()[0]
        if any(kw in first_line for kw in POPUP_SECTION_KEYWORDS):
            chosen.append(paras[i])
            # 헤더만 있는 문단이면 바로 다음(본문) 문단도 함께 포함.
            if len(paras[i]) <= 40 and i + 1 < len(paras):
                chosen.append(paras[i + 1])
                i += 1
        i += 1

    excerpt = "\n\n".join(chosen).strip() if chosen else text
    if len(excerpt) > limit:
        excerpt = excerpt[: limit - 1].rstrip() + "…"
    return excerpt or text[:limit]


def popup_macos(title: str, message: str) -> None:
    """macOS display dialog 팝업으로 분석 발췌를 표시한다 (확인 버튼 하나).

    notify_macos 와 동일하게 텍스트/제목/버튼 라벨을 모두 argv 로 넘겨
    한글·따옴표·줄바꿈이 있어도 osascript 파싱 에러(-2741)가 나지 않게 한다.
    """
    if sys.platform != "darwin":
        return
    body = popup_excerpt(message)
    script = (
        "on run argv\n"
        "    display dialog (item 1 of argv) with title (item 2 of argv) "
        "buttons {(item 3 of argv)} default button (item 3 of argv)\n"
        "end run"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script, body, title, "확인"],
            check=False,
            timeout=300,
        )
    except Exception:  # noqa: BLE001 - 팝업 실패가 본 분석을 막지 않도록
        pass


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
        help="macOS 알림(display notification)으로 한 줄 요약을 표시합니다.",
    )
    parser.add_argument(
        "--popup",
        action="store_true",
        help="macOS 팝업 창(display dialog)으로 핵심 발췌를 표시합니다.",
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

    # --notify 와 --popup 은 독립적으로, 둘 다 켤 수 있다.
    if args.notify:
        notify_macos(f"{ticker} 분석 완료", analysis)
    if args.popup:
        popup_macos(f"{ticker} 분석", analysis)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
