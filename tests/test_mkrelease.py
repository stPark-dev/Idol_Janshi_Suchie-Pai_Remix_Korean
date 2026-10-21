import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import mkrelease  # noqa: E402

CUE = """FILE "remix.bin" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    INDEX 00 00:00:10
    INDEX 01 00:00:12
  TRACK 03 AUDIO
    INDEX 00 00:00:20
    INDEX 01 00:00:21
"""


def test_bps_round_trip_with_changes_and_growth():
    src = bytes(range(256)) * 40
    tgt = bytearray(src)
    tgt[100:110] = b"x" * 10
    tgt[5000] ^= 0xFF
    tgt += b"tail"
    p = mkrelease.bps_create(src, bytes(tgt))
    assert mkrelease.bps_apply(p, src) == bytes(tgt)


def test_bps_rejects_another_source():
    p = mkrelease.bps_create(b"a" * 100, b"b" * 100)
    with pytest.raises(AssertionError):
        mkrelease.bps_apply(p, b"c" * 100)


def test_tracks_split_at_index00_like_redump():
    t = mkrelease.split_tracks(CUE, 30 * 2352)
    assert [(x.number, x.mode, x.start, x.sectors, x.pregap) for x in t] == [
        (1, "MODE1/2352", 0, 10, 0), (2, "AUDIO", 10, 10, 2), (3, "AUDIO", 20, 10, 1)]


def test_redump_cue_reads_korean_track1_and_original_audio():
    t = mkrelease.split_tracks(CUE, 30 * 2352)
    cue = mkrelease.redump_cue(t, "KO", "JP")
    assert cue.splitlines() == [
        'FILE "KO (Track 1).bin" BINARY', "  TRACK 01 MODE1/2352", "    INDEX 01 00:00:00",
        'FILE "JP (Track 2).bin" BINARY', "  TRACK 02 AUDIO", "    INDEX 00 00:00:00", "    INDEX 01 00:00:02",
        'FILE "JP (Track 3).bin" BINARY', "  TRACK 03 AUDIO", "    INDEX 00 00:00:00", "    INDEX 01 00:00:01"]


GOOD = {"distribution": True, "unverified": False, "modes": {"title": "korean", "opening": "korean",
        "graphics": "korean", "subtitles": "korean"}, "screen_checks_pending": [], "subtitle_checks_pending": []}


def test_gate_passes_a_distribution_build():
    assert mkrelease.gate(GOOD, accept_pending=False) == []


def test_gate_refuses_pending_checks_unless_the_owner_accepts_them():
    m = {**GOOD, "distribution": False, "screen_checks_pending": ["credits"], "subtitle_checks_pending": ["sub.winner"]}
    with pytest.raises(SystemExit):
        mkrelease.gate(m, accept_pending=False)
    assert mkrelease.gate(m, accept_pending=True) == ["credits", "sub.winner"]


@pytest.mark.parametrize("change", [{"unverified": True}, {"modes": {**GOOD["modes"], "graphics": "original"}}])
def test_gate_never_accepts_a_development_build(change):
    with pytest.raises(SystemExit):
        mkrelease.gate({**GOOD, "distribution": False, **change}, accept_pending=True)
