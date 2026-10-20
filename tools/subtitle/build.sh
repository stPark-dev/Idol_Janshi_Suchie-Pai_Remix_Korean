#!/bin/sh
# Build assets/subtitle/SUB.BIN (code only; the product build appends the index and the file locations) from crt.S + sub.c.
# Needs a big-endian SH cross gcc; Debian/Ubuntu: apt install gcc-sh4-linux-gnu (no -m2 there,
# so we build for SH-4 without FPU and reject every instruction the SH-2 lacks).
# Use gcc 11 (Ubuntu 22.04: 11.4.0): gcc 12.2 (Debian 12) drops the T-bit test before a
# conditional branch in index_ok() (bt.s on a stale T), so the group never loads.
# Windows: run inside WSL. EXTRA=-DLOG builds the diagnostic logger (no subtitles drawn).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$HERE/../../assets/subtitle/SUB.BIN}"
TMP="${TMPDIR:-/tmp}/khsub"
mkdir -p "$TMP"
CC=${CC:-sh4-linux-gnu-gcc}
PFX=${CC%gcc}
FLAGS="-m4-nofpu -mb -Os -ffreestanding -fno-builtin -nostdlib -fno-pic -fno-zero-initialized-in-bss \
       -fno-tree-loop-distribute-patterns -Wall -Wextra -Werror $EXTRA"
case "$EXTRA" in *-DLOG*) FLAGS="$FLAGS -Wno-unused-function -Wno-unused-variable" ;; esac   # the logger leaves the drawing unused
$CC $FLAGS -c "$HERE/crt.S" -o "$TMP/crt.o"
$CC $FLAGS -c "$HERE/sub.c" -o "$TMP/sub.o"
LDFLAGS="-EB -z noexecstack"
${PFX}ld --help | grep -q no-warn-rwx-segments && LDFLAGS="$LDFLAGS --no-warn-rwx-segments"   # binutils >= 2.39
${PFX}ld $LDFLAGS -T "$HERE/sub.ld" "$TMP/crt.o" "$TMP/sub.o" -o "$TMP/sub.elf"
${PFX}objdump -d "$TMP/sub.elf" > "$TMP/sub.lst"
python3 "$HERE/check_sh2.py" "$TMP/sub.lst"
${PFX}objcopy -O binary "$TMP/sub.elf" "$OUT"
${PFX}nm -n "$TMP/sub.elf" | grep -E " (T|t) "
ls -l "$OUT"
