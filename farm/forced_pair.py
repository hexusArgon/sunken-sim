"""Space where some items are always worn and the other slots come from the pool (GPU-ready).

``ForcedPieces`` keeps the six-slot numbering tables of ``farm.space.Space`` over the pool without the
forced items and starts the unranking at ``6 - len(forced)`` free slots with the legendary / orb /
amplifier flags the forced items already take. ``decode`` returns the free items in pool order followed
by the forced items in the given order; the exact OpenCL kernels unrank the same way (class_cl.forced_kernel)
and fold the items in that order, so kernel and Python oracle see the same build.

Used by the catalog for presets ``force:CODE+CODE`` on a top-N pool (farm.catalog.load).
"""

from __future__ import annotations

import math

from farm.space import Piece, Space


class ForcedPieces(Space):
    def __init__(self, pieces: list[Piece], talents, glyphs, *, forced: tuple[str, ...], **kwargs) -> None:
        by_code = {piece.code: piece for piece in pieces}
        missing = [code for code in forced if code not in by_code]
        if missing:
            raise RuntimeError("закреплённых вещей нет в пуле: " + ", ".join(missing))
        if len(set(forced)) != len(forced) or not 1 <= len(forced) <= 5:
            raise RuntimeError(f"закреплённые вещи: {forced}")
        fixed = [by_code[code] for code in forced]
        for piece in fixed:
            if piece.kind == "stack":
                raise RuntimeError(f"{piece.code}: стакающуюся вещь закрепить нельзя")
        legs = sum(piece.kind == "leg" for piece in fixed)
        orbs = sum(piece.kind == "orb" for piece in fixed)
        amps = sum(1 for piece in fixed if piece.amp)
        if legs > 1 or orbs > 1 or amps > 1:
            raise RuntimeError("две легендарки, две сферы или два усилителя среди закреплённых")
        rest = [piece for piece in pieces if piece.code not in forced]
        super().__init__(rest, talents, glyphs, slots=6, **kwargs)
        self.forced = tuple(forced)
        self.free_slots = 6 - len(forced)
        self.start_flags = (1 if legs else 0, 1 if orbs else 0, 1 if amps else 0)
        self.n_free = len(rest)
        leg, orb, amp = self.start_flags
        self.count_without = self._cell(self.dp_without, 0, self.free_slots, leg, orb, amp)
        self.count_with = self._cell(self.dp_with, 0, self.free_slots, leg, orb, amp)
        self.total = self.count_without + self.count_with
        # the kernel tables cover every piece: the pool first (unranked), the forced ones last
        self.pieces = rest + fixed
        self.forced_indices = tuple(range(len(rest), len(rest) + len(fixed)))
        self.glyph_n = math.comb(len(self.glyphs), self.glyph_picks) if self.glyphs else 0

    def _unrank_free(self, table: list[int], rank: int) -> tuple[str, ...]:
        item = 0
        slots = self.free_slots
        leg, orb, amp = self.start_flags
        chosen: list[str] = []
        guard = 0
        while slots > 0:
            guard += 1
            if guard > 100000 or item >= self.n_free:
                raise RuntimeError("сбой нумерации предметов")
            piece = self.pieces[item]
            skip = self._cell(table, item + 1, slots, leg, orb, amp)
            if rank < skip:
                item += 1
                continue
            rank -= skip
            if piece.amp:
                if amp != 0:
                    raise RuntimeError("сбой нумерации усилителя")
                chosen.append(piece.code)
                item += 1
                slots -= 1
                amp = 1
                continue
            if piece.kind == "stack":
                taken = False
                for count in range(1, slots + 1):
                    branch = self._cell(table, item + 1, slots - count, leg, orb, amp)
                    if rank < branch:
                        chosen.extend([piece.code] * count)
                        item += 1
                        slots -= count
                        taken = True
                        break
                    rank -= branch
                if not taken:
                    raise RuntimeError("сбой нумерации стака")
                continue
            if piece.kind == "leg":
                if leg != 0:
                    raise RuntimeError("сбой нумерации легендарки")
                leg = 1
            elif piece.kind == "orb":
                if orb != 0:
                    raise RuntimeError("сбой нумерации сферы")
                orb = 1
            chosen.append(piece.code)
            item += 1
            slots -= 1
        if rank != 0:
            raise RuntimeError("сбой нумерации хвоста")
        return tuple(chosen)

    def decode(self, index: int):
        if index < 0 or index >= self.total:
            raise IndexError(index)
        if index < self.count_without:
            free = self._unrank_free(self.dp_without, index)
        else:
            free = self._unrank_free(self.dp_with, index - self.count_without)
        return free + self.forced, (), ()
