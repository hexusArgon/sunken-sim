# -*- coding: utf-8 -*-
"""Shared GPU next-event timeline skeleton for hybrid DirectML fights.

Design
------
Each build is a row. Clocks live in a [B, C] tensor; each step takes
``moment = clocks.min(dim=1)`` and fires the highest-priority clock that
matches that moment (priority = column order). Cast lock (busy), mana, and
buff clocks are plain [B] tensors. Events are appended into padded buffers
``when / raw / flags...`` then converted to the class Timeline event tuples
the existing kind-score path already consumes.

This module does not know any class rotation. Class pilots (warrior first)
own the action handlers and call these helpers.

Float32 on DirectML is the production path; clocks for a 30s fight stay
stable enough for DPS rel/abs <= 1e-4 against the CPU float64 oracle when
the control flow matches.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Event special codes shared by warrior (and later peers).
SPEC_NONE = 0
SPEC_SPLASH = 1
SPEC_ECHO = 2
SPEC_FLAT = 3

SPECIAL_NAME = {
    SPEC_NONE: None,
    SPEC_SPLASH: "splash",
    SPEC_ECHO: "echo",
    SPEC_FLAT: "flat",
}


@dataclass
class EventBuffers:
    """Padded per-build event buffers on device (or numpy for CPU tests)."""

    when: object
    raw: object
    magical: object
    count: object
    pot_scale: object
    auto: object
    mastery: object
    enraged: object
    auto_pct: object
    special: object
    length: object  # [B] int
    max_events: int

    def push_mask(
        self,
        torch,
        mask,
        when,
        raw,
        *,
        magical=0.0,
        count=1.0,
        pot_scale=1.0,
        auto=0.0,
        mastery=0.0,
        enraged=0.0,
        auto_pct=0.0,
        special=SPEC_NONE,
    ) -> None:
        """Append one event for every row where mask is True."""
        if not bool(mask.any()):
            return
        B = int(mask.shape[0])
        idx = self.length.clamp(max=self.max_events - 1)
        # rows = 0..B-1
        rows = torch.arange(B, device=mask.device)
        active = mask & (self.length < self.max_events)

        def put(buf, value):
            if not isinstance(value, torch.Tensor):
                value = torch.full((B,), float(value), dtype=buf.dtype, device=buf.device)
            else:
                value = value.to(dtype=buf.dtype)
            buf[rows[active], idx[active]] = value[active]

        put(self.when, when)
        put(self.raw, raw)
        put(self.magical, magical)
        put(self.count, count)
        put(self.pot_scale, pot_scale)
        put(self.auto, auto)
        put(self.mastery, mastery)
        put(self.enraged, enraged)
        put(self.auto_pct, auto_pct)
        put(self.special, special)
        self.length = self.length + active.to(self.length.dtype)


def make_event_buffers(torch, device, batch: int, max_events: int, dtype=None) -> EventBuffers:
    if dtype is None:
        dtype = torch.float32
    z = lambda: torch.zeros((batch, max_events), dtype=dtype, device=device)
    return EventBuffers(
        when=z(),
        raw=z(),
        magical=z(),
        count=z(),
        pot_scale=z(),
        auto=z(),
        mastery=z(),
        enraged=z(),
        auto_pct=z(),
        special=z(),
        length=torch.zeros(batch, dtype=torch.int64, device=device),
        max_events=max_events,
    )


def cooldown_torch(base, haste, cd_temp, flat_cdr, flat=0.0):
    """Vectorized sunken_sim._cooldown: max(0.5, (base*cd_temp - flat_cdr - flat)/(1+haste))."""
    import torch

    if not isinstance(base, torch.Tensor):
        # broadcast scalars against haste tensor
        ref = haste
        base = torch.full_like(ref, float(base))
    if not isinstance(flat, torch.Tensor):
        flat = torch.full_like(haste, float(flat))
    return torch.clamp((base * cd_temp - flat_cdr - flat) / (1.0 + haste), min=0.5)


def pick_priority_clock(clocks, busy, fight: float):
    """Return (moment [B], which [B], active [B]).

    ``which`` is the column index of the highest-priority clock equal to the
    per-row minimum among clocks (priority = lower column index). Rows whose
    min clock is >= fight are inactive. Busy is NOT applied here — callers
    defer clocks that fire during busy, matching CPU simulate.
    """
    import torch

    moment, _ = clocks.min(dim=1)
    active = moment < fight
    # Exact equality only — matches CPU ``moment == next_X``.
    # A 1e-7 epsilon falsely ties clocks that float64 leaves 1 ULP apart
    # (busy vs independently scheduled CD), flipping priority vs the oracle.
    eq = clocks == moment.unsqueeze(1)
    C = clocks.shape[1]
    prio = torch.arange(C, device=clocks.device, dtype=clocks.dtype).view(1, C).expand_as(clocks)
    prio = torch.where(eq, prio, torch.full_like(prio, float(C + 1)))
    which = prio.argmin(dim=1)
    which = torch.where(active, which, torch.zeros_like(which))
    return moment, which, active


def buffers_to_warrior_events(bufs: EventBuffers) -> list[list[tuple]]:
    """Convert device buffers to warrior score_events tuples (CPU lists)."""
    when = bufs.when.detach().cpu().numpy()
    raw = bufs.raw.detach().cpu().numpy()
    magical = bufs.magical.detach().cpu().numpy()
    count = bufs.count.detach().cpu().numpy()
    pot = bufs.pot_scale.detach().cpu().numpy()
    auto = bufs.auto.detach().cpu().numpy()
    mastery = bufs.mastery.detach().cpu().numpy()
    enraged = bufs.enraged.detach().cpu().numpy()
    auto_pct = bufs.auto_pct.detach().cpu().numpy()
    special = bufs.special.detach().cpu().numpy()
    length = bufs.length.detach().cpu().numpy()
    out: list[list[tuple]] = []
    for b in range(when.shape[0]):
        n = int(length[b])
        evs = []
        for i in range(n):
            sp = SPECIAL_NAME.get(int(special[b, i]), None)
            evs.append(
                (
                    float(when[b, i]),
                    "",  # name unused by kind-score
                    float(raw[b, i]),
                    bool(magical[b, i] >= 0.5),
                    int(round(float(count[b, i]))),
                    float(pot[b, i]),
                    bool(auto[b, i] >= 0.5),
                    float(mastery[b, i]),
                    bool(enraged[b, i] >= 0.5),
                    bool(auto_pct[b, i] >= 0.5),
                    sp,
                )
            )
        out.append(evs)
    return out
