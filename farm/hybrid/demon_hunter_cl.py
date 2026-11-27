"""Exact float64 OpenCL kernel for Demon Hunter fights (Havoc, Vengeance, Devourer).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.demon_hunter.stats_of`` (agility primary, Incubus, luck and health
from tooltips) and run ``demon_hunter.simulate`` with its Ledger sums in
insertion order. Fallout on each target is a distribution of expiry times
(``expiry_buff._Buff``), mirrored entry by entry; every chance is a weight.

``demon_hunter.simulate`` has no timeline cache, so every row is its own fight.
Rows the kernel cannot score (more than 5 targets, negative armour, queue or
Chaos-timer overflow) return a non-zero status and are re-scored by the Python
oracle on the host. Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 13

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 havoc, 1 vengeance, 2 devourer */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_HAVOC (SPEC == 0)
#define SP_VENG (SPEC == 1)
#define SP_DEVOUR (SPEC == 2)
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
#define NPAL 13
#define NSRC 11
#define MAXT 8
#define MAXA 160
#define BS 8
#define MAXQ 64
#define MAXC 16
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
#define S_TORM (1UL<<14)
#define S_WARG (1UL<<15)
#define S_HELM (1UL<<16)
#define S_NAARU (1UL<<17)
#define S_SILM (1UL<<18)

#define T_ENDUR (1u<<0)
#define T_INCUB (1u<<1)
#define T_BLADE (1u<<2)
#define T_COSMIC (1u<<3)
#define T_CONSUME (1u<<4)
#define T_FALLOUT (1u<<5)
#define T_CLEAVE (1u<<6)
#define T_FELFIRE (1u<<7)
#define T_NOVA (1u<<8)
#define T_SOULIMM (1u<<9)
#define T_GLAIVE (1u<<10)
#define T_SING (1u<<11)
#define T_VOID (1u<<12)
#define T_CHAINS (1u<<13)
#define T_POWER (1u<<14)

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

/* Ledger order: the 9 seeded sources, then first writes */
#define N_AUTO 0
#define N_IMMO 1
#define N_HUNT 2
#define N_F 3
#define N_BLADE 4
#define N_GLAIVE 5
#define N_NOVA 6
#define N_SING 7
#define N_SPLASH 8
#define N_SULF 9
#define N_ECHO 10

/* nxt[] keys, in demon_hunter.simulate order */
#define K_META 0
#define K_F 1
#define K_HUNT 2
#define K_IMMO 3
#define K_INNER 4

#define Q_BEAM 0
#define Q_STAR 1

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
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
  double fo_e[MAXT][BS + 1], fo_m[MAXT][BS + 1]; int fo_n[MAXT];
  double fo_t[MAXT], fo_lo[MAXT];
  double q_w[MAXQ], q_v[MAXQ]; uint q_s[MAXQ]; int q_k[MAXQ]; int qn; uint seq;
  double cr_w[MAXC], cr_c[MAXC]; int ncr;
  double nxt[5];
  int sing_done[MAXT];
  double mana, mana_time, fury, thrill_until, main_until, stack_until, immo_next, blade_until, blade_stacks;
  double p_power, p_havoc, p_double, p_glaive_crit, p_glaive_beam, q_chaos, immo_interval, immo_dur, singularity;
  int meta, drain, armed, status, targets;
  AP ap;
#if REPORT
  double act_t[MAXA]; int act_id[MAXA]; int nact;
#endif
} St;

/* actions (demon_hunter.simulate names): host ACTION_NAMES */
#define A_META 0
#define A_BEAM 1
#define A_STAR 2
#define A_SPIKES 3
#define A_HUNT 4
#define A_IMMO 5
#define A_INNER 6
#define A_MEND 7
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

/* ---- expiry_buff._Buff (Fallout per target) ---- */
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


#define FO_MASS(s, t, now) bmass((s)->fo_e[t], (s)->fo_m[t], (s)->fo_n[t], (s)->fo_t[t], (s)->fo_lo[t], now)
#define FO_ARGS(s, t) (s)->fo_e[t], (s)->fo_m[t], &(s)->fo_n[t], &(s)->fo_t[t], &(s)->fo_lo[t]

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
  gain_mana(r, s, cost * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * r->mastery);
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

double cooldown_of(double base, const Row* r) {
  double v = (base * r->cd_temp - r->flat_cdr - 0.0) / (1.0 + r->haste);
  return (v > 0.5) ? v : 0.5;
}

/* GenerateFury with chance w: Demonic Power doubles it at 25% x Luck */
void gen(St* s, double amount, double w) {
  if (w <= 0.0) return;
  if (s->p_power > 0.0) {
    double v = s->fury + amount * w * s->p_power;
    s->fury = (v < 100.0) ? v : 100.0;
  }
  double v = s->fury + amount * w;
  s->fury = (v < 100.0) ? v : 100.0;
}

double potency_bonus(const Row* r, const St* s) {
  double value = 0.0;
  if (SP_HAVOC) {
    value += 2.0;
    if (s->meta) value += 4.0 + 0.15 * r->agi;
  }
  return value;
}

double increase(const Row* r, const St* s, int attack) {
  double value = 1.0;
  if (TM(r, T_COSMIC)) value += 0.003 * s->fury;
  if (s->meta && (r->mask & S_TORM)) value += 0.20;
  if (attack && TM(r, T_CHAINS)) value += 0.10;
  return value;
}

double crit_chance(const Row* r, const St* s) {
  double chance = r->crit;
  if (TM(r, T_FALLOUT) && (!SP_VENG || s->meta)) chance += 8.0;
  return chance;
}

double typed(const Row* r, const St* s, int magical, double now) {
  double bonus = 1.0 + (magical ? r->magic_add : r->phys_add);
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(now);
  if (magical && (r->mask & S_TLUM)) bonus += 0.05 + 0.005 * r->mastery;
  if (r->glass) bonus *= 1.15;
  if (magical && SP_DEVOUR && s->meta) bonus *= 1.25 + 0.01 * (double)s->drain;
  return bonus;
}

double taken(const Row* r, St* s, int t, double now) {
  double armor = 15.0 - r->armor_pen;
  if (!TM(r, T_FALLOUT)) return armor_mult(s, armor);
  double on = FO_MASS(s, t, now);
  return on * armor_mult(s, armor - 3.0) + (1.0 - on) * armor_mult(s, armor);
}

/* kind: 0 plain, 1 attack, 2 magic. Returns the crit share. */
double deal(const Row* r, St* s, int name, double raw, int t, double now, int kind, int chaos, double count, double w) {
  int attack = kind == 1;
  double scale = (attack ? r->attack_potency : 1.0) + (SP_HAVOC ? 0.35 : 0.0);
  raw = raw + potency_bonus(r, s) * scale;
  double factor = increase(r, s, attack);
  double share = 0.0;
  if (attack) {
    factor *= typed(r, s, 0, now) * (chaos ? 1.25 : 1.0);
    double chance = crit_chance(r, s);
    double c1 = (chance < 100.0) ? chance : 100.0;
    share = ((c1 > 0.0) ? c1 : 0.0) / 100.0;
    factor *= crit_factor(chance, 2.0 + r->rating);
  } else if (kind == 2) {
    factor *= typed(r, s, 1, now);
    if (r->spell_crit) {
      double chance = crit_chance(r, s);
      double c1 = (chance < 100.0) ? chance : 100.0;
      share = ((c1 > 0.0) ? c1 : 0.0) / 100.0;
      factor *= crit_factor(chance, r->spell_mult + r->rating);
    }
  }
  factor *= taken(r, s, t, now);
  factor *= w;
  double weight_raw = raw * factor, coeff = scale * factor;
  double execute = exec_factor(r, now);
  double amount = (weight_raw + r->potency * coeff) * execute;
  add_src(s, name, amount * count);
  note_damage_mana(r, s, w);
  if (s->p_havoc > 0.0) gen(s, 1.0, w * s->p_havoc);
  if (share > 0.0 && TM(r, T_FALLOUT)) {
    double p = share * w;
    bmaybe(FO_ARGS(s, t), now, 4.0, p, p);
  }
  return share;
}

double dcs(const Row* r) { return 32.0 + 0.75 * r->agi + r->damage; }

void immo_hit(const Row* r, St* s, int t, double now, double w) {
  double raw = 5.0 + 10.0 * RANK + 0.30 * r->agi;
  deal(r, s, N_IMMO, raw, t, now, 2, 0, 1.0, w);
  if (s->p_double > 0.0) deal(r, s, N_IMMO, raw, t, now, 2, 0, 1.0, w * s->p_double);
  if (TM(r, T_SOULIMM)) s->nxt[K_F] -= 0.10 * w;
}

/* on_attack(..., code=True): no Throw Glaive from crits */
void on_attack_code(const Row* r, St* s, int t, double now, double share, double w) {
  immo_hit(r, s, t, now, w);
  if (TM(r, T_BLADE)) {
    double hits;
    if (s->blade_until > now) {
      s->blade_stacks += w;
      hits = s->blade_stacks;
    } else {
      s->blade_stacks = w;
      s->blade_until = now + 4.0;
      hits = 1.0;
    }
    deal(r, s, N_BLADE, 10.0 + 0.10 * dcs(r), t, now, 0, 0, hits, w);
  }
  if (TM(r, T_CLEAVE)) gen(s, 1.0 + 2.0 * share, w);
}

void glaive(const Row* r, St* s, int t, double now, double w) {
  if (w <= 0.0) return;
  double raw = 15.0 + 0.40 * dcs(r);
  double share = deal(r, s, N_GLAIVE, raw, t, now, 1, 1, 1.0, w);
  on_attack_code(r, s, t, now, share, w);
  int other = (t + 1) % s->targets;
  share = deal(r, s, N_GLAIVE, 0.5 * raw, other, now, 1, 1, 1.0, w);
  on_attack_code(r, s, other, now, share, w);
}

/* on_attack(..., code=False) */
void on_attack(const Row* r, St* s, int t, double now, double share, double w) {
  on_attack_code(r, s, t, now, share, w);
  if (s->p_glaive_crit > 0.0) glaive(r, s, t, now, w * share * s->p_glaive_crit);
}

void apply_immolation(St* s, double now) {
  if (s->main_until <= now && s->stack_until <= now) s->immo_next = now + s->immo_interval;
  if (s->main_until > now) s->stack_until = now + s->immo_dur;
  else s->main_until = now + s->immo_dur;
}

void class_cast(const Row* r, St* s, double now, int hunt) {
  if (TM(r, T_NOVA))
    for (int t = 0; t < s->targets; t++) deal(r, s, N_NOVA, 25.0 + 0.50 * r->agi, t, now, 2, 0, 1.0, 1.0);
  if (SP_DEVOUR && !hunt) gen(s, 5.0, 1.0);
}

double cast(const Row* r, St* s, double now, double extra) {
  if (r->mask & S_SULF) s->armed = 1;
  return now + (CAST_POINT + CAST_BACKSWING) + extra + r->cast_lock;
}

double speed_stat(const Row* r, const St* s, double now) {
  double speed = r->aspd;
  if (now < s->thrill_until) speed += 0.25;
  speed += ap_bonus(&s->ap, now);
  return ap_speed(speed);
}

double attack_interval(const Row* r, const St* s, double now) {
  double swing = 1.70 * ((r->mask & S_GALA) ? 1.20 : 1.0);
  if (TM(r, T_VOID) || (r->mask & S_NAARU)) swing *= 0.92;
  return swing / (1.0 + speed_stat(r, s, now));
}

void fury_tick(const Row* r, St* s, double now) {
  if (s->meta) {
    if (s->fury > 0.0) {
      s->fury -= (double)(5 + s->drain);
      if (s->fury <= 0.0) { s->fury = 0.0; s->drain = 0; s->meta = 0; act(s, now, A_MEND); }
      else s->drain += 1;
      if ((r->mask & S_HELM) && SP_DEVOUR) s->nxt[K_F] -= 1.0;
    }
  } else if (s->fury < 25.0) {
    gen(s, 1.0, 1.0);
  }
}

void push(St* s, double when, int kind, double value) {
  if (s->qn >= MAXQ) { if (!s->status) s->status = 5; return; }
  s->seq += 1u;
  s->q_w[s->qn] = when; s->q_s[s->qn] = s->seq; s->q_k[s->qn] = kind; s->q_v[s->qn] = value; s->qn++;
}

int peek_idx(const St* s) {
  int b = -1;
  for (int i = 0; i < s->qn; i++)
    if (b < 0 || s->q_w[i] < s->q_w[b] || (s->q_w[i] == s->q_w[b] && s->q_s[i] < s->q_s[b])) b = i;
  return b;
}

void beam_tick(const Row* r, St* s, double now, double per_hit) {
  int hits = (s->targets == 1) ? 2 : s->targets;
  int c = 0;
  for (int i = 0; i < s->ncr; i++)
    if (now - s->cr_w[i] < 0.20 - 1e-9) { s->cr_w[c] = s->cr_w[i]; s->cr_c[c] = s->cr_c[i]; c++; }
  s->ncr = c;
  double blocked = 0.0;
  for (int i = 0; i < s->ncr; i++) blocked += s->cr_c[i];
  double v = 1.0 - blocked;
  double clear = (v > 0.0) ? v : 0.0;
  double tick_chaos = 0.0;
  for (int k = 0; k < hits; k++) {
    int t = (s->targets == 1) ? 0 : k;
    double p = clear * s->q_chaos;
    clear -= p;
    tick_chaos += p;
    if (p > 0.0) {
      double share = deal(r, s, N_F, per_hit, t, now, 1, 1, 1.0, p);
      on_attack_code(r, s, t, now, share, p);
      if (s->p_glaive_beam > 0.0) glaive(r, s, t, now, p * s->p_glaive_beam);
    }
    deal(r, s, N_F, per_hit, t, now, 0, 0, 1.0, 1.0 - p);
  }
  if (tick_chaos > 0.0) {
    if (s->ncr >= MAXC) { if (!s->status) s->status = 6; return; }
    s->cr_w[s->ncr] = now; s->cr_c[s->ncr] = tick_chaos; s->ncr++;
  }
}

void star_land(const Row* r, St* s, double now) {
  double raw = (125.0 + 2.0 * r->agi) * (1.0 + (0.02 / 10.0) * (r->agi + r->intel));
  for (int t = 0; t < s->targets; t++) {
    deal(r, s, N_F, raw, t, now, 2, 0, 1.0, 1.0);
    if (TM(r, T_SING) && !s->sing_done[t]) {
      s->sing_done[t] = 1;
      deal(r, s, N_SING, s->singularity, t, now, 2, 0, 1.0, 1.0);
    }
  }
}

/* demon_hunter.simulate(build, targets, spec) */
#if REPORT
double fight(const Row* r, int* status_out, St* keep) {
#else
double fight(const Row* r, int* status_out) {
#endif
  St s;
#if REPORT
  s.nact = 0;
#endif
  if (r->targets > MAXT || r->targets < 1) { *status_out = 3; return 0.0; }
  s.targets = r->targets; s.status = 0; s.armed = 0;
  s.nord = 0; s.seen = 0u;
  for (int i = 0; i < 9; i++) { s.seen |= 1u << i; s.ord[s.nord++] = i; s.src[i] = 0.0; }
  double luck_mult = 1.0 + r->luck;
  s.p_power = TM(r, T_POWER) ? chance01(0.25 * luck_mult) : 0.0;
  s.p_havoc = SP_HAVOC ? chance01(0.08 * luck_mult) : 0.0;
  s.p_double = SP_HAVOC ? chance01((5.0 + 0.5 * r->mastery) / 100.0) : 0.0;
  s.p_glaive_crit = TM(r, T_GLAIVE) ? chance01(0.5 * luck_mult) : 0.0;
  s.p_glaive_beam = TM(r, T_GLAIVE) ? chance01(0.20 * luck_mult) : 0.0;
  s.q_chaos = chance01(0.25 * luck_mult);
  s.singularity = 40.0 + 2.0 * r->agi + 0.10 * r->mana_max;
  s.immo_dur = 6.0 + (TM(r, T_ENDUR) ? 3.0 : 0.0);
  double immo_rate = 1.0 + (TM(r, T_FELFIRE) ? (0.15 + 0.12 * r->agi / 100.0) : 0.0);
  s.immo_interval = (1.40 - 0.10 * RANK) / immo_rate;
  s.mana = r->mana_max; s.mana_time = 0.0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  s.meta = 0; s.fury = 0.0; s.drain = 0;
  s.thrill_until = -1.0; s.main_until = -1.0; s.stack_until = -1.0; s.immo_next = FAR;
  s.blade_until = -1.0; s.blade_stacks = 0.0;
  s.ncr = 0; s.qn = 0; s.seq = 0u;
  for (int t = 0; t < MAXT; t++) { s.fo_n[t] = 0; s.fo_t[t] = 0.0; s.fo_lo[t] = INFINITY; s.sing_done[t] = 0; }
  int nova = TM(r, T_NOVA) != 0;
  for (int k = 0; k < 5; k++) s.nxt[k] = 0.0;
  if (SP_VENG && !nova) s.nxt[K_F] = FAR;
  if (!nova) s.nxt[K_INNER] = FAR;
  double next_attack = 0.0, next_fury = 1.0, busy = 0.0;
  int guard = 0;
  while (1) {
    guard += 1;
    if (guard > 400000) break;
    if (s.status) break;
    double attack_at = (busy > next_attack) ? busy : next_attack;
    double cast_at = FAR;
    int choice = -1;
    for (int k = 0; k < 5; k++) {
      if (k == K_META && s.meta) continue;
      double ready = (busy > s.nxt[k]) ? busy : s.nxt[k];
      if (ready < cast_at - 1e-9) { cast_at = ready; choice = k; }
    }
    int qi = peek_idx(&s);
    double event_at = (qi >= 0) ? s.q_w[qi] : FAR;
    double moment = attack_at;
    if (cast_at < moment) moment = cast_at;
    if (event_at < moment) moment = event_at;
    if (next_fury < moment) moment = next_fury;
    if (s.immo_next < moment) moment = s.immo_next;
    if (moment >= FIGHT) break;
    if (moment == event_at) {
      int kind = s.q_k[qi]; double value = s.q_v[qi];
      s.qn--;
      s.q_w[qi] = s.q_w[s.qn]; s.q_s[qi] = s.q_s[s.qn]; s.q_k[qi] = s.q_k[s.qn]; s.q_v[qi] = s.q_v[s.qn];
      if (kind == Q_BEAM) beam_tick(r, &s, moment, value);
      else star_land(r, &s, moment);
      continue;
    }
    if (moment == next_fury) {
      fury_tick(r, &s, moment);
      next_fury += 1.0;
      continue;
    }
    if (moment == s.immo_next) {
      int count = (s.main_until > moment) + (s.stack_until > moment);
      for (int c = 0; c < count; c++)
        for (int t = 0; t < s.targets; t++) immo_hit(r, &s, t, moment, 1.0);
      s.immo_next = (s.main_until > moment || s.stack_until > moment) ? moment + s.immo_interval : FAR;
      continue;
    }
    if (choice >= 0 && cast_at <= attack_at && moment == cast_at) {
      double hit_at = moment + CAST_POINT;
      if (choice == K_META) {
        act(&s, moment, A_META);
        busy = cast(r, &s, moment, 0.0);
        s.meta = 1;
        class_cast(r, &s, hit_at, 0);
        s.nxt[K_META] = moment + cooldown_of(10.0, r);
      } else if (choice == K_F && SP_HAVOC) {
        if (!pay(r, &s, 25.0, moment)) { s.nxt[K_F] = moment + 0.25; continue; }
        act(&s, moment, A_BEAM);
        busy = cast(r, &s, moment, 2.50);
        class_cast(r, &s, hit_at, 0);
        double per_hit = 7.0 + 0.15 * dcs(r);
        double left = 2.50, tick = 0.0, when = hit_at;
        while (left >= 0.03 - 1e-9) {
          if (tick < 0.03) {
            push(&s, when, Q_BEAM, per_hit);
            tick = 0.50 / (1.0 + 0.50 * speed_stat(r, &s, when));
          } else {
            tick -= 0.03;
          }
          left -= 0.03;
          when += 0.03;
        }
        s.nxt[K_F] = moment + cooldown_of(10.0, r);
      } else if (choice == K_F && SP_DEVOUR) {
        if (!pay(r, &s, 25.0, moment)) { s.nxt[K_F] = moment + 0.25; continue; }
        act(&s, moment, A_STAR);
        busy = cast(r, &s, moment, 0.0);
        if (TM(r, T_CONSUME)) for (int i = 0; i < 3; i++) gen(&s, 5.0, 1.0);
        class_cast(r, &s, hit_at, 0);
        push(&s, hit_at + 0.75, Q_STAR, 0.0);
        s.nxt[K_F] = moment + cooldown_of(10.0, r);
      } else if (choice == K_F) {
        if (!pay(r, &s, 25.0, moment)) { s.nxt[K_F] = moment + 0.25; continue; }
        act(&s, moment, A_SPIKES);
        busy = cast(r, &s, moment, 0.0);
        class_cast(r, &s, hit_at, 0);
        s.nxt[K_F] = moment + cooldown_of(10.0, r);
      } else if (choice == K_HUNT) {
        if (!pay(r, &s, 15.0, moment)) { s.nxt[K_HUNT] = moment + 0.25; continue; }
        act(&s, moment, A_HUNT);
        busy = cast(r, &s, moment, 0.0);
        class_cast(r, &s, hit_at, 1);
        s.thrill_until = hit_at + 6.0;
        if (r->mask & S_WARG) apply_immolation(&s, hit_at);
        double raw = 100.0 + 1.80 * r->agi;
        if (SP_DEVOUR) raw *= 1.08 + 0.005 * r->mastery;
        deal(r, &s, N_HUNT, raw, 0, hit_at, 2, 0, 1.0, 1.0);
        if (TM(r, T_SING)) deal(r, &s, N_SING, 0.50 * s.singularity, 0, hit_at, 2, 0, 1.0, 1.0);
        if (SP_DEVOUR) gen(&s, 5.0, 1.0);
        s.nxt[K_HUNT] = moment + cooldown_of(10.0, r);
      } else if (choice == K_IMMO) {
        if (!pay(r, &s, 20.0, moment)) { s.nxt[K_IMMO] = moment + 0.25; continue; }
        act(&s, moment, A_IMMO);
        busy = cast(r, &s, moment, 0.0);
        class_cast(r, &s, hit_at, 0);
        apply_immolation(&s, hit_at);
        s.nxt[K_IMMO] = moment + cooldown_of(10.0, r);
      } else {
        if (!pay(r, &s, 20.0, moment)) { s.nxt[K_INNER] = moment + 0.25; continue; }
        act(&s, moment, A_INNER);
        busy = cast(r, &s, moment, 0.0);
        class_cast(r, &s, hit_at, 0);
        s.nxt[K_INNER] = moment + cooldown_of(12.0, r);
      }
      next_attack = (busy > next_attack) ? busy : next_attack;
      continue;
    }
    moment = attack_at;
    recover(r, &s, moment);
    double power = dcs(r);
    double share = deal(r, &s, N_AUTO, power, 0, moment, 1, s.meta, r->auto_pct, 1.0);
    on_attack(r, &s, 0, moment, share, 1.0);
    gain_mana(r, &s, attack_mana_gain(r));
    if (r->mask & S_ORB) {
      double splash = (20.0 + 0.35 * r->agi) * (double)s.targets * taken(r, &s, 1 % s.targets, moment) * exec_factor(r, moment);
      add_src(&s, N_SPLASH, splash);
      note_damage_mana(r, &s, (double)s.targets);
    }
    if (r->mask & S_SULF) {
      double execute = exec_factor(r, moment);
      double armor = armor_mult(&s, 15.0 - r->armor_pen);
      if (s.armed) {
        s.armed = 0;
        double splash = r->agi * (1.0 + r->magic_add) * (r->glass ? 1.15 : 1.0) * armor * execute * (double)s.targets;
        if (r->spell_crit) splash *= crit_factor(crit_chance(r, &s), r->spell_mult + r->rating);
        add_src(&s, N_SULF, splash);
        note_damage_mana(r, &s, (double)s.targets);
      }
      double echo = power * armor * execute * (0.10 * (1.0 + r->luck));
      add_src(&s, N_ECHO, echo);
    }
    ap_attack(&s.ap, moment, crit_chance(r, &s));
    next_attack = moment + attack_interval(r, &s, moment);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
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

/* demon_hunter.stats_of(build) */
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
  if (GM(r, G_FORT)) agility += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  if (GM(r, G_UNSL) && !(mask & S_UNSI)) { magic_add += 0.18; phys_add += 0.18; }
  if (GM(r, G_FORTUNE)) luck += 0.15;
  if (TM(r, T_INCUB)) magic_add += 0.10 + (0.25 * intel) / 100.0;
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
#define NSTAT 21
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
    o[0] = r.agi; o[1] = r.str; o[2] = r.intel; o[3] = r.damage; o[4] = r.potency; o[5] = r.mastery; o[6] = r.crit;
    o[7] = r.rating; o[8] = r.haste; o[9] = r.aspd; o[10] = r.luck; o[11] = r.magic_add; o[12] = r.phys_add;
    o[13] = r.hp; o[14] = r.mana_max; o[15] = r.mana_regen; o[16] = (r.mask & S_GALA) ? 1.0 : 0.0;
    o[17] = r.cd_temp; o[18] = r.flat_cdr; o[19] = r.armor_pen; o[20] = r.spell_crit ? 1.0 : 0.0;
  }
}
#endif
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "tlum": 4, "I0JA": 5, "I096": 6, "I03C": 7, "I00L": 8,
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I0V4": 14, "I0V5": 15, "I0V6": 16, "I0V7": 17,
    "I0QN": 18,
}
TALENT_BITS = {
    "I0DA": 0, "I0PC": 1, "I07E": 2, "I0FL": 3, "I04P": 4, "I04X": 5, "I07H": 6, "I0FK": 7, "I05K": 8,
    "I0V2": 9, "I0PB": 10, "I08D": 11, "I0V1": 12, "I0C5": 13, "I0V3": 14,
    # demon_hunter.IGNORED_TALENTS: no effect on the fight
    "I05M": 20, "I0PA": 21, "I05S": 22, "I0MD": 23, "I0MC": 24,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"havoc": 0, "vengeance": 1, "devourer": 2}

# Level-15 Demon Hunter (map 2.5.2c), moved from the removed sunken_sim.demon_hunter model
LEVEL = 15
BASE_STR = int(12 + (LEVEL - 1) * 1.2)
BASE_AGI = int(24 + (LEVEL - 1) * 2.4)
BASE_INT = int(14 + (LEVEL - 1) * 1.4)
BASE_HP = 250.0
WHITE_BASE = 32.0  # ua1b 31 + 1d1
SWING = 1.70
HERO_CLASS = "DemonHunter"
TALENT_NAMES = {
    "I0DA": "Enduring Torment", "I0PC": "Incubus", "I07E": "Chaos Blade", "I0FL": "Cosmic Force",
    "I05M": "Demonic Wards", "I04P": "Consume", "I04X": "Fallout", "I0PA": "Darkness", "I05S": "Bloodlet",
    "I07H": "Soul Cleave", "I0FK": "Felfire", "I05K": "Chaos Nova", "I0V2": "Soul Immolation",
    "I0PB": "Throw Glaive", "I08D": "Singularity", "I0V1": "Void Glaive", "I0C5": "Chains of Anguish",
    "I0V3": "Demonic Power",
}
# Demonic Wards / Darkness / Bloodlet are defensive or healing. Pages are UI.
IGNORED_TALENTS = frozenset({"I05M", "I0PA", "I05S", "I0MD", "I0MC"})
F_NAMES = {"havoc": "Eye Beam", "vengeance": "Demon Spikes", "devourer": "Collapsing Star"}


def demon_hunter_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the agility primary fold and the Demon Hunter per-piece columns."""
    import re

    from sunken_sim import pressure, shadow
    from sunken_sim.stacking import stack_fields
    from sunken_sim import expiry_buff

    if (shadow.CAST_POINT, shadow.CAST_BACKSWING, pressure.STR_HP, expiry_buff.BUFF_SLOTS) != (0.15, 0.30, 15.0, 8):
        raise ValueError("kernel constants assume cast 0.15 + 0.30, 15 health per strength and 8 buff slots")
    AP.check()
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(BASE_INT), float(BASE_STR), float(BASE_AGI), float(BASE_HP)], "Demon Hunter")
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
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class DemonHunterCL(C.ExactCL):
    hero = "demon_hunter"
    PYTHON = False  # sunken_sim.demon_hunter fight model removed 2026-11-27: fixtures + report mode
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ()  # no timeline cache: every ESC trial is its own fight
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "pal", "base")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32}
    ACTION_NAMES = ("Metamorphosis", "Eye Beam", "Collapsing Star", "Demon Spikes", "The Hunt", "Immolation Aura",
                    "Inner Demon", "Meta ends")
    STAT_KEYS = ("agi", "str", "int", "damage", "potency", "mastery", "crit", "rating", "haste", "attack_speed", "luck",
                 "magic_add", "phys_add", "hp", "mana_max", "mana_regen", "galactic", "cd_temp", "flat_cdr", "armor_pen",
                 "spell_crit")
    BOOL_STATS = ()  # demon_hunter.stats_of keeps 1.0 / 0.0
    NSRC, MAXA = 11, 160

    @property
    def SOURCE_NAMES(self):
        return ("Автоатака", "Immolation Aura", "The Hunt", F_NAMES[self.spec], "Chaos Blade", "Throw Glaive",
                "Chaos Nova", "Singularity", "Всплеск огня", "Sulfuras", "Sulfuras (удар)")

    @staticmethod
    def module():
        raise RuntimeError("demon_hunter: the Python fight model was removed (2026-11-27)")

    def tables(self, space, items, sources):
        return demon_hunter_tables(space, items, sources)

    def timeline_key(self, build):
        # demon_hunter.simulate has no fight cache: every trial is scored on its own points
        from dataclasses import fields

        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points"))


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
