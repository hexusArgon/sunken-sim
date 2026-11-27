"""Shared host side of the exact OpenCL engines for Shaman and Paladin (farm.hybrid.shaman_cl, paladin_cl).

The kernels follow the Python fights operation by operation in float64
(``FP_CONTRACT OFF``).  Like ``farm.hybrid.priest_cl``, every row carries two
ESC point vectors: the fight (timeline) runs on ``tlpoints``, the score on
``points``.  ``refine`` uses that to replay the timeline cache of the Python
sims (``_TIMELINE``): an ESC trial whose cache key was seen earlier in the
same sextuple is scored on that earlier trial's fight, exactly as
``farm.score.finish_sextuple`` does on the CPU.
"""

from __future__ import annotations

import itertools
import os

import numpy as np

NF = 15
NP = 11
MULTI = 4


def pad(values, fill, what, code):
    values = list(values)
    if len(values) > MULTI:
        raise ValueError(f"{code}: more than {MULTI} {what} entries in the tooltip")
    return values + [fill] * (MULTI - len(values))


NU = 48


def character_tables(space, items: dict, sources: dict, special_bits: dict, talent_bits: dict, glyph_bits: dict,
                     no_effect: set, base: list, label: str) -> dict:
    """Per-piece arrays in the exact form the kernel folds. Pure function of the catalog."""
    from sunken_sim import shadow
    from sunken_sim.stacking import stack_fields

    pieces = space.pieces
    codes = [p.code for p in pieces]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate rawcodes in the chunk space")
    if space.slots != 6:
        raise ValueError("kernel expects six slots")
    if shadow.LEVEL != 15 or shadow.FIGHT != 30.0 or shadow.MEDIAN_MONSTER_HP != 5300.0:
        raise ValueError("kernel constants assume shadow.LEVEL 15, a 30 s fight and 5300 monster HP")
    if shadow.DUMMY_ARMOR != 15.0 or shadow.ARMOR_FACTOR != 0.04 or shadow.CHAOS_UNARMORED != 1.25:
        raise ValueError("kernel constants assume 15 armour, factor 0.04 and chaos 1.25")
    clash = set(codes) & (set(talent_bits) | set(glyph_bits))
    if clash:
        raise ValueError(f"item rawcodes collide with talent/glyph codes: {sorted(clash)}")
    n = len(pieces)
    fold = np.zeros((n, 2, NF), dtype=np.float64)
    uniq = np.zeros((n, NU), dtype=np.float64)
    pmask = np.zeros(n, dtype=np.uint64)
    pkind = np.zeros(n, dtype=np.int32)
    pamp = np.zeros(n, dtype=np.int32)
    psrc = np.zeros(n, dtype=np.int32)
    kinds = {"one": 0, "stack": 1, "leg": 2, "orb": 3}
    cv = shadow._copy_value
    tn = shadow._tip_number
    for i, piece in enumerate(pieces):
        item = items[piece.code]
        code = item.rawcode
        if code != piece.code:
            raise ValueError(f"piece {piece.code} maps to item {code}")
        bonus = stack_fields(code)
        pkind[i] = kinds[piece.kind]
        pamp[i] = 1 if piece.amp else 0
        src = sources.get(code, "drop")
        psrc[i] = {"legendary": 0, "shop": 1, "drop": 2}[src]
        if code in special_bits:
            pmask[i] = np.uint64(1 << special_bits[code])
        for state, first in ((0, True), (1, False)):
            if first:
                prim = bonus["primary"] if (bonus.get("primary") and not item.intel and not item.all_stats) else 0.0
            else:
                prim = bonus.get("primary", 0)
            if code == "I06M":
                haste = 0.075 if first else 0.0
            else:
                haste = cv(code, "haste", item.haste, first) / 100
            fold[i, state] = [
                cv(code, "intel", item.intel, first),
                cv(code, "all_stats", item.all_stats, first),
                cv(code, "strength", item.strength, first),
                cv(code, "all_stats", item.all_stats, first),
                cv(code, "agility", item.agility, first),
                cv(code, "all_stats", item.all_stats, first),
                prim,
                cv(code, "potency", item.potency, first),
                cv(code, "mastery", item.mastery, first),
                cv(code, "damage", item.damage, first),
                item.mana if first else 0,
                cv(code, "crit", item.crit, first),
                cv(code, "crit_rating", item.crit_rating, first),
                haste,
                cv(code, "attack_speed", item.attack_speed, first) / 100,
            ]
        tip = item.tip
        cast = item.cast_stun_chance * item.cast_stun_duration if (item.cast_stun_chance and item.cast_stun_duration > 0) else 0.0
        keep = [1.0 - tn(raw) / 100.0 for raw in shadow._REFUND_PCT.findall(tip)]
        keep += [1.0 - (tn(c) / 100.0) * (tn(p) / 100.0) for c, p in shadow._REFUND_CHANCE.findall(tip)]
        if shadow._MAX_MANA_SEC.search(tip):
            per_second = [tn(raw) / 100.0 for raw in shadow._MAX_MANA_SEC.findall(tip)]
        elif code in shadow._MANA_MAX_FRACTION:
            per_second = [shadow._MANA_MAX_FRACTION[code]]
        else:
            per_second = []
        attack_flat = [tn(f) for f, _p in shadow._ATTACK_MANA.findall(tip)] + [tn(f) for f in shadow._ATTACK_MANA_FLAT.findall(tip)]
        attack_pct = [tn(p) / 100.0 for _f, p in shadow._ATTACK_MANA.findall(tip)]
        row = [
            item.stun_chance * item.stun_duration,
            cast,
            1.0 if item.double_attack_potency else 0.0,
            0.0 if code in ("I07O", "I0NS") else item.armor_pen,
            item.crit_as,
            item.crit_as_duration if item.crit_as else 0.0,
            item.stab_chance,
            item.stab_ratio,
            item.auto_pct,
            item.execute_below,
            item.execute_pct if item.execute_pct > 0 else 0.0,
            1.0 if item.spell_crit else 0.0,
            1.0 if (item.spell_crit and "65%" in tip) else 0.0,
            shadow.item_luck(item),
            shadow._MANA_REGEN_RATE.get(code, 0.0),
        ]
        row += pad([float(m.replace(",", ".")) for m in shadow._MP5.findall(tip)], 0.0, "mp5", code)
        row += pad(keep, 1.0, "refund", code)
        row += pad([tn(raw) for raw in shadow._REFUND_FLAT.findall(tip)], 0.0, "flat refund", code)
        row += pad([tn(raw) / 100.0 for raw in shadow._REFUND_MASTERY.findall(tip)], 0.0, "mastery refund", code)
        row += pad(per_second, 0.0, "mana per second", code)
        row += pad(attack_flat, 0.0, "attack mana", code)
        row += pad(attack_pct, 0.0, "attack mana pct", code)
        row += [1.0 if ("doubled for Critical Strikes" in tip and shadow._ATTACK_MANA.search(tip)) else 0.0]
        row += pad([tn(raw) / 100.0 for raw in shadow._DAMAGE_MANA.findall(tip)], 0.0, "damage mana", code)
        if len(row) != NU:
            raise AssertionError(len(row))
        uniq[i] = row
    index = {code: i for i, code in enumerate(codes)}

    def entries(table):
        out = []
        for c, a in table.items():
            if c in index:
                out.append((0, index[c], a))
            elif c in glyph_bits:
                out.append((1, glyph_bits[c], a))
            elif c in talent_bits:
                out.append((2, talent_bits[c], a))
        return out

    mag = entries(shadow.MAGICAL_ADDS)
    phy = entries(shadow.PHYSICAL_ADDS)
    for c in list(space.talents) + list(space.glyphs):
        if c not in talent_bits and c not in glyph_bits and c not in no_effect:
            raise ValueError(f"talent/glyph {c} is not modelled by the " + label + " kernel")
    return {
        "dp0": np.asarray(space.dp_without, dtype=np.int64),
        "dp1": np.asarray(space.dp_with, dtype=np.int64),
        "count_without": int(space.count_without),
        "total": int(space.total),
        "npieces": n,
        "pkind": pkind,
        "pamp": pamp,
        "fold": np.ascontiguousarray(fold.reshape(-1)),
        "uniq": np.ascontiguousarray(uniq.reshape(-1)),
        "pmask": pmask,
        "psrc": psrc,
        "nmag": len(mag),
        "mag_kind": np.asarray([m[0] for m in mag] or [0], dtype=np.int32),
        "mag_id": np.asarray([m[1] for m in mag] or [-1], dtype=np.int32),
        "mag_amt": np.asarray([m[2] for m in mag] or [0.0], dtype=np.float64),
        "nphy": len(phy),
        "phy_kind": np.asarray([m[0] for m in phy] or [0], dtype=np.int32),
        "phy_id": np.asarray([m[1] for m in phy] or [-1], dtype=np.int32),
        "phy_amt": np.asarray([m[2] for m in phy] or [0.0], dtype=np.float64),
        "base": np.asarray(base, dtype=np.float64),
    }


_UNRANK_HEAD = "  int item = 0, slots = 6, leg = 0, orb = 0, amp = 0, guard = 0, k = 0;\n"
_UNRANK_GUARD = "    if (++guard > 100000 || item >= T->npieces || k > 6) return 1;\n"
_UNRANK_TAIL = "  return (rank != 0 || k != 6) ? 1 : 0;\n}"


def forced_kernel(source: str, space) -> str:
    """The kernel for farm.forced_pair.ForcedPieces: unrank the free slots from the pool (the first
    space.n_free pieces) with the flags the forced items take, then append the forced pieces."""
    for part in (_UNRANK_HEAD, _UNRANK_GUARD, _UNRANK_TAIL):
        if source.count(part) != 1:
            raise ValueError("kernel unrank does not have the shared form: no forced items for it")
    leg, orb, amp = space.start_flags
    forced = list(space.forced_indices)
    pick = " ".join(f"if (f == {i}) return {p};" for i, p in enumerate(forced))
    source = source.replace(_UNRANK_HEAD, f"  int item = 0, slots = {space.free_slots}, leg = {leg}, orb = {orb}, amp = {amp}, "
                                          "guard = 0, k = 0;\n")
    source = source.replace(_UNRANK_GUARD, f"    if (++guard > 100000 || item >= {space.n_free} || k > 6) return 1;\n")
    source = source.replace(_UNRANK_TAIL, f"  if (rank != 0 || k != {space.free_slots}) return 1;\n"
                                          f"  for (int f = 0; f < {len(forced)}; f++) chosen[k++] = forced_piece(f);\n"
                                          "  return 0;\n}")
    head = "int unrank(Tab* T, long index, int* chosen) {"
    if source.count(head) != 1:
        raise ValueError("kernel unrank signature")
    return source.replace(head, f"int forced_piece(int f) {{ {pick} return -1; }}\n\n" + head)


def mask_of(codes, bits: dict, no_effect: set) -> int:
    mask = 0
    for c in codes:
        if c in no_effect:
            continue
        if c not in bits:
            raise KeyError(c)
        mask |= 1 << bits[c]
    return mask


def make_build(space, items: dict, chunk: int, talents=(), glyphs=(), points: dict | None = None):
    from sunken_sim.esc import apply_points
    from sunken_sim.shadow import Build

    codes = space.decode(chunk)[0]
    build = Build(frozenset(talents), frozenset(glyphs), tuple(items[c] for c in codes), 0, 0, 0, 0)
    return apply_points(build, points) if points else build


class ExactCL:
    """One compiled kernel pair (item-only scan, full fights) plus catalog tables."""

    hero = ""
    TABLE_KEYS: tuple = ()
    SCALARS: dict = {}
    # False once the class's Python fight model is removed: self-checks replay farm/hybrid/fixtures/<hero>.json
    # and a row the kernel declines is an error (there is no Python oracle to score it).
    PYTHON = True

    def __init__(self, space, items: dict, sources: dict, targets: int, device=None, spec: str = "") -> None:
        from farm.hybrid.mage_cl import _import_cl, pick_device

        if spec not in self.SPECS:
            raise ValueError(f"{self.hero} spec {spec!r} is not modelled by the kernel")
        cl = _import_cl()
        self.cl = cl
        self.spec = spec
        self.space = space
        self.items = items
        self.device = device or pick_device(cl)
        self.ctx = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.ctx)
        opts = ["-cl-std=CL1.2", f"-DSPEC={self.SPECS[spec]}"]
        if os.environ.get("FARM_CL_NOINLINE", "").strip() == "1":
            opts.append("-DNOINLINE=1")
        source = self.KERNEL
        if getattr(space, "forced_indices", None):
            source = forced_kernel(source, space)
        self.p_bare = cl.Program(self.ctx, source).build(options=opts + ["-DTALENTS=0"])
        self.p_full = cl.Program(self.ctx, source).build(options=opts + ["-DTALENTS=1"])
        self.k_bare = cl.Kernel(self.p_bare, "cls_bare")
        self.k_rows = cl.Kernel(self.p_full, "cls_rows")
        self.targets = int(targets)
        if not 1 <= self.targets <= 8:
            raise ValueError("kernel supports 1..8 targets")
        self.t = self.tables(space, items, sources)
        mf = cl.mem_flags
        self.tab_args = []
        for key in self.TABLE_KEYS:
            value = self.t[key]
            if key in self.SCALARS:
                self.tab_args.append(self.SCALARS[key](value))
            else:
                self.tab_args.append(cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(value)))
        self._cap = 0
        self.name = f"{self.device.name.strip()} ({self.device.platform.name.strip()})"
        self.counts = {"bare_rows": 0, "rows": 0, "oracle_rows": 0, "refined": 0}

    # -- launches -------------------------------------------------------
    def _ensure(self, n: int) -> None:
        if n <= self._cap:
            return
        mf = self.cl.mem_flags
        self._cap = max(n, 1 << 16)
        self.out_dps = self.cl.Buffer(self.ctx, mf.WRITE_ONLY, 8 * self._cap)
        self.out_group = self.cl.Buffer(self.ctx, mf.WRITE_ONLY, self._cap)
        self.out_status = self.cl.Buffer(self.ctx, mf.WRITE_ONLY, self._cap)

    def _read(self, n):
        dps = np.empty(n, dtype=np.float64)
        group = np.empty(n, dtype=np.uint8)
        status = np.empty(n, dtype=np.uint8)
        self.cl.enqueue_copy(self.queue, dps, self.out_dps)
        self.cl.enqueue_copy(self.queue, group, self.out_group)
        self.cl.enqueue_copy(self.queue, status, self.out_status)
        self.queue.finish()
        return dps, group, status

    def bare(self, start: int, n: int):
        self._ensure(n)
        self.k_bare.set_args(np.int64(start), np.int32(n), np.int32(self.targets), *self.tab_args,
                             self.out_dps, self.out_group, self.out_status)
        self.cl.enqueue_nd_range_kernel(self.queue, self.k_bare, (n,), None)
        self.counts["bare_rows"] += n
        return self._read(n)

    def rows(self, chunks, tmasks, gmasks, points, tlpoints=None):
        cl = self.cl
        n = len(chunks)
        if n == 0:
            return np.empty(0), np.empty(0, np.uint8), np.empty(0, np.uint8)
        self._ensure(n)
        mf = cl.mem_flags
        points = np.ascontiguousarray(np.asarray(points, dtype=np.int32).reshape(n, NP))
        tlpoints = points if tlpoints is None else np.ascontiguousarray(np.asarray(tlpoints, dtype=np.int32).reshape(n, NP))

        def buf(a):
            return cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(a))

        # The buffers must outlive the launch: a kernel argument does not keep its buffer alive.
        args = [buf(np.asarray(chunks, dtype=np.int64)), buf(np.asarray(tmasks, dtype=np.uint32)),
                buf(np.asarray(gmasks, dtype=np.uint32)), buf(points), buf(tlpoints)]
        self.k_rows.set_args(np.int32(n), np.int32(self.targets), *args, *self.tab_args,
                             self.out_dps, self.out_group, self.out_status)
        cl.enqueue_nd_range_kernel(self.queue, self.k_rows, (n,), None)
        out = self._read(n)
        del args
        self.counts["rows"] += n
        return out

    # -- explicit pieces and the report (kernels cls_pick / cls_report) ---
    # A class with these kernels sets SOURCE_NAMES (Ledger ids), ACTION_NAMES, STAT_KEYS, NSRC and MAXA.
    def picks_of(self, codes) -> list[int]:
        """Piece indices of an item list (at most 6; -1 pads empty slots)."""
        index = {piece.code: i for i, piece in enumerate(self.space.pieces)}
        out = [index[c] for c in codes]
        if len(out) > 6:
            raise ValueError("more than 6 items")
        return out + [-1] * (6 - len(out))

    def _pick_launch(self, kernel, picks, tmasks, gmasks, points, extra_out=()):
        cl = self.cl
        n = len(picks)
        self._ensure(n)
        mf = cl.mem_flags

        def buf(a):
            return cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(a))

        args = [buf(np.asarray(picks, dtype=np.int32).reshape(n, 6)), buf(np.asarray(tmasks, dtype=np.uint32)),
                buf(np.asarray(gmasks, dtype=np.uint32)), buf(np.asarray(points, dtype=np.int32).reshape(n, NP))]
        kernel.set_args(np.int32(n), np.int32(self.targets), *args, *self.tab_args,
                        self.out_dps, self.out_group, self.out_status, *extra_out)
        cl.enqueue_nd_range_kernel(self.queue, kernel, (n,), None)
        out = self._read(n)
        del args
        return out

    def pick(self, picks, tmasks, gmasks, points):
        """DPS of explicit builds: picks (n, 6) piece indices, -1 = empty slot."""
        n = len(picks)
        if n == 0:
            return np.empty(0), np.empty(0, np.uint8), np.empty(0, np.uint8)
        if not hasattr(self, "_k_pick"):
            self._k_pick = self.cl.Kernel(self.p_full, "cls_pick")
        out = []
        for lo in range(0, n, 1 << 16):
            hi = min(n, lo + (1 << 16))
            out.append(self._pick_launch(self._k_pick, np.asarray(picks[lo:hi]), np.asarray(tmasks[lo:hi]),
                                         np.asarray(gmasks[lo:hi]), np.asarray(points[lo:hi])))
        return tuple(np.concatenate([o[k] for o in out]) for k in range(3))

    def report(self, codes, talents=(), glyphs=(), points: dict | None = None) -> dict:
        """One fight with the sources in Ledger order, the casts, mana left and the stat sheet."""
        from sunken_sim.esc import ESC_ATTRS

        cl = self.cl
        if not hasattr(self, "_k_report"):
            opts = ["-cl-std=CL1.2", f"-DSPEC={self.SPECS[self.spec]}", "-DTALENTS=1", "-DREPORT=1"]
            self._p_report = cl.Program(self.ctx, self.KERNEL).build(options=opts)
            self._k_report = cl.Kernel(self._p_report, "cls_report")
        mf = cl.mem_flags
        picks = np.asarray([self.picks_of(codes)], dtype=np.int32)
        tm = np.asarray([self.talent_mask(talents)], dtype=np.uint32)
        gm = np.asarray([self.glyph_mask(glyphs)], dtype=np.uint32)
        pts = np.asarray([[int((points or {}).get(k, 0)) for k in ESC_ATTRS]], dtype=np.int32)
        outs = {
            "src": np.empty(self.NSRC, np.float64), "ord": np.empty(self.NSRC, np.int32), "nord": np.empty(1, np.int32),
            "mana": np.empty(1, np.float64), "act_t": np.empty(self.MAXA, np.float64),
            "act_id": np.empty(self.MAXA, np.int32), "nact": np.empty(1, np.int32),
            "stats": np.zeros(len(self.STAT_KEYS), np.float64),
        }
        bufs = {k: cl.Buffer(self.ctx, mf.WRITE_ONLY, v.nbytes) for k, v in outs.items()}
        dps, group, status = self._pick_launch(
            self._k_report, picks, tm, gm, pts,
            [bufs[k] for k in ("src", "ord", "nord", "mana", "act_t", "act_id", "nact", "stats")])
        if status[0]:
            raise RuntimeError(f"{self.hero} report status {int(status[0])}")
        for k, v in outs.items():
            cl.enqueue_copy(self.queue, v, bufs[k])
        self.queue.finish()
        sources = {}
        for i in range(int(outs["nord"][0])):
            sources[self.SOURCE_NAMES[int(outs["ord"][i])]] = float(outs["src"][i])
        total = 0.0
        for v in sources.values():
            total += v
        stats = dict(zip(self.STAT_KEYS, (float(x) for x in outs["stats"])))
        if "galactic" in stats:
            stats["galactic"] = bool(stats["galactic"])
        if int(outs["nact"][0]) > self.MAXA:
            raise RuntimeError(f"{self.hero} report: more than {self.MAXA} casts")
        actions = [(float(outs["act_t"][i]), self.ACTION_NAMES[int(outs["act_id"][i])]) for i in range(int(outs["nact"][0]))]
        return {"dps": float(dps[0]), "total": total, "sources": sources, "actions": actions,
                "mana_left": float(outs["mana"][0]), "stats": stats, "group": int(group[0])}

    # -- Python reference ----------------------------------------------
    def oracle_bare(self, chunk: int) -> float:
        return self.py_value(make_build(self.space, self.items, chunk))

    def oracle_fight(self, chunk: int, talents, glyphs, points: dict, tl_points: dict | None = None) -> float:
        build = make_build(self.space, self.items, chunk, talents, glyphs, points)
        build_tl = None if tl_points is None else make_build(self.space, self.items, chunk, talents, glyphs, tl_points)
        return self.py_value(build, build_tl)

    def py_value(self, build, build_tl=None) -> float:
        """simulate(build).dps with an empty timeline cache; with build_tl, after simulate(build_tl)
        filled it (the replayed cache of the ESC search)."""
        if not self.PYTHON:
            raise RuntimeError(f"{self.hero} {self.spec}: the kernel declined a fight and there is no Python model to score it")
        mod = self.module()
        old = getattr(mod, "_TIMELINE", None)
        if old is not None:
            mod._TIMELINE = {}
        try:
            if build_tl is not None and old is not None:
                mod.simulate(build_tl, self.targets, self.spec)
            return mod.simulate(build, self.targets, self.spec).dps
        finally:
            if old is not None:
                mod._TIMELINE = old

    def talent_mask(self, codes) -> int:
        return mask_of(codes, self.TALENT_BITS, self.NO_EFFECT)

    def glyph_mask(self, codes) -> int:
        return mask_of(codes, self.GLYPH_BITS, self.NO_EFFECT)

    def scores(self, chunk: int, builds: list) -> list[float]:
        from sunken_sim.esc import ESC_ATTRS

        tm = [self.talent_mask(b[0]) for b in builds]
        gm = [self.glyph_mask(b[1]) for b in builds]
        pts = [[int(b[2].get(a, 0)) for a in ESC_ATTRS] for b in builds]
        tlp = [[int((b[3] if len(b) > 3 and b[3] is not None else b[2]).get(a, 0)) for a in ESC_ATTRS] for b in builds]
        dps, _group, status = self.rows([chunk] * len(builds), tm, gm, pts, tlp)
        out = [float(v) for v in dps]
        for j in np.nonzero((status != 0) | ~np.isfinite(dps))[0]:
            b = builds[int(j)]
            out[int(j)] = self.oracle_fight(chunk, b[0], b[1], b[2], b[3] if len(b) > 3 else None)
            self.counts["oracle_rows"] += 1
        return out

    def refine(self, chunk: int, equipped: tuple, talent_codes, glyph_codes, picks_without, picks_with, glyph_picks):
        """farm.score.finish_sextuple for this hero/spec, every fight on the device."""
        from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points, points_payload
        from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS, Build

        picks = picks_with if any(item.rawcode == MIND_AMPLIFIER for item in equipped) else picks_without
        combos = list(itertools.combinations(talent_codes, picks))
        values = self.scores(chunk, [(c, (), {}) for c in combos])
        best_dps = -1.0
        best_talents: tuple = ()
        for combo, dps in zip(combos, values):
            if dps > best_dps:
                best_dps = dps
                best_talents = combo
        gcombos = list(itertools.combinations(glyph_codes, glyph_picks))
        values = self.scores(chunk, [(best_talents, g, {}) for g in gcombos])
        best_glyphs: tuple = ()
        for combo, dps in zip(gcombos, values):
            if dps > best_dps:
                best_dps = dps
                best_glyphs = combo
        base = Build(frozenset(best_talents), frozenset(best_glyphs), equipped, 0, 0, 0, 0)
        seen: dict = {}

        def timeline(points: dict) -> dict:
            key = self.timeline_key(apply_points(base, points))
            return seen.setdefault(key, dict(points))

        counts = empty_points()
        pointed = self.scores(chunk, [(best_talents, best_glyphs, counts, timeline(counts))])[0]
        for _ in range(SKILL_POINTS):
            names = [a for a in ESC_ATTRS if counts[a] < ESC_CAP]
            trials = []
            for name in names:
                trial = dict(counts)
                trial[name] += 1
                trials.append((best_talents, best_glyphs, trial, timeline(trial)))
            values = self.scores(chunk, trials)
            pick = None
            pick_dps = -1.0
            for name, dps in zip(names, values):
                if dps > pick_dps:
                    pick_dps = dps
                    pick = name
            if pick is None:
                break
            counts[pick] += 1
            pointed = pick_dps
        self.counts["refined"] += 1
        spent = sum(int(v) for v in counts.values())
        point_fights = 1 if spent == 0 else SKILL_POINTS * len(ESC_ATTRS)
        return pointed, best_talents, best_glyphs, points_payload(counts), len(combos) + len(gcombos) + point_fights


# ---------------------------------------------------------------- parity helpers (module-agnostic)
def oracle(engine: ExactCL, index: int) -> float:
    """farm.score.item_dps on an empty timeline cache."""
    from farm.score import item_dps

    mod = engine.module()
    old = getattr(mod, "_TIMELINE", None)
    if old is not None:
        mod._TIMELINE = {}
    try:
        codes = engine.space.decode(index)[0]
        return item_dps(engine.hero, engine.spec, engine.targets, tuple(engine.items[c] for c in codes))
    finally:
        if old is not None:
            mod._TIMELINE = old


def parity(engine: ExactCL, space, items: dict, sources: dict, targets: int, indices) -> dict:
    from farm.hybrid.mage_cl import GROUP_NAMES
    from farm.runner import build_group

    bad = []
    fallback = 0
    indices = [int(i) for i in indices]
    for index in indices:
        dps, group, status = engine.bare(index, 1)
        ref = oracle(engine, index)
        if status[0]:
            fallback += 1
            continue
        ref_group = build_group([sources.get(c, "drop") for c in space.decode(index)[0]])
        if float(dps[0]).hex() != float(ref).hex() or GROUP_NAMES[int(group[0])] != ref_group:
            bad.append({"chunk": index, "kernel": float(dps[0]), "oracle": float(ref)})
    return {"rows": len(indices), "mismatches": len(bad), "status_rows": fallback, "examples": bad[:5], "ok": not bad}


def random_builds(space, count: int, seed: int) -> list:
    from farm.hybrid.mage_cl import random_builds as _rb

    return _rb(space, count, seed)


def parity_full(engine: ExactCL, space, items: dict, targets: int, builds, timeline_seed: int | None = None) -> dict:
    """Talent/glyph/ESC fights against simulate(...).dps; with timeline_seed, on a replayed cache."""
    import random

    from sunken_sim.esc import ESC_ATTRS

    tl = None
    if timeline_seed is not None:
        rng = random.Random(timeline_seed)
        tl = []
        for _c, _t, _g, points in builds:
            other = dict(points)
            # the replayed cache only ever differs in points the key leaves out
            for a in engine.KEY_FREE:
                if rng.random() < 0.6:
                    other[a] = max(0, min(20, other[a] + rng.choice((-3, -1, 1, 3))))
            tl.append(other)
    dps, _g, status = engine.rows([b[0] for b in builds], [engine.talent_mask(b[1]) for b in builds],
                                  [engine.glyph_mask(b[2]) for b in builds], [[b[3][a] for a in ESC_ATTRS] for b in builds],
                                  None if tl is None else [[p[a] for a in ESC_ATTRS] for p in tl])
    bad = []
    fallback = 0
    for j, ((chunk, talents, glyphs, points), value, st) in enumerate(zip(builds, dps, status)):
        if st:
            fallback += 1
            continue
        ref = engine.oracle_fight(chunk, talents, glyphs, points, None if tl is None else tl[j])
        if float(value).hex() != float(ref).hex():
            bad.append({"chunk": chunk, "talents": talents, "glyphs": glyphs, "kernel": float(value), "oracle": float(ref)})
    return {"rows": len(builds), "mismatches": len(bad), "status_rows": fallback, "examples": bad[:5], "ok": not bad}


def fixture_check(engine: ExactCL, rows: int, full: int, seed: int):
    """Self-check of a class without a Python model: replay frozen Python == GPU fights
    (farm/hybrid/fixtures/<hero>.json) whose items are all in the engine's pool."""
    import json
    import random
    from pathlib import Path

    from sunken_sim.esc import ESC_ATTRS

    data = json.loads((Path(__file__).resolve().parent / "fixtures" / f"{engine.hero}.json").read_text(encoding="utf-8"))
    have = {p.code for p in engine.space.pieces}
    cases = [c for c in data["cases"] if c["spec"] == engine.spec and c["targets"] == engine.targets
             and not c.get("incoming") and not c.get("model_fix") and set(c["items"]) <= have]
    random.Random(seed).shuffle(cases)
    if len(cases) < rows + full:  # split what there is between the two checks
        rows = len(cases) // 2
        full = len(cases) - rows
    parts = []
    for chosen in (cases[:rows], cases[rows:rows + full]):
        bad = []
        if chosen:
            dps, _g, status = engine.pick([engine.picks_of(c["items"]) for c in chosen],
                                          [engine.talent_mask(c["talents"]) for c in chosen],
                                          [engine.glyph_mask(c["glyphs"]) for c in chosen],
                                          [[c["points"][a] for a in ESC_ATTRS] for c in chosen])
            for c, d, st in zip(chosen, dps, status):
                if st or float(d).hex() != c["dps"]:
                    bad.append({"items": c["items"], "kernel": float(d), "fixture": float.fromhex(c["dps"]), "status": int(st)})
        parts.append({"rows": len(chosen), "mismatches": len(bad), "status_rows": sum(1 for b in bad if b["status"]),
                      "examples": bad[:5], "ok": not bad and len(chosen) > 0})
    # The chunk paths (bare scan, rows) against the explicit-pieces kernel on the same items.
    if engine.space.total > 0:
        n = min(max(rows, 1), 256)
        start = random.Random(seed + 7).randrange(max(1, engine.space.total - n))
        n = min(n, engine.space.total - start)
        chunks = list(range(start, start + n))
        picks = [engine.picks_of(engine.space.decode(c)[0]) for c in chunks]
        zero_t, zero_p = [0] * n, [[0] * len(ESC_ATTRS)] * n
        ref, _g, st0 = engine.pick(picks, zero_t, zero_t, zero_p)
        bare, _g, st1 = engine.bare(start, n)
        rowv, _g, st2 = engine.rows(chunks, zero_t, zero_t, zero_p)
        bad = [{"chunk": c, "pick": float(a), "bare": float(b), "rows": float(r)}
               for c, a, b, r, s0, s1, s2 in zip(chunks, ref, bare, rowv, st0, st1, st2)
               if s0 or s1 or s2 or float(a).hex() != float(b).hex() or float(a).hex() != float(r).hex()]
        parts[0]["rows"] += n
        parts[0]["mismatches"] += len(bad)
        parts[0]["examples"] = (parts[0]["examples"] + bad)[:5]
        parts[0]["ok"] = parts[0]["ok"] and not bad
    return parts[0], parts[1]


def self_check(engine: ExactCL, space, items: dict, sources: dict, targets: int, rows: int, full: int, seed: int):
    from farm.hybrid.mage_cl import sample

    if not getattr(engine, "PYTHON", True):
        return fixture_check(engine, rows, full, seed)

    check = parity(engine, space, items, sources, targets, sample(space, rows, seed))
    builds = random_builds(space, full, seed + 1)
    parts = [parity_full(engine, space, items, targets, builds), parity_full(engine, space, items, targets, builds, seed + 2)]
    fights = {"rows": sum(p["rows"] for p in parts), "mismatches": sum(p["mismatches"] for p in parts),
              "status_rows": sum(p["status_rows"] for p in parts),
              "examples": [e for p in parts for e in p["examples"]][:5], "ok": all(p["ok"] for p in parts)}
    return check, fights


def finish_reference(hero: str, spec: str, targets: int, equipped: tuple, space):
    """farm.score.finish_sextuple as one CPU worker runs it on a fresh timeline cache."""
    import importlib

    from farm.score import finish_sextuple

    mod = importlib.import_module(f"sunken_sim.{hero}")
    old = getattr(mod, "_TIMELINE", None)
    if old is not None:
        mod._TIMELINE = {}
    try:
        return finish_sextuple(hero, spec, targets, equipped, space.talents, space.glyphs, space.picks_without,
                               space.picks_with, space.glyph_picks)
    finally:
        if old is not None:
            mod._TIMELINE = old


def full_space(hero: str, class_name: str, talents) -> tuple:
    """Every item of the class pools (shop + drop + legendaries) as one Space: the one-slot screen and reports
    of builds outside a run's top-N use it with the explicit-pieces kernels."""
    from farm.space import Piece, Space
    from sunken_sim.library import load_items
    from sunken_sim.search import GLYPHS, _item_kind, pools_for
    from sunken_sim.shadow import MIND_AMPLIFIER

    shop, drop, legs = pools_for(load_items(), class_name)
    items = {}
    for item in shop + drop + legs:
        items.setdefault(item.rawcode, item)
    pieces = [Piece(code, _item_kind(items[code]), amp=code == MIND_AMPLIFIER, name=items[code].name)
              for code in sorted(items)]
    space = Space(pieces, sorted(talents), sorted(GLYPHS), picks_without=3, picks_with=3,
                  talent_names=dict(talents), glyph_names=dict(GLYPHS))
    return space, items
