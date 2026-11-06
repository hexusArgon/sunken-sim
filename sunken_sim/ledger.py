# -*- coding: utf-8 -*-
"""Typed damage ledger for the GPU kind/weight compile (farm/hybrid/kindscore.py).

A class sim keeps writing to ``sources`` as before; ``sources`` is a Ledger, a
dict that also keeps typed events (when, name, weight, kind[, pot_coeff]).
The optional coefficient adds stats["potency"] * pot_coeff before the kind
multiplier; legacy four-tuples and add_exec calls are unchanged:

  KIND_EXEC: weight * _execute_factor(stats, when). Recorded by add_exec() at the
             hit sites, weight = dealt / execute (pre-execute damage).
  KIND_FLAT: weight as-is. Every other write (sources[x] = ..., +=, the
             auto_pct / probe-restore patterns) is recorded as its delta.

The dict values are bit-identical to the old plain-dict sims (add_exec adds the
same dealt number), so simulate() keeps its numbers; score_events() is the CPU
reference for the GPU sums.
"""

from __future__ import annotations

from sunken_sim.shadow import _execute_factor

KIND_EXEC = 2.0
KIND_FLAT = 3.0


class Ledger(dict):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.events: list[tuple] = []

    def __setitem__(self, name, value) -> None:
        delta = value - dict.get(self, name, 0.0)
        if delta:
            self.events.append((0.0, name, delta, KIND_FLAT))
        dict.__setitem__(self, name, value)

    def add_exec(self, name: str, dealt: float, when: float, execute: float, *,
                 raw_weight: float | None = None, pot_coeff: float = 0.0) -> None:
        """Add dealt to sources; optionally emit raw_weight + potency*pot_coeff.

        raw_weight and pot_coeff are pre-execute; legacy callers still emit
        dealt/execute as a four-tuple. Never infer raw by subtracting potency.
        """
        dict.__setitem__(self, name, dict.get(self, name, 0.0) + dealt)
        if raw_weight is not None:
            # Keep zero-current-damage events too: potency may change on replay.
            self.events.append((when, name, raw_weight, KIND_EXEC, pot_coeff))
        elif dealt:
            self.events.append((when, name, dealt / execute, KIND_EXEC))


def attach(report):
    """Plain-dict sources on the Report, events kept as report.events."""
    ledger = report.sources
    if isinstance(ledger, Ledger):
        report.events = ledger.events
        report.sources = dict(ledger)
    return report


def score_events(events: list, stats: dict) -> dict[str, float]:
    sources: dict[str, float] = {}
    for ev in events:
        when, name, weight, kind = ev[:4]
        if len(ev) > 4:
            weight = weight + stats.get("potency", 0.0) * ev[4]
        if kind == KIND_EXEC:
            amount = weight * _execute_factor(stats, when)
        elif kind == KIND_FLAT:
            amount = weight
        else:
            raise ValueError(f"unknown ledger kind {kind}")
        sources[name] = sources.get(name, 0.0) + amount
    return sources
