#!/usr/bin/env python3
"""아이돌 작사 스치파이 Remix 한글판 빌드.

    python3 tools/khpatch.py build --source "원본.cue" [--out out/ko] [--title original] [--opening original]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remix import build  # noqa: E402
from remix.writeplan import PlanError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="원본 디스크에서 한글판 BIN/CUE 만들기")
    b.add_argument("--source", required=True, type=Path, help="원본 .cue (트랙 1이 FILE 맨 앞에 있는 MODE1/2352)")
    b.add_argument("--out", type=Path, default=Path("out/ko"))
    b.add_argument("--title", choices=("korean", "original"), default="korean", help="타이틀 로고")
    b.add_argument("--opening", choices=("korean", "original"), default="korean", help="오프닝 큰 글자")
    b.add_argument("--select", choices=("korean", "original"), default="korean", help="메뉴·캐릭터 선택·규칙·사운드 테스트 그림 글자")
    b.add_argument("--unverified", action="store_true", help="화면 확인 전 조합도 만들기 (시험용)")
    args = ap.parse_args()
    try:
        m = build.build(args.source, args.out, title=args.title, opening=args.opening, select=args.select,
                        unverified=args.unverified)
    except (build.BuildError, PlanError, ValueError, OSError) as e:
        print(f"빌드 실패: {e}", file=sys.stderr)
        return 1
    print(f"완료: {args.out / m['cue']} (변경 {len(m['changes'])}건, 배포 가능: {m['distribution']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
