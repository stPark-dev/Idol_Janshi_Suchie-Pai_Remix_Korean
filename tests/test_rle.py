import pytest

from remix import rle


def test_word_decode_literal_and_repeat():
    # -2: two literal words, 1: repeat next word 1+2 = 3 times
    stream = bytes.fromhex("fffe 1417 120d 0001 0d0d".replace(" ", ""))
    assert rle.decode(stream, rle.WORD, 10) == bytes.fromhex("1417120d0d0d0d0d0d0d")


def test_byte_decode_literal_and_repeat():
    # 0: repeat 00 twice, -2: two literals, 3: repeat 00 five times
    stream = bytes.fromhex("0000fe02580300")
    assert rle.decode(stream, rle.BYTE, 9) == bytes.fromhex("000002580000000000")


def test_decode_rejects_short_stream():
    with pytest.raises(rle.RleError):
        rle.decode(bytes.fromhex("fe02"), rle.BYTE, 2)


def test_decode_rejects_overrun():
    # run of 5 bytes but only 3 requested
    with pytest.raises(rle.RleError):
        rle.decode(bytes.fromhex("0300"), rle.BYTE, 3)


@pytest.mark.parametrize("unit", [rle.BYTE, rle.WORD])
@pytest.mark.parametrize("data", [
    b"",
    b"\x00\x01",
    bytes(300),
    bytes(range(256)) * 3,
    b"\x05\x05\x07\x07\x07\x07" * 50 + bytes(range(200)),
    bytes([1, 1]) + bytes([2, 3]) * 200 + bytes(1000),
])
def test_round_trip(unit, data):
    assert rle.decode(rle.encode(data, unit), unit, len(data)) == data


@pytest.mark.parametrize("unit", [rle.BYTE, rle.WORD])
def test_encode_respects_control_limits(unit):
    data = bytes(70000 if unit == rle.WORD else 1000) + bytes(range(256)) * (300 if unit == rle.WORD else 2)
    stream = rle.encode(data, unit)
    p = 0
    lo, hi = (-128, 127) if unit == rle.BYTE else (-32768, 32767)
    while p < len(stream):
        n = int.from_bytes(stream[p:p + unit], "big", signed=True)
        assert lo <= n <= hi
        p += unit
        p += -n * unit if n < 0 else unit
    assert p == len(stream)


def test_encode_rejects_odd_word_data():
    with pytest.raises(rle.RleError):
        rle.encode(b"\x00\x01\x02", rle.WORD)


def test_encode_not_larger_than_literal_bound():
    data = bytes(range(256)) * 4
    # worst case: one control unit per 128 literal bytes
    assert len(rle.encode(data, rle.BYTE)) <= len(data) + (len(data) + 127) // 128


@pytest.mark.parametrize("unit", [rle.BYTE, rle.WORD])
def test_optimal_encoder_round_trips_and_is_not_larger(unit):
    import random
    rng = random.Random(5)
    for _ in range(20):
        parts = []
        for _ in range(rng.randint(1, 40)):
            if rng.random() < 0.5:
                parts.append(bytes([rng.randrange(4)]) * (rng.randint(1, 300) * unit))
            else:
                parts.append(bytes(rng.randrange(256) for _ in range(rng.randint(1, 50) * unit)))
        data = b"".join(parts)
        best = rle.encode_optimal(data, unit)
        assert rle.decode(best, unit, len(data)) == data
        assert len(best) <= len(rle.encode(data, unit))


def test_optimal_encoder_prefers_two_runs_inside_literals_only_when_cheaper():
    # "AABAA" byte mode: literal 5 (6 bytes) beats run+lit+run (2+2+2 = 6) or ties; never worse
    data = b"\x01\x01\x02\x01\x01"
    assert len(rle.encode_optimal(data, rle.BYTE)) <= 6
