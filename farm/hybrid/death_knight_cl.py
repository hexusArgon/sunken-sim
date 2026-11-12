"""Exact float64 OpenCL kernel for Death Knight fights (Frost, Blood, Unholy).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.death_knight.stats_of`` (strength primary, item armour, spell crit,
Blood Strike stacks) and run ``death_knight.simulate`` with its Ledger sums in
insertion order. The debuffs Outbreak, Blood Plague and Chill are distributions
of expiry times per target (``death_knight._Buff``), mirrored here entry by entry.

``death_knight.simulate`` has no timeline cache, so every row is its own fight.
Rows the kernel cannot score (more summons than slots, negative armour) return a
non-zero status and are re-scored by the Python oracle on the host.
Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 16

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 frost, 1 blood, 2 unholy */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_FROST (SPEC == 0)
#define SP_BLOOD (SPEC == 1)
#define SP_UNHOLY (SPEC == 2)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 16
#define NSRC 14
#define MAXT 5  /* the farm runs 5 targets; more -> status 3, the host re-scores the row */
#define BS 8
#define MAXS 24
#define LEVEL 15.0
#define RANK 1.0

#define S_SULF (1UL<<0)
#define S_ORB  (1UL<<1)
#define S_GALA (1UL<<2)
#define S_SULG (1UL<<3)
#define S_TLUM (1UL<<4)
#define S_GLAS (1UL<<5)
#define S_FLSK (1UL<<6)
#define S_I03C (1UL<<7)
#define S_I00L (1UL<<8)
#define S_I00Y (1UL<<9)
#define S_HARN (1UL<<10)
#define S_ATIE (1UL<<11)
#define S_CORE (1UL<<12)
#define S_UNSI (1UL<<13)
#define S_BELT (1UL<<14)
#define S_SIPH (1UL<<15)
#define S_COLD (1UL<<16)
#define S_MAW  (1UL<<17)
#define S_SILM (1UL<<18)

#define T_ARMY (1u<<0)
#define T_VIRUL (1u<<1)
#define T_SINDR (1u<<2)
#define T_MARROW (1u<<3)
#define T_OBLIT (1u<<4)
#define T_BTAP (1u<<5)
#define T_LICH (1u<<6)
#define T_USTRK (1u<<7)
#define T_BFORGE (1u<<8)
#define T_DECOMP (1u<<9)
#define T_PEST (1u<<10)
#define T_RAZOR (1u<<11)
#define T_GRIM (1u<<12)
#define T_WORMS (1u<<13)
#define T_DPRES (1u<<14)

#define G_UNSL (1u<<0)
#define G_GLASS (1u<<1)
#define G_FORT (1u<<2)
#define G_SUPR (1u<<3)
#define G_ANIM (1u<<4)
#define G_MIND (1u<<5)
#define G_FORTUNE (1u<<6)
#define G_FREN (1u<<7)
#define G_REPL (1u<<8)

#define TM(r, x) (TALENTS && ((r)->tmask & (x)))
#define GM(r, x) (TALENTS && ((r)->gmask & (x)))

/* Ledger order: the 12 seeded sources, then first writes */
#define N_AUTO 0
#define N_DG 1
#define N_BS 2
#define N_UF 3
#define N_FS 4
#define N_OUTB 5
#define N_PLAGB 6
#define N_USTRK 7
#define N_BREATH 8
#define N_ARMY 9
#define N_WORMS 10
#define N_SPLASH 11
#define N_SULF 12
#define N_ECHO 13

/* ready[] keys */
#define K_UF 0
#define K_FS 1
#define K_BS 2
#define K_DG 3
#define K_ERW 4

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, armor_pen, armor, spell_mult, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, hp;
  double attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  int nexec, targets, glass, spell_crit;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double ob_e[MAXT][BS + 1], ob_m[MAXT][BS + 1]; int ob_n[MAXT];
  double pl_e[MAXT][BS + 1], pl_m[MAXT][BS + 1]; int pl_n[MAXT];
  double ch_e[MAXT][BS + 1], ch_m[MAXT][BS + 1]; int ch_n[MAXT];
  /* cache per debuff: in-order sum of all shares and the earliest expiry */
  double ob_t[MAXT], ob_lo[MAXT], pl_t[MAXT], pl_lo[MAXT], ch_t[MAXT], ch_lo[MAXT];
  double ready[5];
  int sk[MAXS]; double se[MAXS], sn[MAXS], sr[MAXS]; int ns;
  double mana, mana_time, hp_bonus, frozen, marrow, lm, bt, attack_crit, spell_critf, pb_chance;
  int armed, status, army_count, last_cast, rested;
  AP ap;
} St;

double target_hp(double t) {
  double v = 1.0 - t / FIGHT;
  return (0.0 >= v) ? 0.0 : v;
}

double crit_factor(double chance, double mult) {
  double c = (100.0 <= chance) ? 100.0 : chance;
  c = (0.0 >= c) ? 0.0 : c;
  c = c / 100.0;
  return 1.0 + c * (mult - 1.0);
}

double chance01(double v) {
  double m = (1.0 <= v) ? 1.0 : v;
  return (0.0 >= m) ? 0.0 : m;
}

double exec_factor(const Row* r, double t) {
  double hp = target_hp(t);
  double f = 1.0;
  for (int i = 0; i < r->nexec; i++)
    if (hp <= r->ex_thr[i]) f *= 1.0 + r->ex_pct[i];
  return f;
}

void add_src(St* s, int id, double amount) {
  uint bit = 1u << id;
  if (s->seen & bit) s->src[id] = s->src[id] + amount;
  else { s->seen |= bit; s->ord[s->nord++] = id; s->src[id] = 0.0 + amount; }
}

/* ---- death_knight._Buff ----
   _Buff.mass(now) sums the shares of the points with now <= expiry, in order. While now is not past the
   earliest expiry every point is on, so the sum is the cached in-order sum of all shares: the same bits. */
double bmass(const double* e, const double* m, int n, double tot, double lo, double now) {
  if (now <= lo) return tot;
  double total = 0.0;
  for (int k = 0; k < n; k++)
    if (now <= e[k]) total += m[k];
  return total;
}

void bcache(const double* e, const double* m, int n, double* tot, double* lo) {
  double t = 0.0, l = INFINITY;
  for (int k = 0; k < n; k++) { t += m[k]; if (e[k] < l) l = e[k]; }
  *tot = t; *lo = l;
}

void bsure(double* e, double* m, int* n, double* tot, double* lo, double now, double dur) {
  e[0] = now + dur; m[0] = 1.0; *n = 1;
  *tot = 0.0 + 1.0; *lo = e[0];
}

void bmaybe(double* e, double* m, int* n, double* tot, double* lo, double now, double dur, double p_on, double p_off) {
  double active = bmass(e, m, *n, *tot, *lo, now);
  int c = 0;
  for (int k = 0; k < *n; k++) {
    if (now <= e[k]) { e[c] = e[k]; m[c] = m[k] * (1.0 - p_on); c++; }
  }
  double added = p_on * active + p_off * (1.0 - active);
  double until = now + dur;
  if (c > 0 && e[c - 1] == until) m[c - 1] = m[c - 1] + added;
  else { e[c] = until; m[c] = added; c++; }
  while (c > BS) {
    int k = 0;
    for (int j = 1; j < c - 1; j++) if (m[j] < m[k]) k = j;
    m[k + 1] = m[k + 1] + m[k];
    for (int j = k; j < c - 1; j++) { e[j] = e[j + 1]; m[j] = m[j + 1]; }
    c--;
  }
  *n = c;
  bcache(e, m, c, tot, lo);
}

#define OB_MASS(s, t, now) bmass((s)->ob_e[t], (s)->ob_m[t], (s)->ob_n[t], (s)->ob_t[t], (s)->ob_lo[t], now)
#define PL_MASS(s, t, now) bmass((s)->pl_e[t], (s)->pl_m[t], (s)->pl_n[t], (s)->pl_t[t], (s)->pl_lo[t], now)
#define CH_MASS(s, t, now) bmass((s)->ch_e[t], (s)->ch_m[t], (s)->ch_n[t], (s)->ch_t[t], (s)->ch_lo[t], now)
#define OB_ARGS(s, t) (s)->ob_e[t], (s)->ob_m[t], &(s)->ob_n[t], &(s)->ob_t[t], &(s)->ob_lo[t]
#define PL_ARGS(s, t) (s)->pl_e[t], (s)->pl_m[t], &(s)->pl_n[t], &(s)->pl_t[t], &(s)->pl_lo[t]
#define CH_ARGS(s, t) (s)->ch_e[t], (s)->ch_m[t], &(s)->ch_n[t], &(s)->ch_t[t], &(s)->ch_lo[t]

double armor_mult(St* s, double armor) {
  if (armor > 0.0) return 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor);
  if (armor < 0.0) { if (!s->status) s->status = 4; return 1.0; }
  return 1.0;
}

void recover(const Row* r, St* s, double now) {
  double dt = now - s->mana_time;
  if (dt > 0.0) {
    double v = s->mana + r->mana_regen * dt;
    s->mana = (v < r->mana_max) ? v : r->mana_max;
  }
  s->mana_time = now;
}

double dcs(const Row* r) { return 12.0 + 0.75 * r->str + r->damage; }

double max_life(const Row* r, const St* s) { return r->hp + s->hp_bonus; }

int frost_presence(const Row* r) { return SP_FROST || TM(r, T_DPRES); }
int unholy_presence(const Row* r) { return SP_UNHOLY || TM(r, T_DPRES); }

double potency_now(const Row* r, St* s, double now) {
  double value = r->potency;
  if (unholy_presence(r) && r->mana_max > 0.0) {
    recover(r, s, now);
    value += (s->mana / r->mana_max) * (3.0 + 0.4 * LEVEL);
  }
  return value;
}

double increase(const Row* r, St* s, int t, double now) {
  double bonus = 1.0;
  int is_frozen = (t == 0) && (s->frozen >= now);
  double chilled = CH_MASS(s, t, now);
  if (is_frozen) bonus += 0.15;
  else bonus += 0.08 * chilled;
  if (TM(r, T_GRIM)) {
    double count = PL_MASS(s, t, now) + OB_MASS(s, t, now) + (is_frozen ? 1.0 : 0.0) + chilled;
    if (t == 0 && s->marrow >= now) count += 1.0;
    bonus += 0.06 * count;
  }
  return bonus;
}

double typed(const Row* r, St* s, int magical, double now) {
  double bonus = 1.0 + (magical ? r->magic_add : r->phys_add);
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(now);
  if (magical) {
    if (r->mask & S_TLUM) bonus += 0.05 + 0.005 * r->mastery;
    if (frost_presence(r)) {
      recover(r, s, now);
      bonus += 0.01 * (s->mana / 40.0);
    }
    if (TM(r, T_BFORGE)) bonus += 0.05 + 0.01 * (r->armor + (TM(r, T_MARROW) ? 4.0 : 0.0));
  }
  if (r->glass) bonus *= 1.15;
  return bonus;
}

double taken(const Row* r, St* s, int t, double now) {
  double armor = 15.0 - r->armor_pen;
  if (t == 0 && s->marrow >= now) armor -= 5.0;
  return armor_mult(s, armor);
}

double plague_flat(const Row* r, St* s, int t, double now) {
  double on = PL_MASS(s, t, now);
  if (on <= 0.0) return 0.0;
  double value = 2.0 + RANK;
  if (TM(r, T_DECOMP)) value += 3.0 + 0.08 * dcs(r);
  return value * on;
}

void outbreak_on(const Row* r, St* s, int t, double now, double p_on, double p_off) {
  if (SP_UNHOLY) {
    double burst = OB_MASS(s, t, now) * p_on;
    if (burst > 0.0) {
      double raw = 20.0 + 0.015 * max_life(r, s) * s->bt;
      double execute = exec_factor(r, now);
      double amount = raw * increase(r, s, t, now) * taken(r, s, t, now) * execute;
      add_src(s, N_PLAGB, amount * burst);
    }
  }
  bmaybe(OB_ARGS(s, t), now, 8.0, p_on, p_off);
}

void after_hit(const Row* r, St* s, int t, double now, double procs, int on_only) {
  if (SP_UNHOLY && procs > 0.0) {
    double p_on = chance01(s->pb_chance * procs);
    double p_off = on_only ? 0.0 : chance01(0.5 * s->pb_chance * procs);
    outbreak_on(r, s, t, now, p_on, p_off);
  }
}

void note_damage_mana(const Row* r, St* s, double count) {
  if (r->damage_mana_pct != 0.0) {
    double v = s->mana + r->damage_mana_pct * r->mana_max * count;
    s->mana = (v < r->mana_max) ? v : r->mana_max;
  }
}

double deal(const Row* r, St* s, int name, double raw, int t, double now, int magical, double potency_scale,
            double weight, double procs, int on_only) {
  double pot = potency_now(r, s, now);
  double amount = raw + pot * potency_scale + plague_flat(r, s, t, now);
  double ty = typed(r, s, magical, now);
  amount *= ty * increase(r, s, t, now);
  amount *= magical ? s->spell_critf : s->attack_crit;
  double execute = exec_factor(r, now);
  amount *= taken(r, s, t, now) * execute;
  add_src(s, name, amount * weight);
  note_damage_mana(r, s, procs);
  after_hit(r, s, t, now, procs, on_only);
  return amount;
}

double summon_hit(const Row* r, St* s, int name, double raw, int t, double now, double weight) {
  double execute = exec_factor(r, now);
  double pf = plague_flat(r, s, t, now);
  double amount = (raw + pf) * increase(r, s, t, now) * taken(r, s, t, now) * execute;
  add_src(s, name, amount * weight);
  after_hit(r, s, t, now, weight, 0);
  return amount;
}

void unholy_strikes(const Row* r, St* s, double now) {
  if (TM(r, T_USTRK)) {
    for (int k = 0; k < 2; k++) deal(r, s, N_USTRK, 15.0 + 0.40 * r->str, 0, now, 1, 1.0, 1.0, 1.0, 0);
  }
}

void razorice(const Row* r, St* s, double now, double chance) {
  if (TM(r, T_RAZOR)) {
    double v = s->ready[K_FS] - 0.30 * chance;
    s->ready[K_FS] = (v > now) ? v : now;
  }
}

void ghoul_proc(const Row* r, St* s, double now, double g) {
  double on = OB_MASS(s, 0, now);
  if (s->frozen >= now) {
    outbreak_on(r, s, 0, now, g, g);
  } else {
    double p_chill = g * on + 0.5 * g * (1.0 - on);
    outbreak_on(r, s, 0, now, 0.0, 0.5 * g);
    bmaybe(CH_ARGS(s, 0), now, 4.0, p_chill, p_chill);
  }
}

double cooldown_of(double base, const Row* r, double flat) {
  double v = (base * r->cd_temp - r->flat_cdr - flat) / (1.0 + r->haste);
  return (v > 0.5) ? v : 0.5;
}

void add_summon(St* s, int kind, double end, double next, double raw) {
  if (s->ns >= MAXS) { if (!s->status) s->status = 2; return; }
  s->sk[s->ns] = kind; s->se[s->ns] = end; s->sn[s->ns] = next; s->sr[s->ns] = raw; s->ns++;
}

void cast_spell(const Row* r, St* s, int key, double now) {
  if (r->mask & S_SULF) { if (!s->armed) s->armed = 1; }
  double hit = now + CAST_POINT;
  double life = max_life(r, s);
  const int targets = r->targets;
  if (key == K_DG) {
    double raw = 20.0 + 10.0 * LEVEL + 0.10 * life * s->bt;
    if (TM(r, T_OBLIT)) raw += 0.75 * dcs(r);
    deal(r, s, N_DG, raw, 0, hit, 1, 1.0, 1.0, 1.0, 0);
    recover(r, s, hit);
    double v = s->mana + 0.05 * r->mana_max;
    s->mana = (v < r->mana_max) ? v : r->mana_max;
    unholy_strikes(r, s, hit);
  } else if (key == K_BS) {
    double raw = 70.0 * RANK - 10.0 + 0.10 * life * s->bt;
    if (TM(r, T_OBLIT)) raw += 0.75 * dcs(r);
    if (r->mask & S_MAW) {
      double healing = (60.0 * RANK - 40.0) + 0.10 * life * s->bt;
      if (r->mask & S_SIPH) healing *= 2.0;
      raw += 0.35 * healing;
    }
    deal(r, s, N_BS, raw, 0, hit, 1, 1.0, 1.0, 1.0, 0);
    if (!(r->mask & S_MAW)) bsure(PL_ARGS(s, 0), hit, 4.0);
    if (TM(r, T_MARROW)) s->marrow = hit + 5.0;
    if (!s->rested) s->hp_bonus += 1.0;
  } else if (key == K_UF) {
    double raw = 50.0 + 0.05 * life * s->bt;
    if (TM(r, T_OBLIT)) raw += 0.50 * dcs(r);
    for (int t = 0; t < targets; t++) {
      deal(r, s, N_UF, raw, t, hit, 1, 1.0, 1.0, 1.0, 0);
      outbreak_on(r, s, t, hit, 1.0, 1.0);
    }
  } else if (key == K_FS) {
    double raw = 70.0 + 0.05 * life * s->bt + 0.15 * r->mana_max;
    if (TM(r, T_LICH)) raw *= 1.20;
    if (TM(r, T_OBLIT)) raw += 1.00 * dcs(r);
    if (SP_FROST) raw = raw * (1.05 + 0.005 * r->mastery) + 0.10 * r->mana_max;
    deal(r, s, N_FS, raw, 0, hit, 1, 1.0, 1.0, 1.0, 0);
    s->frozen = hit + 1.5;
    unholy_strikes(r, s, hit);
    if (TM(r, T_SINDR)) {
      double wyrm = 20.0 + 0.05 * r->mana_max + 0.05 * life * s->bt;
      for (int t = 0; t < targets; t++) {
        if (t == 0 && s->frozen >= hit) {
          deal(r, s, N_BREATH, wyrm * 1.5, t, hit, 1, 1.0, 1.0, 1.0, 0);
        } else {
          deal(r, s, N_BREATH, wyrm, t, hit, 1, 1.0, 1.0, 1.0, 0);
          bsure(CH_ARGS(s, t), hit, 5.0);
        }
      }
    }
  } else if (key == K_ERW) {
    if (s->last_cast >= 0) {
      s->ready[s->last_cast] = now;
      s->rested = (s->last_cast == K_BS);
    }
  }
  if (key != K_ERW) { s->rested = 0; s->last_cast = key; }
  if (TM(r, T_WORMS)) {
    double raw = 5.0 + (double)(long)(0.12 * dcs(r) + 0.005 * life * s->bt);
    add_summon(s, 1, hit + 7.0, hit, raw);
  }
  if (TM(r, T_ARMY) && key != K_ERW) {
    s->army_count += 1;
    if (s->army_count >= 3) {
      s->army_count = 0;
      double raw = 10.0 + (double)(long)(0.35 * dcs(r));
      add_summon(s, 0, hit + 16.0, hit, raw);
    }
  }
}

double fight(const Row* r, int* status) {
  St s;
  s.nord = 0; s.seen = 0u;
  for (int id = 0; id < 12; id++) { s.seen |= 1u << id; s.ord[s.nord++] = id; s.src[id] = 0.0; }
  s.status = 0;
  if (r->targets > MAXT) { *status = 3; return 0.0; }
  s.lm = 1.0 + r->luck;
  s.bt = TM(r, T_BTAP) ? 1.35 : 1.0;
  s.attack_crit = crit_factor(r->crit, 2.0 + r->rating);
  s.spell_critf = r->spell_crit ? crit_factor(r->crit, r->spell_mult + r->rating) : 1.0;
  const int has_erw = !SP_UNHOLY;
  const double drain = 1.5 + 2.0 * LEVEL;
  const int targets = r->targets;
  for (int i = 0; i < MAXT; i++) {
    s.ob_n[i] = 0; s.pl_n[i] = 0; s.ch_n[i] = 0;
    s.ob_t[i] = 0.0; s.pl_t[i] = 0.0; s.ch_t[i] = 0.0; s.ob_lo[i] = INFINITY; s.pl_lo[i] = INFINITY; s.ch_lo[i] = INFINITY;
  }
  s.hp_bonus = 0.0;
  s.mana = r->mana_max; s.mana_time = 0.0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  s.frozen = -1.0; s.marrow = -1.0;
  s.armed = 0; s.army_count = 0; s.last_cast = -1; s.rested = 0; s.ns = 0;
  s.pb_chance = 0.05 * (TM(r, T_PEST) ? 1.25 : 1.0) * s.lm;
  const double ghoul_chance = chance01(0.10 * s.lm);
  const double worm_chance = chance01(0.20 * s.lm);
  const double razor_chance = chance01(0.15 * s.lm);
  const double decomp_chance = chance01(0.20 * s.lm);
  s.ready[K_UF] = 0.0; s.ready[K_FS] = 0.0; s.ready[K_BS] = 0.0; s.ready[K_DG] = 0.0;
  s.ready[K_ERW] = has_erw ? 0.0 : FIGHT + 1.0;
  const double base_cd[5] = {12.0, 8.0, 7.0, 10.0, 14.0};
  const double fs_flat = (TM(r, T_LICH) ? 1.0 : 0.0) + ((r->mask & S_COLD) ? 2.0 : 0.0);
  const double tick_rate = 1.0 + (SP_UNHOLY ? 0.10 + 0.005 * r->mastery : 0.0) + ((r->mask & S_BELT) ? 0.25 : 0.0);
  double next_tick = 1.0 * (1.0 - (0.10 + 0.005 * r->mastery));
  double next_presence = 0.25;
  const double virulent = TM(r, T_VIRUL) ? chance01((0.12 + 0.005 * r->potency) * s.lm) : 0.0;
  const double decomp = (1.0 - virulent) * decomp_chance + virulent * (1.0 - (1.0 - decomp_chance) * (1.0 - decomp_chance));
  const double share = 1.0 / (double)targets;
  double next_attack = 0.0, busy = 0.0;
  int guard = 0;
  while (1) {
    guard += 1;
    if (guard > 200000) break;
    if (s.status) break;
    double mn = s.ready[K_UF];
    for (int k = 1; k < 4; k++) if (s.ready[k] < mn) mn = s.ready[k];
    double spell_at = (mn > busy) ? mn : busy;
    double erw_at = FIGHT + 1.0;
    if (has_erw && s.last_cast >= 0 && s.ready[K_ERW] < FIGHT) {
      double b2 = (s.ready[K_ERW] > busy) ? s.ready[K_ERW] : busy;
      if (s.ready[s.last_cast] - b2 > 2.0) erw_at = b2;
    }
    double summon_at = FIGHT;
    int any = 0;
    for (int k = 0; k < s.ns; k++) {
      if (s.sn[k] < s.se[k]) {
        if (!any || s.sn[k] < summon_at) summon_at = s.sn[k];
        any = 1;
      }
    }
    double moment = next_attack;
    if (spell_at < moment) moment = spell_at;
    if (erw_at < moment) moment = erw_at;
    if (summon_at < moment) moment = summon_at;
    if (next_tick < moment) moment = next_tick;
    if (next_presence < moment) moment = next_presence;
    if (moment >= FIGHT) break;
    {
      int c = 0;
      for (int k = 0; k < s.ns; k++) {
        if (s.sn[k] < s.se[k]) { s.sk[c] = s.sk[k]; s.se[c] = s.se[k]; s.sn[c] = s.sn[k]; s.sr[c] = s.sr[k]; c++; }
      }
      s.ns = c;
    }
    if (moment == next_presence) {
      recover(r, &s, moment);
      if (s.mana >= drain) s.mana = s.mana - drain / 4.0;
      next_presence = moment + 0.25;
      continue;
    }
    if (moment == next_tick) {
      for (int t = 0; t < targets; t++) {
        double on = OB_MASS(&s, t, moment);
        if (on > 0.0) {
          double raw = 5.0 * RANK + 0.008 * max_life(r, &s) * s.bt;
          double times = 1.0 + virulent;
          deal(r, &s, N_OUTB, raw, t, moment, 1, 1.0, on * times, times, 1);
          if (TM(r, T_DECOMP)) {
            double p = on * decomp;
            bmaybe(PL_ARGS(&s, t), moment, 4.0, p, p);
          }
        }
      }
      next_tick = moment + 1.25 / tick_rate;
      continue;
    }
    if (moment == summon_at) {
      for (int k = 0; k < s.ns; k++) {
        if (s.sn[k] != moment) continue;
        if (s.sk[k] == 0) {
          summon_hit(r, &s, N_ARMY, s.sr[k], 0, moment, 1.0);
          if (!SP_BLOOD) ghoul_proc(r, &s, moment, ghoul_chance);
          razorice(r, &s, moment, razor_chance);
          s.sn[k] = moment + 1.65;
        } else {
          for (int t = 0; t < targets; t++) {
            double dealt = summon_hit(r, &s, N_WORMS, s.sr[k], t, moment, share);
            double w = share * worm_chance;
            deal(r, &s, N_WORMS, 2.0 * dealt, t, moment, 1, 0.0, w, w, 0);
          }
          razorice(r, &s, moment, razor_chance);
          s.sn[k] = moment + 1.5;
        }
      }
      continue;
    }
    if (moment == erw_at && erw_at <= next_attack) {
      cast_spell(r, &s, K_ERW, moment);
      busy = moment + CAST_POINT + CAST_BACKSWING + r->cast_lock;
      s.ready[K_ERW] = moment + cooldown_of(14.0, r, 0.0);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    if (moment == spell_at && spell_at <= next_attack) {
      int key = 0;
      double best = (s.ready[0] > busy) ? s.ready[0] : busy;
      for (int k = 1; k < 4; k++) {
        double v = (s.ready[k] > busy) ? s.ready[k] : busy;
        if (v < best) { best = v; key = k; }
      }
      cast_spell(r, &s, key, moment);
      busy = moment + CAST_POINT + CAST_BACKSWING + r->cast_lock;
      double flat = (key == K_FS) ? fs_flat : 0.0;
      s.ready[key] = moment + cooldown_of(base_cd[key], r, flat);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    if (moment == next_attack && next_attack < busy) { next_attack = busy; continue; }
    if (moment == next_attack) {
      recover(r, &s, moment);
      double swing = 2.0 * ((r->mask & S_GALA) ? 1.20 : 1.0);
      ap_attack(&s.ap, moment, r->crit);
      double interval = swing / (1.0 + ap_speed(r->aspd + ap_bonus(&s.ap, moment)));
      deal(r, &s, N_AUTO, dcs(r), 0, moment, 0, r->attack_potency, r->auto_pct, 1.0, 0);
      double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
      if (r->attack_mana_crit != 0.0) {
        double cc = (r->crit < 100.0) ? r->crit : 100.0;
        gain *= 1.0 + cc / 100.0;
      }
      double mv = s.mana + gain;
      s.mana = (mv < r->mana_max) ? mv : r->mana_max;
      razorice(r, &s, moment, 1.0);
      int side = 1 % targets;
      if (r->mask & S_ORB) {
        double splash = (20.0 + 0.35 * r->str) * (double)targets * taken(r, &s, side, moment) * exec_factor(r, moment);
        add_src(&s, N_SPLASH, splash);
        note_damage_mana(r, &s, (double)targets);
      }
      if (r->mask & S_SULF) {
        double execute = exec_factor(r, moment);
        if (s.armed) {
          s.armed = 0;
          double ty = typed(r, &s, 1, moment);
          double splash = r->str * ty * s.spell_critf * taken(r, &s, side, moment) * execute * (double)targets;
          add_src(&s, N_SULF, splash);
          note_damage_mana(r, &s, (double)targets);
        }
        double echo = dcs(r) * taken(r, &s, 0, moment) * execute * (0.10 * (1.0 + r->luck));
        add_src(&s, N_ECHO, echo);
      }
      next_attack = moment + interval;
      continue;
    }
    break;
  }
  if (s.status) { *status = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < s.nord; i++) total += s.src[s.ord[i]];
  return total / FIGHT;
}

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  __global const double* pal; __global const double* base;
} Tab;

int unrank(Tab* T, long index, int* chosen) {
  if (index < 0 || index >= T->total) return 1;
  __global const long* table = T->dp0;
  long rank = index;
  if (index >= T->count_without) { table = T->dp1; rank = index - T->count_without; }
  int item = 0, slots = 6, leg = 0, orb = 0, amp = 0, guard = 0, k = 0;
  while (slots > 0) {
    if (++guard > 100000 || item >= T->npieces || k > 6) return 1;
    long skip = table[IDX(item + 1, slots, leg, orb, amp)];
    if (rank < skip) { item++; continue; }
    rank -= skip;
    int kind = T->pkind[item];
    if (T->pamp[item]) {
      if (amp) return 1;
      chosen[k++] = item; item++; slots--; amp = 1;
      continue;
    }
    if (kind == 1) {
      int took = 0;
      for (int count = 1; count <= slots; count++) {
        long branch = table[IDX(item + 1, slots - count, leg, orb, amp)];
        if (rank < branch) {
          for (int cc = 0; cc < count; cc++) chosen[k++] = item;
          item++; slots -= count; took = 1;
          break;
        }
        rank -= branch;
      }
      if (!took) return 1;
      continue;
    }
    if (kind == 2) { if (leg) return 1; leg = 1; }
    else if (kind == 3) { if (orb) return 1; orb = 1; }
    chosen[k++] = item; item++; slots--;
  }
  return (rank != 0 || k != 6) ? 1 : 0;
}

/* death_knight.stats_of(build) */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double strength = T->base[1], agility = T->base[2], intel = T->base[0];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 0.0;
  double crit = (double)pts[6];
  double rating = 0.0, haste = 0.0, aspd = 0.0, magic_add = 0.0, phys_add = 0.0, mana_flat = 0.0, health_flat = 0.0;
  double armor_pen = 0.0, armor_items = 0.0, auto_pct = 1.0, attack_potency = 1.0, spell_mult = 1.50;
  int spell_crit = 0;
  double luck = 0.01 * (double)pts[9];
  haste += 0.01 * (double)pts[3];
  aspd += 0.02 * (double)pts[4];
  damage += 2.0 * (double)pts[5];
  mana_flat += 20.0 * (double)pts[1];
  ulong mask = 0;
  int n_core = 0, n_sulg = 0, has_shop = 0, has_drop = 0, nexec = 0;
  for (int si = 0; si < 6; si++) {
    int p = chosen[si];
    int f1 = 1;
    for (int j = 0; j < si; j++) if (chosen[j] == p) { f1 = 0; break; }
    first[si] = f1;
    __global const double* f = T->fold + ((long)p * 2 + (f1 ? 0 : 1)) * NF;
    strength = strength + f[2];
    strength = strength + f[3];
    agility = agility + f[4];
    agility = agility + f[5];
    intel = intel + f[0];
    intel = intel + f[1];
    strength = strength + f[6];
    potency += f[7];
    mastery += f[8];
    damage += f[9];
    crit += f[11];
    rating += f[12];
    haste += f[13];
    aspd += f[14];
    ulong m = T->pmask[p];
    mask |= m;
    if (m & S_CORE) n_core++;
    if (m & S_SULG) n_sulg++;
    if (T->psrc[p] == 1) has_shop = 1;
    else if (T->psrc[p] == 2) has_drop = 1;
    if (f1) {
      __global const double* u = T->uniq + (long)p * NU;
      __global const double* a = T->pal + (long)p * NPAL;
      magic_add += a[0];
      phys_add += a[1];
      magic_add += a[2];
      phys_add += a[2];
      if (a[4] == 0.0) { magic_add += a[3]; phys_add += a[3]; }
      armor_pen += u[3];
      armor_items += a[13];
      if (u[11] != 0.0) spell_crit = 1;
      if (u[12] != 0.0) spell_mult = 1.65;
      if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
      auto_pct += u[8];
      if (u[2] != 0.0) attack_potency = 2.0;
      mana_flat += f[10];
      for (int j = 0; j < 4; j++) luck += a[5 + j];
      for (int j = 0; j < 4; j++) health_flat += a[9 + j];
    }
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) strength += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  if (GM(r, G_UNSL) && !(mask & S_UNSI)) { magic_add += 0.18; phys_add += 0.18; }
  if (GM(r, G_FORTUNE)) luck += 0.15;
  health_flat += 375.0;
  double hp = (T->base[3] + 15.0 * strength) + health_flat;
  double agility_speed = 0.004 * agility;
  agility_speed = (1.0 <= agility_speed) ? 1.0 : agility_speed;
  double sp = aspd + agility_speed;
  sp = (sp > -0.8) ? sp : -0.8;
  aspd = (4.0 <= sp) ? 4.0 : sp;
  double flat_cdr = GM(r, G_MIND) ? 0.20 : 0.0;
  if (mask & S_FLSK) flat_cdr += 0.50;
  if (mask & S_I03C) flat_cdr += 0.50;
  if (mask & S_I00L) flat_cdr += 1.50;
  if (mask & S_I00Y) flat_cdr -= 1.00;
  double cd_temp = 1.0;
  if (mask & S_HARN) cd_temp *= 0.92;
  if (mask & S_ATIE) cd_temp *= 0.87;
  cd_temp *= 1.0 + 0.12 * (double)n_core + 0.10 * (double)n_sulg;
  double mana_max = 120.0 + 7.0 * intel + mana_flat;
  double cast_lock = 0.0, regen_rate = 0.0, mp5 = 0.0;
  double persec = 0.0, aflat = 0.0, apct = 0.0, dpct = 0.0;
  int acrit = 0;
  for (int si = 0; si < 6; si++) {
    if (!first[si]) continue;
    __global const double* u = T->uniq + (long)chosen[si] * NU;
    cast_lock += u[1];
    regen_rate += u[14];
    for (int j = 0; j < 4; j++) mp5 += u[15 + j];
    for (int j = 0; j < 4; j++) persec += u[31 + j];
    for (int j = 0; j < 4; j++) aflat += u[35 + j];
    for (int j = 0; j < 4; j++) apct += u[39 + j];
    if (u[43] != 0.0) acrit = 1;
    for (int j = 0; j < 4; j++) dpct += u[44 + j];
  }
  double stat = (1.20 + 0.10 * intel) * (1.0 + regen_rate);
  stat += mp5 / 5.0;
  stat += persec * mana_max;
  if (GM(r, G_REPL)) stat += 1.50 + 0.0075 * mana_max;
  r->str = strength; r->agi = agility; r->intel = intel; r->potency = potency; r->mastery = mastery; r->damage = damage;
  r->crit = crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->magic_add = magic_add; r->phys_add = phys_add; r->armor_pen = armor_pen;
  r->armor = (3.0 + 0.1 * agility) + armor_items;
  r->spell_crit = spell_crit; r->spell_mult = spell_mult;
  r->auto_pct = auto_pct; r->attack_potency = attack_potency;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock; r->hp = hp;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->nexec = nexec; r->targets = targets;
  r->glass = (GM(r, G_GLASS) || (mask & S_GLAS)) ? 1 : 0;
}

double row_value(Tab* T, long index, uint tmask, uint gmask, const int* pts, int targets, int* status, int* group) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row r;
  sheet(T, &r, chosen, tmask, gmask, pts, targets, group);
  return fight(&r, status);
}

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    __global const double* pal, __global const double* base

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.pal = pal; T.base = base;

__kernel void cls_bare(const long start, const int n, const int targets, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = 0;
  int status = 0, group = 0;
  double d = row_value(&T, start + gid, 0u, 0u, pts, targets, &status, &group);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
}

__kernel void cls_rows(const int n, const int targets, __global const long* chunks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, __global const int* tlpoints, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0;
  double d = row_value(&T, chunks[gid], tmasks[gid], gmasks[gid], pts, targets, &status, &group);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
}
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "tlum": 4, "I0JA": 5, "I096": 6, "I03C": 7, "I00L": 8,
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I07T": 14, "I0NM": 15, "I0NK": 16, "I0RZ": 17,
    "I0QN": 18,
}
TALENT_BITS = {
    "I0CS": 0, "I0E3": 1, "I0CR": 2, "I09S": 3, "I0GP": 4, "I09T": 5, "I0IZ": 6, "I0EV": 7, "I03X": 8,
    "I0CV": 9, "I0IY": 10, "I0DS": 11, "I07Z": 12, "I03W": 13, "I05O": 14,
    # death_knight.IGNORED_TALENTS: no effect on the fight
    "I0CU": 20, "I0G9": 21, "I03G": 22, "I0MD": 23, "I0MC": 24,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"frost": 0, "blood": 1, "unholy": 2}


def death_knight_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the strength primary fold and the Death Knight per-piece columns."""
    import re

    from sunken_sim import death_knight as D, pressure, shadow
    from sunken_sim.stacking import stack_fields

    if (D.WHITE_BASE, D.SWING, D.BASE_MANA, D.BASE_HP, D.BASE_ARMOR, D.AGI_ARMOR, D.RANK, D.BLOOD_STRIKE_STACKS,
            D.DEATH_GRIP_CD, D.ERW_CD, D.BLOOD_STRIKE_CD, D.UNHOLY_FURY_CD, D.FROST_STRIKE_CD, D.OUTBREAK_TIME,
            D.BLOOD_PLAGUE_TIME, D.MARROW_TIME, D.MARROW_ARMOR, D.BONE_SHIELD_ARMOR, D.FREEZE_TIME, D.CHILL_TIME,
            D.GHOUL_CHILL, D.GHOUL_TIME, D.GHOUL_SWING, D.WORM_TIME, D.WORM_SWING, D.BLOOD_TAP, D.PRESENCE_STEP,
            D.BUFF_SLOTS) != \
            (12.0, 2.0, 120.0, 310.0, 3.0, 0.1, 1, 375, 10.0, 14.0, 7.0, 12.0, 8.0, 8.0, 4.0, 5.0, 5.0, 4.0, 1.5, 5.0,
             4.0, 16.0, 1.65, 7.0, 1.5, 1.35, 0.25, 8):
        raise ValueError("kernel constants assume the 2026-11-12 death knight")
    if (shadow.CAST_POINT, shadow.CAST_BACKSWING, pressure.STR_HP) != (0.15, 0.30, 15.0):
        raise ValueError("kernel constants assume cast point 0.15, backswing 0.30 and 15 health per strength")
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(D.BASE_INT), float(D.BASE_STR), float(D.BASE_AGI), float(D.BASE_HP)], "Death Knight")
    pieces = space.pieces
    n = len(pieces)
    fold = t["fold"].reshape(n, 2, C.NF).copy()
    pal = np.zeros((n, NPAL), dtype=np.float64)
    cv = shadow._copy_value
    for i, piece in enumerate(pieces):
        item = items[piece.code]
        code = item.rawcode
        bonus = stack_fields(code)
        for state, first in ((0, True), (1, False)):
            if first:
                prim = bonus["primary"] if (bonus.get("primary") and not item.strength and not item.all_stats) else 0.0
            else:
                prim = bonus.get("primary", 0)
            fold[i, state, 6] = prim
            fold[i, state, 13] = cv(code, "haste", item.haste, first) / 100
        lucks = [shadow.item_luck(item)]
        health = [float(int(raw)) for raw in re.findall(r"\+(\d+) Health\b", item.tip)]
        pal[i] = [
            shadow.MAGICAL_ADDS.get(code, 0.0),
            shadow.PHYSICAL_ADDS.get(code, 0.0),
            item.source_pct / 100.0,
            item.damage_pct / 100.0 - item.source_pct / 100.0,
            1.0 if (code in shadow.MAGICAL_ADDS or code in shadow.PHYSICAL_ADDS) else 0.0,
            *C.pad(lucks, 0.0, "luck", code),
            *C.pad(health, 0.0, "health", code),
            float(getattr(item, "armor", 0) or 0),
            0.0,
            0.0,
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class DeathKnightCL(C.ExactCL):
    hero = "death_knight"
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ()  # no timeline cache: every ESC trial is its own fight
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "pal", "base")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32}

    @staticmethod
    def module():
        from sunken_sim import death_knight

        return death_knight

    def tables(self, space, items, sources):
        return death_knight_tables(space, items, sources)

    def timeline_key(self, build):
        # death_knight.simulate has no fight cache: every trial is scored on its own points
        from dataclasses import fields

        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points"))


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
