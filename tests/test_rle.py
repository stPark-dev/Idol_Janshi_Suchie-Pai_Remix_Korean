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
