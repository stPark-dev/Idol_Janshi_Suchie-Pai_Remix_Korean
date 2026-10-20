/* SUB.BIN entry points, loaded at BASE = 0x060F9000 by the stub in the executable "A".

   The stub replaces every call of the file loader 0x0601A6A4(name, dest).  On the first call
   it reads SUB.BIN through the loader itself, purges the cache and jumps to BASE+0x00 with the
   caller's r4/r5/pr intact; later calls jump straight there.  Without SUB.BIN it goes on to
   the loader.

   BASE+0x00  load hook:   file loader 0x0601A6A4(name, dest)
   BASE+0x10  magic "KHSU" (the stub checks it)
   BASE+0x14  vblank hook: the vblank-in handler's tail jump to 0x060ABE48 (SCL frame end,
              which uploads the VDP2 registers from their RAM copies)
   BASE+0x18  play hook:   voice player 0x0603BBBC(name)
   BASE+0x1C  play hook:   its waiting variant 0x0603BD4C(name)
   BASE+0x20  dir hook:    directory changer 0x0601A71A(name)
   BASE+0x24  FAD and size of SUB.BIN and SUBDAT.BIN, written by the build
   The hooks other than the load hook are installed in RAM by SUB.BIN on its first call.
*/
        .section .text.entry, "ax"
        .global _start
_start:
        bra     load_hook
        nop
        .long   0, 0, 0                 /* pad to BASE+0x10 */
        .long   0x4B485355              /* BASE+0x10: magic "KHSU" */
        bra     vblank_hook             /* BASE+0x14 */
        nop
        bra     play_hook               /* BASE+0x18 */
        nop
        bra     play2_hook              /* BASE+0x1C */
        nop
        bra     dir_hook                /* BASE+0x20 */
        nop
        .global files
files:  .long   0, 0, 0, 0              /* BASE+0x24: sub_fad, sub_size, dat_fad, dat_size */

load_hook:
        sts.l   pr, @-r15
        mov.l   r4, @-r15
        mov.l   r5, @-r15
        mov.l   .Lon_load, r0
        jsr     @r0                     /* sub_on_load(name) */
        nop
        mov.l   @r15+, r5
        mov.l   @r15+, r4
        lds.l   @r15+, pr
        mov.l   .Lorig_load, r0
        jmp     @r0                     /* tail call: original loader(name, dest) */
        nop

play_hook:
        sts.l   pr, @-r15
        mov.l   r4, @-r15
        mov.l   .Lon_play, r0
        jsr     @r0                     /* sub_on_play(name) */
        nop
        mov.l   @r15+, r4
        lds.l   @r15+, pr
        mov.l   .Lorig_play, r0
        jmp     @r0                     /* tail call: original voice player(name) */
        nop

play2_hook:
        sts.l   pr, @-r15
        mov.l   r4, @-r15
        mov.l   .Lon_play, r0
        jsr     @r0                     /* sub_on_play(name) */
        nop
        mov.l   @r15+, r4
        lds.l   @r15+, pr
        mov.l   .Lorig_play2, r0
        jmp     @r0                     /* tail call: the waiting variant(name) */
        nop

dir_hook:
        sts.l   pr, @-r15
        mov.l   .Lorig_dir, r0
        jsr     @r0                     /* directory changer(name): reads the new directory */
        nop
        mov.l   r0, @-r15
        mov.l   .Lon_dir, r0
        jsr     @r0                     /* sub_on_dir() */
        nop
        mov.l   @r15+, r0               /* the changer's result */
        lds.l   @r15+, pr
        rts
        nop

vblank_hook:
        sts.l   pr, @-r15
        mov.l   .Lorig_vblank, r0
        jsr     @r0                     /* SCL frame end + VDP2 register upload */
        nop
        mov.l   .Lon_vblank, r0
        jsr     @r0                     /* sub_on_vblank(): our NBG3 fields on top */
        nop
        lds.l   @r15+, pr
        rts
        nop

        .align  2
.Lon_load:      .long   sub_on_load
.Lorig_load:    .long   0x0601A6A4
.Lon_play:      .long   sub_on_play
.Lorig_play:    .long   0x0603BBBC
.Lorig_play2:   .long   0x0603BD4C
.Lorig_dir:     .long   0x0601A71A
.Lon_dir:       .long   sub_on_dir
.Lorig_vblank:  .long   0x060ABE48
.Lon_vblank:    .long   sub_on_vblank
