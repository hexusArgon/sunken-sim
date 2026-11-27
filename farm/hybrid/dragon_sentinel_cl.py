"""Exact float64 OpenCL kernel for Dragon Sentinel fights (Ruby, Obsidian, Emerald). GPU only.

One work-item scores one fight: unrank the six items (or take explicit pieces), fold the sheet
(strength primary, item armour and "+N Attack Damage", Dragonborn, Blazing Strikes) and run every
policy (Lifebinder on / off when allowed, Dragon Form used), keeping the best, with Ledger sums in
insertion order. Dragonfire and Dragon Claw are distributions of expiry times per target, Obsidian
Branded a short list of (expiry, share, value); every chance is a weight.

The Python model (sunken_sim.dragon_sentinel) was removed on 2026-11-27 after bit-exact parity:
farm/hybrid/fixtures/dragon_sentinel.json holds the frozen fights, report mode (-DREPORT=1) gives
sources in Ledger order, casts, mana left and the stat sheet. Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import re

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
/* spec: 0 ruby, 1 obsidian, 2 emerald */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_RUBY (SPEC == 0)
#define SP_OBS (SPEC == 1)
#define SP_EMER (SPEC == 2)
/* REPORT 1: the report kernel also keeps the final fight state (sources in Ledger order, casts, mana) */
#ifndef REPORT
#define REPORT 0
#endif

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 16
#define NSRC 16
#define MAXT 8
#define MAXA 160
#define BS 8
/* largest queue seen on 6000 random fights per spec: Ruby 11, Obsidian 10, Emerald 4 (5 targets); overflow -> status 5 */
#define MAXQ 32
#define BK 3
#define RANK 1.0
#define FAR 300.0

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
#define S_GAUNT (1UL<<14)
#define S_DRAKE (1UL<<15)
#define S_EYE  (1UL<<16)
#define S_LHELM (1UL<<17)
#define S_SILM (1UL<<18)

#define T_WORLD (1u<<0)
#define T_DBORN (1u<<1)
#define T_EARTH (1u<<2)
#define T_SCALES (1u<<3)
#define T_GIFT (1u<<4)
#define T_MELT (1u<<5)
#define T_HEATED (1u<<6)
#define T_ENGULF (1u<<7)
#define T_ALEX (1u<<8)
#define T_BHEART (1u<<9)
#define T_WAKING (1u<<10)
#define T_EXPL (1u<<11)
#define T_LEGACY (1u<<12)
#define T_BLAZE (1u<<13)

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

/* Ledger: only Автоатака is seeded; every other source in order of first write */
#define N_AUTO 0
#define N_BURN 1
#define N_BURNP 2
#define N_BURNC 3
#define N_STRIKE 4
#define N_DRAKE 5
#define N_SHIELD 6
#define N_EXPL 7
#define N_ENGULF 8
#define N_CLEANSE 9
#define N_CFHEAL 10
#define N_BHEART 11
#define N_BOLT 12
#define N_SPLASH 13
#define N_SULF 14
#define N_ECHO 15

/* order[] keys */
#define K_FORM 0
#define K_LIFE 1
#define K_BURN 2
#define K_CLEANSE 3
#define K_STRIKE 4
#define K_SHIELD 5

/* events */
#define E_FURY 0
#define E_BURN 1
#define E_ENGULF 2
#define E_CLEANSE 3
#define E_LIFE 4
#define E_BOLT 5

/* burnout sources */
#define B_HERO 0
#define B_PASSIVE 1
#define B_CRIT 2

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd, armor;
  double magic_add, phys_add, armor_pen, spell_mult, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, hp;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  int nexec, targets, glass, spell_crit;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double fi_e[MAXT][BS + 1], fi_m[MAXT][BS + 1]; int fi_n[MAXT]; double fi_t[MAXT], fi_lo[MAXT];
  double cl_e[MAXT][BS + 1], cl_m[MAXT][BS + 1]; int cl_n[MAXT]; double cl_t[MAXT], cl_lo[MAXT];
#if SPEC == 1
  double br_e[MAXT][BK + 1], br_m[MAXT][BK + 1], br_v[MAXT][BK + 1]; int br_n[MAXT];
#endif
#if SPEC == 2
  double cleanse_until[MAXT];
#endif
  double q_w[MAXQ], q_p[MAXQ], q_m[MAXQ]; uint q_s[MAXQ]; uchar q_k[MAXQ], q_a[MAXQ]; int qn; uint seq;
  uint lp_seq; double lp_at;
  double nxt[6]; uchar order[6]; int norder;
  double am[7]; uchar am_neg[7];
  double mana, mana_time, molten_until, life_until, form_until, burnout_bonus, fury, fury_max;
  double trig0, trig2, trig3, max_life, strength;
  int life_ticking, heated, bolt_target, armed, status, targets;
  AP ap;
#if REPORT
  double act_t[MAXA]; int act_id[MAXA]; int nact;
#endif
} St;

/* actions (dragon_sentinel.simulate names): host ACTION_NAMES, ids = K_* order keys */
void act(St* s, double now, int id) {
#if REPORT
  if (s->nact < MAXA) { s->act_t[s->nact] = now; s->act_id[s->nact] = id; }
  s->nact++;
#else
  (void)s; (void)now; (void)id;
#endif
}

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

/* max(0.0, min(1.0, v)) */
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

double armor_mult(St* s, double armor) {
  if (armor > 0.0) return 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor);
  if (armor < 0.0) return 2.0 - pow(1.0 - 0.04, -armor);  /* shadow.armor_taken */
  return 1.0;
}

/* ---- expiry_buff._Buff (Dragonfire, Dragon Claw per target) ---- */
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


#define FI_MASS(s, t, now) bmass((s)->fi_e[t], (s)->fi_m[t], (s)->fi_n[t], (s)->fi_t[t], (s)->fi_lo[t], now)
#define FI_ARGS(s, t) (s)->fi_e[t], (s)->fi_m[t], &(s)->fi_n[t], &(s)->fi_t[t], &(s)->fi_lo[t]
#define CL_MASS(s, t, now) bmass((s)->cl_e[t], (s)->cl_m[t], (s)->cl_n[t], (s)->cl_t[t], (s)->cl_lo[t], now)
#define CL_ARGS(s, t) (s)->cl_e[t], (s)->cl_m[t], &(s)->cl_n[t], &(s)->cl_t[t], &(s)->cl_lo[t]

void recover(const Row* r, St* s, double now) {
  if (now > s->mana_time && s->mana < r->mana_max) {
    double v = s->mana + r->mana_regen * (now - s->mana_time);
    s->mana = (v < r->mana_max) ? v : r->mana_max;
  }
  s->mana_time = now;
}

void gain_mana(const Row* r, St* s, double amount) {
  double v = s->mana + amount;
  s->mana = (v < r->mana_max) ? v : r->mana_max;
}

int pay(const Row* r, St* s, double cost, double now) {
  recover(r, s, now);
  if (s->mana < cost) return 0;
  s->mana -= cost;
  if (cost > 0.0) gain_mana(r, s, cost * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * r->mastery);
  return 1;
}

void note_damage_mana(const Row* r, St* s, double count) {
  if (r->damage_mana_pct != 0.0) gain_mana(r, s, r->damage_mana_pct * r->mana_max * count);
}

double attack_mana_gain(const Row* r) {
  double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
  if (r->attack_mana_crit != 0.0) {
    double c = (100.0 < r->crit) ? 100.0 : r->crit;
    gain *= 1.0 + c / 100.0;
  }
  return gain;
}

double cooldown_of(double base, const Row* r, double flat) {
  double v = (base * r->cd_temp - r->flat_cdr - flat) / (1.0 + r->haste);
  return (v > 0.5) ? v : 0.5;
}

void push(St* s, double at, int kind, int a, int t, double p) {
  if (s->qn >= MAXQ) { if (!s->status) s->status = 5; return; }
  s->seq += 1u;
  int i = s->qn++;
  s->q_w[i] = at; s->q_s[i] = s->seq; s->q_k[i] = (uchar)kind; s->q_a[i] = (uchar)a; s->q_p[i] = p; s->q_m[i] = -1.0;
}

/* dragon_sentinel push_passive: back-to-back passive procs at one moment merge into one impact */
void push_passive(St* s, double at, double p) {
  if (s->lp_seq != 0u && s->lp_seq == s->seq && s->lp_at == at) {
    for (int i = 0; i < s->qn; i++) {
      if (s->q_s[i] == s->lp_seq) {
        s->q_p[i] = s->q_p[i] + p;
        s->q_m[i] = s->q_m[i] * (1.0 - p);
        return;
      }
    }
  }
  push(s, at, E_BURN, B_PASSIVE, 0, p);
  if (s->status) return;
  s->q_m[s->qn - 1] = 1.0 - p;
  s->lp_seq = s->seq; s->lp_at = at;
}

int peek_idx(const St* s) {
  int b = -1;
  for (int i = 0; i < s->qn; i++)
    if (b < 0 || s->q_w[i] < s->q_w[b] || (s->q_w[i] == s->q_w[b] && s->q_s[i] < s->q_s[b])) b = i;
  return b;
}

int in_form(const St* s, double now) { return s->form_until > now; }

double armor_now(const Row* r, const St* s, double now) {
  double value = r->armor;
  if (SP_OBS && in_form(s, now)) value += 8.0;
  if (s->molten_until > now) value += 2.0 + (TM(r, T_EARTH) ? 3.0 : 0.0);
  return value;
}

double potency_now(const Row* r, const St* s, double now) {
  double value = r->potency;
  if (TM(r, T_SCALES)) value += 0.5 * armor_now(r, s, now);
  return value;
}

double ruby_bonus(const St* s) { return 0.05 + 0.20 * s->strength / 100.0; }

double typed(const Row* r, int kind, double now) {
  /* kind: 0 none, 1 magical, 2 physical */
  double bonus = 1.0;
  if (kind == 1) bonus += r->magic_add;
  else if (kind == 2) bonus += r->phys_add;
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(now);
  if (kind == 1 && (r->mask & S_TLUM)) bonus += 0.05 + 0.005 * r->mastery;
  if (r->glass) bonus *= 1.15;
  return bonus;
}

double dcs(const Row* r, const St* s) { return 14.0 + 0.75 * s->strength + r->damage; }

/* armor_taken(15 - pen - v) for Branded values v = 0..6, filled once per fight */
double am_of(St* s, int v) {
  return s->am[v];
}

#if SPEC == 1
double taken(const Row* r, St* s, int t, double now) {
  double off = 1.0, total = 0.0;
  for (int k = 0; k < s->br_n[t]; k++) {
    if (now < s->br_e[t][k]) {
      total += s->br_m[t][k] * am_of(s, (int)s->br_v[t][k]);
      off -= s->br_m[t][k];
    }
  }
  return total + off * am_of(s, 0);
}

double brand_mass(const St* s, int t, double now) {
  double total = 0.0;
  for (int k = 0; k < s->br_n[t]; k++) if (now < s->br_e[t][k]) total += s->br_m[t][k];
  return total;
}

void brand_apply(St* s, int t, double now, double w, double value) {
  int c = 0;
  for (int k = 0; k < s->br_n[t]; k++)
    if (s->br_e[t][k] > now) { s->br_e[t][c] = s->br_e[t][k]; s->br_m[t][c] = s->br_m[t][k]; s->br_v[t][c] = s->br_v[t][k]; c++; }
  s->br_n[t] = c;
  double added = w * (1.0 - brand_mass(s, t, now));
  if (added <= 0.0) return;
  s->br_e[t][c] = now + 3.0; s->br_m[t][c] = added; s->br_v[t][c] = value; c++;
  if (c > BK) {
    int j = 0;
    for (int i = 1; i < c; i++) if (s->br_m[t][i] < s->br_m[t][j]) j = i;
    int k = (j + 1 < c) ? j + 1 : j - 1;
    s->br_m[t][k] += s->br_m[t][j];
    for (int i = j; i < c - 1; i++) { s->br_e[t][i] = s->br_e[t][i + 1]; s->br_m[t][i] = s->br_m[t][i + 1]; s->br_v[t][i] = s->br_v[t][i + 1]; }
    c--;
  }
  s->br_n[t] = c;
}
#else
/* no Branded outside Obsidian: the loop above with br_n == 0 */
double taken(const Row* r, St* s, int t, double now) { return 0.0 + 1.0 * am_of(s, 0); }
void brand_apply(St* s, int t, double now, double w, double value) {}
#endif

double melting(const Row* r, St* s, int t, double now) {
  if (!TM(r, T_MELT)) return 0.0;
  double flat = 0.0;
  double on = FI_MASS(s, t, now);
  if (on > 0.0) flat += on * (5.0 + (SP_RUBY ? 0.004 * s->max_life : 0.0));
  on = CL_MASS(s, t, now);
  if (on > 0.0) flat += on * (5.0 + (SP_RUBY ? 0.005 * s->max_life : 0.0));
  return flat;
}

void legacy_cdr(const Row* r, St* s, double now, double w) {
  if (!TM(r, T_LEGACY) || w <= 0.0) return;
  int key = -1;
  for (int i = 0; i < s->norder; i++) {
    int k = s->order[i];
    if (k == K_FORM) continue;
    if (key < 0 || s->nxt[k] > s->nxt[key]) key = k;
  }
  if (key < 0) return;
  if (s->nxt[key] > now) {
    double v = s->nxt[key] - 0.75 * w;
    s->nxt[key] = (v > now) ? v : now;
  }
}

void add_fury(St* s, double amount) {
  double v = s->fury + amount;
  s->fury = (v < s->fury_max) ? v : s->fury_max;
}

/* hero_hit over targets t0..t0+n-1; kind 0 none, 1 magical, 2 physical */
double hero_hit(const Row* r, St* s, int name, double raw, double now, int t0, int n, int kind, int attack,
                double potency_scale, double mult, int procs, int crit, double w) {
  /* dragon_sentinel.hero_hit. Everything the Python loop recomputes per target but that does not depend on
     the target (amount before Melting Flames, the armour factor without Branded, the proc chances, the
     Branded value) is computed once: the same expressions, so the same bits. */
  double chance = r->crit;
  double execute = exec_factor(r, now);
  double factor = typed(r, kind, now);
  if (TM(r, T_ALEX) && s->life_until > now) factor *= 1.10;
  double pot = potency_now(r, s, now);
  double luck_mult = 1.0 + r->luck;
  double base = (raw + pot * potency_scale) * factor * mult;
  if (attack && crit) base *= crit_factor(chance, 2.0 + r->rating);
  else if (r->spell_crit && crit) base *= crit_factor(chance, r->spell_mult + r->rating);
  const int melt = TM(r, T_MELT) != 0;
  /* without Branded every target takes the same armour factor */
  double tk_all = SP_OBS ? 0.0 : taken(r, s, t0, now);
  double brand_v = 0.0;
  if (SP_OBS) {
    double a = (double)(int)(1.0 + 0.08 * armor_now(r, s, now));
    brand_v = (6.0 < a) ? 6.0 : a;
  }
  double legacy = TM(r, T_LEGACY) ? 1.15 : 1.0;
  double p_fury = procs ? chance01(0.02 * luck_mult) * w : 0.0;
  double p_cf = (procs && SP_EMER) ? chance01(3.0 * legacy * luck_mult / 100.0) * w : 0.0;
  double total = 0.0;
  for (int t = t0; t < t0 + n; t++) {
    double amount = base;
    if (melt) amount += melting(r, s, t, now);
    double tk = SP_OBS ? taken(r, s, t, now) : tk_all;
    total += amount * tk * execute * w;
    if (SP_OBS) brand_apply(s, t, now, w, brand_v);
    if (!procs) continue;
    add_fury(s, p_fury);
    if (!SP_EMER) {
      double proc = (1.0 + s->burnout_bonus) * legacy;
      double p = chance01(proc * luck_mult / 100.0) * w;
      if (p > 0.0) {
        s->burnout_bonus = s->burnout_bonus * (1.0 - p);
        push_passive(s, now + 0.5, p);
        legacy_cdr(r, s, now, p);
      }
    }
    if (SP_EMER) legacy_cdr(r, s, now, p_cf);
  }
  add_src(s, name, total);
  note_damage_mana(r, s, (double)n * w);
  return total;
}

double cleansing_damage(const St* s) { return 7.0 + 0.01 * s->max_life; }

void heal(const Row* r, St* s, double now) {
  if (!SP_EMER) return;
  double proc = 8.0 * (TM(r, T_LEGACY) ? 1.15 : 1.0);
  double p = chance01(proc * (1.0 + r->luck) / 100.0);
  if (p > 0.0) {
    hero_hit(r, s, N_CFHEAL, 4.0 * cleansing_damage(s), now, 0, s->targets, 0, 0, 0.0, 1.0, 1, 0, p / (double)s->targets);
    legacy_cdr(r, s, now, p);
  }
}

void burnout_impact(const Row* r, St* s, double now, int source, double w, double miss) {
  double dmg = 25.0 * RANK + 1.20 * s->strength;
  if (source == B_PASSIVE) dmg *= 0.40;
  if (SP_RUBY) dmg *= 1.05 + 0.005 * r->mastery;
  if (SP_RUBY && in_form(s, now)) dmg *= 1.0 + ruby_bonus(s);
  if (r->mask & S_GAUNT) dmg *= 1.25;
  int value;
  if (TM(r, T_WORLD) && source == B_HERO) value = SP_OBS ? -1 : 3;
  else value = 2;
  double w12, w3;
  if (value >= 0) {
    double keep = (miss < 0.0) ? (1.0 - w) : miss;
    s->trig0 = s->trig0 * keep;
    if (value == 3) {
      s->trig2 = s->trig2 * keep;
      s->trig3 = 1.0 - (s->trig0 + s->trig2);
    } else {
      s->trig3 = s->trig3 * keep;
      s->trig2 = 1.0 - (s->trig0 + s->trig3);
    }
    w12 = w; w3 = (value == 3) ? w : 0.0;
  } else {
    w12 = w * (s->trig2 + s->trig3); w3 = w * s->trig3;
  }
  int name = (source == B_HERO) ? N_BURN : (source == B_PASSIVE) ? N_BURNP : N_BURNC;
  for (int hit = 1; hit <= 3; hit++) {
    double ww = (hit == 3) ? w3 : w12;
    if (hit == 3) dmg *= 0.60;
    if (ww <= 0.0) continue;
    hero_hit(r, s, name, dmg, now, 0, s->targets, 1, 0, 1.0, 1.0, source != B_PASSIVE, 1, ww);
  }
}

void dragon_strike(const Row* r, St* s, double now, int name, double w) {
  double dmg = 60.0 * RANK + 0.03 * s->max_life;
  int form = in_form(s, now);
  if (form) dmg *= 1.25;
  if (SP_RUBY && form) dmg *= 1.0 + ruby_bonus(s);
  hero_hit(r, s, name, dmg, now, 0, s->targets, 1, 0, 1.0, 1.0, 1, 1, w);
  /* Dragonfire / Dragon Claw are read only by Melting Flames */
  if (!TM(r, T_MELT)) return;
  for (int t = 0; t < s->targets; t++) {
    if (w >= 1.0) bsure(FI_ARGS(s, t), now, 5.0);
    else bmaybe(FI_ARGS(s, t), now, 5.0, w, w);
    if (form) {
      if (w >= 1.0) bsure(CL_ARGS(s, t), now, 5.0);
      else bmaybe(CL_ARGS(s, t), now, 5.0, w, w);
    }
  }
}

double tick_rate(const Row* r, const St* s) {
  double rate = 1.0;
  if (TM(r, T_GIFT)) rate += 0.15 + 0.008 * potency_now(r, s, 0.0);
  if (r->mask & S_LHELM) rate += 0.25;
  return rate;
}

double attack_interval(const Row* r, const St* s, double now) {
  double swing = 2.00 * ((r->mask & S_GALA) ? 1.20 : 1.0);
  double speed = ap_speed(r->aspd + ap_bonus(&s->ap, now));
  return swing / (1.0 + speed);
}

#if REPORT
double sim_policy(const Row* r, int use_life, int use_form, int* status_out, int* forms_out, St* keep) {
#else
double sim_policy(const Row* r, int use_life, int use_form, int* status_out, int* forms_out) {
#endif
  St s;
#if REPORT
  s.nact = 0;
#endif
  if (r->targets > MAXT || r->targets < 1) { *status_out = 3; return 0.0; }
  s.targets = r->targets; s.status = 0; s.armed = 0;
  s.nord = 1; s.seen = 1u; s.ord[0] = N_AUTO; s.src[N_AUTO] = 0.0;
  s.strength = (double)(int)r->str;
  for (int v = 0; v <= 6; v++) {
    double armor = 15.0 - r->armor_pen - (double)v;
    s.am_neg[v] = armor < 0.0;
    s.am[v] = armor_mult(&s, armor);
  }
  s.max_life = r->hp;
  s.mana = r->mana_max; s.mana_time = 0.0;
  s.qn = 0; s.seq = 0u; s.lp_seq = 0u; s.lp_at = 0.0;
  for (int t = 0; t < MAXT; t++) {
    s.fi_n[t] = 0; s.fi_t[t] = 0.0; s.fi_lo[t] = INFINITY;
    s.cl_n[t] = 0; s.cl_t[t] = 0.0; s.cl_lo[t] = INFINITY;
#if SPEC == 1
    s.br_n[t] = 0;
#endif
#if SPEC == 2
    s.cleanse_until[t] = -1.0;
#endif
  }
  s.molten_until = -1.0; s.life_until = -1.0; s.life_ticking = 0; s.form_until = -1.0; s.heated = 0;
  s.burnout_bonus = 0.0; s.trig0 = 1.0; s.trig2 = 0.0; s.trig3 = 0.0;
  s.fury_max = TM(r, T_WAKING) ? 85.0 : 100.0; s.fury = s.fury_max; s.bolt_target = 0;
  int forms = 0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  double gen = 1.0 / (1.0 + r->haste);
  if (TM(r, T_DBORN)) gen /= 1.0 + 0.01 * r->mastery;
  if (r->mask & S_EYE) gen /= 1.20;
  push(&s, gen, E_FURY, 0, 0, 0.0);
  if (TM(r, T_ENGULF)) push(&s, 1.5 / (1.0 + 0.01 * r->mastery), E_ENGULF, 0, 0, 0.0);
  if (SP_EMER) push(&s, 1.0, E_CLEANSE, 0, 0, 0.0);
  s.norder = 0;
  if (use_form) s.order[s.norder++] = K_FORM;
  if (use_life) s.order[s.norder++] = K_LIFE;
  s.order[s.norder++] = SP_EMER ? K_CLEANSE : K_BURN;
  s.order[s.norder++] = K_STRIKE;
  s.order[s.norder++] = K_SHIELD;
  for (int k = 0; k < 6; k++) s.nxt[k] = 0.0;
  double next_attack = 0.0, busy = 0.0, clock = 0.0;
  int loops = 0;
  while (1) {
    loops += 1;
    if (loops > 400000) break;
    if (s.status) break;
    double attack_at = next_attack;
    if (busy > attack_at) attack_at = busy;
    if (clock > attack_at) attack_at = clock;
    double cast_at = FAR;
    int choice = -1;
    for (int i = 0; i < s.norder; i++) {
      int key = s.order[i];
      if (key == K_FORM && (s.fury < s.fury_max - 1e-9 || in_form(&s, clock))) continue;
      double ready = s.nxt[key];
      if (busy > ready) ready = busy;
      if (clock > ready) ready = clock;
      if (ready < cast_at - 1e-9) { cast_at = ready; choice = key; }
    }
    int qi = peek_idx(&s);
    double event_at = (qi >= 0) ? s.q_w[qi] : FAR;
    double moment = attack_at;
    if (cast_at < moment) moment = cast_at;
    if (event_at < moment) moment = event_at;
    if (moment >= FIGHT) break;
    clock = moment;
    if (event_at == moment && event_at < attack_at && event_at < cast_at) {
      int kind = s.q_k[qi], a = s.q_a[qi]; double p = s.q_p[qi], miss = s.q_m[qi];
      s.qn--;
      s.q_w[qi] = s.q_w[s.qn]; s.q_s[qi] = s.q_s[s.qn]; s.q_k[qi] = s.q_k[s.qn];
      s.q_a[qi] = s.q_a[s.qn]; s.q_p[qi] = s.q_p[s.qn]; s.q_m[qi] = s.q_m[s.qn];
      if (kind == E_FURY) {
        add_fury(&s, 1.0);
        push(&s, moment + gen, E_FURY, 0, 0, 0.0);
      } else if (kind == E_BURN) {
        burnout_impact(r, &s, moment, a, p, miss);
      } else if (kind == E_ENGULF) {
        hero_hit(r, &s, N_ENGULF, 5.0 * RANK + 0.5 * armor_now(r, &s, moment), moment, 0, s.targets, 1, 0, 1.0, 1.0, 1, 1, 1.0);
        push(&s, moment + 1.5 / (1.0 + 0.01 * r->mastery), E_ENGULF, 0, 0, 0.0);
      } else if (kind == E_CLEANSE) {
#if SPEC == 2
        int first = -1, n = 0, contiguous = 1;
        for (int t = 0; t < s.targets; t++) {
          if (s.cleanse_until[t] > moment) {
            if (first < 0) first = t;
            else if (t != first + n) contiguous = 0;
            n++;
          }
        }
        if (n > 0) {
          if (!contiguous) { if (!s.status) s.status = 7; break; }
          hero_hit(r, &s, N_CLEANSE, cleansing_damage(&s), moment, first, n, 0, 0, 0.0, 1.0, 1, 0, 1.0);
        }
        push(&s, moment + 1.0, E_CLEANSE, 0, 0, 0.0);
#endif
      } else if (kind == E_LIFE) {
        if (s.life_until > moment) {
          heal(r, &s, moment);
          if (TM(r, T_BHEART))
            hero_hit(r, &s, N_BHEART, 5.0 + 3.0 * 15.0, moment, 0, s.targets, 0, 0, 0.0, 1.0, 1, 0, 1.0);
          push(&s, moment + 1.0 / tick_rate(r, &s), E_LIFE, 0, 0, 0.0);
        } else {
          s.life_ticking = 0;
        }
      } else {
        if (in_form(&s, moment)) {
          int t = s.bolt_target % s.targets;
          s.bolt_target += 1;
          hero_hit(r, &s, N_BOLT, 25.0, moment, t, 1, 0, 0, 0.0, 1.0, 1, 1, 1.0);
          push(&s, moment + 0.5, E_BOLT, 0, 0, 0.0);
        }
      }
      continue;
    }
    if (cast_at <= attack_at && choice >= 0 && moment == cast_at) {
      int key = choice;
      double cost = (key == K_FORM) ? 0.0 : (key == K_BURN || key == K_CLEANSE) ? 20.0 : (key == K_STRIKE || key == K_LIFE) ? 15.0 : 10.0;
      if (!pay(r, &s, cost, moment)) { s.nxt[key] = moment + 0.25; continue; }
      act(&s, moment, key);
      double hit_at = moment + CAST_POINT;
      busy = moment + (CAST_POINT + CAST_BACKSWING) + r->cast_lock;
      if (r->mask & S_SULF) s.armed = 1;
      if (SP_RUBY) s.burnout_bonus += 0.50;
      double flat = 0.0;
      if (key == K_FORM) {
        forms += 1;
        s.fury = 0.0;
        s.form_until = hit_at + 12.0;
        heal(r, &s, hit_at);
        if (TM(r, T_WAKING)) {
          for (int i = 0; i < s.norder; i++) {
            int o = s.order[i];
            if (o != K_FORM) s.nxt[o] = (hit_at < s.nxt[o]) ? hit_at : s.nxt[o];
          }
        }
        if (SP_RUBY) push(&s, hit_at + 0.5, E_BOLT, 0, 0, 0.0);
      } else if (key == K_LIFE) {
        double dur = 6.0 + (in_form(&s, hit_at) ? 6.0 : 0.0) + (TM(r, T_ALEX) ? 2.0 : 0.0);
        double until = hit_at + dur;
        s.life_until = (until > s.life_until) ? until : s.life_until;
        heal(r, &s, hit_at);
        if (!s.life_ticking) {
          s.life_ticking = 1;
          push(&s, hit_at + 1.0, E_LIFE, 0, 0, 0.0);
        }
      } else if (key == K_BURN) {
        push(&s, hit_at + 0.5, E_BURN, B_HERO, 0, 1.0);
        s.heated = TM(r, T_HEATED) ? 1 : 0;
        if (in_form(&s, hit_at)) flat = 2.0;
      } else if (key == K_CLEANSE) {
#if SPEC == 2
        for (int t = 0; t < s.targets; t++) s.cleanse_until[t] = hit_at + 4.0;
        heal(r, &s, hit_at);
#endif
      } else if (key == K_STRIKE) {
        dragon_strike(r, &s, hit_at, N_STRIKE, 1.0);
      } else {
        double dmg = (50.0 * RANK + 1.10 * s.strength) * (1.0 + 0.03 * armor_now(r, &s, hit_at));
        if (SP_RUBY && in_form(&s, hit_at)) dmg *= 1.0 + ruby_bonus(&s);
        if (s.heated) { dmg *= 1.25; s.heated = 0; }
        hero_hit(r, &s, N_SHIELD, dmg, hit_at, 0, 1, 1, 0, 1.0, 1.0, 1, 1, 1.0);
        if (TM(r, T_EXPL) && s.targets > 1)
          hero_hit(r, &s, N_EXPL, 0.15 * dmg, hit_at, 1, s.targets - 1, 1, 0, 0.0, 1.0, 1, 1, 1.0);
        s.molten_until = hit_at + 5.0 + (TM(r, T_EARTH) ? 2.0 : 0.0);
        if (TM(r, T_EXPL)) flat = 1.0;
      }
      if (key != K_FORM) {
        double base = (key == K_BURN || key == K_CLEANSE || key == K_SHIELD) ? 8.0 : 7.0;
        s.nxt[key] = moment + cooldown_of(base, r, flat);
      } else {
        s.nxt[key] = moment + 3.0;
      }
      next_attack = (busy > next_attack) ? busy : next_attack;
      continue;
    }
    moment = attack_at;
    recover(r, &s, moment);
    double power = dcs(r, &s);
    double before = s.src[N_AUTO];
    double chaos = in_form(&s, moment) ? 1.25 : 1.0;
    hero_hit(r, &s, N_AUTO, power, moment, 0, 1, 2, 1, r->attack_potency, chaos, 1, 1, 1.0);
    if (r->auto_pct != 1.0) s.src[N_AUTO] = before + (s.src[N_AUTO] - before) * r->auto_pct;
    double c1 = (r->crit < 100.0) ? r->crit : 100.0;
    double p_crit = ((c1 > 0.0) ? c1 : 0.0) / 100.0;
    double luck_mult = 1.0 + r->luck;
    if (!SP_EMER) {
      double p = chance01(p_crit * 0.33 * luck_mult);
      if (p > 0.0) push(&s, moment + 0.5, E_BURN, B_CRIT, 0, p);
    }
    if (r->mask & S_DRAKE) {
      double chance = (p_crit * 30.0 + (1.0 - p_crit) * 15.0) / 100.0;
      double p = chance01(chance * luck_mult);
      if (p > 0.0) dragon_strike(r, &s, moment, N_DRAKE, p);
    }
    gain_mana(r, &s, attack_mana_gain(r));
    if (r->mask & S_ORB) {
      double splash = (20.0 + 0.35 * s.strength) * (double)s.targets * taken(r, &s, 0, moment) * exec_factor(r, moment);
      add_src(&s, N_SPLASH, splash);
      note_damage_mana(r, &s, (double)s.targets);
    }
    if (r->mask & S_SULF) {
      double execute = exec_factor(r, moment);
      if (s.armed) {
        s.armed = 0;
        double splash = s.strength * typed(r, 1, moment) * taken(r, &s, 0, moment) * execute * (double)s.targets;
        if (r->spell_crit) splash *= crit_factor(r->crit, r->spell_mult + r->rating);
        add_src(&s, N_SULF, splash);
        note_damage_mana(r, &s, (double)s.targets);
      }
      double echo = power * taken(r, &s, 0, moment) * execute * (0.10 * (1.0 + r->luck));
      add_src(&s, N_ECHO, echo);
    }
    ap_attack(&s.ap, moment, r->crit);
    next_attack = moment + attack_interval(r, &s, moment);
  }
  *forms_out = forms;
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < s.nord; i++) total += s.src[s.ord[i]];
#if REPORT
  recover(r, &s, FIGHT);
  *keep = s;
#endif
  return total / FIGHT;
}

/* dragon_sentinel.simulate: best of the two (Lifebinder on / off, Dragon Form) policies */
#if REPORT
double fight(const Row* r, int* status_out, St* keep) {
  St tmp;
#else
double fight(const Row* r, int* status_out) {
#endif
  double best = 0.0;
  int have = 0;
  /* dragon_sentinel.policies_for: (Lifebinder, Dragon Form) only with Burning Heart, Alexstrasza or Emerald,
     then (no Lifebinder, Dragon Form) */
  int life_ok = SP_EMER || TM(r, T_BHEART) || TM(r, T_ALEX);
  for (int i = life_ok ? 0 : 1; i < 2; i++) {
    int st = 0, forms = 0;
#if REPORT
    double d = sim_policy(r, i == 0, 1, &st, &forms, &tmp);
#else
    double d = sim_policy(r, i == 0, 1, &st, &forms);
#endif
    if (st) { *status_out = st; return 0.0; }
    if (!have || d > best + 1e-9) {
      best = d; have = 1;
#if REPORT
      *keep = tmp;
#endif
    }
  }
  return best;
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

/* dragon_sentinel.stats_of(build) */
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
    strength = strength + f[6];
    potency += f[7];
    mastery += f[8];
    damage += f[9];
    {
      __global const double* a0 = T->pal + (long)p * NPAL;
      damage += f1 ? a0[14] : a0[15];
    }
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
      if (u[11] != 0.0) spell_crit = 1;
      if (u[12] != 0.0) spell_mult = 1.65;
      if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
      auto_pct += u[8];
      armor_items += a[13];
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
  if (TM(r, T_DBORN)) mastery += 10.0;
  if (TM(r, T_BLAZE)) { aspd += 0.20; crit += 5.0; }
  double hp = (T->base[3] + 15.0 * strength) + health_flat;
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
  r->armor = (4.0 + 0.1 * agility) + armor_items + (TM(r, T_SCALES) ? 3.0 : 0.0);
  r->magic_add = magic_add; r->phys_add = phys_add; r->armor_pen = armor_pen;
  r->spell_crit = spell_crit; r->spell_mult = spell_mult;
  r->auto_pct = auto_pct; r->attack_potency = attack_potency;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock; r->hp = hp;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->nexec = nexec; r->targets = targets;
  r->glass = (GM(r, G_GLASS) || (mask & S_GLAS)) ? 1 : 0;
}

#if !REPORT
double row_value(Tab* T, long index, uint tmask, uint gmask, const int* pts, int targets, int* status, int* group) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row r;
  sheet(T, &r, chosen, tmask, gmask, pts, targets, group);
  return fight(&r, status);
}
#endif

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    __global const double* pal, __global const double* base

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.pal = pal; T.base = base;

#if !REPORT
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
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0, chosen[6];
  double d = 0.0;
  if (!picks_ok(&T, picks, gid, chosen)) status = 1;
  else {
    Row r;
    sheet(&T, &r, chosen, tmasks[gid], gmasks[gid], pts, targets, &group);
    d = fight(&r, &status);
  }
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
}
#else
#define NSTAT 22
__kernel void cls_report(const int n, const int targets, __global const int* picks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status,
    __global double* out_src, __global int* out_ord, __global int* out_nord, __global double* out_mana,
    __global double* out_act_t, __global int* out_act_id, __global int* out_nact, __global double* out_stats)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = points[(long)gid * NP + j];
  int status = 0, group = 0, chosen[6];
  double d = 0.0;
  St keep;
  keep.nord = 0; keep.nact = 0; keep.mana = 0.0;
  Row r;
  if (!picks_ok(&T, picks, gid, chosen)) status = 1;
  else {
    sheet(&T, &r, chosen, tmasks[gid], gmasks[gid], pts, targets, &group);
    d = fight(&r, &status, &keep);
  }
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
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
    o[0] = r.str; o[1] = r.agi; o[2] = r.intel; o[3] = r.damage; o[4] = r.potency; o[5] = r.mastery; o[6] = r.crit;
    o[7] = r.rating; o[8] = r.haste; o[9] = r.aspd; o[10] = r.luck; o[11] = r.magic_add; o[12] = r.phys_add;
    o[13] = r.hp; o[14] = r.armor; o[15] = r.mana_max; o[16] = r.mana_regen; o[17] = (r.mask & S_GALA) ? 1.0 : 0.0;
    o[18] = r.cd_temp; o[19] = r.flat_cdr; o[20] = r.armor_pen; o[21] = r.spell_crit ? 1.0 : 0.0;
  }
}
#endif
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "tlum": 4, "I0JA": 5, "I096": 6, "I03C": 7, "I00L": 8,
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I0TK": 14, "I0TL": 15, "I0TI": 16, "I0TH": 17,
    "I0QN": 18,
}
TALENT_BITS = {
    "I0QJ": 0, "I0LV": 1, "I0LU": 2, "I0JF": 3, "I0QH": 4, "I0B0": 5, "I0TG": 6, "I0QI": 7, "I0LT": 8,
    "I0LW": 9, "I0QK": 10, "I0QL": 11, "I0TE": 12, "I0TF": 13,
    # dragon_sentinel.IGNORED_TALENTS: no effect on the fight
    "I0JE": 20, "I0MF": 21, "I0HQ": 22, "I0MQ": 23, "I0MD": 24, "I0MC": 25,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN", "I0OH"}
SPECS = {"ruby": 0, "obsidian": 1, "emerald": 2}

# Level-15 Dragon Sentinel (map 2.5.2c), moved from the removed sunken_sim.dragon_sentinel model
LEVEL = 15
WHITE_STR = int(27 + (LEVEL - 1) * 2.7)  # O00P ustr/ustp
WHITE_AGI = int(9 + (LEVEL - 1) * 0.9)  # uagi/uagp
WHITE_INT = int(14 + (LEVEL - 1) * 1.4)  # uint/uinp
BASE_STR = WHITE_STR + 4  # A0F6 L1 Istr
BASE_AGI = WHITE_AGI
BASE_INT = WHITE_INT + 4  # A0F6 L1 Iint
BASE_HP = 300.0
WHITE_BASE = 14.0  # DCS BaseDamage 13 + 1
SWING = 2.00  # O00P ua1c
HERO_CLASS = "DragonSentinel"
TALENT_NAMES = {
    "I0JE": "Ysera's Gift", "I0MF": "Pacify", "I0QJ": "Worldbreaker", "I0LV": "Dragonborn", "I0LU": "Earthen Crust",
    "I0JF": "Draconic Scales", "I0HQ": "Backfire", "I0QH": "Gift of Life", "I0B0": "Melting Flames",
    "I0TG": "Heated Shield", "I0QI": "Engulfing Flames", "I0LT": "Alexstrasza's Gift", "I0LW": "Burning Heart",
    "I0QK": "Waking Dragon", "I0QL": "Explosive Impact", "I0TE": "Legacy of the Aspects", "I0TF": "Blazing Strikes",
    "I0MQ": "Lifeblossom",
}
IGNORED_TALENTS = frozenset({"I0JE", "I0MF", "I0HQ", "I0MQ", "I0MD", "I0MC"})
IGNORED_REASONS = {
    "I0JE": "лечение самого раненого союзного героя (только если его HP < 100%, сам DS исключён)",
    "I0MF": "контроль (CC), урона нет",
    "I0HQ": "урон только когда враг под Dragonfire атакует — пустышка не атакует",
    "I0MQ": "лечение / раздача Lifebinder союзникам, урона нет",
    "I0MD": "страница талантов (UI)",
    "I0MC": "страница талантов (UI)",
}
ATTACK_DAMAGE_RE = re.compile(r"(?m)^\+(\d+) Attack Damage\b")


def dragon_sentinel_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the strength primary fold and the Dragon Sentinel per-piece columns."""
    import re

    from sunken_sim import expiry_buff, pressure, shadow
    from sunken_sim.stacking import stack_fields

    if (shadow.CAST_POINT, shadow.CAST_BACKSWING, pressure.STR_HP, expiry_buff.BUFF_SLOTS) != (0.15, 0.30, 15.0, 8):
        raise ValueError("kernel constants assume cast 0.15 + 0.30, 15 health per strength and 8 buff slots")
    AP.check()
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(BASE_INT), float(BASE_STR), float(BASE_AGI), float(BASE_HP)],
                           "Dragon Sentinel")
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
        attack_damage = float(sum(int(v) for v in ATTACK_DAMAGE_RE.findall(item.tip)))
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
            cv(code, "damage", attack_damage, True),
            cv(code, "damage", attack_damage, False),
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class DragonSentinelCL(C.ExactCL):
    hero = "dragon_sentinel"
    PYTHON = False  # sunken_sim.dragon_sentinel fight model removed 2026-11-27: fixtures + report mode
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ()  # no timeline cache: every ESC trial is its own fight
    SOURCE_NAMES = ("Автоатака", "Burnout", "Burnout (пассив)", "Burnout (крит, Blazing Strikes)", "Dragon Strike",
                    "Dragon Strike (Drake Sword)", "Blazing Shield", "Blazing Shield (Explosive Impact)",
                    "Engulfing Flames", "Cleansing Fire", "Cleansing Fire (от лечения)", "Burning Heart",
                    "Ruby Dragon Form (огненные снаряды)", "Всплеск огня", "Sulfuras", "Sulfuras (удар)")
    ACTION_NAMES = ("Dragon Form", "Lifebinder", "Burnout", "Cleansing Fire", "Dragon Strike", "Blazing Shield")
    STAT_KEYS = ("str", "agi", "int", "damage", "potency", "mastery", "crit", "rating", "haste", "attack_speed", "luck",
                 "magic_add", "phys_add", "hp", "armor", "mana_max", "mana_regen", "galactic", "cd_temp", "flat_cdr",
                 "armor_pen", "spell_crit")
    BOOL_STATS = ()  # dragon_sentinel.stats_of keeps 1.0 / 0.0
    NSRC, MAXA = 16, 160
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "pal", "base")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32}

    @staticmethod
    def module():
        raise RuntimeError("dragon_sentinel: the Python fight model was removed (2026-11-27)")

    def tables(self, space, items, sources):
        return dragon_sentinel_tables(space, items, sources)

    def timeline_key(self, build):
        # dragon_sentinel.simulate had no fight cache: every trial is scored on its own points
        from dataclasses import fields

        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points"))


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
