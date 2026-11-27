"""Exact float64 OpenCL kernel for Berserker fights (Headhunter, Poison, Fury).

One work-item scores one fight: unrank the six items, fold the sheet like
the removed ``sunken_sim.berserker.stats_of`` (agility primary, Blood Fury agility from
health, Gift of the Blood God, Hemotoxin, typed adds, luck and health from
tooltips) and run the fight of the removed ``berserker.simulate`` with its Ledger sums in insertion order.

``berserker.simulate`` has no timeline cache, so every row is its own fight.
Two library calls of the sim are not computed on the device:

* ``x ** y`` (Python ``float.__pow__``, the host libm ``pow``) in the Surge of
  Toxins proc chances: looked up by the exact (base, exponent) bits in a table
  that the host fills with its own ``**``; a miss returns status 7 and the
  host adds the value and runs the rows again (like the Priest ``math.exp``);
* the hero health table of ``pressure.hero_hp_ratio`` is replayed exactly on
  the device (91 every 0.2 s, +50 % every 1 s, 0.01 s sampling).
Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 27
POW_MISS = 7
MAX_POW_ROUNDS = 8

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 headhunter, 1 poison, 2 fury */
#ifndef SPEC
#define SPEC 0
#endif
/* REPORT 1: the report kernel also keeps the final fight state (sources in Ledger order, casts, mana) */
#ifndef REPORT
#define REPORT 0
#endif
#define MAXA 64
#define SP_HEAD (SPEC == 0)
#define SP_POISON (SPEC == 1)
#define SP_FURY (SPEC == 2)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 27
#define MAXT 8
#define MAXP 16
#define VK 8
#define NSRC 15
#define NG 8
#define NBM 96
#define LEVEL 15.0
#define TROPHIES 200.0

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
#define S_VENOM (1UL<<14)
#define S_FANAT (1UL<<15)
#define S_SILM (1UL<<16)
#define S_SPIKE (1UL<<17)
#define S_THORN (1UL<<18)
#define S_DSCALE (1UL<<19)
#define S_SUN (1UL<<20)
#define S_SOD (1UL<<21)
#define S_BMASK (1UL<<22)
#define S_SEAL (1UL<<23)
#define S_PCB (1UL<<24)
#define S_ICE (1UL<<25)
#define S_NERUB (1UL<<26)
#define S_EV12 (1UL<<27)
#define S_EV13 (1UL<<28)
#define S_EV16A (1UL<<29)
#define S_EV16B (1UL<<30)
#define S_EV18 (1UL<<31)
#define S_ALE (1UL<<32)
#define S_CRIM (1UL<<33)
#define S_IGM (1UL<<34)
#define S_FURN (1UL<<35)
#define S_BLS (1UL<<36)
#define S_BHOWL (1UL<<37)
#define S_SERA (1UL<<38)
#define S_EVD (1UL<<39)
#define S_BLOOD (1UL<<40)
#define S_TITAN (1UL<<41)
#define S_CSKULL (1UL<<42)
#define S_REDC (1UL<<43)
#define S_GORE (1UL<<44)
#define S_BREAV (1UL<<45)
#define S_FIGUR (1UL<<46)
#define S_SANG (1UL<<47)
#define S_SVAMP (1UL<<48)
#define S_MASO (1UL<<49)
#define S_PRIM (1UL<<50)
#define S_IDRA (1UL<<51)
#define S_JADE (1UL<<52)
#define S_AMBER (1UL<<53)
#define S_EARTH (1UL<<54)
#define S_MOON (1UL<<55)
#define S_HAURA (1UL<<56)
#define S_UNHOLY (1UL<<57)
#define S_CRUS (1UL<<58)
#define S_TRIBAL (1UL<<59)
#define S_SERAPH (1UL<<60)
#define S_HIGHL (1UL<<61)
#define S_HOLYS (1UL<<62)
#define S_GIANT (1UL<<63)
/* Builds where incoming hits change the damage (otherwise the hit stream is not run at all) */
#define HP_DEP (S_FANAT | S_ALE | S_CRIM | S_IGM | S_FURN | S_BLS | S_BHOWL | S_BLOOD)
#define HIT_DEP (S_SPIKE | S_THORN | S_DSCALE | S_SUN | S_SOD | S_BMASK | S_SEAL | S_PCB | S_ICE | S_EVD)

#define T_AXE (1u<<0)
#define T_DAMBALA (1u<<1)
#define T_BERSERK (1u<<2)
#define T_EXEC (1u<<3)
#define T_DEADLY (1u<<4)
#define T_BOMB (1u<<5)
#define T_BONE (1u<<6)
#define T_CRAZE (1u<<7)
#define T_LEECH (1u<<8)
#define T_BLADES (1u<<9)
#define T_BHUNT (1u<<10)
#define T_SNAKE (1u<<11)
#define T_WOUND (1u<<12)
#define T_HEMO (1u<<13)
#define T_GIFT (1u<<14)

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

/* Ledger order: the 8 seeded sources, then first writes */
#define N_AUTO 0
#define N_SACK 1
#define N_SKULL 2
#define N_VA 3
#define N_SURGE 4
#define N_SNAKE 5
#define N_AXE 6
#define N_SPLASH 7
#define N_SULF 8
#define N_ECHO 9
#define N_REFL 10
#define N_SUNS 11
#define N_SOD 12
#define N_EVADE 13
#define N_BLOOD 14

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, hemo, armor_pen, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, hp;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  double spell_mult;
  /* healing that changes the damage, the DamageIncrease pool */
  double regen, regen_pct, heal_power, lifesteal, recv_mod, own_extra, ht_atk_pct, ht_atk_flat, heal_flat, heal_flat_int;
  double heal_pot, pool_flat, voodoo, armor_hero, regen_hp;
  int nexec, targets, glass, spell_crit;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  __global const ulong* pkb; __global const ulong* pke; __global const double* pv; int np;
} PowT;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double va_e[MAXT][VK], va_m[MAXT][VK]; int va_n[MAXT];
  double surge_p[MAXT], surge_at[MAXT];
  double pend[MAXP]; int npend;
  double mana, mana_time, lm;
  /* incoming hits (expected values): dummy j attacks at db[j] + 0.5 k with mass dm[j][k] */
  double hp_max, hp_health, hp_next_heal, hp_cap; int hp_on, hits_on;
  double db[MAXT], dm[MAXT][NG];
  double dinc;
  double bz_end, bz_stacks;              /* Berserk B03J window and stacks */
  double bm_t[NBM], bm_q[NBM]; int bm_n;  /* Battlemask rolls in the last 6 s: time, 1 - chance */
  double seal[21];                       /* Seal of the Black Empire stack distribution */
  double ice_ready;
  double rg_t, bl_store, ida_end, ida_next;
  int armed, status;
  ulong miss_b, miss_e;
  AP ap;
#if REPORT
  double act_t[MAXA]; int act_id[MAXA]; int nact;
#endif
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

/* host-Python x ** y, looked up by the exact bits of (x, y) */
double pow_lookup(const PowT* P, St* s, double x, double y) {
  ulong kb = as_ulong(x), ke = as_ulong(y);
  int lo = 0, hi = P->np;
  while (lo < hi) {
    int mid = (lo + hi) >> 1;
    if (P->pkb[mid] < kb || (P->pkb[mid] == kb && P->pke[mid] < ke)) lo = mid + 1; else hi = mid;
  }
  if (lo < P->np && P->pkb[lo] == kb && P->pke[lo] == ke) return P->pv[lo];
  if (!s->status) { s->status = 7; s->miss_b = kb; s->miss_e = ke; }
  return 0.5;
}

/* ---- incoming hits (docs/defense-model.md; user model 2026-11-17/20/21) --------------------------
 * Dummy j (0..targets-1) attacks the hero every 1 s, first at 0.2 * (j % 5 + 1) s; dummies 0 .. melee-1
 * are melee, melee = round(targets * 122 / 176). A hit is 5% of max HP (no damage reduction). The hero
 * heals 75% of max HP every 3 s, never above the heal ceiling, never below 1 HP. Chance effects are
 * expectations: a stun (Nerubian Scales) moves that share of the dummy's next attack 1.5 s later instead
 * of 1 s, an Icecrown freeze 2.5 s. Health is the expected health. */
int melee_count(int targets) { return (2 * targets * 122 + 176) / 352; }

double hero_ratio(St* s, double t) {
  (void)t;
  if (!s->hp_on) return 1.0;
  return s->hp_health / s->hp_max;
}

void hp_add(St* s, double delta) {
  double h = s->hp_health + delta;
  if (delta > 0.0) {
    double ceiling = s->hp_max * s->hp_cap;
    if (s->hp_health >= ceiling) return;
    h = (h < ceiling) ? h : ceiling;
  }
  s->hp_health = (h > 1.0) ? h : 1.0;
}

double dummy_next(const St* s, int j, int* k) {
  for (int i = 0; i < NG; i++) if (s->dm[j][i] > 0.0) { *k = i; return s->db[j] + 0.5 * (double)i; }
  *k = -1;
  return 1.0e9;
}

void dummy_push(St* s, int j, int k, double mass) {
  if (k < NG && mass > 0.0) s->dm[j][k] += mass;
}

double seal_mean(const St* s) {
  double e = 0.0;
  for (int k = 1; k <= 20; k++) e += (double)k * s->seal[k];
  return e;
}

#define MAST(r, s) ((r)->mastery + (((r)->mask & S_SEAL) ? seal_mean(s) : 0.0))

double bm_active(St* s, double t) {
  double q = 1.0;
  int w = 0;
  for (int i = 0; i < s->bm_n; i++) {
    if (t < s->bm_t[i] + 6.0) { s->bm_t[w] = s->bm_t[i]; s->bm_q[w] = s->bm_q[i]; w++; q *= s->bm_q[i]; }
  }
  s->bm_n = w;
  return 1.0 - q;
}

/* DamageIncrease_Amount by hero health (PreDamage_Increase): Crimson Fury / Immortal Gladiator's Mask
 * +15% at <= 40%, The Furnace + missing% / 500, Belt of Living Strength +12% at >= 75%. One additive pool. */
void dinc_update(const Row* r, St* s) {
  if (!(r->mask & (S_CRIM | S_IGM | S_FURN | S_BLS))) { s->dinc = 0.0; return; }
  double pct = 100.0 * hero_ratio(s, 0.0);
  double d = 0.0;
  if ((r->mask & S_CRIM) && pct <= 40.0) d += 0.15;
  if ((r->mask & S_IGM) && pct <= 40.0) d += 0.15;
  if (r->mask & S_FURN) d += ((100.0 - pct) / 50.0) / 10.0;
  if ((r->mask & S_BLS) && pct >= 75.0) d += 0.12;
  s->dinc = d;
}

/* evasion: product of the hit-chance factors of PreDamage_Reduce */
double hit_chance(const Row* r, St* s) {
  double h = 1.0;
  if (r->mask & S_EV12) h *= 0.88;
  if (r->mask & S_EV13) h *= 0.87;
  if (r->mask & S_EV16A) h *= 0.84;
  if (r->mask & S_EV16B) h *= 0.84;
  if (r->mask & S_EV18) h *= 0.82;
  if ((r->mask & S_ALE) && hero_ratio(s, 0.0) <= 0.40) h *= 0.82;
  return h;
}

/* Healing (trigger Healing): Healing Type amount x (1 + received modifiers [+ own Healing Power when the hero
 * heals itself]); Bloodlord's Regalia stores 100% of own and 20% of allies' Healing Type healing. Healing only
 * runs when the hero's health changes the damage (s->hp_on). */
void heal_ht(const Row* r, St* s, double amount, int self) {
  if (!s->hp_on || amount <= 0.0) return;
  if (self) amount += r->heal_flat + r->heal_flat_int * r->intel + r->heal_pot * r->potency;
  double m = r->recv_mod + (self ? r->heal_power + r->own_extra : 0.0);
  if (r->mask & S_FIGUR) m += 0.01 * r->armor_hero;
  if (m < -1.0) return;
  amount *= 1.0 + m;
  if (r->mask & S_BLOOD) s->bl_store += (self ? 1.0 : 0.20) * amount;
  if (amount >= 1.0) hp_add(s, amount);
}

void heal_plain(St* s, double amount) {
  if (s->hp_on && amount > 0.0) hp_add(s, amount);
}

/* HP regeneration between events: (items + auras) x (1 + % + Dark Iron Ale 1% per 3% missing) + % of max HP;
 * Titan's Breastplate disables it, Cursed Skull turns it into damage to the hero. */
void regen_adv(const Row* r, St* s, double t) {
  if (!s->hp_on) return;
  double dt = t - s->rg_t;
  s->rg_t = t;
  if (dt <= 0.0 || (r->mask & S_TITAN)) return;
  double pct = r->regen_pct;
  if (r->mask & S_ALE) pct += (100.0 * (1.0 - hero_ratio(s, t)) / 3.0) / 100.0;
  double rate = r->regen * (1.0 + pct) + r->regen_hp;
  if (rate <= 0.0) return;
  hp_add(s, (r->mask & S_CSKULL) ? -rate * dt : rate * dt);
}

/* Venomous Axes buff per target: expiry points with probabilities (see sunken_sim/berserker.py). */
double va_mass(const St* s, int i, double now) {
  double total = 0.0;
  for (int k = 0; k < s->va_n[i]; k++)
    if (now < s->va_e[i][k]) total += s->va_m[i][k];
  return total;
}

void va_apply(St* s, int i, double now) {
  s->va_e[i][0] = now + 4.0; s->va_m[i][0] = 1.0; s->va_n[i] = 1;
}

double armor_mult(St* s, double armor) {
  if (armor > 0.0) return 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor);
  if (armor < 0.0) { if (!s->status) s->status = 4; return 1.0; }
  return 1.0;
}

/* DamageIncrease_Amount (PreDamage_Increase): 1 + hero-health entries (s->dinc) + Voodoo Doll 3% + Ancient
 * Voodoo Doll 4% + 2% per other buff on the target + Giantsbane 0.75% per point of target armor. */
double pool_of(const Row* r, St* s, int i, double now, double armor) {
  if (!(r->mask & S_GIANT) && r->pool_flat == 0.0 && r->voodoo == 0.0 && s->dinc == 0.0) return 1.0;
  double d = 1.0 + s->dinc + r->pool_flat;
  if (r->mask & S_GIANT) d += (0.03 / 4.0) * armor;
  if (r->voodoo != 0.0) {
    double va = va_mass(s, i, now);
    double buffs = va + (TM(r, T_WOUND) ? va : 0.0);
    if (now - s->surge_at[i] <= 5.0) buffs += s->surge_p[i];
    d += 0.04 + 0.02 * buffs;
  }
  return d;
}

double taken_for(const Row* r, St* s, int i, double now) {
  double armor = 15.0 - r->armor_pen;
  if (TM(r, T_WOUND)) {
    double p = va_mass(s, i, now);
    if (p > 0.0) {
      double base = armor_mult(s, armor) * pool_of(r, s, i, now, armor);
      double low = armor_mult(s, armor - 3.0) * pool_of(r, s, i, now, armor - 3.0);
      return (1.0 - p) * base + p * low;
    }
  }
  double pool = pool_of(r, s, i, now, armor);
  if (pool == 1.0) return armor_mult(s, armor);
  return armor_mult(s, armor) * pool;
}

double gen_mult(const Row* r, double when) {
  double bonus = 1.0;
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(when);
  if (r->glass) bonus *= 1.15;
  return bonus;
}

double physical(const Row* r, double when) {
  double bonus = 1.0 + r->phys_add + r->hemo;
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(when);
  if (r->glass) bonus *= 1.15;
  return bonus;
}

void finish(const Row* r, St* s, int name, double raw, int index, double when, double count, double pot_coeff) {
  double execute = exec_factor(r, when);
  double scale = taken_for(r, s, index, when) * (SP_FURY ? 0.85 : 1.0) * count;
  double weight = raw * scale, coeff = pot_coeff * scale;
  double dealt = (weight + r->potency * coeff) * execute;
  add_src(s, name, dealt);
  if (s->hp_on) {
    if (r->mask & S_SVAMP) heal_plain(s, count * chance01(0.03 * s->lm) * 40.0);
    if (r->mask & S_SANG) heal_plain(s, 0.025 * ((hero_ratio(s, when) < 0.40) ? 2.0 : 1.0) * dealt);
  }
}

void surge_proc(St* s, int i, double when, double chance) {
  if (when - s->surge_at[i] > 5.0) s->surge_p[i] = 0.0;
  s->surge_p[i] = 1.0 - (1.0 - s->surge_p[i]) * (1.0 - chance01(chance));
  s->surge_at[i] = when;
}

void poison_spec_proc(const PowT* P, St* s, int i, double when, double events) {
  if (SP_POISON && events > 0.0) {
    double chance = 1.0 - pow_lookup(P, s, 1.0 - chance01(0.03 * s->lm), events);
    surge_proc(s, i, when, chance);
  }
}

void surge_consume(const Row* r, St* s, int i, double when) {
  if (when - s->surge_at[i] > 5.0) s->surge_p[i] = 0.0;
  if (s->surge_p[i] <= 0.0) return;
  double raw = 15.0 * LEVEL + 2.5 * r->agi;
  double g = gen_mult(r, when);
  finish(r, s, N_SURGE, raw * g, i, when, s->surge_p[i], g);
  s->surge_p[i] = 0.0;
}

double dcs(const Row* r) {
  double value = 30.0 + 0.75 * r->agi + r->damage;
  value += TROPHIES;
  if (TM(r, T_CRAZE)) value += 30.0;
  return value;
}

double attack_crit(const Row* r, St* s, double when) {
  double chance = r->crit;
  if (TM(r, T_BONE)) chance += 10.0 + 0.5 * (100.0 * (1.0 - hero_ratio(s, when)));
  return chance;
}

double attack_hit(const Row* r, St* s, int name, double raw, double when, double potency_scale, int index, double count) {
  double amount = raw;
  double increase = 1.0;
  if (SP_HEAD) increase += 0.12;
  if (TM(r, T_EXEC) && target_hp(when) <= 0.40) increase += 0.35;
  amount *= increase;
  double chance = attack_crit(r, s, when);
  double mult = 2.0 + r->rating;
  if (SP_HEAD) mult += 0.10 + 0.008 * MAST(r, s);
  double cf = crit_factor(chance, mult);
  double expected = amount * cf;
  double pot_coeff = potency_scale * increase * cf;
  if (TM(r, T_BHUNT)) {
    double c1 = (100.0 <= chance) ? 100.0 : chance;
    double share = ((0.0 >= c1) ? 0.0 : c1) / 100.0;
    expected += share * (15.0 + 0.05 * r->hp) * mult;
  }
  double ph = physical(r, when);
  finish(r, s, name, expected * ph, index, when, count, pot_coeff * ph);
  return 0.0;
}

void va_tick(const Row* r, const PowT* P, St* s, int index, double now, double w, int refresh) {
  double calls = 1.0;
  if (TM(r, T_DEADLY)) calls += chance01(0.30 * s->lm);
  if (TM(r, T_WOUND)) calls += chance01(0.30 * s->lm);
  if (TM(r, T_LEECH)) calls += chance01(0.30 * s->lm);
  double scale = TM(r, T_DAMBALA) ? 0.25 : 0.15;
  double raw = 10.0 * 1.0 + scale * dcs(r);
  double coeff = crit_factor(r->crit * s->lm, 1.5 + r->rating);
  raw *= coeff;
  if (TM(r, T_DEADLY)) {
    double deadly = 1.0 + 0.005 * 100.0 * (1.0 - target_hp(now));
    raw *= deadly;
    coeff *= deadly;
  }
  double ticks = 1.0;
  if (SP_POISON) ticks += chance01((5.0 + 0.5 * MAST(r, s)) / 100.0);
  double typed = TM(r, T_HEMO) ? physical(r, now) : gen_mult(r, now);
  finish(r, s, N_VA, raw * typed, index, now, calls * ticks * w, coeff * typed);
  if (!SP_POISON) surge_proc(s, index, now, (1.0 - pow_lookup(P, s, 1.0 - chance01(0.02 * s->lm), calls)) * w);
  else poison_spec_proc(P, s, index, now, calls * ticks * w);
  if (refresh && TM(r, T_DAMBALA)) {
    double d = chance01(0.20 * s->lm);
    double keep = 1.0 - d;
    if (TM(r, T_DEADLY)) keep *= 1.0 - chance01(0.30 * s->lm) * d;
    if (TM(r, T_WOUND)) keep *= 1.0 - chance01(0.30 * s->lm) * d;
    if (TM(r, T_LEECH)) keep *= 1.0 - chance01(0.30 * s->lm) * d;
    double q = 1.0 - keep;
    double alive = now - 1e-9;
    int n = 0;
    for (int k = 0; k < s->va_n[index]; k++) {
      if (alive < s->va_e[index][k]) {
        s->va_e[index][n] = s->va_e[index][k];
        s->va_m[index][n] = s->va_m[index][k] * (1.0 - q);
        n++;
      }
    }
    if (n >= VK) { if (!s->status) s->status = 8; return; }
    s->va_e[index][n] = now + 4.0;
    s->va_m[index][n] = q * w;
    s->va_n[index] = n + 1;
  }
}

void recover(const Row* r, St* s, double now) {
  if (now > s->mana_time && s->mana < r->mana_max) {
    double v = s->mana + r->mana_regen * (now - s->mana_time);
    s->mana = (v < r->mana_max) ? v : r->mana_max;
  }
  s->mana_time = now;
}

int pay(const Row* r, St* s, double cost, double now) {
  recover(r, s, now);
  if (s->mana < cost) return 0;
  s->mana -= cost;
  double back = cost * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * MAST(r, s);
  double v = s->mana + back;
  s->mana = (v < r->mana_max) ? v : r->mana_max;
  return 1;
}

void damage_mana(const Row* r, St* s, double count) {
  if (r->damage_mana_pct != 0.0) {
    double v = s->mana + r->damage_mana_pct * r->mana_max * count;
    s->mana = (v < r->mana_max) ? v : r->mana_max;
  }
}

double cooldown_of(double base, const Row* r) {
  double v = (base * r->cd_temp - r->flat_cdr) / (1.0 + r->haste);
  return (v > 0.5) ? v : 0.5;
}

/* Berserk (I0A2): the first damage taken without buff B03J casts it (6 s, stacks 0); every later damage
 * instance while it lasts adds a stack: +12% attack speed, +3% (Fury 2%) per stack. */
double berserk_speed(const Row* r, St* s, double now) {
  if (!TM(r, T_BERSERK) || now >= s->bz_end) return 0.0;
  double per = SP_FURY ? 0.02 : 0.03;
  return 0.12 + per * s->bz_stacks;
}

void axe_hit(const Row* r, St* s, double now, double count) {
  attack_hit(r, s, N_AXE, 20.0 + 1.25 * dcs(r), now, r->attack_potency, 0, count);
}

/* PreDamage_Enemies (PreDamageEvent 4, before evasion): one damage instance of mass m taken at now.
 * axe = the Axe Mastery chance of this instance (5% x Luck from enemies, 10% x Luck self-damage). */
void taken_event(const Row* r, St* s, double now, double m, double axe) {
  if (m <= 0.0) return;
  if ((r->mask & S_IDRA) && s->hp_on) {
    if (now >= s->ida_end) s->ida_next = now + 1.0;
    s->ida_end = now + 5.0;
  }
  if (TM(r, T_AXE) && axe > 0.0) axe_hit(r, s, now, m * axe);
  if (TM(r, T_BERSERK)) {
    if (now < s->bz_end) s->bz_stacks += m;
    else { s->bz_end = now + 6.0; s->bz_stacks = 0.0; }
  }
  if (r->mask & S_BMASK) {
    if (s->bm_n >= NBM) bm_active(s, now);
    if (s->bm_n < NBM) { s->bm_t[s->bm_n] = now; s->bm_q[s->bm_n] = 1.0 - m * chance01(0.08 * s->lm); s->bm_n++; }
    else if (!s->status) s->status = 2;
  }
  if (r->mask & S_SEAL) {
    double p = m * chance01(0.25 * s->lm);
    for (int k = 19; k >= 0; k--) { double move = s->seal[k] * p; s->seal[k] -= move; s->seal[k + 1] += move; }
  }
}

/* Damage of an incoming-hit effect on dummy i: magical = Magical Type (Sunstrider), else untyped. */
void item_dmg(const Row* r, St* s, int name, double raw, int i, double when, int magical) {
  double v = raw * gen_mult(r, when) * taken_for(r, s, i, when) * exec_factor(r, when) * (SP_FURY ? 0.85 : 1.0);
  if (magical) {
    v *= 1.0 + r->magic_add;
    if (r->spell_crit) {
      double rating = r->spell_mult + r->rating;
      if (SP_HEAD) rating += 0.10 + 0.008 * MAST(r, s);
      v *= crit_factor(attack_crit(r, s, when), rating);
    }
  }
  add_src(s, name, v);
}

double taken_avg(const Row* r, St* s, double when) {
  double t = 0.0;
  for (int i = 0; i < r->targets; i++) t += taken_for(r, s, i, when);
  return t / (double)r->targets;
}

/* One attack of dummy j, mass m, at now (Hero_Attacked, PreDamage 4, evasion, landing, OnDamage). */
void dummy_attack(const Row* r, St* s, int j, double m, double now) {
  int melee = j < melee_count(r->targets);
  double hit = 0.05 * s->hp_max;
  /* attack start: Hero_Attacked */
  recover(r, s, now);
  double gain = 0.0;
  if (r->mask & S_PCB) gain += 3.0;
  if (r->mask & S_ICE) gain += 2.0 + (0.01 / 5.0) * r->mana_max;
  if (gain > 0.0) { double v = s->mana + m * gain; s->mana = (v < r->mana_max) ? v : r->mana_max; }
  if (r->mask & S_EVD) heal_plain(s, m * chance01(0.05 * s->lm) * 0.08 * r->mana_max);
  if (r->mask & S_MASO) heal_plain(s, m * 0.003 * s->hp_max);
  if (r->mask & S_SOD) item_dmg(r, s, N_SOD, 125.0 * m * chance01(0.08 * s->lm), j, now, 0);
  /* PreDamage 4 */
  taken_event(r, s, now, m, chance01(0.05 * s->lm));
  /* PreDamage 6: evasion; an evaded hit has amount 0 */
  double land = m * hit_chance(r, s);
  double evaded = m - land;
  if ((r->mask & S_EV13) && evaded > 0.0) item_dmg(r, s, N_EVADE, 100.0 * evaded, j, now, 0);
  if ((r->mask & S_EV16A) && evaded > 0.0) heal_ht(r, s, evaded * 0.025 * s->hp_max, 1);
  if (land > 0.0) {
    if (melee) {
      double back = 0.0;
      if (r->mask & S_SPIKE) back += 0.10;
      if (r->mask & S_THORN) back += 0.10;
      if (back > 0.0) item_dmg(r, s, N_REFL, back * hit * land, j, now, 0);
    }
    if (r->mask & S_DSCALE) item_dmg(r, s, N_REFL, 0.10 * hit * land, j, now, 0);
    if (r->mask & S_SUN) {
      double v = 0.15 * hit * land * gen_mult(r, now) * taken_avg(r, s, now) * exec_factor(r, now) * (SP_FURY ? 0.85 : 1.0);
      v *= 1.0 + r->magic_add;
      if (r->spell_crit) {
        double rating = r->spell_mult + r->rating;
        if (SP_HEAD) rating += 0.10 + 0.008 * MAST(r, s);
        v *= crit_factor(attack_crit(r, s, now), rating);
      }
      add_src(s, N_SUNS, v);
    }
    if (s->hp_on) hp_add(s, -land * hit);
    if (r->mask & S_JADE) heal_ht(r, s, land * chance01(0.20 * s->lm) * 0.40 * hit, 1);
  }
  /* the dummy's next attack: 1 s, a stun 1.5 s, an Icecrown freeze 2.5 s */
  int k0 = 0;
  double t0 = dummy_next(s, j, &k0);
  (void)t0;
  s->dm[j][k0] -= m;
  if (s->dm[j][k0] < 1e-12) s->dm[j][k0] = 0.0;
  double frozen = 0.0;
  if ((r->mask & S_ICE) && now >= s->ice_ready) {
    frozen = m;
    s->ice_ready = now + ((hero_ratio(s, now) <= 0.40) ? 12.0 : 20.0);
  }
  double stun = (r->mask & S_NERUB) ? (m - frozen) * chance01(0.05 * s->lm) : 0.0;
  dummy_push(s, j, k0 + 5, frozen);
  dummy_push(s, j, k0 + 3, stun);
  dummy_push(s, j, k0 + 2, m - frozen - stun);
  /* keep slot 0 the earliest live slot (see below) */
  int lead = 0;
  while (lead < NG && s->dm[j][lead] <= 0.0) lead++;
  if (lead > 0 && lead < NG) {
    for (int i = 0; i < NG; i++) s->dm[j][i] = (i + lead < NG) ? s->dm[j][i + lead] : 0.0;
    s->db[j] += 0.5 * (double)lead;
  }
}

/* Spellcasts (Toxic Sack, Skull Split): Crown of the Highlord 3% max HP, Holy Scepter 2% max HP, Amber's Gaze 50
 * (doubled < 40%), Crusader's Chestplate the mana cost, Tribal Staff 25% primary, Seraphim Staff 25 + 75% primary. */
void cast_heal(const Row* r, St* s, double now, double cost) {
  if (!s->hp_on) return;
  if (r->mask & S_HIGHL) heal_ht(r, s, 0.03 * s->hp_max, 1);
  if (r->mask & S_HOLYS) heal_plain(s, 0.02 * s->hp_max);
  if (r->mask & S_AMBER) heal_ht(r, s, 50.0 * ((hero_ratio(s, now) < 0.40) ? 2.0 : 1.0), 1);
  if (r->mask & S_CRUS) heal_ht(r, s, cost, 1);
  if (r->mask & S_TRIBAL) heal_ht(r, s, 0.25 * r->agi, 1);
  if (r->mask & S_SERAPH) heal_ht(r, s, 25.0 + 0.75 * r->agi, 1);
}

/* After an auto attack that dealt `dealt` to its target: lifesteal (AfterDamage_Global) and on-attack heals. */
void attack_heal(const Row* r, St* s, double now, double dealt) {
  double ls = r->lifesteal;
  if (r->mask & S_BREAV) ls += 0.13;
  else if (r->mask & S_SERA) ls += 0.10;
  double heal = ls * dealt;
  if (r->mask & S_REDC) heal += 10.0 + LEVEL;
  if (r->mask & S_GORE) {
    double part = (0.01 / 2.0) * 5300.0, cap = 0.03 * s->hp_max;
    heal += (part > cap) ? cap : part;
  }
  if (heal >= 1.0 && hero_ratio(s, now) < 1.0) {
    if (r->mask & S_REDC) heal_ht(r, s, heal, 1);
    else heal_plain(s, heal);
  }
  if (r->ht_atk_pct != 0.0 || r->ht_atk_flat != 0.0) heal_ht(r, s, r->ht_atk_flat + r->ht_atk_pct * s->hp_max, 1);
  if (r->mask & S_EARTH) heal_ht(r, s, 10.0 + 0.20 * r->agi + 0.03 * r->mana_max, 1);
  if (r->mask & S_MOON) heal_ht(r, s, 0.035 * r->mana_max, 1);
}

#if REPORT
double fight(const Row* r, const PowT* P, int* status, ulong* miss_b, ulong* miss_e, St* keep) {
#else
double fight(const Row* r, const PowT* P, int* status, ulong* miss_b, ulong* miss_e) {
#endif
  St s;
#if REPORT
  s.nact = 0;
#endif
  s.nord = 0; s.seen = 0u;
  for (int id = 0; id < 8; id++) { s.seen |= 1u << id; s.ord[s.nord++] = id; s.src[id] = 0.0; }
  s.status = 0; s.miss_b = 0; s.miss_e = 0;
  s.lm = 1.0 + r->luck;
  const int targets = r->targets;
  for (int i = 0; i < MAXT; i++) { s.va_n[i] = 0; s.surge_p[i] = 0.0; s.surge_at[i] = -1.0; }
  s.npend = 0;
  s.mana = r->mana_max; s.mana_time = 0.0; s.armed = 0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  s.dinc = 0.0;
  s.rg_t = 0.0; s.bl_store = 0.0; s.ida_end = -1.0; s.ida_next = 1.0e9;
  s.hp_max = r->hp; s.hp_health = r->hp; s.hp_cap = (r->mask & S_CRIM) ? 0.38 : 1.0;
  s.hp_on = (r->hp > 1.0) && ((r->mask & (HP_DEP | S_ICE)) || TM(r, T_BONE));
  s.hits_on = s.hp_on || (r->mask & HIT_DEP) || TM(r, T_AXE) || TM(r, T_BERSERK);
  s.hp_next_heal = 3.0;
  s.bz_end = -1.0; s.bz_stacks = 0.0; s.bm_n = 0; s.ice_ready = 0.0;
  for (int k = 0; k <= 20; k++) s.seal[k] = 0.0;
  s.seal[0] = 1.0;
  for (int j = 0; j < MAXT; j++) {
    s.db[j] = 0.2 * (double)(j % 5 + 1);
    for (int k = 0; k < NG; k++) s.dm[j][k] = 0.0;
    if (j < targets) s.dm[j][0] = 1.0;
  }
  const int sulf = (r->mask & S_SULF) != 0;
  const int blades = TM(r, T_BLADES) || (r->mask & S_VENOM);
  const double fury_mult = SP_FURY ? 0.85 : 1.0;
  const double agi = r->agi;
  const double cast_time = CAST_POINT + CAST_BACKSWING;
  double next_attack = 0.0, next_sack = 0.0, next_skull = 0.0, next_tick = 1.0, busy = 0.0;
  int guard = 0;
  while (1) {
    guard += 1;
    if (guard > 400000) break;
    if (s.status) break;
    double land = s.npend ? s.pend[0] : FIGHT;
    double moment = next_attack;
    if (next_sack < moment) moment = next_sack;
    if (next_skull < moment) moment = next_skull;
    if (next_tick < moment) moment = next_tick;
    int hit_j = -1, hit_k = -1;
    double next_hit = 1.0e9;
    if (s.hits_on) {
      for (int j = 0; j < targets; j++) {
        int k;
        double t = dummy_next(&s, j, &k);
        if (t < next_hit) { next_hit = t; hit_j = j; hit_k = k; }
      }
    }
    double next_heal = s.hp_on ? s.hp_next_heal : 1.0e9;
    double next_ida = (s.hp_on && s.ida_next < s.ida_end) ? s.ida_next : 1.0e9;
    if (next_hit < moment) moment = next_hit;
    if (next_heal < moment) moment = next_heal;
    if (next_ida < moment) moment = next_ida;
    if (land < moment) moment = land;
    if (moment >= FIGHT) break;
    regen_adv(r, &s, moment);
    if (moment == land) {
      for (int k = 1; k < s.npend; k++) s.pend[k - 1] = s.pend[k];
      s.npend--;
      double raw = 80.0 * 1.0 - 20.0 + 2.2 * agi;
      for (int i = 0; i < targets; i++) {
        double coeff = 1.0;
        if (TM(r, T_BOMB)) { double p = va_mass(&s, i, moment); coeff = 1.6 * p + 1.3 * (1.0 - p); }
        double ph = physical(r, moment);
        finish(r, &s, N_SACK, raw * coeff * ph, i, moment, 1.0, coeff * ph);
        poison_spec_proc(P, &s, i, moment, 1.0);
        va_apply(&s, i, moment);
      }
      damage_mana(r, &s, (double)targets);
      continue;
    }
    if (moment == next_tick) {
      for (int i = 0; i < targets; i++) {
        double w = va_mass(&s, i, moment - 1e-9);
        if (w > 0.0) va_tick(r, P, &s, i, moment, w, 1);
      }
      next_tick += 1.0;
      continue;
    }
    if (moment == next_ida) {
      heal_ht(r, &s, 0.02 * s.hp_max, 1);
      s.ida_next += 1.0;
      dinc_update(r, &s);
      continue;
    }
    if (moment == next_hit) {
      dummy_attack(r, &s, hit_j, s.dm[hit_j][hit_k], moment);
      dinc_update(r, &s);
      continue;
    }
    if (moment == next_heal) {
      /* the model heal: Healing Type, from an ally (Agility hero) */
      heal_ht(r, &s, 0.75 * s.hp_max, 0);
      s.hp_next_heal += 3.0;
      /* Bloodlord's Regalia: every 3 s, 20% of the stored healing x (1 + 0.06 x level) to every enemy in 500 */
      if (r->mask & S_BLOOD) {
        double dmg = 0.20 * s.bl_store * (1.0 + 0.06 * LEVEL);
        if (dmg >= 1.0) for (int i = 0; i < targets; i++) item_dmg(r, &s, N_BLOOD, dmg, i, moment, 0);
        s.bl_store = 0.0;
      }
      dinc_update(r, &s);
      continue;
    }
    if (moment < busy) {
      if (moment == next_attack) next_attack = busy;
      else if (moment == next_sack) next_sack = busy;
      else if (moment == next_skull) next_skull = busy;
      continue;
    }
    if (moment == next_sack) {
      if (!pay(r, &s, 30.0, moment)) { next_sack = moment + 0.25; continue; }
#if REPORT
      if (s.nact < MAXA) { s.act_t[s.nact] = moment; s.act_id[s.nact] = 0; s.nact++; }
#endif
      cast_heal(r, &s, moment, 30.0);
      if (s.npend >= MAXP) { s.status = 2; break; }
      double t = moment + CAST_POINT + 0.75;
      int k = s.npend++;
      while (k > 0 && s.pend[k - 1] > t) { s.pend[k] = s.pend[k - 1]; k--; }
      s.pend[k] = t;
      if (sulf) s.armed = 1;
      busy = moment + cast_time + r->cast_lock;
      next_sack = moment + cooldown_of(10.0, r);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    if (moment == next_skull) {
      if (!pay(r, &s, 25.0, moment)) { next_skull = moment + 0.25; continue; }
#if REPORT
      if (s.nact < MAXA) { s.act_t[s.nact] = moment; s.act_id[s.nact] = 1; s.nact++; }
#endif
      cast_heal(r, &s, moment, 25.0);
      double hit = moment + CAST_POINT;
      double raw = 150.0 * 1.0 + 2.0 * dcs(r) + 0.05 * 5300.0;
      double coeff = (TM(r, T_EXEC) && target_hp(hit) <= 0.40) ? 1.35 : 1.0;
      double ph = physical(r, hit);
      finish(r, &s, N_SKULL, raw * coeff * ph, 0, hit, 1.0, coeff * ph);
      poison_spec_proc(P, &s, 0, hit, 1.0);
      damage_mana(r, &s, 1.0);
      if (sulf) s.armed = 1;
      busy = moment + cast_time + r->cast_lock;
      next_skull = moment + cooldown_of(20.0, r);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    if (moment == next_attack) {
      recover(r, &s, moment);
      double power = dcs(r);
      if (r->mask & S_SERA) power += 0.01 * r->hp;
      double had_va = va_mass(&s, 0, moment);
      surge_consume(r, &s, 0, moment);
      double auto_before = (s.seen & (1u << N_AUTO)) ? s.src[N_AUTO] : 0.0;
      attack_hit(r, &s, N_AUTO, power, moment, r->attack_potency, 0, r->auto_pct);
      if (s.hp_on) attack_heal(r, &s, moment, s.src[N_AUTO] - auto_before);
      poison_spec_proc(P, &s, 0, moment, 1.0);
      double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
      if (r->attack_mana_crit != 0.0) {
        double cc = (r->crit < 100.0) ? r->crit : 100.0;
        gain *= 1.0 + cc / 100.0;
      }
      double mv = s.mana + gain;
      s.mana = (mv < r->mana_max) ? mv : r->mana_max;
      damage_mana(r, &s, 1.0);
      va_apply(&s, 0, moment);
      if (blades && had_va > 0.0) va_tick(r, P, &s, 0, moment, had_va, 0);
      if (TM(r, T_SNAKE)) {
        double chance = chance01(0.20 * s.lm);
        double raw = 2.0 * (10.0 * 1.0 + 0.5 * agi);
        for (int i = 0; i < targets; i++) {
          double g = gen_mult(r, moment);
          finish(r, &s, N_SNAKE, raw * g, i, moment, chance, g);
          if (s.surge_p[i] > 0.0 && moment - s.surge_at[i] <= 5.0) {
            double consumed = s.surge_p[i] * chance;
            double g2 = gen_mult(r, moment);
            double surge_value = (15.0 * LEVEL + 2.5 * agi) * g2;
            finish(r, &s, N_SURGE, surge_value, i, moment, consumed, gen_mult(r, moment));
            s.surge_p[i] -= consumed;
          }
        }
        damage_mana(r, &s, (double)targets * chance);
      }
      /* self-damage of the attack (PreDamage_Heroes): Blood Fury 3 + 6 x level, Blood Craze 30% x Luck
       * for half of it again, Blade of the Fallen Seraph 1% of max HP; each is a damage instance taken */
      {
        double axe = chance01(0.10 * s.lm);
        double craze = TM(r, T_CRAZE) ? chance01(0.30 * s.lm) : 0.0;
        double fury = 3.0 + 6.0 * LEVEL;
        if (s.hp_on) hp_add(&s, -(fury + craze * 0.5 * fury));
        taken_event(r, &s, moment, 1.0, axe);
        taken_event(r, &s, moment, craze, axe);
        if (r->mask & S_SERA) {
          if (s.hp_on) hp_add(&s, -0.01 * r->hp);
          taken_event(r, &s, moment, 1.0, axe);
        }
        dinc_update(r, &s);
      }
      if (r->mask & S_ORB) {
        double ex = exec_factor(r, moment);
        double splash = (20.0 + 0.35 * agi) * (double)targets * taken_for(r, &s, 0, moment) * exec_factor(r, moment);
        add_src(&s, N_SPLASH, splash * fury_mult);
        (void)ex;
        damage_mana(r, &s, (double)targets);
      }
      if (sulf) {
        double execute = exec_factor(r, moment);
        double taken = taken_for(r, &s, 0, moment);
        if (s.armed) {
          s.armed = 0;
          double splash = agi * (1.0 + r->magic_add) * gen_mult(r, moment) * taken * execute * (double)targets;
          if (r->spell_crit) {
            double rating = r->spell_mult + r->rating;
            if (SP_HEAD) rating += 0.10 + 0.008 * MAST(r, &s);
            splash *= crit_factor(attack_crit(r, &s, moment), rating);
          }
          add_src(&s, N_SULF, splash * fury_mult);
          damage_mana(r, &s, (double)targets);
        }
        double echo = power * taken * execute * (0.10 * (1.0 + r->luck));
        add_src(&s, N_ECHO, echo * fury_mult);
      }
      ap_attack(&s.ap, moment, attack_crit(r, &s, moment));
      double swing = 1.6 * ((r->mask & S_GALA) ? 1.20 : 1.0);
      if (r->mask & S_BHOWL) swing *= 1.0 - (1.0 - hero_ratio(&s, moment)) * 0.30;
      double speed = r->aspd + berserk_speed(r, &s, moment) + ap_bonus(&s.ap, moment);
      if (r->mask & S_BMASK) speed += 0.28 * bm_active(&s, moment);
      if (r->mask & S_FANAT) speed += 0.01 * 100.0 * (1.0 - hero_ratio(&s, moment));
      speed = (-0.8 >= speed) ? -0.8 : speed;
      speed = (4.0 <= speed) ? 4.0 : speed;
      next_attack = moment + swing / (1.0 + speed);
      continue;
    }
    break;
  }
  if (s.status) { *status = s.status; *miss_b = s.miss_b; *miss_e = s.miss_e; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < s.nord; i++) total += s.src[s.ord[i]];
#if REPORT
  recover(r, &s, FIGHT);
  *keep = s;
#endif
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

/* berserker.stats_of(build) */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double strength = T->base[1], agility = T->base[2], intel = T->base[0];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 0.0;
  double crit = (double)pts[6];
  double rating = 0.0, haste = 0.0, aspd = 0.0, magic_add = 0.0, phys_add = 0.0, mana_flat = 0.0, health_flat = 0.0;
  double armor_pen = 0.0, auto_pct = 1.0, attack_potency = 1.0, spell_mult = 1.50;
  int spell_crit = 0;
  double luck = 0.01 * (double)pts[9];
  haste += 0.01 * (double)pts[3];
  aspd += 0.02 * (double)pts[4];
  damage += 2.0 * (double)pts[5];
  mana_flat += 20.0 * (double)pts[1];
  ulong mask = 0;
  int n_core = 0, n_sulg = 0, has_shop = 0, has_drop = 0, nexec = 0;
  double hcol[14];
  for (int j = 0; j < 14; j++) hcol[j] = 0.0;
  for (int si = 0; si < 6; si++) {
    int p = chosen[si];
    if (p < 0) { first[si] = 0; continue; }
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
    agility = agility + f[6];
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
      if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
      auto_pct += u[8];
      if (u[2] != 0.0) attack_potency = 2.0;
      if (u[11] != 0.0) spell_crit = 1;
      if (u[12] != 0.0) spell_mult = 1.65;
      mana_flat += f[10];
      for (int j = 0; j < 4; j++) luck += a[5 + j];
      for (int j = 0; j < 4; j++) health_flat += a[9 + j];
      for (int j = 0; j < 14; j++) hcol[j] += a[13 + j];
    }
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) agility += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  if (GM(r, G_UNSL) && !(mask & S_UNSI)) { magic_add += 0.18; phys_add += 0.18; }
  if (GM(r, G_FORTUNE)) luck += 0.15;
  double hp_before = (T->base[3] + 15.0 * strength) + health_flat;
  double fury_agi = (double)(long)(hp_before / 25.0);
  if (!TM(r, T_GIFT)) fury_agi = (100.0 <= fury_agi) ? 100.0 : fury_agi;
  agility += fury_agi;
  if (TM(r, T_GIFT)) strength += 10.0 + LEVEL;
  double hp = (T->base[3] + 15.0 * strength) + health_flat;
  double hemo = TM(r, T_HEMO) ? (0.08 + 0.0025 * agility) : 0.0;
  double agility_speed = 0.004 * agility;
  agility_speed = (1.0 <= agility_speed) ? 1.0 : agility_speed;
  aspd = aspd + agility_speed;
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
  double keep = 1.0, rflat = 0.0, rmast = 0.0, persec = 0.0, aflat = 0.0, apct = 0.0, dpct = 0.0;
  int acrit = 0;
  for (int si = 0; si < 6; si++) {
    if (!first[si]) continue;
    __global const double* u = T->uniq + (long)chosen[si] * NU;
    cast_lock += u[1];
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
  double stat = (1.20 + 0.10 * intel) * (1.0 + regen_rate);
  stat += mp5 / 5.0;
  stat += persec * mana_max;
  if (GM(r, G_REPL)) stat += 1.50 + 0.0075 * mana_max;
  r->str = strength; r->agi = agility; r->intel = intel; r->potency = potency; r->mastery = mastery; r->damage = damage;
  r->crit = crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->magic_add = magic_add; r->phys_add = phys_add; r->hemo = hemo; r->armor_pen = armor_pen;
  r->auto_pct = auto_pct; r->attack_potency = attack_potency;
  r->spell_crit = spell_crit; r->spell_mult = spell_mult;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock; r->hp = hp;
  /* healing columns (pal 13..26) */
  double aura = ((mask & (S_HAURA | S_TRIBAL)) ? 10.0 : 0.0) + ((mask & S_UNHOLY) ? 5.0 : 0.0);
  r->regen = hcol[0] + aura; r->regen_pct = hcol[1]; r->heal_power = hcol[2]; r->lifesteal = hcol[3];
  r->recv_mod = hcol[4]; r->own_extra = hcol[5]; r->ht_atk_pct = hcol[6]; r->ht_atk_flat = hcol[7];
  r->regen_hp = hcol[8] * hp; r->heal_flat = hcol[9]; r->heal_flat_int = hcol[10]; r->heal_pot = hcol[11];
  r->pool_flat = hcol[12]; r->voodoo = hcol[13];
  r->armor_hero = 0.1 * agility;
  if ((mask & S_PRIM) && !(mask & S_TITAN)) {
    double regen_stat = r->regen * (1.0 + r->regen_pct) + r->regen_hp;
    r->phys_add += 0.005 * regen_stat;
  }
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->nexec = nexec; r->targets = targets;
  r->glass = (GM(r, G_GLASS) || (mask & S_GLAS)) ? 1 : 0;
}

#if !REPORT
double row_value(Tab* T, const PowT* P, long index, uint tmask, uint gmask, const int* pts, int targets,
                 int* status, int* group, ulong* mb, ulong* me) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row r;
  sheet(T, &r, chosen, tmask, gmask, pts, targets, group);
  return fight(&r, P, status, mb, me);
}
#endif

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    __global const double* pal, __global const double* base, \
    __global const ulong* pkb, __global const ulong* pke, __global const double* pv, const int npow

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.pal = pal; T.base = base; \
  PowT P; P.pkb = pkb; P.pke = pke; P.pv = pv; P.np = npow;

#if !REPORT
__kernel void cls_bare(const long start, const int n, const int targets, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status, __global ulong* out_mb, __global ulong* out_me)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = 0;
  int status = 0, group = 0;
  ulong mb = 0, me = 0;
  double d = row_value(&T, &P, start + gid, 0u, 0u, pts, targets, &status, &group, &mb, &me);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status; out_mb[gid] = mb; out_me[gid] = me;
}

__kernel void cls_rows(const int n, const int targets, __global const long* chunks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, __global const int* tlpoints, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status, __global ulong* out_mb, __global ulong* out_me)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0;
  ulong mb = 0, me = 0;
  double d = row_value(&T, &P, chunks[gid], tmasks[gid], gmasks[gid], pts, targets, &status, &group, &mb, &me);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status; out_mb[gid] = mb; out_me[gid] = me;
}
#endif

/* Explicit pieces (-1 = empty slot): the one-slot screen and any build outside the pool's 6-item ranks. */
int picks_ok(Tab* T, __global const int* picks, long gid, int* chosen) {
  for (int j = 0; j < 6; j++) {
    int p = picks[gid * 6 + j];
    if (p >= T->npieces) return 0;
    chosen[j] = (p < 0) ? -1 : p;
  }
  return 1;
}

#if !REPORT
__kernel void cls_pick(const int n, const int targets, __global const int* picks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status, __global ulong* out_mb, __global ulong* out_me)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0, chosen[6];
  ulong mb = 0, me = 0;
  double d = 0.0;
  if (!picks_ok(&T, picks, gid, chosen)) status = 1;
  else {
    Row r;
    sheet(&T, &r, chosen, tmasks[gid], gmasks[gid], pts, targets, &group);
    d = fight(&r, &P, &status, &mb, &me);
  }
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status; out_mb[gid] = mb; out_me[gid] = me;
}
#else
#define NSTAT 20
__kernel void cls_report(const int n, const int targets, __global const int* picks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status, __global ulong* out_mb, __global ulong* out_me,
    __global double* out_src, __global int* out_ord, __global int* out_nord, __global double* out_mana,
    __global double* out_act_t, __global int* out_act_id, __global int* out_nact, __global double* out_stats)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0, chosen[6];
  ulong mb = 0, me = 0;
  double d = 0.0;
  St keep;
  keep.nord = 0; keep.nact = 0; keep.mana = 0.0;
  Row r;
  if (!picks_ok(&T, picks, gid, chosen)) status = 1;
  else {
    sheet(&T, &r, chosen, tmasks[gid], gmasks[gid], pts, targets, &group);
    d = fight(&r, &P, &status, &mb, &me, &keep);
  }
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status; out_mb[gid] = mb; out_me[gid] = me;
  out_nord[gid] = keep.nord;
  for (int i = 0; i < NSRC; i++) {
    out_ord[(long)gid * NSRC + i] = (i < keep.nord) ? keep.ord[i] : -1;
    out_src[(long)gid * NSRC + i] = (i < keep.nord) ? keep.src[keep.ord[i]] : 0.0;
  }
  out_mana[gid] = (status == 0 && r.mana_max > 0.0) ? 100.0 * keep.mana / r.mana_max : 0.0;
  out_nact[gid] = keep.nact;
  for (int i = 0; i < MAXA; i++) {
    out_act_t[(long)gid * MAXA + i] = (i < keep.nact) ? keep.act_t[i] : 0.0;
    out_act_id[(long)gid * MAXA + i] = (i < keep.nact) ? keep.act_id[i] : -1;
  }
  __global double* o = out_stats + (long)gid * NSTAT;
  if (status == 0) {
    o[0] = r.agi; o[1] = r.str; o[2] = r.intel; o[3] = r.damage; o[4] = r.potency; o[5] = r.mastery; o[6] = r.crit;
    o[7] = r.rating; o[8] = r.haste; o[9] = r.aspd; o[10] = r.luck; o[11] = r.magic_add; o[12] = r.phys_add;
    o[13] = r.hp; o[14] = r.mana_max; o[15] = r.mana_regen; o[16] = (r.mask & S_GALA) ? 1.0 : 0.0;
    o[17] = r.cd_temp; o[18] = r.flat_cdr; o[19] = r.armor_pen;
  }
}
#endif
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "tlum": 4, "I0JA": 5, "I096": 6, "I03C": 7, "I00L": 8,
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I0U2": 14, "I0U5": 15,
    "I0QN": 16,
    # incoming hits (docs/defense-model.md, Berserker inventory)
    "I0BC": 17, "stre": 17,                  # Spiked Carapace A083: 10% of melee damage back
    "I0BD": 18, "I0GX": 18, "I0JK": 18,      # Thorns Aura A0NH: 10% of melee damage back
    "I02Q": 19,                               # Dragonscale Aura: 10% of attack damage taken
    "I04M": 20,                               # Sunstrider Crown: 15% of attack damage taken, magical
    "I0B5": 21,                               # Shield of Death: 8% x Luck, 125 on attack
    "I0GE": 22,                               # Warlord's Battlemask: 8% x Luck, +28% AS 6 s
    "I09X": 23,                               # Seal of the Black Empire: 25% x Luck, +1 Mastery (20)
    "I0F2": 24,                               # Plasma-Core Belt: +3 mana per attack against the hero
    "I015": 25,                               # Icecrown Ring: mana per attack, freezes the attacker
    "I06N": 26,                               # Nerubian Scales: 5% x Luck stun 1.5 s
    "I07A": 27, "I07C": 28, "I0IS": 29, "I0SU": 30, "I0DL": 31, "I06J": 32,  # evasion
    "I024": 33, "arsc": 34, "I079": 35, "fgun": 36,  # DamageIncrease pool by hero health
    "I05N": 37,                               # Bloodhowl: base attack cooldown x (1 - 0.30 missing)
    "I00J": 38,                               # Blade of the Fallen Seraph: +1% max HP per attack, self-damage
    "I0D4": 39,                               # Eversong Defender: 5% x Luck heal 8% max mana on attack
    # healing that changes the damage (only with an HP-dependent effect or Bloodlord's Regalia)
    "I05V": 40,   # Bloodlord's Regalia: stores Healing Type healing, bursts every 3 s
    "I025": 41,   # Titan's Breastplate: regeneration disabled (and -50% Healing Type, pal)
    "I02K": 42,   # Cursed Skull: regeneration damages the hero instead
    "I02R": 43,   # Edge of the Red Court: lifesteal is Healing Type, +10 + level per lifesteal
    "I04H": 44,   # Goredrinker: lifesteal + 0.5% target max HP, at most 3% own max HP
    "I0NU": 45,   # Bloodreaver Scythe: Vampiric Aura 13% (owner), Seraph's aura 10%
    "I0D0": 46,   # Dragon Figurine: +1% healing received per armor
    "I0EC": 47,   # Bloodstone: Sanguine Aura, 2.5% of damage enemies take (doubled < 40%)
    "I074": 48,   # Seal of Vampirism: damage dealt 3% x Luck -> +40 health
    "I0IB": 49,   # Masochist Mask: attacks against the hero restore 0.3% max HP
    "I0P3": 50,   # Primalist Ring: +0.5% Physical Type damage per point of HP regeneration
    "I06C": 51,   # Staff of Idrassil: damage taken -> Blessing 5 s, 1% + 1% max HP per second
    "I0SL": 52,   # Jade Forest Mantle: 20% x Luck heal 40% of damage taken
    "engr": 53,   # Amber's Gaze: spellcasts restore 50 (doubled < 40%)
    "I0UH": 54,   # Earthliving Weapon: attacks restore 10 + 20% primary + 3% max mana
    "I058": 55,   # Moon Scythe: attacks restore 3.5% max mana
    "I0HY": 56,   # Idol of the Forest: Healing Aura +10 HP regeneration
    "I02B": 57,   # Signet of the Scourge: Unholy Aura +5 HP regeneration (+15% regen, pal)
    "sor1": 58,   # Crusader's Chestplate: spellcasts restore their mana cost
    "I0HN": 59,   # Tribal Staff: Healing Aura +10 regen; spellcasts restore 25% primary
    "I0SR": 60,   # Seraphim Staff: spellcasts restore 25 + 75% primary
    "I066": 61,   # Crown of the Highlord: spellcasts restore 3% max HP
    "I07N": 62,   # Holy Scepter: spellcasts restore 2% max HP
    # DamageIncrease pool by target (PreDamage_Increase)
    "I0CZ": 63,   # Giantsbane: + 0.75% per point of target armor
}
# pal columns (not mask bits): Voodoo Doll, Ancient Voodoo Doll
POOL_FLAT = {"I0AM": 0.03}
TALENT_BITS = {
    "I0LO": 0, "I0PE": 1, "I0A2": 2, "I0LS": 3, "I09O": 4, "I0LR": 5, "I09V": 6, "I0LQ": 7, "I0PD": 8,
    "I0PF": 9, "I0A3": 10, "I0PG": 11, "I0HS": 12, "I0TZ": 13, "I0U1": 14,
    # berserker.IGNORED_TALENTS: no effect on the fight
    "I0MD": 20, "I0MC": 21, "I0LP": 22, "I0PH": 23, "I0U0": 24,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"headhunter": 0, "poison": 1, "fury": 2}

# Level-15 Berserker O005 (map 2.5.2c): base attributes int(base + 14 * per-level), base health.
LEVEL = 15
BASE_STR = int(14 + (LEVEL - 1) * 1.4)
BASE_AGI = int(28 + (LEVEL - 1) * 2.8)
BASE_INT = int(8 + (LEVEL - 1) * 0.8)
BASE_HP = 230.0
WHITE_BASE = 30.0
SWING = 1.6

# Talent names and the talents without a fight effect (moved from the removed sunken_sim.berserker model).
TALENT_NAMES = {'I0LO': 'Axe Mastery',
    'I0PE': 'Might of Dambala',
    'I0A2': 'Berserk',
    'I0LS': 'Executor',
    'I09O': 'Deadly Poison',
    'I0LP': 'Voodoo Shuffle',
    'I0LR': 'Poison Bomb',
    'I09V': 'Boneslicer',
    'I0LQ': 'Blood Craze',
    'I0PD': 'Leeching Poison',
    'I0PF': 'Poisoned Blades',
    'I0A3': 'Blood Hunter',
    'I0PG': 'Way of the Snake',
    'I0PH': "Taz'dingo", 'I0HS': 'Wound Poison',
    'I0TZ': 'Hemotoxin',
    'I0U0': 'Gurubashi Ward',
    'I0U1': 'Gift of the Blood God'}
IGNORED_TALENTS = frozenset({"I0MD", "I0MC", "I0LP", "I0PH", "I0U0"})


# Healing Type / regeneration numbers of the map (trigger Healing, AfterDamage_Global, item tooltips).
RECV_MOD = {"I0C4": 0.15, "I06I": 0.18, "I05V": 0.10, "fgrd": -0.30, "I025": -0.50, "oven": 0.12}
OWN_EXTRA = {"I06I": 0.12}            # Husk of Nordrassil: 30% for the hero's own Healing Type effects
HT_ATTACK = {"I0NE": (0.0, 0.03), "I06F": (10.0, 0.01)}  # attacks restore flat + % max HP (Healing Type)
REGEN_MAXHP = {"I06L": 0.01, "modt": 0.01}
HEAL_FLAT = {"I07D": 8.0, "I062": 5.0, "rde3": 3.0, "I03N": 5.0}
HEAL_FLAT_INT = {"I062": 0.05}
HEAL_POT = {"I0EZ": 0.5}
VOODOO = {"spsh": 1.0}


def heal_columns(item) -> list:
    """pal 13..26: regen flat, regen %, Healing Power, lifesteal, received-healing modifier, own-healing extra,
    Healing Type per attack (% max HP, flat), regen % of max HP, flat heal bonus, its Intelligence part, its
    Potency part, flat DamageIncrease (Voodoo Doll), Ancient Voodoo Doll."""
    import re

    code, tip = item.rawcode, item.tip
    num = lambda raw: float(raw.replace(",", "."))
    regen = sum(num(v) for v in re.findall(r"\+(\d+(?:[.,]\d+)?) Health per [Ss]econd", tip))
    regen_pct = sum(num(v) for v in re.findall(r"Increases your Health Regeneration by (\d+(?:[.,]\d+)?)%", tip)) / 100.0
    power = sum(num(v) for v in re.findall(r"\+(\d+(?:[.,]\d+)?)% Healing Power", tip)) / 100.0
    steal = sum(num(v) for v in re.findall(r"\+(\d+(?:[.,]\d+)?)% Lifesteal", tip)) / 100.0
    flat, pct = HT_ATTACK.get(code, (0.0, 0.0))
    return [regen, regen_pct, power, steal, RECV_MOD.get(code, 0.0), OWN_EXTRA.get(code, 0.0), pct, flat,
            REGEN_MAXHP.get(code, 0.0), HEAL_FLAT.get(code, 0.0), HEAL_FLAT_INT.get(code, 0.0), HEAL_POT.get(code, 0.0),
            POOL_FLAT.get(code, 0.0), VOODOO.get(code, 0.0)]


def berserker_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the agility primary fold and the berserker-only per-piece columns."""
    import re

    from sunken_sim import pressure, shadow
    from sunken_sim.stacking import stack_fields

    if (pressure.ATTACK_INTERVAL, pressure.ATTACK_COOLDOWN, pressure.SLOTS, pressure.HIT_OF_MAX, pressure.HEAL_OF_MAX,
            pressure.HEAL_EVERY, pressure.HP_FLOOR, pressure.STR_HP) != (0.2, 1.0, 5, 0.05, 0.75, 3.0, 1.0, 15.0):
        raise ValueError("kernel constants assume the 2026-11-17 hero health model")
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(BASE_INT), float(BASE_STR), float(BASE_AGI), float(BASE_HP)], "Berserker")
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
                prim = bonus["primary"] if (bonus.get("primary") and not item.agility and not item.all_stats) else 0.0
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
            *heal_columns(item),
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class BerserkerCL(C.ExactCL):
    hero = "berserker"
    PYTHON = False  # sunken_sim.berserker fight model removed 2026-11-21: fixtures + report mode
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ()  # no timeline cache: every ESC trial is its own fight
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "pal", "base")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pow_b = np.zeros(0, dtype=np.uint64)
        self.pow_e = np.zeros(0, dtype=np.uint64)
        self.pow_v = np.zeros(0, dtype=np.float64)
        self._pow_upload()
        self.counts.update(pow_values=0, pow_reruns=0)

    @staticmethod
    def module():
        raise RuntimeError("berserker: the Python fight model was removed (2026-11-21)")

    def tables(self, space, items, sources):
        return berserker_tables(space, items, sources)

    def timeline_key(self, build):
        # berserker.simulate has no fight cache: every trial is scored on its own points
        from dataclasses import fields

        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points"))

    # -- x ** y table ---------------------------------------------------
    def _pow_upload(self) -> None:
        mf = self.cl.mem_flags
        b = self.pow_b if len(self.pow_b) else np.zeros(1, dtype=np.uint64)
        e = self.pow_e if len(self.pow_e) else np.zeros(1, dtype=np.uint64)
        v = self.pow_v if len(self.pow_v) else np.zeros(1, dtype=np.float64)
        self._pow_bufs = [self.cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(a)) for a in (b, e, v)]

    def _pow_args(self):
        return [*self._pow_bufs, np.int32(len(self.pow_b))]

    def pow_add(self, kb, ke) -> int:
        """Add host-Python ``x ** y`` for the (x, y) float64 bit patterns."""
        pairs = sorted(set(zip((int(x) for x in kb), (int(y) for y in ke))) - set(zip(self.pow_b.tolist(), self.pow_e.tolist())))
        if not pairs:
            return 0
        allp = sorted(set(zip(self.pow_b.tolist(), self.pow_e.tolist())) | set(pairs))
        vals = dict(zip(zip(self.pow_b.tolist(), self.pow_e.tolist()), self.pow_v.tolist()))
        for b, e in pairs:
            x = float(np.array([b], dtype=np.uint64).view(np.float64)[0])
            y = float(np.array([e], dtype=np.uint64).view(np.float64)[0])
            vals[(b, e)] = x ** y
        self.pow_b = np.array([p[0] for p in allp], dtype=np.uint64)
        self.pow_e = np.array([p[1] for p in allp], dtype=np.uint64)
        self.pow_v = np.array([vals[p] for p in allp], dtype=np.float64)
        self._pow_upload()
        self.counts["pow_values"] = len(self.pow_b)
        return len(pairs)

    # -- launches with the pow table --------------------------------------
    def _ensure(self, n: int) -> None:
        if n <= self._cap:
            return
        super()._ensure(n)
        mf = self.cl.mem_flags
        self.out_mb = self.cl.Buffer(self.ctx, mf.WRITE_ONLY, 8 * self._cap)
        self.out_me = self.cl.Buffer(self.ctx, mf.WRITE_ONLY, 8 * self._cap)

    def _read5(self, n):
        dps, group, status = self._read(n)
        mb = np.empty(n, dtype=np.uint64)
        me = np.empty(n, dtype=np.uint64)
        self.cl.enqueue_copy(self.queue, mb, self.out_mb)
        self.cl.enqueue_copy(self.queue, me, self.out_me)
        self.queue.finish()
        return dps, group, status, mb, me

    def _launch_rows(self, chunks, tmasks, gmasks, points):
        cl = self.cl
        n = len(chunks)
        self._ensure(n)
        mf = cl.mem_flags

        def buf(a):
            return cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(a))

        pts = np.ascontiguousarray(np.asarray(points, dtype=np.int32).reshape(n, C.NP))
        # The buffers must outlive the launch: a kernel argument does not keep its buffer alive.
        args = [buf(np.asarray(chunks, dtype=np.int64)), buf(np.asarray(tmasks, dtype=np.uint32)),
                buf(np.asarray(gmasks, dtype=np.uint32)), buf(pts), buf(pts)]
        self.k_rows_any.set_args(np.int32(n), np.int32(self.targets), *args, *self.tab_args, *self._pow_args(),
                                 self.out_dps, self.out_group, self.out_status, self.out_mb, self.out_me)
        cl.enqueue_nd_range_kernel(self.queue, self.k_rows_any, (n,), None)
        out = self._read5(n)
        del args
        return out

    def _settle(self, dps, group, status, mb, me, rerun) -> None:
        for _ in range(MAX_POW_ROUNDS):
            idx = np.nonzero(status == POW_MISS)[0]
            if not len(idx):
                return
            self.pow_add(mb[idx], me[idx])
            d, g, s, b, e = rerun(idx)
            dps[idx], group[idx], status[idx], mb[idx], me[idx] = d, g, s, b, e
            self.counts["pow_reruns"] += len(idx)

    def bare(self, start: int, n: int):
        self._ensure(n)
        self.k_bare.set_args(np.int64(start), np.int32(n), np.int32(self.targets), *self.tab_args, *self._pow_args(),
                             self.out_dps, self.out_group, self.out_status, self.out_mb, self.out_me)
        self.cl.enqueue_nd_range_kernel(self.queue, self.k_bare, (n,), None)
        dps, group, status, mb, me = self._read5(n)
        self.counts["bare_rows"] += n

        def rerun(idx):
            k = len(idx)
            self.k_rows_any = self.k_rows_bare
            return self._launch_rows(start + idx.astype(np.int64), np.zeros(k, np.uint32), np.zeros(k, np.uint32),
                                     np.zeros((k, C.NP), np.int32))

        self._settle(dps, group, status, mb, me, rerun)
        return dps, group, status

    def rows(self, chunks, tmasks, gmasks, points, tlpoints=None):
        n = len(chunks)
        if n == 0:
            return np.empty(0), np.empty(0, np.uint8), np.empty(0, np.uint8)
        chunks = np.asarray(chunks, dtype=np.int64)
        tmasks = np.asarray(tmasks, dtype=np.uint32)
        gmasks = np.asarray(gmasks, dtype=np.uint32)
        points = np.asarray(points, dtype=np.int32).reshape(n, C.NP)
        self.k_rows_any = self.k_rows
        dps, group, status, mb, me = self._launch_rows(chunks, tmasks, gmasks, points)
        self.counts["rows"] += n

        def rerun(idx):
            self.k_rows_any = self.k_rows
            return self._launch_rows(chunks[idx], tmasks[idx], gmasks[idx], points[idx])

        self._settle(dps, group, status, mb, me, rerun)
        return dps, group, status

    # -- explicit pieces and the report ------------------------------------
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
                buf(np.asarray(gmasks, dtype=np.uint32)), buf(np.asarray(points, dtype=np.int32).reshape(n, C.NP))]
        kernel.set_args(np.int32(n), np.int32(self.targets), *args, *self.tab_args, *self._pow_args(),
                        self.out_dps, self.out_group, self.out_status, self.out_mb, self.out_me, *extra_out)
        cl.enqueue_nd_range_kernel(self.queue, kernel, (n,), None)
        out = self._read5(n)
        del args
        return out

    def pick(self, picks, tmasks, gmasks, points):
        """DPS of explicit builds: picks (n, 6) piece indices, -1 = empty slot."""
        n = len(picks)
        if n == 0:
            return np.empty(0), np.empty(0, np.uint8), np.empty(0, np.uint8)
        if not hasattr(self, "_k_pick"):
            self._k_pick = self.cl.Kernel(self.p_full, "cls_pick")
        picks = np.asarray(picks, dtype=np.int32).reshape(n, 6)
        tmasks = np.asarray(tmasks, dtype=np.uint32)
        gmasks = np.asarray(gmasks, dtype=np.uint32)
        points = np.asarray(points, dtype=np.int32).reshape(n, C.NP)
        dps, group, status, mb, me = self._pick_launch(self._k_pick, picks, tmasks, gmasks, points)
        # A fight stops at its first missing x ** y: keep adding values while every round fills some.
        for _ in range(1000):
            idx = np.nonzero(status == POW_MISS)[0]
            if not len(idx) or not self.pow_add(mb[idx], me[idx]):
                break
            d, g, st, b_, e_ = self._pick_launch(self._k_pick, picks[idx], tmasks[idx], gmasks[idx], points[idx])
            dps[idx], group[idx], status[idx], mb[idx], me[idx] = d, g, st, b_, e_
            self.counts["pow_reruns"] += len(idx)
        return dps, group, status

    SOURCE_NAMES = ("Автоатака", "Toxic Sack", "Skull Split", "Venomous Axes", "Surge of Toxins", "Way of the Snake",
                    "Axe Mastery", "Всплеск огня", "Sulfuras", "Sulfuras (удар)",
                    "Отражение урона", "Sunstrider Crown", "Shield of Death", "Shado-Pan Faceguard",
                    "Bloodlord's Regalia")
    ACTION_NAMES = ("Toxic Sack", "Skull Split")
    STAT_KEYS = ("agi", "str", "int", "damage", "potency", "mastery", "crit", "rating", "haste", "attack_speed", "luck",
                 "magic_add", "phys_add", "hp", "mana_max", "mana_regen", "galactic", "cd_temp", "flat_cdr", "armor_pen")
    NSRC, MAXA = 15, 64

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
            "act_id": np.empty(self.MAXA, np.int32), "nact": np.empty(1, np.int32), "stats": np.zeros(len(self.STAT_KEYS), np.float64),
        }
        for _ in range(1000):
            bufs = {k: cl.Buffer(self.ctx, mf.WRITE_ONLY, v.nbytes) for k, v in outs.items()}
            dps, group, status, mb, me = self._pick_launch(
                self._k_report, picks, tm, gm, pts,
                [bufs[k] for k in ("src", "ord", "nord", "mana", "act_t", "act_id", "nact", "stats")])
            if status[0] != POW_MISS:
                break
            self.pow_add(mb, me)
        if status[0]:
            raise RuntimeError(f"berserker report status {int(status[0])}")
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
        stats["galactic"] = bool(stats["galactic"])
        actions = [(float(outs["act_t"][i]), self.ACTION_NAMES[int(outs["act_id"][i])]) for i in range(int(outs["nact"][0]))]
        return {"dps": float(dps[0]), "total": total, "sources": sources, "actions": actions,
                "mana_left": float(outs["mana"][0]), "stats": stats, "group": int(group[0])}

    @property
    def k_rows_bare(self):
        if not hasattr(self, "_k_rows_bare"):
            self._k_rows_bare = self.cl.Kernel(self.p_bare, "cls_rows")
        return self._k_rows_bare


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check


# Builds whose fight depends on the incoming hits (talents and items): their frozen pre-2026-11-21 values changed
# on purpose with the incoming-hit model and are not replayed by farm/hybrid/test_fixtures.py.
INCOMING_TALENTS = frozenset({"I0LO", "I0A2", "I09V"})
INCOMING_ITEMS = (frozenset(code for code, bit in SPECIAL_BITS.items() if bit >= 17) | {"I0U5"}
                  | set(RECV_MOD) | set(HT_ATTACK) | set(REGEN_MAXHP) | set(HEAL_FLAT) | set(HEAL_POT) | set(POOL_FLAT) | set(VOODOO))
