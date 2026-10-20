OUTPUT_FORMAT("elf32-shbig-linux")
ENTRY(_start)
SECTIONS
{
    . = 0x060F9000;
    .text : { *(.text.entry) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss : { *(.bss .bss.*) *(COMMON) }
    _end = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
ASSERT(_end <= 0x060FB000, "subtitle code overruns its 8 KB (the index follows at BASE+0x2000)")
