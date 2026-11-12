"""Exact float64 OpenCL kernel for Berserker fights (Headhunter, Poison, Fury).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.berserker.stats_of`` (agility primary, Blood Fury agility from
health, Gift of the Blood God, Hemotoxin, typed adds, luck and health from
tooltips) and run ``berserker.simulate`` with its Ledger sums in insertion order.

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

from farm.hybrid import class_cl as C

NPAL = 13
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
#define NPAL 13
#define MAXT 8
#define MAXP 16
#define NSRC 10
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

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, hemo, armor_pen, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, hp;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  int nexec, targets, glass;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  __global const ulong* pkb; __global const ulong* pke; __global const double* pv; int np;
} PowT;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double va_until[MAXT], dambala[MAXT], surge_p[MAXT], surge_at[MAXT];
  double pend[MAXP]; int npend;
  double mana, mana_time, lm;
  double hp_max, hp_health, hp_next_hit, hp_next_heal; long hp_idx; int hp_flat;
  int armed, status;
  ulong miss_b, miss_e;
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

/* pressure.hero_hp_ratio(time, hp, 0.0): the 0.01 s health table, replayed with a cursor */
void hp_reset(St* s) {
  s->hp_health = s->hp_max;
  s->hp_next_hit = 0.2;
  s->hp_next_heal = 1.0;
  s->hp_idx = -1;
}

double hero_ratio(St* s, double t) {
  if (s->hp_flat) return 1.0;
  long index = (long)(t * 100.0 + 1e-6);
  index = (index < 0) ? 0 : index;
  index = (index > 3000) ? 3000 : index;
  if (index >= 3000) return 1.0;  /* the last table slot is never painted: it stays 1.0 */
  if (index < s->hp_idx) hp_reset(s);
  /* apply every event whose paint index is <= index (events past FIGHT never happen) */
  while (1) {
    int is_hit = s->hp_next_hit <= s->hp_next_heal;
    double moment = is_hit ? s->hp_next_hit : s->hp_next_heal;
    if (moment > FIGHT) break;
    long ei = (long)(moment * 100.0 + 1e-6);
    ei = (ei > 3000) ? 3000 : ei;
    if (ei > index) break;
    if (is_hit) {
      double h = s->hp_health - 91.0;
      s->hp_health = (1.0 >= h) ? 1.0 : h;
      s->hp_next_hit = s->hp_next_hit + 0.2;
    } else {
      double ceiling = s->hp_max * 1.0;
      if (s->hp_health < ceiling) {
        double h = s->hp_health + 0.5 * s->hp_max;
        s->hp_health = (ceiling <= h) ? ceiling : h;
      }
      s->hp_next_heal = s->hp_next_heal + 1.0;
    }
  }
  s->hp_idx = index;
  return s->hp_health / s->hp_max;
}

int va_on(const St* s, int i, double now) { return now < s->va_until[i]; }

double taken_for(const Row* r, St* s, int i, double now) {
  double armor = 15.0 - r->armor_pen;
  if (TM(r, T_WOUND) && va_on(s, i, now)) armor -= 3.0;
  if (armor > 0.0) return 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor);
  if (armor < 0.0) { if (!s->status) s->status = 4; return 1.0; }
  return 1.0;
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

double attack_hit(const Row* r, St* s, int name, double raw, double when, double potency_scale, int index, double count) {
  double amount = raw;
  double increase = 1.0;
  if (SP_HEAD) increase += 0.12;
  if (TM(r, T_EXEC) && target_hp(when) <= 0.40) increase += 0.35;
  amount *= increase;
  double chance = r->crit;
  if (TM(r, T_BONE)) chance += 10.0 + 0.5 * (100.0 * (1.0 - hero_ratio(s, when)));
  double mult = 2.0 + r->rating;
  if (SP_HEAD) mult += 0.10 + 0.008 * r->mastery;
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

void va_tick(const Row* r, const PowT* P, St* s, int index, double now) {
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
  if (SP_POISON) ticks += chance01((5.0 + 0.5 * r->mastery) / 100.0);
  double typed = TM(r, T_HEMO) ? physical(r, now) : gen_mult(r, now);
  finish(r, s, N_VA, raw * typed, index, now, calls * ticks, coeff * typed);
  if (!SP_POISON) surge_proc(s, index, now, 1.0 - pow_lookup(P, s, 1.0 - chance01(0.02 * s->lm), calls));
  else poison_spec_proc(P, s, index, now, calls * ticks);
  if (TM(r, T_DAMBALA)) {
    s->dambala[index] += chance01(0.20 * s->lm) * calls * ticks;
    while (s->dambala[index] >= 1.0) {
      s->dambala[index] -= 1.0;
      double v = now + 4.0;
      s->va_until[index] = (s->va_until[index] >= v) ? s->va_until[index] : v;
    }
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
  double back = cost * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * r->mastery;
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

double berserk_speed(const Row* r, double now) {
  if (!TM(r, T_BERSERK) || now < 0.2) return 0.0;
  double phase = fmod(now - 0.2, 6.0 + 0.2);
  if (phase >= 6.0) return 0.0;
  int stacks = (int)(phase / 0.2 + 1e-9);
  double per = SP_FURY ? 0.02 : 0.03;
  return 0.12 + per * (double)stacks;
}

void axe_hit(const Row* r, St* s, double now, double count) {
  attack_hit(r, s, N_AXE, 20.0 + 1.25 * dcs(r), now, r->attack_potency, 0, count);
}

double fight(const Row* r, const PowT* P, int* status, ulong* miss_b, ulong* miss_e) {
  St s;
  s.nord = 0; s.seen = 0u;
  for (int id = 0; id < 8; id++) { s.seen |= 1u << id; s.ord[s.nord++] = id; s.src[id] = 0.0; }
  s.status = 0; s.miss_b = 0; s.miss_e = 0;
  s.lm = 1.0 + r->luck;
  const int targets = r->targets;
  for (int i = 0; i < MAXT; i++) { s.va_until[i] = -1.0; s.dambala[i] = 0.0; s.surge_p[i] = 0.0; s.surge_at[i] = -1.0; }
  s.npend = 0;
  s.mana = r->mana_max; s.mana_time = 0.0; s.armed = 0;
  s.hp_flat = 0;
  if (r->hp <= 1.0) s.hp_flat = 1;
  else { s.hp_max = rint(r->hp * 1000.0) / 1000.0; if (s.hp_max <= 1.0) s.hp_flat = 1; hp_reset(&s); }
  const int sulf = (r->mask & S_SULF) != 0;
  const int blades = TM(r, T_BLADES) || (r->mask & S_VENOM);
  const double fury_mult = SP_FURY ? 0.85 : 1.0;
  const double agi = r->agi;
  const double cast_time = CAST_POINT + CAST_BACKSWING;
  double next_attack = 0.0, next_sack = 0.0, next_skull = 0.0, next_tick = 1.0, next_pressure = 0.2, busy = 0.0;
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
    if (next_pressure < moment) moment = next_pressure;
    if (land < moment) moment = land;
    if (moment >= FIGHT) break;
    if (moment == land) {
      for (int k = 1; k < s.npend; k++) s.pend[k - 1] = s.pend[k];
      s.npend--;
      double raw = 80.0 * 1.0 - 20.0 + 2.2 * agi;
      for (int i = 0; i < targets; i++) {
        double coeff = 1.0;
        if (TM(r, T_BOMB)) coeff = va_on(&s, i, moment) ? 1.6 : 1.3;
        double ph = physical(r, moment);
        finish(r, &s, N_SACK, raw * coeff * ph, i, moment, 1.0, coeff * ph);
        poison_spec_proc(P, &s, i, moment, 1.0);
        double v = moment + 4.0;
        s.va_until[i] = (s.va_until[i] >= v) ? s.va_until[i] : v;
      }
      damage_mana(r, &s, (double)targets);
      continue;
    }
    if (moment == next_tick) {
      for (int i = 0; i < targets; i++)
        if (va_on(&s, i, moment - 1e-9)) va_tick(r, P, &s, i, moment);
      next_tick += 1.0;
      continue;
    }
    if (moment == next_pressure) {
      if (TM(r, T_AXE)) axe_hit(r, &s, moment, chance01(0.05 * s.lm));
      next_pressure += 0.2;
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
      int had_va = va_on(&s, 0, moment);
      surge_consume(r, &s, 0, moment);
      attack_hit(r, &s, N_AUTO, power, moment, r->attack_potency, 0, r->auto_pct);
      poison_spec_proc(P, &s, 0, moment, 1.0);
      double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
      if (r->attack_mana_crit != 0.0) {
        double cc = (r->crit < 100.0) ? r->crit : 100.0;
        gain *= 1.0 + cc / 100.0;
      }
      double mv = s.mana + gain;
      s.mana = (mv < r->mana_max) ? mv : r->mana_max;
      damage_mana(r, &s, 1.0);
      double v = moment + 4.0;
      s.va_until[0] = (s.va_until[0] >= v) ? s.va_until[0] : v;
      if (blades && had_va) va_tick(r, P, &s, 0, moment);
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
      if (TM(r, T_AXE)) {
        double rolls = 1.0 + (TM(r, T_CRAZE) ? chance01(0.30 * s.lm) : 0.0);
        axe_hit(r, &s, moment, rolls * chance01(0.10 * s.lm));
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
          add_src(&s, N_SULF, splash * fury_mult);
          damage_mana(r, &s, (double)targets);
        }
        double echo = power * taken * execute * (0.10 * (1.0 + r->luck));
        add_src(&s, N_ECHO, echo * fury_mult);
      }
      double swing = 1.6 * ((r->mask & S_GALA) ? 1.20 : 1.0);
      double speed = r->aspd + berserk_speed(r, moment);
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
  double armor_pen = 0.0, auto_pct = 1.0, attack_potency = 1.0;
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
      mana_flat += f[10];
      for (int j = 0; j < 4; j++) luck += a[5 + j];
      for (int j = 0; j < 4; j++) health_flat += a[9 + j];
    }
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) agility += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  if (GM(r, G_FREN)) aspd += 0.10;
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
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock; r->hp = hp;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->nexec = nexec; r->targets = targets;
  r->glass = (GM(r, G_GLASS) || (mask & S_GLAS)) ? 1 : 0;
}

double row_value(Tab* T, const PowT* P, long index, uint tmask, uint gmask, const int* pts, int targets,
                 int* status, int* group, ulong* mb, ulong* me) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row r;
  sheet(T, &r, chosen, tmask, gmask, pts, targets, group);
  return fight(&r, P, status, mb, me);
}

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
"""

SPECIAL_BITS = {
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "tlum": 4, "I0JA": 5, "I096": 6, "I03C": 7, "I00L": 8,
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I0U2": 14, "I0U5": 15,
}
TALENT_BITS = {
    "I0LO": 0, "I0PE": 1, "I0A2": 2, "I0LS": 3, "I09O": 4, "I0LR": 5, "I09V": 6, "I0LQ": 7, "I0PD": 8,
    "I0PF": 9, "I0A3": 10, "I0PG": 11, "I0HS": 12, "I0TZ": 13, "I0U1": 14,
    # berserker.IGNORED_TALENTS: no effect on the fight
    "I0MD": 20, "I0MC": 21, "I0LP": 22, "I0PH": 23, "I0U0": 24,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"headhunter": 0, "poison": 1, "fury": 2}


def berserker_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the agility primary fold and the berserker-only per-piece columns."""
    import re

    from sunken_sim import berserker as B, pressure, shadow
    from sunken_sim.stacking import stack_fields

    if (B.WHITE_BASE, B.SWING, B.BASE_MANA, B.BASE_HP, B.RANK, B.TROPHIES, B.SACK_CD, B.SACK_MANA, B.SACK_DELAY,
            B.SKULL_CD, B.SKULL_MANA, B.VA_DUR, B.SURGE_DUR, B.BERSERK_DUR, B.PRESSURE_STEP, B.BLOOD_CRAZE_DCS) != \
            (30.0, 1.6, 120.0, 230.0, 1, 200, 10.0, 30.0, 0.75, 20.0, 25.0, 4.0, 5.0, 6.0, 0.2, 30.0):
        raise ValueError("kernel constants assume the 2026-11-12 berserker")
    if (pressure.ATTACK_INTERVAL, pressure.ATTACK_DAMAGE, pressure.HEAL_OF_MAX, pressure.HP_FLOOR, pressure.STR_HP) != \
            (0.2, 91.0, 0.5, 1.0, 15.0):
        raise ValueError("kernel constants assume the 2026-11-12 hero health model")
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(B.BASE_INT), float(B.BASE_STR), float(B.BASE_AGI), float(B.BASE_HP)], "Berserker")
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
        lucks = [int(raw) / 100.0 for raw in re.findall(r"\+(\d+)% Luck\b", item.tip)]
        health = [float(int(raw)) for raw in re.findall(r"\+(\d+) Health\b", item.tip)]
        pal[i] = [
            shadow.MAGICAL_ADDS.get(code, 0.0),
            shadow.PHYSICAL_ADDS.get(code, 0.0),
            item.source_pct / 100.0,
            item.damage_pct / 100.0 - item.source_pct / 100.0,
            1.0 if (code in shadow.MAGICAL_ADDS or code in shadow.PHYSICAL_ADDS) else 0.0,
            *C.pad(lucks, 0.0, "luck", code),
            *C.pad(health, 0.0, "health", code),
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class BerserkerCL(C.ExactCL):
    hero = "berserker"
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
        from sunken_sim import berserker

        return berserker

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
