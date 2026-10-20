"""Run-length codec used by CX entries (docs/initial-survey.md 2.2).

The stream is a sequence of signed big-endian control units followed by data units. A unit
is one byte (entry kind 0x0000) or one 16-bit word (entry kind 0x0400):
    n < 0   -> copy the next -n units literally
    n >= 0  -> repeat the next unit n + 2 times
The decoder stops when the requested output size is reached. Round trips through the game
were confirmed on screen for both unit sizes (docs/initial-survey.md 3.6, 3.7).
"""

import bisect

BYTE = 1
WORD = 2

MIN_RUN = 3   # a run of 2 costs the same as two literals but would split a literal block


class RleError(ValueError):
    pass


def _limits(unit: int) -> tuple[int, int]:
    if unit not in (BYTE, WORD):
        raise RleError(f"unit must be 1 or 2, not {unit}")
    bits = 8 * unit
    return 1 << (bits - 1), (1 << (bits - 1)) - 1 + 2   # longest literal block, longest run


def decode(stream: bytes, unit: int, size: int) -> bytes:
    _limits(unit)
    out = bytearray()
    p = 0
    while len(out) < size:
        if p + unit > len(stream):
            raise RleError(f"stream ends after {len(out)} of {size} bytes")
        n = int.from_bytes(stream[p:p + unit], "big", signed=True)
        p += unit
        if n < 0:
            chunk = stream[p:p - n * unit]
            if len(chunk) != -n * unit:
                raise RleError("literal block passes the end of the stream")
            out += chunk
            p -= n * unit
        else:
            word = stream[p:p + unit]
            if len(word) != unit:
                raise RleError("repeat unit missing at the end of the stream")
            out += word * (n + 2)
            p += unit
        if len(out) > size:
            raise RleError(f"block passes the requested size ({len(out)} > {size})")
    return bytes(out)


def encode(data: bytes, unit: int) -> bytes:
    max_lit, max_run = _limits(unit)
    if len(data) % unit:
        raise RleError("data is not a whole number of units")
    units = [data[i:i + unit] for i in range(0, len(data), unit)]
    out = bytearray()
    lit: list[bytes] = []

    def flush() -> None:
        while lit:
            chunk = lit[:max_lit]
            del lit[:max_lit]
            out.extend((-len(chunk)).to_bytes(unit, "big", signed=True))
            out.extend(b"".join(chunk))

    i = 0
    while i < len(units):
        j = i
        while j < len(units) and j - i < max_run and units[j] == units[i]:
            j += 1
        if j - i >= MIN_RUN:
            flush()
            out.extend((j - i - 2).to_bytes(unit, "big", signed=True))
            out.extend(units[i])
            i = j
        else:
            lit.append(units[i])
            i += 1
    flush()
    return bytes(out)


def encode_optimal(data: bytes, unit: int, candidates: int = 16) -> bytes:
    """Shortest stream found by dynamic programming over block boundaries.

    A literal block only ends where a run of two or more units starts, at the block length limit,
    or at the end; a run takes its full length or a few units less. Never longer than encode().
    """
    max_lit, max_run = _limits(unit)
    if len(data) % unit:
        raise RleError("data is not a whole number of units")
    units = [data[i:i + unit] for i in range(0, len(data), unit)]
    n = len(units)
    run = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        run[i] = min(run[i + 1] + 1, max_run) if i + 1 < n and units[i] == units[i + 1] else 1
    starts = [i for i in range(n) if run[i] >= 2] + [n]
    INF = float("inf")
    cost = [INF] * (n + 1)
    step = [None] * (n + 1)
    cost[n] = 0
    for i in range(n - 1, -1, -1):
        best, how = INF, None
        r = run[i]
        if r >= 2:
            for ln in {*range(2, min(r, 8) + 1), r, r - 1}:
                if ln >= 2:
                    c = 2 * unit + cost[i + ln]
                    if c < best:
                        best, how = c, ("run", ln)
        k = bisect.bisect_right(starts, i)
        ends = starts[k:k + candidates]
        ends.append(min(i + max_lit, n))
        for j in ends:
            if j - i > max_lit or j <= i:
                continue
            c = unit * (1 + j - i) + cost[j]
            if c < best:
                best, how = c, ("lit", j - i)
        cost[i], step[i] = best, how
    out = bytearray()
    i = 0
    while i < n:
        kind, ln = step[i]
        if kind == "run":
            out += (ln - 2).to_bytes(unit, "big", signed=True) + units[i]
        else:
            out += (-ln).to_bytes(unit, "big", signed=True) + b"".join(units[i:i + ln])
        i += ln
    greedy = encode(data, unit)
    return bytes(out) if len(out) <= len(greedy) else greedy
