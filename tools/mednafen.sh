#!/bin/sh
# run_ko.sh 공용: Mednafen 찾기, 설정 폴더(work/mednafen_play)와 BIOS 준비 후 실행
cd "$(dirname "$0")/.."
CUE="$1"; shift
if [ ! -f "$CUE" ]; then
  echo "디스크 이미지가 없습니다: $CUE (먼저 python3 tools/khpatch.py build --source 원본.cue)" >&2
  exit 1
fi
export MEDNAFEN_HOME="$PWD/work/mednafen_play"
mkdir -p "$MEDNAFEN_HOME/firmware"
if [ ! -f "$MEDNAFEN_HOME/firmware/sega_101.bin" ]; then
  if [ ! -f sega_101.bin ]; then
    echo "Saturn BIOS가 없습니다: 프로젝트 폴더에 sega_101.bin을 두세요" >&2
    exit 1
  fi
  cp sega_101.bin "$MEDNAFEN_HOME/firmware/"
fi
[ -f "$MEDNAFEN_HOME/mednafen.cfg" ] || [ ! -f work/mednafen_home/mednafen.cfg ] || cp work/mednafen_home/mednafen.cfg "$MEDNAFEN_HOME/"
if command -v mednafen >/dev/null 2>&1; then
  MED=mednafen
elif [ -x ../suchie-pai2/work/tools/mednafen/usr/games/mednafen ]; then
  MED=../suchie-pai2/work/tools/mednafen/usr/games/mednafen
  export LD_LIBRARY_PATH="$PWD/../suchie-pai2/work/tools/libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
else
  echo "Mednafen이 없습니다: sudo apt install mednafen" >&2
  exit 1
fi
exec "$MED" -sound 1 -sound.driver sdl -video.fs 0 "$@" "$CUE"
