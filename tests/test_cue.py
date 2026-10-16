from pathlib import Path

import pytest

from remix import build

SINGLE = '''FILE "remix.bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    INDEX 00 32:46:68
    INDEX 01 32:48:68
'''
REDUMP = '''FILE "Game (Track 1).bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
FILE "Game (Track 2).bin" BINARY
  TRACK 02 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
'''
SUBDIR = '''FILE "bins/x.bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
'''


def test_single_bin_with_audio_points_to_output():
    text, data = build.parse_cue(SINGLE, Path("/src"))
    assert data == Path("/src/remix.bin")
    out = build.rewrite_cue(SINGLE, Path("/src"), "remix_ko.bin")
    assert out.splitlines()[0] == 'FILE "remix_ko.bin" BINARY'
    assert out.count("FILE") == 1 and "TRACK 02 AUDIO" in out


def test_redump_track1_replaced_other_tracks_absolute():
    out = build.rewrite_cue(REDUMP, Path("/src"), "remix_ko.bin")
    files = [l for l in out.splitlines() if l.startswith("FILE")]
    assert files[0] == 'FILE "remix_ko.bin" BINARY'
    assert files[1] == f'FILE "{Path("/src/Game (Track 2).bin").resolve()}" BINARY'


def test_subdirectory_file_is_replaced_not_redirected_to_source():
    out = build.rewrite_cue(SUBDIR, Path("/src"), "remix_ko.bin")
    assert out.splitlines()[0] == 'FILE "remix_ko.bin" BINARY'
    assert "/src/bins/x.bin" not in out


def test_parse_rejects_cue_without_leading_mode1_track():
    with pytest.raises(build.BuildError):
        build.parse_cue('FILE "a.bin" BINARY\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n', Path("/src"))


def test_build_refuses_to_overwrite_source(tmp_path):
    src = tmp_path / "remix_ko.bin"
    src.write_bytes(b"")
    (tmp_path / "remix_ko.cue").write_text(SINGLE.replace("remix.bin", "remix_ko.bin"))
    with pytest.raises(build.BuildError, match="source"):
        build.check_output_paths(tmp_path / "remix_ko.cue", src, tmp_path, "remix_ko")
