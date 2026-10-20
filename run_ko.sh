#!/bin/sh
# 아이돌 작사 스치파이 Remix 한글판 실행 — Mednafen (창 모드, 소리 켬). 디스크: out/ko/remix_ko.cue
cd "$(dirname "$0")"
exec ./tools/mednafen.sh "${KO_CUE:-out/ko/remix_ko.cue}" "$@"
