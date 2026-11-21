"""Exact float64 OpenCL kernel for Mage fights (Fire, Frost, Arcane): the bare scan and the refinement.

One work-item scores one fight: unrank the six items of a chunk, fold the sheet
the way ``sunken_sim.shadow.character`` + ``sunken_sim.mage.sheet`` do (talents,
glyphs and ESC points included), run ``sunken_sim.mage.simulate`` for the job's
spec (every Diamond Ring binding), compile the events in the order of
``mage._compile`` and score them as ``mage._score``.

* ``MageCL.bare`` - item-only DPS of a range of chunks (the admission scan).
* ``MageCL.rows`` - arbitrary (chunk, talents, glyphs, ESC points) fights.
* ``MageCL.refine`` - ``farm.score.finish_sextuple`` (talents, then glyphs,
  then greedy ESC) with every fight on the device, same order, same ties.

The farm worker below (``eval_span``, ``preflight``, ``run_job``) also drives
the Priest engine of ``farm.hybrid.priest_cl``: ``make_engine`` picks the
engine by hero, and each engine module brings its own ``self_check``.

Exactness: float64 everywhere, ``FP_CONTRACT OFF`` (no fused multiply-add),
the operation order of the Python oracle, ``pow`` values precomputed by the
host Python.  A fight the kernel cannot reproduce (event queue or hydra
overflow, negative armour, out-of-order health query) returns a non-zero
status and is re-scored by the Python oracle on the host.
"""

from __future__ import annotations

import itertools
import os
import sys

import numpy as np

from farm.hybrid import attack_procs_cl as AP

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 fire, 1 frost, 2 arcane (one program per spec) */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_FIRE (SPEC == 0)
#define SP_FROST (SPEC == 1)
#define SP_ARCANE (SPEC == 2)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXT 8
#define MAXQ 64
/* Lava Spawn adds a fractional hydra on almost every hit; item-only fights add three per cast. */
#if TALENTS
#define MAXH 1024
#else
#define MAXH 64
#endif
#define MAXE 6
#define NF 15
#define NU 49
#define NB 11
#define NP 11

/* item specials (piece mask) */
#define S_RING  (1UL<<0)
#define S_SULF  (1UL<<1)
#define S_FORB  (1UL<<2)
#define S_GIRD  (1UL<<3)
#define S_PADS  (1UL<<4)
#define S_STAF  (1UL<<5)
#define S_MANT  (1UL<<6)
#define S_REDI  (1UL<<7)
#define S_HOOD  (1UL<<8)
#define S_GLOV  (1UL<<9)
#define S_FELO  (1UL<<10)
#define S_FURN  (1UL<<11)
#define S_BLOO  (1UL<<12)
#define S_CRIM  (1UL<<13)
#define S_MASK  (1UL<<14)
#define S_GALA  (1UL<<15)
#define S_SULG  (1UL<<16)
#define S_FLSK  (1UL<<17)
#define S_I03C  (1UL<<18)
#define S_I00L  (1UL<<19)
#define S_I00Y  (1UL<<20)
#define S_HARN  (1UL<<21)
#define S_ATIE  (1UL<<22)
#define S_SOUL  (1UL<<23)
#define S_TLUM  (1UL<<24)
#define S_CORE  (1UL<<25)

/* talents */
#define T_GREATER (1u<<0)
#define T_FROSTB  (1u<<1)
#define T_FREEZEB (1u<<2)
#define T_LANCE   (1u<<3)
#define T_SURGE   (1u<<4)
#define T_BURNING (1u<<5)
#define T_LAVA    (1u<<6)
#define T_NOVA    (1u<<7)
#define T_BOLT    (1u<<8)
#define T_OVERP   (1u<<9)
#define T_AMPL    (1u<<10)
#define T_BLAZE   (1u<<11)
#define T_SPLINT  (1u<<12)
#define T_PYROM   (1u<<13)
#define T_ARCH    (1u<<14)
#define T_START   (1u<<15)
#define T_SHARDS  (1u<<16)

/* glyphs */
#define G_FORT  (1u<<0)
#define G_UNSL  (1u<<1)
#define G_SUPR  (1u<<2)
#define G_FREN  (1u<<3)
#define G_HELL  (1u<<4)
#define G_THUN  (1u<<5)
#define G_BLOOD (1u<<6)
#define G_ANIM  (1u<<7)
#define G_GLASS (1u<<8)
#define G_MIND  (1u<<9)
#define G_REPL  (1u<<10)
#define G_FORTUNE (1u<<11)

#define TM(r, x) (TALENTS && ((r)->tmask & (x)))
#define GM(r, x) (TALENTS && ((r)->gmask & (x)))

/* event kinds (compile) */
#define K_AUTO 0
#define K_SPLASH 1
#define K_SULF 2
#define K_ECHO 3
#define K_HELL 4
#define K_PYRO 5
#define K_HYDRA 6
#define K_CLEAVE 7
#define K_B0 8
#define K_BOMB 8
#define K_BURST 9
#define K_FIREBOMB 10
#define K_RING 11
#define K_BLAST 12
#define K_NOVA 13
#define K_LANCE 14
#define K_BOLT 15
#define K_BOLTSPL 16
#define K_THUNDER 17
#define K_BLIZ 18

/* pending events */
#define E_SWING 0
#define E_FIN0 1
#define E_BOMB 5
#define E_RING 6
#define E_HYDRA 7
#define E_BOLT2 8
#define E_HELL 9
#define E_WAVE 10
#define E_MANA 11

#define B_LB 0
#define B_HY 1
#define B_AB 2
#define B_RF 3

typedef struct {
  double intel, str, potency, mastery, ad, mana_max, crit, rating, haste, aspd;
  double crit_as, crit_as_dur, spell_mult, flat_cdr, cd_temp, stun_ps, cast_lock;
  double attack_potency, auto_pct, armor_pen, soul_rate, stab_chance, stab_ratio, luck;
  double attack_base, mana_regen, cast_refund, cast_refund_flat, cast_refund_mastery;
  double attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double bomb_period, mag_sum, phys_sum, flat_health, arch;
  double ex_thr[MAXE], ex_pct[MAXE];
  int spell_crit, nexec, targets, frenzy;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  int trivial, done, last_q;
  double maxh, ceiling, health, next_hit, next_heal; int slot, targets;
} HP;

typedef struct {
  double base[NB], slope[NB], pbase[NB], pslope[NB];
  double auto_w, soul_w, splash, hell_w, hell_raw, blood;
  double pyro_b, pyro_s, pyro_pb, pyro_ps, pyro_mb, pyro_ms, pyro_raw, pyro_rawm;
  double hyd_b, hyd_p, clv_b, clv_p, sulf_b, sulf_s, echo;
} Comp;

typedef struct {
  double hq_w[MAXQ]; uint hq_s[MAXQ]; int hq_k[MAXQ];
  double hy_exp[MAXH], hy_cnt[MAXH];
  double bomb_exp[MAXT], bomb_power[MAXT], chill_exp[MAXT], freeze_exp[MAXT];
  double ready[4], spell_cd[4], costs[4];
  double mana, mana_time, cinder, cinder_chance, lava_chance, blast_cost, crit_until, crit_charge;
  double frenzy_until, frenzy_charge, splinter, hydra_duration, burst_chance;
  double blizzard_until, wave_gap;
  int waves;
  double hero_ready, busy_until, reset;
  uint seq;
  int hn, nh, hydra_ticking, charges, max_charges, armed, status;
  AP ap;
} St;

inline double target_hp(double t) {
  double v = 1.0 - t / FIGHT;
  return (0.0 >= v) ? 0.0 : v;
}

inline double crit_factor(double chance, double mult) {
  double c = (100.0 <= chance) ? 100.0 : chance;
  c = (0.0 >= c) ? 0.0 : c;
  c = c / 100.0;
  return 1.0 + c * (mult - 1.0);
}

inline double armor_taken(double armor, int* status) {
  if (armor > 0.0) return 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor);
  if (armor < 0.0) { *status = 4; return 1.0; }
  return 1.0;
}

/* pressure.hit_time / pressure.slot_hits: dummy j hits at 0.2 * (j % 5 + 1) + k seconds */
inline double hp_hit_time(int slot) { return (double)(slot / 5) + 0.2 * (double)(slot % 5 + 1); }
inline int hp_slot_hits(int slot, int targets) { return targets / 5 + ((slot % 5 < targets % 5) ? 1 : 0); }

void hp_init(HP* h, double str, double flat_health, int crimson, int targets) {
  double cap = crimson ? 0.38 : 1.0;
  double health = (230.0 + 15.0 * str) + flat_health;
  h->last_q = 0; h->done = 0; h->trivial = 0;
  if (health <= 1.0) { h->trivial = 1; return; }
  double mm = rint(health * 1000.0);
  double cm = rint(cap * 1000.0);
  double maxh = mm / 1000.0;
  double heal_cap = cm / 1000.0;
  if (maxh <= 1.0) { h->trivial = 1; return; }
  h->maxh = maxh;
  h->health = maxh;
  h->ceiling = maxh * heal_cap;
  h->targets = targets;
  if (targets <= 0) { h->trivial = 1; return; }
  h->slot = 0;
  while (hp_slot_hits(h->slot, targets) == 0) h->slot++;
  h->next_hit = hp_hit_time(h->slot);
  h->next_heal = 3.0;
}

double hp_ratio(HP* h, double t, int* status) {
  if (h->trivial) return 1.0;
  int q = (int)(t * 100.0 + 1e-6);
  if (q < 0) q = 0;
  if (q > 3000) q = 3000;
  if (q < h->last_q) *status = 5;
  h->last_q = q;
  if (q >= 3000) return 1.0;
  while (!h->done) {
    double moment; int hit;
    if (h->next_hit <= h->next_heal) { moment = h->next_hit; hit = 1; }
    else { moment = h->next_heal; hit = 0; }
    if (moment > FIGHT) { h->done = 1; break; }
    int p = (int)(moment * 100.0 + 1e-6);
    if (p > 3000) p = 3000;
    if (p > q) break;
    if (hit) {
      double hitv = 0.05 * h->maxh;
      double v = h->health - (double)hp_slot_hits(h->slot, h->targets) * hitv;
      h->health = (1.0 >= v) ? 1.0 : v;
      h->slot++;
      while (hp_slot_hits(h->slot, h->targets) == 0) h->slot++;
      h->next_hit = hp_hit_time(h->slot);
    } else {
      if (h->health < h->ceiling) {
        double v = h->health + 0.75 * h->maxh;
        h->health = (h->ceiling <= v) ? h->ceiling : v;
      }
      h->next_heal = h->next_heal + 3.0;
    }
  }
  return h->health / h->maxh;
}

double dealt_factor(Row* r, HP* h, double t, int hc, int* status) {
  if (!(r->mask & (S_FURN | S_MASK | S_CRIM))) return 1.0;
  double ratio = hp_ratio(h, t, status);
  double f = 1.0;
  if ((r->mask & S_FURN) && !hc) f += 0.20 * (1.0 - ratio);
  if (ratio <= 0.40) {
    if (r->mask & S_MASK) f += 0.15;
    if (r->mask & S_CRIM) f += 0.15;
  }
  return f;
}

/* _magic(codes, t, event mana, evocation) -> _magic_factors, then factors(): base + slope * splinter */
void factors(Row* r, double t, double spl, double ev_mana, double* b, double* s) {
  double ta = r->mag_sum;
  if (r->mask & S_SULG) ta += 0.13 + 0.25 * target_hp(t);
  double extra = SP_ARCANE ? (0.08 + ev_mana / 7500.0) : 0.0;
  double bonus = 1.0 + ta + extra;
  double slope = 0.0;
  if (r->mask & S_TLUM) { bonus += 0.05; slope = 0.005; }
  if (GM(r, G_GLASS)) { bonus *= 1.15; slope *= 1.15; }
  *b = bonus + slope * spl;
  *s = slope;
}

double phys(Row* r, double t) {
  double ta = r->phys_sum;
  if (r->mask & S_SULG) ta += 0.13 + 0.25 * target_hp(t);
  double bonus = 1.0 + ta;
  if (GM(r, G_GLASS)) bonus *= 1.15;
  return bonus;
}

double exec_factor(Row* r, double t) {
  double hp = target_hp(t);
  double f = 1.0;
  for (int i = 0; i < r->nexec; i++)
    if (hp <= r->ex_thr[i]) f *= 1.0 + r->ex_pct[i];
  return f;
}

void compile_ev(Row* r, HP* h, Comp* c, double when, int kind, double hits, double raw_w, double pot_w,
                int magical, double spl, double ev_mana, int* status) {
  double dealt = dealt_factor(r, h, when, kind == K_HYDRA || kind == K_CLEAVE, status);
  raw_w *= dealt;
  pot_w *= dealt;
  double b, s;
  if (kind == K_AUTO) {
    double w = exec_factor(r, when) * phys(r, when) * raw_w;
    c->auto_w += w;
    c->soul_w += w * target_hp(when);
  } else if (kind == K_SPLASH) {
    c->splash += raw_w;
  } else if (kind == K_HELL) {
    c->hell_raw = 48.0 * ((hits == 1.0) ? 2.0 : (hits >= 4.0) ? 0.5 : 1.0);
    c->hell_w += raw_w;
  } else if (kind == K_PYRO) {
    double fire_m = SP_FIRE ? 0.0075 : 0.0;
    double coef = 1.0 + fire_m * spl;
    if (magical) {
      factors(r, when, spl, ev_mana, &b, &s);
      c->pyro_b += b * raw_w * coef;
      c->pyro_s += s * raw_w * coef;
      c->pyro_mb += b * raw_w * fire_m;
      c->pyro_ms += s * raw_w * fire_m;
      c->pyro_pb += b * pot_w;
      c->pyro_ps += s * pot_w;
    } else {
      c->pyro_raw += raw_w * coef;
      c->pyro_rawm += raw_w * fire_m;
    }
  } else if (kind == K_HYDRA) {
    c->hyd_b += raw_w; c->hyd_p += pot_w;
  } else if (kind == K_CLEAVE) {
    c->clv_b += raw_w; c->clv_p += pot_w;
  } else if (kind == K_SULF) {
    factors(r, when, spl, ev_mana, &b, &s);
    c->sulf_b += b * raw_w;
    c->sulf_s += s * raw_w;
  } else if (kind == K_ECHO) {
    c->echo += raw_w;
  } else {
    int k = kind - K_B0;
    factors(r, when, spl, ev_mana, &b, &s);
    c->base[k] += b * raw_w;
    c->slope[k] += s * raw_w;
    c->pbase[k] += b * pot_w;
    c->pslope[k] += s * pot_w;
  }
  if (GM(r, G_BLOOD) && kind != K_ECHO) c->blood += dealt;
}

void push(St* s, double when, int kind) {
  if (!(when < FIGHT)) return;
  s->seq += 1;
  if (s->hn >= MAXQ) { s->status = 2; return; }
  int i = s->hn++;
  uint sq = s->seq;
  while (i > 0) {
    int p = (i - 1) >> 1;
    if (when < s->hq_w[p] || (when == s->hq_w[p] && sq < s->hq_s[p])) {
      s->hq_w[i] = s->hq_w[p]; s->hq_s[i] = s->hq_s[p]; s->hq_k[i] = s->hq_k[p];
      i = p;
    } else break;
  }
  s->hq_w[i] = when; s->hq_s[i] = sq; s->hq_k[i] = kind;
}

void pop(St* s, double* when, int* kind) {
  *when = s->hq_w[0];
  *kind = s->hq_k[0];
  int n = --s->hn;
  if (n == 0) return;
  double w = s->hq_w[n]; uint sq = s->hq_s[n]; int k = s->hq_k[n];
  int i = 0;
  while (1) {
    int l = 2 * i + 1;
    if (l >= n) break;
    int rr = l + 1;
    int m = l;
    if (rr < n && (s->hq_w[rr] < s->hq_w[l] || (s->hq_w[rr] == s->hq_w[l] && s->hq_s[rr] < s->hq_s[l]))) m = rr;
    if (s->hq_w[m] < w || (s->hq_w[m] == w && s->hq_s[m] < sq)) {
      s->hq_w[i] = s->hq_w[m]; s->hq_s[i] = s->hq_s[m]; s->hq_k[i] = s->hq_k[m];
      i = m;
    } else break;
  }
  s->hq_w[i] = w; s->hq_s[i] = sq; s->hq_k[i] = k;
}

/* sum(count for expiry, count in hydras if expiry > now) */
double alive(St* s, double now) {
  double t = 0.0;
  for (int i = 0; i < s->nh; i++)
    if (s->hy_exp[i] > now) t += s->hy_cnt[i];
  return t;
}

/* Drop hydras that no later query can count.  Queries happen at hero_ready
   (cast choice) or at the current event time; both only move forward, but
   hero_ready may lag behind the event clock, so the safe horizon is the
   smaller of the two.  The surviving entries keep their order, so every sum
   adds the same numbers in the same order as the Python list. */
void compact_hydras(St* s, double now) {
  double horizon = (s->hero_ready <= now) ? s->hero_ready : now;
  int keep = 0;
  for (int i = 0; i < s->nh; i++) {
    if (s->hy_exp[i] > horizon) {
      s->hy_exp[keep] = s->hy_exp[i];
      s->hy_cnt[keep] = s->hy_cnt[i];
      keep++;
    }
  }
  s->nh = keep;
}

double bite(St* s, Row* r, int idx, double now) {
  if (!TM(r, T_FROSTB)) return 1.0;
  if (s->freeze_exp[idx] > now) return 1.12;
  if (s->chill_exp[idx] > now) return 1.08;
  return 1.0;
}

double bite_all(St* s, Row* r, double now) {
  if (!TM(r, T_FROSTB)) return 1.0;
  double t = 0.0;
  for (int i = 0; i < r->targets; i++) t += bite(s, r, i, now);
  return t / (double)r->targets;
}

double current_as(St* s, Row* r, double now) {
  double v = r->aspd + ap_bonus(&s->ap, now);
  v = (4.0 <= v) ? 4.0 : v;
  v = (-0.8 >= v) ? -0.8 : v;
  return v;
}

double hydra_gap(St* s, Row* r, double now) {
  if (!SP_FIRE) return 1.55;
  return 1.55 / (1.0 + 0.75 * current_as(s, r, now));
}

double swing_base(Row* r, HP* h, double now, int* status) {
  double base = r->attack_base;
  if (r->mask & S_BLOO) {
    double missing = 1.0 - hp_ratio(h, now, status);
    base *= 1.0 - 0.30 * missing;
  }
  return base;
}

double current_swing(St* s, Row* r, HP* h, double now, int* status) {
  double base = swing_base(r, h, now, status);
  if (SP_FIRE) return base;
  return base / (1.0 + current_as(s, r, now));
}

/* reset_chance(): Arcane, Overpowered or Shoulderpads; the mastery part needs Arcane itself */
double reset_chance(St* s, Row* r) {
  if (!SP_ARCANE && !TM(r, T_OVERP) && !(r->mask & S_PADS)) return 0.0;
  double chance = 0.15;
  if (SP_ARCANE) chance += 0.05 + 0.002 * (r->mastery + s->splinter);
  if (r->mask & S_STAF) chance += 0.05;
  return (1.0 <= chance) ? 1.0 : chance;
}

void recover_mana(St* s, Row* r, double now) {
  if (now > s->mana_time && s->mana < r->mana_max) {
    double v = s->mana + r->mana_regen * (now - s->mana_time);
    s->mana = (r->mana_max <= v) ? r->mana_max : v;
  }
  s->mana_time = now;
}

void on_auto(St* s, Row* r, double now) {
  double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
  if (r->attack_mana_crit != 0.0) {
    double cc = (r->crit <= 100.0) ? r->crit : 100.0;
    gain *= 1.0 + cc / 100.0;
  }
  double v = s->mana + gain;
  s->mana = (r->mana_max <= v) ? r->mana_max : v;
  ap_attack(&s->ap, now, r->crit);
}

void spawn_hydras(St* s, Row* r, double now, double count, double duration) {
  double room = 10.0 - alive(s, now);
  double mx = (0.0 >= room) ? 0.0 : room;
  count = (count <= mx) ? count : mx;
  if (count <= 0.0) return;
  if (s->nh >= MAXH) compact_hydras(s, now);
  if (s->nh >= MAXH) { s->status = 3; return; }
  s->hy_exp[s->nh] = now + duration;
  s->hy_cnt[s->nh] = count;
  s->nh++;
  if (!s->hydra_ticking) {
    s->hydra_ticking = 1;
    push(s, now + hydra_gap(s, r, now), E_HYDRA);
  }
}

void add(St* s, Row* r, HP* h, Comp* c, double when, int kind, double hits, double raw_w, double pot_w,
         int disease, int magical) {
  if (when >= FIGHT || hits <= 0.0) return;
  if (r->damage_mana_pct != 0.0) {
    double v = s->mana + r->damage_mana_pct * r->mana_max;
    s->mana = (r->mana_max <= v) ? r->mana_max : v;
  }
  compile_ev(r, h, c, when, kind, hits, raw_w, pot_w, magical, s->splinter, s->mana, &s->status);
  /* gain_cinder(hits, disease, when) */
  int cinder_on = SP_FIRE || TM(r, T_OVERP) || (r->mask & S_PADS);
  if (cinder_on && !disease && s->cinder < 100.0) {
    double v = s->cinder + s->cinder_chance * hits;
    s->cinder = (100.0 <= v) ? 100.0 : v;
  }
  if (TM(r, T_LAVA) && !disease) spawn_hydras(s, r, when, s->lava_chance * hits, s->hydra_duration * 0.5);
}

void start_bomb(St* s, Row* r, int idx, double now, double power) {
  if (s->bomb_exp[idx] <= now) {
    s->bomb_power[idx] = power;
    int any = 0;
    for (int t = 0; t < r->targets; t++) if (s->bomb_exp[t] > now) { any = 1; break; }
    if (!any) push(s, now + r->bomb_period, E_BOMB);
  } else {
    s->bomb_power[idx] = (s->bomb_power[idx] >= power) ? s->bomb_power[idx] : power;
  }
  s->bomb_exp[idx] = now + 8.0;
}

void apply_chill(St* s, Row* r, int idx, double now, double duration, double explicit_freeze) {
  int fresh = s->chill_exp[idx] <= now;
  double v = now + duration;
  s->chill_exp[idx] = (s->chill_exp[idx] >= v) ? s->chill_exp[idx] : v;
  if (explicit_freeze != 0.0) {
    double f = now + explicit_freeze;
    s->freeze_exp[idx] = (s->freeze_exp[idx] >= f) ? s->freeze_exp[idx] : f;
  } else if (TM(r, T_FROSTB) && fresh) {
    double f = now + 1.5;
    s->freeze_exp[idx] = (s->freeze_exp[idx] >= f) ? s->freeze_exp[idx] : f;
  }
  if (TM(r, T_FREEZEB) && s->bomb_exp[idx] <= now) start_bomb(s, r, idx, now, fresh ? 0.20 : 0.08);
  int froze = explicit_freeze > 0.0 || (TM(r, T_FROSTB) && fresh);
  if (TM(r, T_SPLINT)) {
    double sp = s->splinter + (froze ? 4.0 : 2.0);
    s->splinter = (30.0 <= sp) ? 30.0 : sp;
  }
}

void cast_lance(St* s, Row* r, HP* h, Comp* c, double now) {
  if (!TM(r, T_LANCE)) return;
  int idx = 0;
  for (int i = 0; i < r->targets; i++) if (s->chill_exp[i] <= now) { idx = i; break; }
  double taken = bite(s, r, idx, now);
  add(s, r, h, c, now, K_LANCE, 1.0, taken, taken, 0, 0);
  apply_chill(s, r, idx, now, 4.0, 0.0);
}

void finish_blast(St* s, Row* r, HP* h, Comp* c, double now, __global const double* p120, __global const double* p115) {
  int split_on = SP_FIRE || (r->mask & S_GIRD);
  int pyro_on = SP_FIRE || TM(r, T_OVERP);
  int stacks_on = SP_ARCANE || (r->mask & S_GIRD);
  double mult = p120[s->charges];
  double quarter = split_on ? 0.25 : 1.0;
  double taken = bite_all(s, r, now);
  double tg = (double)r->targets;
  if (split_on) add(s, r, h, c, now, K_BLAST, 3.0, 3.0 * taken * mult * quarter, 3.0 * taken, 0, 0);
  int greater = TM(r, T_GREATER) ? 1 : 0;
  if (pyro_on && s->cinder >= (greater ? 50.0 : 30.0)) {
    double spent = s->cinder;
    s->cinder = 0.0;
    add(s, r, h, c, now, K_PYRO, tg, tg * taken * spent, greater ? (tg * taken) : 0.0, 1, greater);
  }
  if (TM(r, T_NOVA)) {
    double chance = (target_hp(now) > 0.90) ? 1.0 : 0.10;
    double weight = tg * chance * taken;
    add(s, r, h, c, now, K_NOVA, weight, weight, weight, 0, 0);
  }
  if (TM(r, T_BOLT)) {
    int chilled = s->chill_exp[0] > now;
    int bombed = s->bomb_exp[0] > now;
    double bonus = (chilled ? 1.25 : 1.0) * (bombed ? 1.25 : 1.0);
    double b0 = bite(s, r, 0, now);
    add(s, r, h, c, now, K_BOLT, 1.0, b0 * bonus, b0 * bonus, 0, 0);
    if (chilled && r->targets > 1) {
      double splash = (tg - 1.0) * taken * bonus * 0.15;
      add(s, r, h, c, now, K_BOLTSPL, tg - 1.0, splash, splash, 0, 0);
    }
    if (chilled && bombed) {
      push(s, now + 0.5, E_BOLT2);
      s->chill_exp[0] = now;
      s->bomb_exp[0] = now;
      s->bomb_power[0] = 0.0;
    }
  }
  add(s, r, h, c, now, K_BLAST, 1.0, taken * mult * quarter, taken, 0, 0);
  if (stacks_on && s->charges < s->max_charges) {
    s->charges += (TM(r, T_SURGE) && s->charges < 3) ? 2 : 1;
    if (s->charges > s->max_charges) s->charges = s->max_charges;
    s->blast_cost = 30.0 * p115[s->charges];
  }
}

void resolve(St* s, Row* r, HP* h, Comp* c, int name, double now, __global const double* p120, __global const double* p115) {
  double tg = (double)r->targets;
  cast_lance(s, r, h, c, now);
  if (GM(r, G_THUN)) {
    double taken = 0.18 * tg * bite_all(s, r, now);
    add(s, r, h, c, now, K_THUNDER, 0.18 * tg, taken, taken, 0, 0);
  }
  if (name == B_LB) {
    int idx = 0;
    for (int t = 1; t < r->targets; t++) if (s->bomb_exp[t] < s->bomb_exp[idx]) idx = t;
    if (s->bomb_exp[idx] > now) {
      double taken = tg * bite_all(s, r, now);
      add(s, r, h, c, now, K_FIREBOMB, tg, taken, taken, 0, 0);
    }
    start_bomb(s, r, idx, now, 1.0);
    if (TM(r, T_FREEZEB)) apply_chill(s, r, idx, now, 4.0, 0.0);
  } else if (name == B_RF) {
    push(s, now + 1.65, E_RING);
  } else if (name == B_HY) {
    if (SP_FIRE) {
      spawn_hydras(s, r, now, 3.0, s->hydra_duration);
    } else if (SP_FROST) {
      s->blizzard_until = now + (double)s->waves * s->wave_gap;
      for (int w = 0; w < s->waves; w++) push(s, now + (double)w * s->wave_gap, E_WAVE);
    } else {
      push(s, now + 1.0, E_MANA);
      push(s, now + 2.0, E_MANA);
      push(s, now + 3.0, E_MANA);
    }
  } else {
    finish_blast(s, r, h, c, now, p120, p115);
  }
}

int choose(St* s, Row* r, double now) {
  int order[4]; int n = 0;
  int lb = 0;
  for (int t = 0; t < r->targets; t++) if (s->bomb_exp[t] < now + 1.0) { lb = 1; break; }
  if (lb) order[n++] = B_LB;
  if (!SP_ARCANE) order[n++] = B_HY;
  order[n++] = B_AB; order[n++] = B_RF;
  int waiting = 0;
  for (int i = 0; i < n; i++) {
    int name = order[i];
    if (s->ready[name] > now) continue;
    if (SP_FROST && name == B_HY && s->blizzard_until > now) continue;
    if (SP_FIRE && name == B_HY && alive(s, now) >= 10.0) continue;
    waiting = 1;
    double cost = (name == B_AB) ? s->blast_cost : s->costs[name];
    if (s->mana >= cost) return name;
  }
  /* Evocation when a ready spell cannot be paid for: affordable() = ready and mana >= 0 */
  if (SP_ARCANE && waiting && !(s->ready[B_HY] > now) && s->mana >= s->costs[B_HY]) return B_HY;
  return -1;
}

void begin_cast(St* s, Row* r, int name, double now) {
  recover_mana(s, r, now);
  double spent = (name == B_AB) ? s->blast_cost : s->costs[name];
  s->mana -= spent;
  double back = spent * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * r->mastery;
  double v = s->mana + back;
  s->mana = (r->mana_max <= v) ? r->mana_max : v;
  double duration = s->spell_cd[name];
  if (r->mask & S_SULF) s->armed = 1;
  s->busy_until = now + CAST_POINT + CAST_BACKSWING + r->cast_lock;
  s->hero_ready = s->busy_until;
  int target = (r->mask & S_REDI) ? B_AB : name;
  double chance = reset_chance(s, r);
  if (target == name) {
    s->ready[name] = now + duration * (1.0 - chance);
  } else {
    s->ready[name] = now + duration;
    double rem = s->ready[target] - now;
    rem = (0.0 >= rem) ? 0.0 : rem;
    s->ready[target] = now + rem * (1.0 - chance);
  }
  push(s, now + CAST_POINT, E_FIN0 + name);
}

double score(Row* r, Comp* c, int* status) {
  double potency = r->potency, crit = r->crit, mastery = r->mastery, intel = r->intel, arch = r->arch;
  double spell_crit = r->spell_crit ? crit_factor(crit, r->spell_mult + r->rating) : 1.0;
  double attack_crit = crit_factor(crit, 2.0 + r->rating);
  double gloves = (r->mask & S_GLOV) ? 1.15 : 1.0;
  double glass = GM(r, G_GLASS) ? 1.15 : 1.0;
  double raws[NB];
  raws[0] = 10.0 + 0.12 * intel * arch;
  raws[1] = 10.0 + 0.12 * intel;
  raws[2] = (40.0 + intel * arch) * (TM(r, T_START) ? 1.25 : 1.0);
  raws[3] = (60.0 + 1.80 * intel * arch) * gloves;
  raws[4] = 80.0 + 2.50 * intel * arch;
  raws[5] = 50.0 + 3.0 * intel * arch;
  raws[6] = 20.0 + 0.50 * intel * arch;
  raws[7] = 20.0 + 0.90 * intel * arch + 50.0;
  raws[8] = raws[7];
  raws[9] = 35.0 + 2.0 * intel;
  raws[10] = (5.0 + 0.50 * intel * arch) * (TM(r, T_SHARDS) ? 1.20 : 1.0);
  double raw_pyro = TM(r, T_GREATER) ? (10.0 + 0.08 * intel * arch) : (10.0 + 0.10 * intel * arch);
  double raw_hydra = 5.0 + floor(0.40 * intel * arch);
  double pen = armor_taken(15.0 - r->armor_pen, status);
  double full = armor_taken(15.0, status);
  double total = 0.0;
  double A = 0.0; int ap = 0;
  double a1 = (r->ad + potency * r->attack_potency) * r->auto_pct * attack_crit * c->auto_w;
  if (a1 != 0.0) { A = A + a1; ap = 1; }
  double a2 = r->soul_rate * 5300.0 * r->auto_pct * attack_crit * c->soul_w;
  if (a2 != 0.0) { A = A + a2; ap = 1; }
  if (ap) total += A * pen;
  double sp = (20.0 + 0.35 * intel) * c->splash;
  if (sp != 0.0) total += sp * pen;
  for (int k = 0; k < NB; k++) {
    double mag = c->base[k] + c->slope[k] * mastery;
    double pot = c->pbase[k] + c->pslope[k] * mastery;
    double amt = spell_crit * (raws[k] * mag + potency * pot);
    if (amt != 0.0) total += amt * pen;
  }
  double pyro_mag = c->pyro_b + c->pyro_s * mastery + (c->pyro_mb + c->pyro_ms * mastery) * mastery;
  double pyro_pot = c->pyro_pb + c->pyro_ps * mastery;
  double P = 0.0; int pp = 0;
  double p1 = spell_crit * (raw_pyro * pyro_mag + potency * pyro_pot);
  if (p1 != 0.0) { P = P + p1; pp = 1; }
  double p2 = raw_pyro * (c->pyro_raw + c->pyro_rawm * mastery);
  if (p2 != 0.0) { P = P + p2; pp = 1; }
  if (pp) total += P * full;
  double hy = glass * (raw_hydra * c->hyd_b + potency * r->attack_potency * c->hyd_p);
  if (hy != 0.0) total += hy * full;
  double cl = glass * (raw_hydra * c->clv_b + potency * r->attack_potency * c->clv_p);
  if (cl != 0.0) total += cl * full;
  double smag = c->sulf_b + c->sulf_s * mastery;
  double su = spell_crit * intel * smag;
  if (su != 0.0) total += su * pen;
  double se = r->ad * c->echo;
  if (se != 0.0) total += se * full;
  if (c->hell_w != 0.0) {
    double hv = (c->hell_raw + potency) * glass * c->hell_w;
    if (hv != 0.0) total += hv * pen;
  }
  if (c->blood != 0.0) {
    double bv = 0.03 * (20.0 + 1.6 * intel + potency) * glass * c->blood;
    if (bv != 0.0) total += bv * pen;
  }
  if (r->stab_chance != 0.0 && c->auto_w != 0.0) {
    double chance = r->stab_chance * (1.0 + r->luck);
    double stab_raw = r->stab_ratio * r->ad;
    double stab = (stab_raw + potency * r->attack_potency) * r->auto_pct * attack_crit * 1.25 * chance * c->auto_w;
    double v = 0.0 + stab * full;
    total += v * full;
  }
  return total;
}

double fight(Row* r, int bound, int* status_out, __global const double* p120, __global const double* p115) {
  St s; HP h; Comp c;
  hp_init(&h, r->str, r->flat_health, (r->mask & S_CRIM) != 0, r->targets);
  double base_cd[4] = {8.0, 13.0, 8.0, 13.0};
  double extra[4] = {0.0, 0.0, 0.0, 0.0};
  if (SP_FIRE && (r->mask & S_FELO)) extra[B_HY] = 3.0;
  if (TM(r, T_AMPL)) extra[B_AB] = 2.0;
  s.costs[B_LB] = 30.0; s.costs[B_HY] = SP_ARCANE ? 0.0 : 40.0; s.costs[B_AB] = 0.0; s.costs[B_RF] = 40.0;
  for (int b = 0; b < 4; b++) {
    double temp = r->cd_temp * ((bound == b) ? 0.70 : 1.0);
    double v = (base_cd[b] * temp - r->flat_cdr - extra[b]) / (1.0 + r->haste);
    s.spell_cd[b] = (0.5 >= v) ? 0.5 : v;
    s.ready[b] = 0.0;
  }
  s.cinder_chance = (0.20 + ((r->mask & S_STAF) ? 0.05 : 0.0)) * (1.0 + r->luck);
  s.lava_chance = 0.02 * (1.0 + r->luck);
  s.max_charges = TM(r, T_SURGE) ? 8 : 3;
  s.hydra_duration = TM(r, T_BURNING) ? 14.0 : 10.0;
  s.burst_chance = 0.15 + (TM(r, T_BLAZE) ? 0.15 : 0.0);
  s.reset = 0.0;
  /* Iceflow Mantle raises the wave count; the gap stays 1 / (1 + haste) */
  double wave_haste = (r->mask & S_MANT) ? (1.20 + r->haste) : (1.0 + r->haste);
  s.waves = (int)(5.0 * wave_haste + 0.50);
  s.wave_gap = 1.0 / (1.0 + r->haste);
  s.blizzard_until = 0.0;
  s.mana = r->mana_max; s.mana_time = 0.0; s.crit_until = 0.0; s.crit_charge = 0.0;
  s.frenzy_until = 0.0; s.frenzy_charge = 0.0; s.splinter = 0.0;
  ap_init(&s.ap, r->frenzy ? frenzy_chance(r->luck) : 0.0, r->crit_as, r->crit_as_dur);
  s.blast_cost = 30.0; s.charges = 0; s.cinder = 0.0;
  for (int t = 0; t < MAXT; t++) { s.bomb_exp[t] = 0.0; s.bomb_power[t] = 0.0; s.chill_exp[t] = 0.0; s.freeze_exp[t] = 0.0; }
  s.nh = 0; s.hydra_ticking = 0; s.hero_ready = 0.0; s.busy_until = 0.0; s.armed = 0;
  s.hn = 0; s.seq = 0; s.status = 0;
  for (int k = 0; k < NB; k++) { c.base[k] = 0.0; c.slope[k] = 0.0; c.pbase[k] = 0.0; c.pslope[k] = 0.0; }
  c.auto_w = 0.0; c.soul_w = 0.0; c.splash = 0.0; c.hell_w = 0.0; c.hell_raw = 0.0; c.blood = 0.0;
  c.pyro_b = 0.0; c.pyro_s = 0.0; c.pyro_pb = 0.0; c.pyro_ps = 0.0; c.pyro_mb = 0.0; c.pyro_ms = 0.0;
  c.pyro_raw = 0.0; c.pyro_rawm = 0.0;
  c.hyd_b = 0.0; c.hyd_p = 0.0; c.clv_b = 0.0; c.clv_p = 0.0; c.sulf_b = 0.0; c.sulf_s = 0.0; c.echo = 0.0;
  double tg = (double)r->targets;

  push(&s, 0.0, E_SWING);
  if (GM(r, G_HELL)) push(&s, 0.0, E_HELL);
  while (s.hn > 0 && !s.status) {
    double event_time = s.hq_w[0];
    while (s.hero_ready <= event_time && s.hero_ready < FIGHT) {
      double now = s.hero_ready;
      recover_mana(&s, r, now);
      int name = choose(&s, r, now);
      if (name < 0) break;
      begin_cast(&s, r, name, now);
    }
    double when; int kind;
    pop(&s, &when, &kind);
    if (when >= FIGHT) break;
    recover_mana(&s, r, when);
    if (kind == E_SWING) {
      if (when < s.busy_until) {
        push(&s, s.busy_until, E_SWING);
      } else {
        on_auto(&s, r, when);
        double taken = bite_all(&s, r, when);
        add(&s, r, &h, &c, when, K_AUTO, 1.0, taken, taken, 0, 0);
        if (r->mask & S_SULF) {
          if (s.armed) {
            s.armed = 0;
            add(&s, r, &h, &c, when, K_SULF, tg, tg, 0.0, 0, 0);
          }
          double echo = 0.10 * (1.0 + r->luck);
          add(&s, r, &h, &c, when, K_ECHO, echo, echo, 0.0, 0, 0);
        }
        if (r->mask & S_FORB) add(&s, r, &h, &c, when, K_SPLASH, tg, tg, tg, 0, 0);
        double hr = when + r->stun_ps;
        s.hero_ready = (s.hero_ready >= hr) ? s.hero_ready : hr;
        push(&s, when + current_swing(&s, r, &h, when, &s.status) + r->stun_ps, E_SWING);
      }
    } else if (kind >= E_FIN0 && kind < E_FIN0 + 4) {
      resolve(&s, r, &h, &c, kind - E_FIN0, when, p120, p115);
    } else if (kind == E_BOMB) {
      int act_i[MAXT]; double act_p[MAXT]; int na = 0;
      for (int t = 0; t < r->targets; t++)
        if (s.bomb_exp[t] > when && s.bomb_power[t] > 0.0) { act_i[na] = t; act_p[na] = s.bomb_power[t]; na++; }
      if (na) {
        for (int a = 0; a < na; a++) {
          double power = act_p[a];
          double taken = power * bite(&s, r, act_i[a], when);
          add(&s, r, &h, &c, when, K_BOMB, power, taken, taken, 0, 0);
          double burst = s.burst_chance * power * tg * bite_all(&s, r, when);
          add(&s, r, &h, &c, when, K_BURST, s.burst_chance * power * tg, burst, burst, 0, 0);
        }
        push(&s, when + r->bomb_period, E_BOMB);
      }
    } else if (kind == E_RING) {
      double freeze_for = (r->mask & S_GLOV) ? 3.0 : 2.0;
      for (int t = 0; t < r->targets; t++) {
        int already = s.chill_exp[t] > when;
        double taken = bite(&s, r, t, when);
        add(&s, r, &h, &c, when, K_RING, 1.0, taken, taken, 0, 0);
        apply_chill(&s, r, t, when, 3.5, already ? freeze_for : 0.0);
      }
    } else if (kind == E_BOLT2) {
      double taken = bite(&s, r, 0, when);
      add(&s, r, &h, &c, when, K_BOLT, 1.0, taken, taken, 0, 0);
    } else if (kind == E_HYDRA) {
      double count = alive(&s, when);
      if (count <= 0.0) {
        s.hydra_ticking = 0;
      } else {
        double bitten = bite_all(&s, r, when);
        double primary = count * bitten * (TM(r, T_BURNING) ? 1.20 : 1.0);
        double others = (double)((r->targets - 1 > 0) ? r->targets - 1 : 0);
        double cleave = count * 0.20 * others * bitten;
        add(&s, r, &h, &c, when, K_HYDRA, count, primary, primary, 0, 0);
        if (cleave != 0.0) add(&s, r, &h, &c, when, K_CLEAVE, count * others, cleave, cleave, 0, 0);
        push(&s, when + hydra_gap(&s, r, when), E_HYDRA);
      }
    } else if (kind == E_HELL) {
      double taken = tg * bite_all(&s, r, when);
      add(&s, r, &h, &c, when, K_HELL, tg, taken, taken, 0, 0);
      push(&s, when + 1.25, E_HELL);
    } else if (kind == E_WAVE) {
      for (int t = 0; t < r->targets; t++) {
        double taken = bite(&s, r, t, when);
        add(&s, r, &h, &c, when, K_BLIZ, 1.0, taken, taken, 0, 0);
        apply_chill(&s, r, t, when, 3.0, 0.0);
      }
    } else if (kind == E_MANA) {
      s.mana += 0.10 * (r->mana_max - s.mana);
    }
  }
  int st = s.status;
  double total = score(r, &c, &st);
  if (st) *status_out = st;
  return total / FIGHT;
}

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  int nmag; __global const int* mag_kind; __global const int* mag_id; __global const double* mag_amt;
  int nphy; __global const int* phy_kind; __global const int* phy_id; __global const double* phy_amt;
  __global const double* p120; __global const double* p115; __global const double* base;
} Tab;

/* farm chunk -> six piece ids; 0 on success */
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
      int taken = 0;
      for (int count = 1; count <= slots; count++) {
        long branch = table[IDX(item + 1, slots - count, leg, orb, amp)];
        if (rank < branch) {
          for (int cc = 0; cc < count; cc++) chosen[k++] = item;
          item++; slots -= count; taken = 1;
          break;
        }
        rank -= branch;
      }
      if (!taken) return 1;
      continue;
    }
    if (kind == 2) { if (leg) return 1; leg = 1; }
    else if (kind == 3) { if (orb) return 1; orb = 1; }
    chosen[k++] = item; item++; slots--;
  }
  return (rank != 0 || k != 6) ? 1 : 0;
}

int present(Tab* T, int kind, int id, const int* chosen, uint tmask, uint gmask) {
  if (kind == 0) { for (int si = 0; si < 6; si++) if (chosen[si] == id) return 1; return 0; }
  if (kind == 1) return (gmask >> id) & 1u;
  return (tmask >> id) & 1u;
}

/* shadow.character(build, mage bases, white 11, bake_timed_buffs=False) + mage.sheet */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double intel = T->base[0], strength = T->base[1], agility = T->base[2];
  /* ESC: health, mana, healing, haste, attack_speed, damage, crit, potency, mastery, luck, pet */
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 2.0 * (double)pts[5];
  double mana = 20.0 * (double)pts[1];
  double crit = (double)pts[6];
  double rating = 0.0;
  double haste = 0.01 * (double)pts[3];
  double aspd = 0.02 * (double)pts[4];
  ulong mask = 0;
  int n_core = 0, n_sulg = 0, sc = 0, sc65 = 0, has_shop = 0, has_drop = 0;
  for (int si = 0; si < 6; si++) {
    int p = chosen[si];
    int f1 = 1;
    for (int j = 0; j < si; j++) if (chosen[j] == p) { f1 = 0; break; }
    first[si] = f1;
    __global const double* f = T->fold + ((long)p * 2 + (f1 ? 0 : 1)) * NF;
    intel = intel + f[0];
    intel = intel + f[1];
    strength = strength + f[2];
    strength = strength + f[3];
    agility = agility + f[4];
    agility = agility + f[5];
    intel = intel + f[6];
    potency += f[7];
    mastery += f[8];
    damage += f[9];
    mana += f[10];
    crit += f[11];
    rating += f[12];
    haste += f[13];
    aspd += f[14];
    ulong m = T->pmask[p];
    mask |= m;
    if (m & S_CORE) n_core++;
    if (m & S_SULG) n_sulg++;
    __global const double* u = T->uniq + (long)p * NU;
    if (u[11] != 0.0) sc = 1;
    if (u[12] != 0.0) sc65 = 1;
    if (T->psrc[p] == 1) has_shop = 1;
    else if (T->psrc[p] == 2) has_drop = 1;
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  if (GM(r, G_FORT)) intel += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  damage = 11.0 + 0.75 * intel + damage;
  mana = 175.0 + 7.0 * intel + mana;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  double agility_speed = 0.004 * agility;
  agility_speed = (1.0 <= agility_speed) ? 1.0 : agility_speed;
  double asum = aspd + agility_speed;
  asum = (4.0 <= asum) ? 4.0 : asum;
  aspd = (-0.8 >= asum) ? -0.8 : asum;
  double attack_base = 2.0 * ((mask & S_GALA) ? 1.20 : 1.0);
  double flat_cdr = 0.0;
  if (GM(r, G_MIND)) flat_cdr += 0.20;
  if (mask & S_FLSK) flat_cdr += 0.50;
  if (mask & S_I03C) flat_cdr += 0.50;
  if (mask & S_I00L) flat_cdr += 1.50;
  if (mask & S_I00Y) flat_cdr -= 1.00;
  double cd_temp = 1.0;
  if (mask & S_HARN) cd_temp *= 0.92;
  if (mask & S_ATIE) cd_temp *= 0.87;
  double cd_inc = 1.0;
  cd_inc += 0.12 * (double)n_core;
  cd_inc += 0.10 * (double)n_sulg;
  cd_temp *= cd_inc;

  double stun_ps = 0.0, cast_lock = 0.0, armor_pen = 0.0, crit_as = 0.0, crit_as_dur = 0.0;
  double stab_ch = 0.0, stab_ra = 0.0, auto_pct = 1.0, flat_h = 0.0, regen_rate = 0.0, mp5 = 0.0;
  double keep = 1.0, rflat = 0.0, rmast = 0.0, persec = 0.0, aflat = 0.0, apct = 0.0, dpct = 0.0;
  int dap = 0, acrit = 0, nexec = 0;
  for (int si = 0; si < 6; si++) {
    if (!first[si]) continue;
    __global const double* u = T->uniq + (long)chosen[si] * NU;
    stun_ps += u[0];
    cast_lock += u[1];
    if (u[2] != 0.0) dap = 1;
    armor_pen += u[3];
    crit_as += u[4];
    crit_as_dur = (crit_as_dur >= u[5]) ? crit_as_dur : u[5];
    stab_ch += u[6];
    stab_ra = (stab_ra >= u[7]) ? stab_ra : u[7];
    auto_pct += u[8];
    if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
    flat_h += u[13];
    regen_rate += u[14];
    for (int j = 0; j < 4; j++) mp5 += u[15 + j];
    for (int j = 0; j < 4; j++) keep *= u[19 + j];
    for (int j = 0; j < 4; j++) rflat += u[23 + j];
    for (int j = 0; j < 4; j++) rmast += u[27 + j];
    for (int j = 0; j < 4; j++) persec += u[31 + j];
    for (int j = 0; j < 4; j++) aflat += u[35 + j];
    for (int j = 0; j < 4; j++) apct += u[39 + j];
    if (u[43] != 0.0) acrit = 1;
    for (int j = 0; j < 4; j++) dpct += u[44 + j];
  }
  double mag_sum = 0.0, phys_sum = 0.0;
  for (int e = 0; e < T->nmag; e++)
    if (present(T, T->mag_kind[e], T->mag_id[e], chosen, tmask, gmask)) mag_sum += T->mag_amt[e];
  for (int e = 0; e < T->nphy; e++)
    if (present(T, T->phy_kind[e], T->phy_id[e], chosen, tmask, gmask)) phys_sum += T->phy_amt[e];
  double stat = (1.20 + 0.10 * intel) * (1.0 + regen_rate);
  stat += mp5 / 5.0;
  stat += persec * mana;
  if (GM(r, G_REPL)) stat += 1.50 + 0.0075 * mana;
  double arch = TM(r, T_ARCH) ? 1.35 : 1.0;
  if (TM(r, T_PYROM)) potency += 3.0 + 0.05 * intel * arch;
  double period = 0.75;
  if (TM(r, T_BLAZE)) period /= 1.15 + (0.50 * potency) / 100.0;
  if (mask & S_HOOD) period /= 1.25;

  r->intel = intel; r->str = strength; r->potency = potency; r->mastery = mastery; r->ad = damage;
  r->mana_max = mana; r->crit = (100.0 <= crit) ? 100.0 : crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->crit_as = crit_as; r->crit_as_dur = crit_as_dur; r->spell_mult = sc65 ? 1.65 : 1.50;
  r->flat_cdr = flat_cdr; r->cd_temp = cd_temp; r->stun_ps = stun_ps; r->cast_lock = cast_lock;
  r->attack_potency = dap ? 2.0 : 1.0; r->auto_pct = auto_pct; r->armor_pen = armor_pen;
  r->soul_rate = (mask & S_SOUL) ? 0.003 : 0.0; r->stab_chance = stab_ch; r->stab_ratio = stab_ra;
  double luck = 0.01 * (double)pts[9];
  for (int si = 0; si < 6; si++) if (first[si]) luck += T->uniq[(long)chosen[si] * NU + 48];
  if (GM(r, G_FORTUNE)) luck += 0.15;
  r->luck = luck;
  r->attack_base = attack_base; r->mana_regen = stat * 0.80;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->bomb_period = period; r->mag_sum = mag_sum; r->phys_sum = phys_sum; r->flat_health = flat_h; r->arch = arch;
  r->spell_crit = sc; r->nexec = nexec; r->targets = targets; r->frenzy = GM(r, G_FREN) ? 1 : 0;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
}

double row_dps(Tab* T, long index, uint tmask, uint gmask, const int* pts, int targets, int* status, int* group) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row r;
  sheet(T, &r, chosen, tmask, gmask, pts, targets, group);
  double best = 0.0;
  if (r.mask & S_RING) {
    int first = 1;
    for (int b = 0; b < 4; b++) {
      if (SP_ARCANE && b == B_HY) continue;
      double d = fight(&r, b, status, T->p120, T->p115);
      if (first || d > best) best = d;
      first = 0;
    }
  } else {
    best = fight(&r, -1, status, T->p120, T->p115);
  }
  return best;
}

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    const int nmag, __global const int* mag_kind, __global const int* mag_id, __global const double* mag_amt, \
    const int nphy, __global const int* phy_kind, __global const int* phy_id, __global const double* phy_amt, \
    __global const double* p120, __global const double* p115, __global const double* base

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.nmag = nmag; T.mag_kind = mag_kind; T.mag_id = mag_id; T.mag_amt = mag_amt; \
  T.nphy = nphy; T.phy_kind = phy_kind; T.phy_id = phy_id; T.phy_amt = phy_amt; \
  T.p120 = p120; T.p115 = p115; T.base = base;

__kernel void fire_bare(const long start, const int n, const int targets, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = 0;
  int status = 0, group = 0;
  double d = row_dps(&T, start + gid, 0u, 0u, pts, targets, &status, &group);
  out_dps[gid] = d;
  out_group[gid] = (uchar)group;
  out_status[gid] = (uchar)status;
}

__kernel void fire_rows(const int n, const int targets, __global const long* chunks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0;
  double d = row_dps(&T, chunks[gid], tmasks[gid], gmasks[gid], pts, targets, &status, &group);
  out_dps[gid] = d;
  out_group[gid] = (uchar)group;
  out_status[gid] = (uchar)status;
}
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I00D": 0, "I0BR": 1, "I07O": 2, "I0UX": 3, "I0UY": 4, "I0UW": 5, "I0UU": 6, "I0UV": 7,
    "I0UR": 8, "I0UT": 9, "I0US": 10, "I079": 11, "I05N": 12, "I024": 13, "arsc": 14, "I0JO": 15,
    "I0QT": 16, "I096": 17, "I03C": 18, "I00L": 19, "I00Y": 20, "I07P": 21, "I048": 22, "I03L": 23,
    "tlum": 24, "I0FW": 25,
}
TALENT_BITS = {
    "I0UQ": 0, "I0KT": 1, "I0Q7": 2, "I0QA": 3, "I0KV": 4, "I0NZ": 5, "I0UP": 6, "I0KP": 7,
    "I0UO": 8, "I0QB": 9, "I0O0": 10, "I0KR": 11, "I0Q9": 12, "I0KQ": 13, "I0KU": 14, "I0KS": 15,
    "I0KO": 16,
}
GLYPH_BITS = {
    "I07B": 0, "I0AV": 1, "I0EK": 2, "I0GZ": 3, "I0H3": 4, "I0H5": 5, "I0H6": 6, "I0HC": 7,
    "I0JA": 8, "I0OF": 9, "I0H0": 10, "I0EJ": 11,
}
# Codes the mage oracle never reads: picking them changes nothing in the fight.
NO_EFFECT = {"I0EN", "I0Q8"}
# Codes the oracle reads through _has() but the kernel does not model (other heroes' talents).
UNSUPPORTED_CODES = {"I0SA", "I0PU", "I0PS", "I0Q9_ARCANE"}
GROUP_NAMES = {0: None, 1: "shop", 2: "drop", 3: "shop_random"}
NF = 15
NU = 49
NP = 11
MULTI = 4


def _pad(values, fill, what, code):
    values = list(values)
    if len(values) > MULTI:
        raise ValueError(f"{code}: more than {MULTI} {what} entries in the tooltip")
    return values + [fill] * (MULTI - len(values))


def tables(space, items: dict, sources: dict) -> dict:
    """Per-piece arrays in the exact form the kernel folds. Pure function of the catalog."""
    from sunken_sim import mage, shadow
    from sunken_sim.stacking import stack_fields

    pieces = space.pieces
    codes = [p.code for p in pieces]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate rawcodes in the chunk space")
    if space.slots != 6:
        raise ValueError("kernel expects six slots")
    if shadow.LEVEL != 15 or mage.FIGHT != 30.0:
        raise ValueError("kernel constants assume shadow.LEVEL 15 and a 30 s fight")
    clash = set(codes) & (set(TALENT_BITS) | set(GLYPH_BITS) | UNSUPPORTED_CODES)
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
        if code in SPECIAL_BITS:
            pmask[i] = np.uint64(1 << SPECIAL_BITS[code])
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
            sum(float(match) for match in mage._FLAT_HEALTH.findall(tip)),
            shadow._MANA_REGEN_RATE.get(code, 0.0),
        ]
        row += _pad([float(m.replace(",", ".")) for m in shadow._MP5.findall(tip)], 0.0, "mp5", code)
        row += _pad(keep, 1.0, "refund", code)
        row += _pad([tn(raw) for raw in shadow._REFUND_FLAT.findall(tip)], 0.0, "flat refund", code)
        row += _pad([tn(raw) / 100.0 for raw in shadow._REFUND_MASTERY.findall(tip)], 0.0, "mastery refund", code)
        row += _pad(per_second, 0.0, "mana per second", code)
        row += _pad(attack_flat, 0.0, "attack mana", code)
        row += _pad(attack_pct, 0.0, "attack mana pct", code)
        row += [1.0 if ("doubled for Critical Strikes" in tip and shadow._ATTACK_MANA.search(tip)) else 0.0]
        row += _pad([tn(raw) / 100.0 for raw in shadow._DAMAGE_MANA.findall(tip)], 0.0, "damage mana", code)
        row += [shadow.item_luck(item)]
        if len(row) != NU:
            raise AssertionError(len(row))
        uniq[i] = row
    index = {code: i for i, code in enumerate(codes)}

    def entries(table):
        out = []
        for c, a in table.items():
            if c in index:
                out.append((0, index[c], a))
            elif c in GLYPH_BITS:
                out.append((1, GLYPH_BITS[c], a))
            elif c in TALENT_BITS:
                out.append((2, TALENT_BITS[c], a))
        return out

    mag = entries(shadow.MAGICAL_ADDS)
    phy = entries(shadow.PHYSICAL_ADDS)
    for c in list(space.talents) + list(space.glyphs):
        if c not in TALENT_BITS and c not in GLYPH_BITS and c not in NO_EFFECT:
            raise ValueError(f"talent/glyph {c} is not modelled by the Fire kernel")
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
        "p120": np.asarray([1.20 ** k for k in range(9)], dtype=np.float64),
        "p115": np.asarray([1.15 ** k for k in range(9)], dtype=np.float64),
        "base": np.asarray([mage.BASE_INT, mage.BASE_STR, mage.BASE_AGI], dtype=np.float64),
    }


TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
              "nmag", "mag_kind", "mag_id", "mag_amt", "nphy", "phy_kind", "phy_id", "phy_amt", "p120", "p115", "base")
SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32, "nmag": np.int32, "nphy": np.int32}


def _import_cl():
    try:
        import pyopencl as cl  # noqa: F401
        return cl
    except ImportError:
        extra = os.environ.get("FARM_FIRE_CL_PATH") or str(
            __import__("pathlib").Path(__file__).resolve().parents[2] / ".gpu-deps"
        )
        if os.path.isdir(extra) and extra not in sys.path:
            sys.path.insert(0, extra)
        import pyopencl as cl
        return cl


def pick_device(cl, want: str | None = None):
    """GPU with cl_khr_fp64 first; FARM_FIRE_CL_DEVICE=cpu|gpu|<substring> overrides."""
    want = (want or os.environ.get("FARM_FIRE_CL_DEVICE", "")).strip().lower()
    found = []
    for platform in cl.get_platforms():
        for device in platform.get_devices():
            if "cl_khr_fp64" not in device.extensions and not device.double_fp_config:
                continue
            found.append(device)
    if not found:
        raise RuntimeError("no OpenCL device with float64 support")

    def is_gpu(d):
        return bool(d.type & cl.device_type.GPU)

    if want in ("cpu",):
        found = [d for d in found if not is_gpu(d)] or found
    elif want and want not in ("gpu", "auto"):
        found = [d for d in found if want in d.name.lower()] or found
    found.sort(key=lambda d: (not is_gpu(d), -d.max_compute_units))
    return found[0]


def talent_mask(codes) -> int:
    mask = 0
    for c in codes:
        if c in NO_EFFECT:
            continue
        mask |= 1 << TALENT_BITS[c]
    return mask


def glyph_mask(codes) -> int:
    mask = 0
    for c in codes:
        if c in NO_EFFECT:
            continue
        mask |= 1 << GLYPH_BITS[c]
    return mask


SPECS = {"fire": 0, "frost": 1, "arcane": 2}


class MageCL:
    """Compiled kernels plus device-resident catalog tables for one Mage spec and chunk space."""

    hero = "mage"

    def __init__(self, space, items: dict, sources: dict, targets: int, device=None, spec: str = "fire") -> None:
        if spec not in SPECS:
            raise ValueError(f"mage spec {spec!r} is not modelled by the kernel")
        cl = _import_cl()
        self.cl = cl
        self.spec = spec
        self.space = space
        self.items = items
        self.device = device or pick_device(cl)
        self.ctx = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.ctx)
        # Two builds of one source: the item-only scan compiles every talent and glyph branch out.
        opts = ["-cl-std=CL1.2", f"-DSPEC={SPECS[spec]}"]
        self.p_bare = cl.Program(self.ctx, KERNEL).build(options=opts + ["-DTALENTS=0"])
        self.p_full = cl.Program(self.ctx, KERNEL).build(options=opts + ["-DTALENTS=1"])
        self.k_bare = cl.Kernel(self.p_bare, "fire_bare")
        self.k_rows = cl.Kernel(self.p_full, "fire_rows")
        self.targets = int(targets)
        if not 1 <= self.targets <= 8:
            raise ValueError("kernel supports 1..8 targets")
        self.t = tables(space, items, sources)
        mf = cl.mem_flags
        self.tab_args = []
        for key in TABLE_KEYS:
            value = self.t[key]
            if key in SCALARS:
                self.tab_args.append(SCALARS[key](value))
            else:
                self.tab_args.append(cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=value))
        self._cap = 0
        self.name = f"{self.device.name.strip()} ({self.device.platform.name.strip()})"
        self.counts = {"bare_rows": 0, "rows": 0, "oracle_rows": 0, "refined": 0}

    def _ensure(self, n: int) -> None:
        if n <= self._cap:
            return
        cl = self.cl
        mf = cl.mem_flags
        self._cap = max(n, 1 << 16)
        self.out_dps = cl.Buffer(self.ctx, mf.WRITE_ONLY, 8 * self._cap)
        self.out_group = cl.Buffer(self.ctx, mf.WRITE_ONLY, self._cap)
        self.out_status = cl.Buffer(self.ctx, mf.WRITE_ONLY, self._cap)

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
        """(dps float64[n], group uint8[n], status uint8[n]) for item-only chunks [start, start+n)."""
        self._ensure(n)
        self.k_bare.set_args(np.int64(start), np.int32(n), np.int32(self.targets), *self.tab_args,
                             self.out_dps, self.out_group, self.out_status)
        self.cl.enqueue_nd_range_kernel(self.queue, self.k_bare, (n,), None)
        self.counts["bare_rows"] += n
        return self._read(n)

    def rows(self, chunks, tmasks, gmasks, points):
        """DPS of explicit fights: chunk, talent mask, glyph mask, ESC points (ESC_ATTRS order)."""
        cl = self.cl
        n = len(chunks)
        if n == 0:
            return np.empty(0), np.empty(0, np.uint8), np.empty(0, np.uint8)
        self._ensure(n)
        mf = cl.mem_flags
        c = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.asarray(chunks, dtype=np.int64))
        t = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.asarray(tmasks, dtype=np.uint32))
        g = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.asarray(gmasks, dtype=np.uint32))
        p = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR,
                      hostbuf=np.ascontiguousarray(np.asarray(points, dtype=np.int32).reshape(n, NP)))
        self.k_rows.set_args(np.int32(n), np.int32(self.targets), c, t, g, p, *self.tab_args,
                             self.out_dps, self.out_group, self.out_status)
        cl.enqueue_nd_range_kernel(self.queue, self.k_rows, (n,), None)
        self.counts["rows"] += n
        return self._read(n)

    def oracle_bare(self, chunk: int) -> float:
        return oracle(self.space, self.items, self.targets, chunk, self.spec)

    def scores(self, chunk: int, builds: list) -> list[float]:
        """Exact DPS for (talents, glyphs, points dict) of one chunk; oracle for declined rows."""
        from sunken_sim.esc import ESC_ATTRS

        chunks = [chunk] * len(builds)
        tm = [talent_mask(t) for t, _g, _p in builds]
        gm = [glyph_mask(g) for _t, g, _p in builds]
        pts = [[int(p.get(a, 0)) for a in ESC_ATTRS] for _t, _g, p in builds]
        dps, _group, status = self.rows(chunks, tm, gm, pts)
        out = [float(v) for v in dps]
        for j in np.nonzero((status != 0) | ~np.isfinite(dps))[0]:
            out[int(j)] = oracle_fight(self.space, self.items, self.targets, chunk, *builds[int(j)], spec=self.spec)
            self.counts["oracle_rows"] += 1
        return out

    def refine(self, chunk: int, equipped: tuple, talent_codes, glyph_codes, picks_without, picks_with, glyph_picks):
        """farm.score.finish_sextuple for this Mage spec, every fight on the device."""
        from sunken_sim.esc import ESC_ATTRS, ESC_CAP, empty_points, points_payload
        from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS

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
        # sunken_sim.esc.greedy_points, one device launch per step
        counts = empty_points()
        pointed = self.scores(chunk, [(best_talents, best_glyphs, counts)])[0]
        for _ in range(SKILL_POINTS):
            names = [a for a in ESC_ATTRS if counts[a] < ESC_CAP]
            trials = []
            for name in names:
                trial = dict(counts)
                trial[name] += 1
                trials.append((best_talents, best_glyphs, trial))
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
        fights = len(combos) + len(gcombos) + SKILL_POINTS * len(ESC_ATTRS)
        return pointed, best_talents, best_glyphs, points_payload(counts), fights


def FireCL(space, items: dict, sources: dict, targets: int, device=None) -> MageCL:
    """Fire Mage engine (the first spec on the device; kept for callers and tests)."""
    return MageCL(space, items, sources, targets, device=device, spec="fire")


def oracle(space, items: dict, targets: int, index: int, spec: str = "fire") -> float:
    """The Python reference for one chunk: farm.score.item_dps."""
    from farm.score import item_dps

    codes = space.decode(index)[0]
    return item_dps("mage", spec, targets, tuple(items[c] for c in codes))


def oracle_fight(space, items: dict, targets: int, index: int, talents, glyphs, points: dict, spec: str = "fire") -> float:
    """mage.simulate(...).dps for one chunk with talents, glyphs and ESC points."""
    from sunken_sim import mage
    from sunken_sim.esc import apply_points
    from sunken_sim.shadow import Build

    codes = space.decode(index)[0]
    build = apply_points(Build(frozenset(talents), frozenset(glyphs), tuple(items[c] for c in codes), 0, 0, 0, 0), points)
    return mage.simulate(build, targets, spec=spec, use_history=False).dps


def parity(engine: "MageCL", space, items: dict, sources: dict, targets: int, indices) -> dict:
    """Bit-exact comparison of the bare scan against the Python oracle (dps and source group)."""
    from farm.runner import build_group

    bad = []
    fallback = 0
    indices = [int(i) for i in indices]
    for index in indices:
        dps, group, status = engine.bare(int(index), 1)
        ref = oracle(space, items, targets, int(index), getattr(engine, "spec", "fire"))
        if status[0]:
            fallback += 1
            continue
        codes = space.decode(int(index))[0]
        ref_group = build_group([sources.get(c, "drop") for c in codes])
        if float(dps[0]).hex() != float(ref).hex() or GROUP_NAMES[int(group[0])] != ref_group:
            bad.append({"chunk": int(index), "kernel": float(dps[0]), "oracle": float(ref)})
    return {"rows": len(indices), "mismatches": len(bad), "status_rows": fallback,
            "examples": bad[:5], "ok": not bad}


def random_builds(space, count: int, seed: int) -> list:
    """(chunk, talents, glyphs, points) drawn like refinement: legal picks, ESC under cap 20, total <= 30."""
    import random

    from sunken_sim.esc import ESC_ATTRS

    rng = random.Random(seed)
    out = []
    for chunk in sample(space, count, seed):
        codes = space.decode(chunk)[0]
        picks = space.picks_with if "I0IC" in codes else space.picks_without
        talents = tuple(rng.sample(list(space.talents), picks)) if rng.random() < 0.9 else ()
        glyphs = tuple(rng.sample(list(space.glyphs), space.glyph_picks)) if rng.random() < 0.8 else ()
        points = {a: 0 for a in ESC_ATTRS}
        if rng.random() < 0.7:
            for _ in range(rng.randrange(31)):
                a = rng.choice(ESC_ATTRS)
                if points[a] < 20:
                    points[a] += 1
        out.append((chunk, talents, glyphs, points))
    return out


def parity_full(engine: "MageCL", space, items: dict, targets: int, builds) -> dict:
    """Bit-exact comparison of talent/glyph/ESC fights against mage.simulate."""
    from sunken_sim.esc import ESC_ATTRS

    chunks = [b[0] for b in builds]
    dps, _g, status = engine.rows(chunks, [talent_mask(b[1]) for b in builds], [glyph_mask(b[2]) for b in builds],
                                  [[b[3][a] for a in ESC_ATTRS] for b in builds])
    bad = []
    fallback = 0
    for (chunk, talents, glyphs, points), value, st in zip(builds, dps, status):
        if st:
            fallback += 1
            continue
        ref = oracle_fight(space, items, targets, chunk, talents, glyphs, points, spec=getattr(engine, "spec", "fire"))
        if float(value).hex() != float(ref).hex():
            bad.append({"chunk": chunk, "talents": talents, "glyphs": glyphs, "points": {k: v for k, v in points.items() if v},
                        "kernel": float(value), "oracle": float(ref)})
    return {"rows": len(builds), "mismatches": len(bad), "status_rows": fallback, "examples": bad[:5], "ok": not bad}


def sample(space, count: int, seed: int) -> list[int]:
    """Random chunks from both halves (with and without Mind Amplifier)."""
    import random

    rng = random.Random(seed)
    out = []
    for i in range(count):
        if i % 4 == 3 and space.count_with:
            out.append(space.count_without + rng.randrange(space.count_with))
        else:
            out.append(rng.randrange(space.count_without or space.total))
    return sorted(out)


def self_check(engine: "MageCL", space, items: dict, sources: dict, targets: int, rows: int, full: int, seed: int):
    """(bare parity, fight parity) on random chunks and random talent/glyph/ESC fights."""
    check = parity(engine, space, items, sources, targets, sample(space, rows, seed))
    fights = parity_full(engine, space, items, targets, random_builds(space, full, seed + 1))
    return check, fights


OPENCL_SPECS = ({("mage", spec) for spec in SPECS} | {("priest", spec) for spec in ("shadow", "discipline", "holy")}
                | {("shaman", spec) for spec in ("restoration", "enhancement", "elemental")}
                | {("paladin", spec) for spec in ("retribution", "protection", "holy")}
                | {("druid", spec) for spec in ("restoration", "balance")}
                | {("berserker", spec) for spec in ("headhunter", "poison", "fury")}
                | {("death_knight", spec) for spec in ("frost", "blood", "unholy")}
                | {("demon_hunter", spec) for spec in ("havoc", "vengeance", "devourer")}
                | {("dragon_sentinel", spec) for spec in ("ruby", "obsidian", "emerald")}
                | {("feral_druid", spec) for spec in ("primal", "guardian", "savage")}
                | {("hunter", spec) for spec in ("marksmanship", "beast_mastery", "survival")}
                | {("monk", spec) for spec in ("windwalker", "brewmaster", "mistweaver")}
                | {("necromancer", spec) for spec in ("bone", "blood", "essence")})


def make_engine(hero: str, space, items: dict, sources: dict, targets: int, spec: str, device=None):
    """The exact OpenCL engine for a hero/spec (Mage: this module, Priest: farm.hybrid.priest_cl)."""
    if hero == "mage":
        return MageCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "priest":
        from farm.hybrid.priest_cl import PriestCL

        return PriestCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "shaman":
        from farm.hybrid.shaman_cl import ShamanCL

        return ShamanCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "paladin":
        from farm.hybrid.paladin_cl import PaladinCL

        return PaladinCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "druid":  # the caster Druid (sunken_sim.druid); Feral Druid is a separate class, not modelled
        from farm.hybrid.druid_cl import DruidCL

        return DruidCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "berserker":
        from farm.hybrid.berserker_cl import BerserkerCL

        return BerserkerCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "death_knight":
        from farm.hybrid.death_knight_cl import DeathKnightCL

        return DeathKnightCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "demon_hunter":
        from farm.hybrid.demon_hunter_cl import DemonHunterCL

        return DemonHunterCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "dragon_sentinel":
        from farm.hybrid.dragon_sentinel_cl import DragonSentinelCL

        return DragonSentinelCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "feral_druid":
        from farm.hybrid.feral_druid_cl import FeralDruidCL

        return FeralDruidCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "hunter":
        from farm.hybrid.hunter_cl import HunterCL

        return HunterCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "monk":
        from farm.hybrid.monk_cl import MonkCL

        return MonkCL(space, items, sources, targets, device=device, spec=spec)
    if hero == "necromancer":
        from farm.hybrid.necromancer_cl import NecromancerCL

        return NecromancerCL(space, items, sources, targets, device=device, spec=spec)
    raise ValueError(f"no OpenCL engine for {hero}/{spec}")


def engine_module(engine):
    hero = getattr(engine, "hero", "mage")
    if hero == "priest":
        from farm.hybrid import priest_cl

        return priest_cl
    if hero == "shaman":
        from farm.hybrid import shaman_cl

        return shaman_cl
    if hero == "paladin":
        from farm.hybrid import paladin_cl

        return paladin_cl
    if hero == "druid":
        from farm.hybrid import druid_cl

        return druid_cl
    if hero == "berserker":
        from farm.hybrid import berserker_cl

        return berserker_cl
    if hero == "death_knight":
        from farm.hybrid import death_knight_cl

        return death_knight_cl
    if hero == "demon_hunter":
        from farm.hybrid import demon_hunter_cl

        return demon_hunter_cl
    if hero == "dragon_sentinel":
        from farm.hybrid import dragon_sentinel_cl

        return dragon_sentinel_cl
    if hero == "feral_druid":
        from farm.hybrid import feral_druid_cl

        return feral_druid_cl
    if hero == "hunter":
        from farm.hybrid import hunter_cl

        return hunter_cl
    if hero == "monk":
        from farm.hybrid import monk_cl

        return monk_cl
    if hero == "necromancer":
        from farm.hybrid import necromancer_cl

        return necromancer_cl
    return sys.modules[__name__]


# ---------------------------------------------------------------- farm worker
TARGET_LAUNCH_S = 0.25   # stay far below the Windows GPU watchdog (TDR, 2 s)
FIRST_LAUNCH = 4096
MAX_LAUNCH = 1 << 20
WORKER_CHECK_ROWS = 24
WORKER_CHECK_FULL = 24

_ENGINE = None
_ENGINE_NOTE = ""
_LAUNCH = FIRST_LAUNCH
_REFINE = True


def _worker_engine():
    """One OpenCL context per worker process, self-checked against the oracle once."""
    global _ENGINE, _ENGINE_NOTE, _REFINE
    from farm import runner as R

    if _ENGINE is not None and (_ENGINE.hero, _ENGINE.spec, _ENGINE.space) != (R._HERO, R._SPEC, R._SPACE):
        _ENGINE, _ENGINE_NOTE, _REFINE = None, "", True  # another job in this process
    if _ENGINE is not None or _ENGINE_NOTE:
        return _ENGINE

    tag = f"{R._HERO}-{R._SPEC}-opencl"
    try:
        engine = make_engine(R._HERO, R._SPACE, R._ITEMS, R._SOURCES, R._TARGETS, R._SPEC)
        check, full = engine_module(engine).self_check(engine, R._SPACE, R._ITEMS, R._SOURCES, R._TARGETS,
                                                       WORKER_CHECK_ROWS, WORKER_CHECK_FULL, os.getpid())
        if not check["ok"]:
            raise RuntimeError(f"worker self-check mismatch: {check['examples'][:2]}")
        if not full["ok"]:
            if not getattr(engine, "PYTHON", True):
                raise RuntimeError(f"fixture self-check mismatch: {full['examples'][:2]}")
            _REFINE = False
            print(f"{tag}: refinement self-check mismatch, refinement stays on CPU: {full['examples'][:1]}", flush=True)
        _ENGINE = engine
        print(f"{tag} worker pid={os.getpid()} device={engine.name} self-check "
              f"{check['rows']}+{full['rows']} fights exact", flush=True)
    except Exception as exc:  # exact CPU span path below
        _ENGINE_NOTE = f"OpenCL unavailable in worker: {type(exc).__name__}: {exc}"
        print(f"{tag}: " + _ENGINE_NOTE, flush=True)
    return _ENGINE


def _floors(snapshot: dict) -> tuple[float, float, float]:
    from farm import admission as A

    def floor(key):
        rows = (snapshot or {}).get(key) or []
        return -np.inf if len(rows) < A.LIMIT else min(float(r["dps"]) for r in rows)

    return floor("overall"), floor("shop"), floor("drop")


def candidates(dps: np.ndarray, group: np.ndarray, snapshot: dict) -> np.ndarray:
    """Rows that can still enter the bare item-only top (10 or 50 per category, farm.admission.LIMIT).

    Category floors only rise (a full top replaces its lowest score), so a
    row at or below a floor taken before its claim is rejected by the claim
    too.  Skipping those claims leaves the gate state identical.
    """
    overall, shop, drop = _floors(snapshot)
    keep = dps > overall
    keep |= (group == 1) & (dps > shop)
    keep |= (group == 2) & (dps > drop)
    return np.nonzero(keep)[0]


def eval_span(start: int, stop: int) -> dict:
    """farm.runner.eval_span with every fight on OpenCL (Mage or Priest). Same payload, same gate."""
    global _LAUNCH
    import time

    from farm import runner as R
    from farm.score import finish_sextuple

    engine = _worker_engine()
    if engine is None:
        payload = R.eval_span(start, stop)
        payload["fire_execution"] = dict(actual="cpu-fallback", gpu_compile_rows=0, cpu_compile_rows=stop - start,
                                         reasons=[_ENGINE_NOTE], pid=os.getpid(), engine_state="cpu")
        return payload
    space = R._SPACE
    hits: list[dict] = []
    fights = 0
    errors = 0
    error = ""
    gpu_rows = 0
    oracle_rows = 0
    cpu_refined = 0
    done = start
    index = start
    while index < stop:
        if R._STOP is not None and R._STOP.is_set():
            break
        n = min(stop - index, _LAUNCH)
        t0 = time.perf_counter()
        dps, group, status = engine.bare(index, n)
        spent = time.perf_counter() - t0
        if spent > 0 and n == _LAUNCH:
            # Grow at most 4x per launch, shrink at once: one launch stays near TARGET_LAUNCH_S.
            _LAUNCH = int(max(1024, min(MAX_LAUNCH, 4 * n, n * TARGET_LAUNCH_S / spent)))
        gpu_rows += n
        redo = np.nonzero((status != 0) | ~np.isfinite(dps))[0]
        for j in redo:  # exact oracle for the rare rows the kernel declines
            chunk = index + int(j)
            codes = space.decode(chunk)[0]
            dps[j] = engine.oracle_bare(chunk)
            g = R.build_group([R._SOURCES.get(c, "drop") for c in codes])
            group[j] = {None: 0, "shop": 1, "drop": 2, "shop_random": 3}[g]
            oracle_rows += 1
        snapshot = R.item_bar_snapshot(*R._BAR) if R._BAR is not None else {}
        interrupted = None
        for j in candidates(dps, group, snapshot):
            chunk = index + int(j)
            if R._STOP is not None and R._STOP.is_set():
                # Rows before this candidate are final (non-candidates are rejected by
                # construction); resume rescans from here and claims it then.
                interrupted = chunk
                break
            bare = float(dps[j])
            group_name = GROUP_NAMES[int(group[j])]
            try:
                if not R.claim_item_bars(bare, group_name, chunk):
                    continue
                codes = space.decode(chunk)[0]
                equipped = tuple(R._ITEMS[c] for c in codes)
                sources = [R._SOURCES.get(item.rawcode, "drop") for item in equipped]
                args = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
                if _REFINE:
                    total, talent_codes, glyph_codes, points, extra = engine.refine(chunk, *args)
                else:
                    total, talent_codes, glyph_codes, points, extra = finish_sextuple(R._HERO, R._SPEC, R._TARGETS, *args)
                    cpu_refined += 1
                fights += extra
                if isinstance(points, dict):
                    esc_full = dict(points)
                else:
                    crit, potency, luck, mastery = points
                    esc_full = {"crit": crit, "potency": potency, "luck": luck, "mastery": mastery}
                hits.append({
                    "dps": total,
                    "item_dps": bare,
                    "fights": extra + 1,
                    "chunk": chunk,
                    "group": group_name,
                    "items": [{"name": item.name, "code": item.rawcode, "source": source}
                              for item, source in zip(equipped, sources)],
                    "talents": sorted(space.talent_names.get(code, code) for code in talent_codes),
                    "glyphs": sorted(space.glyph_names.get(code, code) for code in glyph_codes),
                    "points": esc_full,
                })
            except Exception as exc:
                errors += 1
                if not error:
                    error = f"{chunk}: {exc}"
        if interrupted is not None:
            fights += interrupted - index
            done = interrupted
            break
        fights += n
        index += n
        done = index
    oracle_rows += engine.counts["oracle_rows"]
    engine.counts["oracle_rows"] = 0
    return {
        "start": start, "done": done, "fights": fights, "hits": R._compact(hits), "errors": errors, "error": error,
        "fire_execution": dict(actual="opencl", gpu_compile_rows=gpu_rows, cpu_compile_rows=oracle_rows,
                               reasons=(["refinement on CPU oracle"] if cpu_refined else []),
                               pid=os.getpid(), engine_state="opencl"),
    }


# ---------------------------------------------------------------- job entry
# Refinement (talents, glyphs, greedy ESC) also runs on the device, so a few
# workers keep the GPU busy; spans stay small because admissions bunch at the
# start of the space (200 of 825 Top-80 admissions in the first 100k chunks).
DEFAULT_WORKERS = 4
DEFAULT_SPAN = 16384
PREFLIGHT_ROWS = 256
PREFLIGHT_FULL = 256


def preflight(job: dict) -> dict:
    """Parent-side exact parity on random chunks and fights; the context is released afterwards."""
    import gc
    import time

    from farm.catalog import load
    from farm.runner import source_map

    space, items = load(job["hero"], job["spec"], job["pool"], job.get("preset") or None, job.get("top") or None)
    sources = source_map(items)
    t0 = time.perf_counter()
    engine = make_engine(job["hero"], space, items, sources, int(job["targets"]), job["spec"])
    name = engine.name
    check, full = engine_module(engine).self_check(engine, space, items, sources, int(job["targets"]),
                                                   PREFLIGHT_ROWS, PREFLIGHT_FULL, 15)
    t1 = time.perf_counter()
    engine.bare(0, 4096)
    t2 = time.perf_counter()
    del engine
    gc.collect()
    return dict(ok=check["ok"] and full["ok"], name=name, parity=check, parity_full=full, seconds=round(t1 - t0, 2),
                probe_rows_per_s=round(4096 / max(t2 - t1, 1e-9)))


def workers(job: dict) -> int:
    raw = job.get("fire_cl_workers") or os.environ.get("FARM_FIRE_CL_WORKERS") or DEFAULT_WORKERS
    value = int(raw)
    if not 1 <= value <= 32:
        raise ValueError("fire_cl_workers must be 1..32")
    return value


def span_rows(job: dict) -> int:
    raw = job.get("fire_cl_span") or os.environ.get("FARM_FIRE_CL_SPAN") or DEFAULT_SPAN
    value = int(raw)
    if not 1024 <= value <= (1 << 24):
        raise ValueError("fire_cl_span must be 1024..16777216")
    return value


def run_job(job: dict, box: dict, tick) -> dict:
    """Mage or Priest job with every fight on OpenCL; any preflight failure keeps the hybrid route."""
    from farm import admission as A
    from farm import runner as R

    hero, spec = job.get("hero"), job.get("spec")
    if (hero, spec) not in OPENCL_SPECS:
        raise ValueError("OpenCL backend: mage, priest, shaman, paladin, berserker, death_knight, demon_hunter, dragon_sentinel, feral_druid, hunter, monk, necromancer (three specs each) or druid (restoration, balance)")
    job = dict(job, admission_policy=A.policy(job))
    meta = {"worker": job.get("worker", "local-hybrid"), "status": "opencl", "device": "opencl",
            "name": "", "gpu_fights": True, "backend": f"{hero}-opencl-exact-v3",
            "selection": dict(requested="opencl", selected="opencl", actual="opencl")}
    try:
        checked = preflight(job)
    except Exception as exc:
        checked = dict(ok=False, reason=f"{type(exc).__name__}: {exc}")
    if not checked.get("ok"):
        reason = checked.get("reason") or f"parity failed: {checked.get('parity')} {checked.get('parity_full')}"
        print(f"{hero}-{spec}-opencl preflight failed, hybrid route kept: " + reason, flush=True)
        from farm.hybrid.runner import run_job as hybrid_job
        return hybrid_job(dict(job, fire_backend="hybrid", opencl=False, opencl_fallback=reason), box, tick)
    meta.update(name=checked["name"], preflight=checked)
    job = dict(job, pool_workers=workers(job), span_rows=span_rows(job))
    meta["pool_workers"] = job["pool_workers"]
    meta["span_rows"] = job["span_rows"]
    tick({"hybrid": meta})
    return R.run_job(dict(job, hybrid=dict(meta)), box, tick, eval_fn=eval_span)
