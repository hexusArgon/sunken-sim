"""Prototype GPU kernel: batched raw item-stat totals per build.

This is NOT a fight sim and NOT DPS. It is input prep: for a span of chunk
indices it sums the flat numeric fields of the equipped items (intel, crit,
haste, ...). CPU (pure Python) is the reference; the device version must match
it within PARITY_TOL or the caller falls back to CPU.
"""

from __future__ import annotations

import dataclasses
import math

from farm.hybrid.device import DeviceInfo

PARITY_TOL = 1e-4  # relative; DirectML works in float32


def stat_fields(item_cls) -> tuple[str, ...]:
    """Numeric (int/float, not bool) dataclass fields of Item."""
    names = []
    for field in dataclasses.fields(item_cls):
        kind = field.type if isinstance(field.type, str) else getattr(field.type, "__name__", "")
        if kind in ("int", "float"):
            names.append(field.name)
    return tuple(names)


def item_table(items: dict, fields: tuple[str, ...]) -> tuple[dict[str, int], list[list[float]]]:
    """Row 0 is all zeros (padding). Code -> row index."""
    index: dict[str, int] = {}
    table: list[list[float]] = [[0.0] * len(fields)]
    for code in sorted(items):
        item = items[code]
        index[code] = len(table)
        table.append([float(getattr(item, name, 0) or 0) for name in fields])
    return index, table


def decode_rows(space, index: dict[str, int], start: int, stop: int) -> list[list[int]]:
    """Item row ids per chunk, padded with 0 to space.slots."""
    width = int(space.slots)
    rows: list[list[int]] = []
    for chunk in range(start, stop):
        codes = space.decode(chunk)[0]
        row = [index[code] for code in codes][:width]
        row += [0] * (width - len(row))
        rows.append(row)
    return rows


def totals_cpu(table: list[list[float]], rows: list[list[int]]) -> list[list[float]]:
    width = len(table[0]) if table else 0
    out = []
    for row in rows:
        acc = [0.0] * width
        for rid in row:
            for col, value in enumerate(table[rid]):
                acc[col] += value
        out.append(acc)
    return out


def totals_device(table: list[list[float]], rows: list[list[int]], device: DeviceInfo) -> list[list[float]]:
    """Gather + sum on the device (DirectML) or torch CPU when device is cpu."""
    import torch

    target = device.handle if device.gpu else torch.device("cpu")
    tab = torch.tensor(table, dtype=torch.float32).to(target)
    idx = torch.tensor(rows, dtype=torch.int64).to(target)
    summed = tab[idx].sum(dim=1)
    return summed.cpu().tolist()


def parity(reference: list[list[float]], other: list[list[float]], tol: float = PARITY_TOL) -> tuple[bool, float]:
    worst = 0.0
    if len(reference) != len(other):
        return False, math.inf
    for left, right in zip(reference, other):
        if len(left) != len(right):
            return False, math.inf
        for a, b in zip(left, right):
            err = abs(a - b) / max(1.0, abs(a))
            worst = max(worst, err)
    return worst <= tol, worst