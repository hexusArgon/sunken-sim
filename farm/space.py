"""Numbered chunks.

A chunk is one legal six-item loadout. Talents, glyphs and skill points are
not separate numbers: a worker scores them only when the item DPS beats the
greedy floor, the same way extract/run_hp.py does.

Item sets are combinations in rawcode order: one legendary, one orb, a
stacking item may fill several slots, everything else is a single copy.
Sets that include Mind Amplifier are numbered after the sets that do not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Piece:
    code: str
    kind: str
    amp: bool = False
    name: str = ""


class Space:
    def __init__(
        self,
        pieces: list[Piece],
        talents: list[str],
        glyphs: list[str],
        *,
        slots: int = 6,
        picks_without: int = 3,
        picks_with: int = 4,
        glyph_picks: int = 3,
        talent_names: dict[str, str] | None = None,
        glyph_names: dict[str, str] | None = None,
    ) -> None:
        for piece in pieces:
            if piece.kind not in ("leg", "orb", "stack", "one"):
                raise ValueError(piece.kind)
        self.pieces = list(pieces)
        self.talents = list(talents)
        self.glyphs = list(glyphs)
        self.slots = slots
        self.picks_without = picks_without
        self.picks_with = picks_with
        self.glyph_picks = glyph_picks
        self.talent_names = dict(talent_names or {})
        self.glyph_names = dict(glyph_names or {})
        self._span = slots + 1
        self.dp_without = self._counts(False)
        self.dp_with = self._counts(True)
        self.count_without = self._cell(self.dp_without, 0, slots, 0, 0, 0)
        self.count_with = self._cell(self.dp_with, 0, slots, 0, 0, 0)
        self.glyph_n = math.comb(len(glyphs), glyph_picks) if glyphs else 0
        self.total = self.count_without + self.count_with

    def _idx(self, item: int, slots: int, leg: int, orb: int, amp: int) -> int:
        return ((((item * self._span + slots) * 2 + leg) * 2 + orb) * 2 + amp)

    def _cell(self, table: list[int], item: int, slots: int, leg: int, orb: int, amp: int) -> int:
        return table[self._idx(item, slots, leg, orb, amp)]

    def _counts(self, must_amp: bool) -> list[int]:
        pieces = self.pieces
        n = len(pieces)
        table = [0] * ((n + 1) * self._span * 8)
        for leg in (0, 1):
            for orb in (0, 1):
                for amp in (0, 1):
                    ok = amp == 1 if must_amp else amp == 0
                    table[self._idx(n, 0, leg, orb, amp)] = 1 if ok else 0
        for item in range(n - 1, -1, -1):
            piece = pieces[item]
            for slots in range(self.slots + 1):
                for leg in (0, 1):
                    for orb in (0, 1):
                        for amp in (0, 1):
                            if slots == 0:
                                ok = amp == 1 if must_amp else amp == 0
                                table[self._idx(item, 0, leg, orb, amp)] = 1 if ok else 0
                                continue
                            total = self._cell(table, item + 1, slots, leg, orb, amp)
                            if piece.amp:
                                if amp == 0:
                                    total += self._cell(table, item + 1, slots - 1, leg, orb, 1)
                            elif piece.kind == "leg":
                                if leg == 0:
                                    total += self._cell(table, item + 1, slots - 1, 1, orb, amp)
                            elif piece.kind == "orb":
                                if orb == 0:
                                    total += self._cell(table, item + 1, slots - 1, leg, 1, amp)
                            elif piece.kind == "stack":
                                for count in range(1, slots + 1):
                                    total += self._cell(table, item + 1, slots - count, leg, orb, amp)
                            elif slots >= 1:
                                total += self._cell(table, item + 1, slots - 1, leg, orb, amp)
                            table[self._idx(item, slots, leg, orb, amp)] = total
        return table

    def _unrank_items(self, table: list[int], rank: int) -> tuple[str, ...]:
        item = 0
        slots = self.slots
        leg = orb = amp = 0
        chosen: list[str] = []
        guard = 0
        while slots > 0:
            guard += 1
            if guard > 100000:
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

    def _unrank_comb(self, rank: int, options: list[str], picks: int) -> tuple[str, ...]:
        chosen = []
        current = 0
        count = len(options)
        for remaining in range(picks, 0, -1):
            while True:
                ways = math.comb(count - current - 1, remaining - 1)
                if rank < ways:
                    chosen.append(options[current])
                    current += 1
                    break
                rank -= ways
                current += 1
        return tuple(chosen)

    def decode(self, index: int) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        if index < 0 or index >= self.total:
            raise IndexError(index)
        if index < self.count_without:
            items = self._unrank_items(self.dp_without, index)
        else:
            items = self._unrank_items(self.dp_with, index - self.count_without)
        return items, (), ()
