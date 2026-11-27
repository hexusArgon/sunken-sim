"""Exact float64 OpenCL kernel for Feral Druid fights (Primal, Guardian, Savage).

The Feral Druid (O00R, agility, ``sunken_sim.feral_druid``) only; the caster Druid is farm.hybrid.druid_cl.

One work-item scores one fight: unrank the six items, fold the sheet like ``feral_druid.sheet``
(``shadow.character`` with the feral bases, agility primary, white 32, no baked buffs, then the feral
damage / mana / swing / health / armour), run the event loop of ``feral_druid._simulate_feral`` for every
Diamond Ring binding (best of them) and score every event as ``feral_druid.score_events`` the moment it is
emitted, with sources in insertion order. Battle Frenzy / Silent Messenger: farm.hybrid.attack_procs_cl.

The fight does not depend on Potency (``score_events`` applies it per event), so a replayed timeline
cache scores exactly like a fresh fight: tlpoints are not needed.
Rows the kernel cannot score (negative armour, queue overflow, more than MAXT targets) return a non-zero
status and are re-scored by the Python oracle. Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import re

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 2

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 primal, 1 guardian, 2 savage */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_PRIMAL (SPEC == 0)
#define SP_BEAR (SPEC == 1)
#define SP_CAT (SPEC == 2)
/* REPORT 1: the report kernel also keeps the final fight state (sources in Ledger order, casts, mana) */
#ifndef REPORT
#define REPORT 0
#endif
#define MAXA 160

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define CAST_TIME (CAST_POINT + CAST_BACKSWING)
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 2
#define MAXT 8
#define MAXQ 32
#define NSRC 8

#define S_RING (1UL<<0)
#define S_SULF (1UL<<1)
#define S_ORB  (1UL<<2)
#define S_GALA (1UL<<3)
#define S_SULG (1UL<<4)
#define S_TLUM (1UL<<5)
#define S_GLAS (1UL<<6)
#define S_FLSK (1UL<<7)
#define S_I03C (1UL<<8)
#define S_I00L (1UL<<9)
#define S_I00Y (1UL<<10)
#define S_HARN (1UL<<11)
#define S_ATIE (1UL<<12)
#define S_CORE (1UL<<13)
#define S_ASHA (1UL<<14)
#define S_SHPAD (1UL<<15)
#define S_PACK (1UL<<16)
#define S_SILM (1UL<<17)
#define S_INSA (1UL<<18)
#define S_CATH (1UL<<19)

#define T_PFURY (1u<<0)
#define T_RAZOR (1u<<1)
#define T_SROAR (1u<<2)
#define T_MAIM (1u<<3)
#define T_FFRENZY (1u<<4)
#define T_WILD (1u<<5)
#define T_GRIZZLY (1u<<6)
#define T_MOMENTUM (1u<<7)
#define T_REND (1u<<8)
#define T_URSOC (1u<<9)
#define T_OPEN (1u<<10)
#define T_SHRED (1u<<11)
#define T_FRESH (1u<<12)
#define T_LUNAR (1u<<13)

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

/* buttons: feral_druid.buttons order */
#define B_SWIPE 0
#define B_BITE 1
#define B_ROAR 2

/* clock kinds */
#define K_CAST 0
#define K_RAKE 1

/* event kinds (feral_druid.KIND_*) */
#define KD_PHYS 0
#define KD_MAG 1
#define KD_EXEC 2

/* sources */
#define N_AUTO 0
#define N_SWIPE 1
#define N_BITE 2
#define N_RAKE 3
#define N_FRENZY 4
#define N_FIRE 5
#define N_SULF 6
#define N_SULF_ECHO 7

typedef struct {
  double intel, str, agi, potency, mastery, ad, mana_max, crit, rating, haste, aspd;
  double spell_mult, flat_cdr, cd_temp, cast_lock;
  double auto_pct, armor_pen, luck, attack_potency;
  double attack_base, mana_regen, cast_refund, cast_refund_flat, cast_refund_mastery;
  double attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double mag_sum, phy_sum, max_hp, armor;
  double ex_thr[MAXE], ex_pct[MAXE];
  int spell_crit, nexec, targets;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
} Sco;

typedef struct {
  double q_w[MAXQ]; uint q_s[MAXQ]; int q_k[MAXQ]; int q_p[MAXQ]; int qn; uint seq;
  double rake[MAXT];
  double ready[3];
  double mana, mana_time, fer, fer_time;
  double berserk_until, roar_until, maim_until, bite_window, swipe_window, next_hit_bonus;
  double fer_max, fer_rate, rake_period, attack_inc, crit_bonus, rating_bonus, taken_plain, taken_maim;
  int rake_clock, armed, status, targets, bound;
  int ferocity_on, lunar, ursoc, momentum, rend, maim, wild, razor, frenzy, shifted, glass;
  AP ap;
#if REPORT
  double act_t[MAXA]; int act_id[MAXA]; int nact;
#endif
} St;

/* actions: feral_druid.BOUND_NAME of the cast button (host ACTION_NAMES, ids = B_*) */
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

double armor_taken(double armor, int* status) {
  if (armor > 0.0) return 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor);
  if (armor < 0.0) return 2.0 - pow(1.0 - 0.04, -armor);  /* shadow.armor_taken */
  return 1.0;
}

double exec_factor(const Row* r, double t) {
  double hp = target_hp(t);
  double f = 1.0;
  for (int i = 0; i < r->nexec; i++)
    if (hp <= r->ex_thr[i]) f *= 1.0 + r->ex_pct[i];
  return f;
}

void add_src(Sco* q, int id, double amount) {
  uint bit = 1u << id;
  if (q->seen & bit) q->src[id] = q->src[id] + amount;
  else { q->seen |= bit; q->ord[q->nord++] = id; q->src[id] = 0.0 + amount; }
}

/* shadow._magical_multiplier(codes, when, mastery) */
double magical(const Row* r, const St* s, double t) {
  double ta = r->mag_sum;
  if (r->mask & S_SULG) ta += 0.13 + 0.25 * target_hp(t);
  double bonus = 1.0 + ta + 0.0;
  double slope = 0.0;
  if (r->mask & S_TLUM) { bonus += 0.05; slope = 0.005; }
  if (r->mask & S_INSA) { bonus *= 1.15; slope *= 1.15; }
  if (r->mask & S_CATH) bonus += 0.30 * target_hp(t);
  if (s->glass) { bonus *= 1.15; slope *= 1.15; }
  return bonus + slope * r->mastery;
}

/* feral_druid.score_events for one event */
void emit(const Row* r, const St* s, Sco* q, int name, double when, double weight, int kind, double pc) {
  double w = weight + r->potency * pc;
  double amount;
  if (kind == KD_MAG) amount = w * magical(r, s, when) * exec_factor(r, when);
  else amount = w * exec_factor(r, when);
  if (amount != 0.0) add_src(q, name, amount);
}

/* ---- clock: (when, order, kind, payload), pop the smallest (when, order) ---- */
void push(St* s, double when, int kind, int payload) {
  if (when >= FIGHT) return;
  s->seq += 1u;
  if (s->qn >= MAXQ) { s->status = 2; return; }
  int i = s->qn++;
  s->q_w[i] = when; s->q_s[i] = s->seq; s->q_k[i] = kind; s->q_p[i] = payload;
}

int peek_idx(const St* s) {
  int b = -1;
  for (int i = 0; i < s->qn; i++)
    if (b < 0 || s->q_w[i] < s->q_w[b] || (s->q_w[i] == s->q_w[b] && s->q_s[i] < s->q_s[b])) b = i;
  return b;
}

double peek(const St* s) {
  int b = peek_idx(s);
  return (b >= 0) ? s->q_w[b] : FIGHT;
}

/* ---- fight helpers (feral_druid._simulate_feral closures) ---- */
double luck_mult(const Row* r) { return 1.0 + r->luck; }
double proc(const Row* r, double percent) {
  double v = percent / 100.0 * luck_mult(r);
  return (1.0 <= v) ? 1.0 : v;
}

void recover(St* s, const Row* r, double now) {
  if (now > s->mana_time && s->mana < r->mana_max) {
    double v = s->mana + r->mana_regen * (now - s->mana_time);
    s->mana = (r->mana_max <= v) ? r->mana_max : v;
  }
  s->mana_time = (s->mana_time >= now) ? s->mana_time : now;
  if (s->ferocity_on && now > s->fer_time) {
    double v = s->fer + s->fer_rate * (now - s->fer_time);
    s->fer = (s->fer_max <= v) ? s->fer_max : v;
    s->fer_time = now;
  }
}

int pay(St* s, const Row* r, double cost, double now) {
  recover(s, r, now);
  if (s->mana < cost) return 0;
  s->mana -= cost;
  double back = cost * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * r->mastery;
  double v = s->mana + back;
  s->mana = (r->mana_max <= v) ? r->mana_max : v;
  return 1;
}

double dcs(const Row* r, const St* s, double now) {
  if (now < s->berserk_until && (SP_CAT || s->momentum)) {
    double bonus = 0.20 + ((s->momentum && s->shifted) ? 0.15 : 0.0);
    return r->ad * (1.0 + bonus);
  }
  return r->ad;
}

double crit_of(const Row* r, const St* s) {
  double v = r->crit + s->crit_bonus;
  return (100.0 <= v) ? 100.0 : v;
}

double physical(const Row* r, const St* s, double now) {
  double extra = TM(r, T_PFURY) ? 0.10 : 0.0;
  if ((r->mask & S_PACK) && now < s->roar_until) extra += 0.15;
  double ta = r->phy_sum;
  if (r->mask & S_SULG) ta += 0.13 + 0.25 * target_hp(now);
  double bonus = 1.0 + ta + extra;
  if (s->glass) bonus *= 1.15;
  return bonus;
}

double taken_main(const St* s, double now) { return (now < s->maim_until) ? s->taken_maim : s->taken_plain; }

/* magical: -1 = None (Lunar Inspiration decides), 0 = False, 1 = True */
void deal(St* s, const Row* r, Sco* q, int name, double raw, double now, double count, int attack, double main_share,
          double attack_share, int magical_flag, double potency_scale, int auto_hit) {
  if (count <= 0.0 || now >= FIGHT) return;
  int is_magic = (magical_flag < 0) ? s->lunar : magical_flag;
  double mult = is_magic ? 1.0 : physical(r, s, now);
  double co = crit_of(r, s);
  double attack_mult = (1.0 + s->attack_inc) * crit_factor(co, 2.0 + r->rating + s->rating_bonus);
  double spell_mult = r->spell_crit ? crit_factor(co, r->spell_mult + r->rating + s->rating_bonus) : 1.0;
  if (attack) mult *= attack_mult;
  else mult *= attack_share * attack_mult + (1.0 - attack_share) * spell_mult;
  double share = (1.0 <= main_share) ? 1.0 : main_share;
  share = (0.0 >= share) ? 0.0 : share;
  mult *= share * taken_main(s, now) + (1.0 - share) * s->taken_plain;
  double weight = raw * mult * count;
  double pc = potency_scale * mult * count;
  if (weight != 0.0 || pc != 0.0) {
    if (auto_hit && r->auto_pct != 1.0) { weight = weight * r->auto_pct; pc = pc * r->auto_pct; }
    emit(r, s, q, name, now, weight, is_magic ? KD_MAG : KD_PHYS, pc);
  } else if (auto_hit && r->auto_pct != 1.0) {
    s->status = 6;  /* Python would rescale the previous event */
  }
  if (r->damage_mana_pct != 0.0) {
    double v = s->mana + r->damage_mana_pct * r->mana_max * count;
    s->mana = (r->mana_max <= v) ? r->mana_max : v;
  }
}

void apply_rake(St* s, double now, int first, int n) {
  for (int i = first; i < first + n; i++) s->rake[i] = now + 4.0;
  if (!s->rake_clock) {
    s->rake_clock = 1;
    push(s, now + s->rake_period, K_RAKE, 0);
  }
}

double swipe_raw(const Row* r, const St* s, double now) {
  double power = dcs(r, s, now);
  double raw = 30.0 + 1.15 * power;
  if (SP_PRIMAL) {
    raw += 0.55 * r->agi + 0.20 * power;
    if (s->ursoc) raw *= 1.0 + 0.005 * r->str;
  } else if (SP_BEAR) {
    raw += 0.03 * r->max_hp;
  } else {
    raw += 0.40 * r->agi;
  }
  if (r->mask & S_ASHA) raw *= 1.25;
  return raw;
}

void swipe_hit(St* s, const Row* r, Sco* q, double now, double raw, int name, double weight) {
  double low = (target_hp(now) * 100.0 <= crit_of(r, s)) ? 1.15 : 1.0;
  double share = s->razor ? 0.10 * luck_mult(r) : 0.0;
  share = (1.0 <= share) ? 1.0 : share;
  deal(s, r, q, name, raw * low, now, (double)s->targets * weight, 0, 1.0 / (double)s->targets, share, -1, 1.0, 0);
}

double cooldown(const Row* r, const St* s, double base, int key, double flat) {
  double temp = r->cd_temp * ((s->bound == key) ? 0.70 : 1.0);
  double v = (base * temp - r->flat_cdr - flat) / (1.0 + r->haste);
  return (0.5 >= v) ? 0.5 : v;
}

double cast_cost(int b) { return (b == B_SWIPE) ? 15.0 : (b == B_BITE) ? 10.0 : 20.0; }

double cast_cd(const Row* r, const St* s, int b) {
  double flat = s->wild ? 1.0 : 0.0;
  if (b == B_SWIPE) return cooldown(r, s, 6.0, b, flat);
  if (b == B_BITE) return cooldown(r, s, 10.0 - (s->maim ? 2.0 : 0.0), b, flat);
  return cooldown(r, s, 12.0, b, flat);
}

void on_cast(St* s, const Row* r, int b, double now) {
  recover(s, r, now);
  if (b == B_BITE && s->ferocity_on && s->fer >= 40.0) {
    double left = s->ready[B_BITE] - now;
    double spent = s->fer;
    if (80.0 < spent) spent = 80.0;
    if (left * 10.0 < spent) spent = left * 10.0;
    s->fer -= spent;
    double v = s->ready[B_BITE] - spent / 10.0;
    double lo = now + 0.5;
    s->ready[B_BITE] = (lo >= v) ? lo : v;
  }
  double bonus = 0.0;
  if (s->wild) bonus += 25.0 + 0.75 * r->agi;
  if (b == B_ROAR && SP_CAT) bonus += 50.0 + 1.5 * r->agi;
  s->next_hit_bonus = bonus;
}

void resolve(St* s, const Row* r, Sco* q, int b, double now) {
  recover(s, r, now);
  if (b == B_SWIPE) {
    double raw = swipe_raw(r, s, now);
    if (s->rend && now < s->swipe_window) { raw *= 1.25; s->swipe_window = -1.0; }
    if (s->ferocity_on && s->fer >= 40.0) {
      double spent = (80.0 < s->fer) ? 80.0 : s->fer;
      s->fer -= spent;
      raw *= 1.0 + 0.01 * spent;
    }
    swipe_hit(s, r, q, now, raw, N_SWIPE, 1.0);
    apply_rake(s, now, 0, s->targets);
    if (s->rend) s->bite_window = now + 2.0;
  } else if (b == B_BITE) {
    double raw = 100.0 + 1.5 * dcs(r, s, now);
    if (SP_PRIMAL) {
      raw *= 1.25;
      if (s->ursoc) raw *= 1.0 + 0.005 * r->str;
    }
    if (s->rend && now < s->bite_window) { raw *= 1.35; s->bite_window = -1.0; }
    if (s->maim) s->maim_until = now + 5.0;
    deal(s, r, q, N_BITE, raw, now, 1.0, 0, 1.0, 0.0, -1, 1.0, 0);
    if (s->shifted || s->momentum) s->berserk_until = now + 5.0;
    apply_rake(s, now, 0, 1);
    if (s->rend) s->swipe_window = now + 2.0;
  } else {
    s->roar_until = now + 7.0;
    if (s->ferocity_on) {
      double v = s->fer + 0.25 * s->fer_max;
      s->fer = (s->fer_max <= v) ? s->fer_max : v;
    }
  }
}

double attack_interval(const Row* r, const St* s, double now) {
  double speed = r->aspd;
  if (TM(r, T_SROAR) && now < s->roar_until) speed += 0.28;
  speed += ap_bonus(&s->ap, now);
  speed = ap_speed(speed);
  return r->attack_base / (1.0 + speed);
}

void on_attack(St* s, const Row* r, Sco* q, double now) {
  recover(s, r, now);
  double raw = dcs(r, s, now) + s->next_hit_bonus;
  s->next_hit_bonus = 0.0;
  if (TM(r, T_FRESH)) raw += 0.02 * r->max_hp;
  deal(s, r, q, N_AUTO, raw, now, 1.0, 1, 1.0, 0.0, 0, r->attack_potency, 1);
  {
    double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
    if (r->attack_mana_crit != 0.0) gain *= 1.0 + ((100.0 <= r->crit) ? 100.0 : r->crit) / 100.0;
    double v = s->mana + gain;
    s->mana = (r->mana_max <= v) ? r->mana_max : v;
  }
  if (SP_CAT && now >= s->rake[0]) apply_rake(s, now, 0, 1);
  if (s->frenzy) {
    double crit_p = crit_of(r, s) / 100.0;
    double chance = (1.0 - crit_p) * proc(r, 5.0) + crit_p * proc(r, 7.5);
    if (chance > 0.0) swipe_hit(s, r, q, now, swipe_raw(r, s, now), N_FRENZY, chance);
  }
  if (r->mask & S_ORB) {
    double splash_w = (20.0 + 0.35 * r->intel) * (double)s->targets * s->taken_plain;
    if (splash_w != 0.0) emit(r, s, q, N_FIRE, now, splash_w, KD_EXEC, 0.0);
  }
  if (r->mask & S_SULF) {
    if (s->armed) {
      s->armed = 0;
      double cf = r->spell_crit ? crit_factor(crit_of(r, s), r->spell_mult + r->rating) : 1.0;
      double splash_w = r->agi * cf * s->taken_plain * (double)s->targets;
      if (splash_w != 0.0) emit(r, s, q, N_SULF, now, splash_w, KD_MAG, 0.0);
    }
    double echo_w = dcs(r, s, now) * s->taken_plain * (0.10 * (1.0 + r->luck));
    if (echo_w != 0.0) emit(r, s, q, N_SULF_ECHO, now, echo_w, KD_EXEC, 0.0);
  }
  ap_attack(&s->ap, now, crit_of(r, s));
}

void on_rake(St* s, const Row* r, Sco* q, double now) {
  int live[MAXT];
  int nl = 0, has0 = 0;
  for (int i = 0; i < s->targets; i++)
    if (now <= s->rake[i] + 1e-9) { live[nl++] = i; if (i == 0) has0 = 1; }
  if (nl == 0) { s->rake_clock = 0; return; }
  double raw = 10.0 + 0.10 * dcs(r, s, now);
  if (SP_PRIMAL) {
    double chance = proc(r, 30.0);
    raw *= 1.0 + 0.35 * chance;
    if (s->ferocity_on) {
      recover(s, r, now);
      double v = s->fer + 2.0 * chance * (double)nl;
      s->fer = (s->fer_max <= v) ? s->fer_max : v;
    }
  }
  double share = 0.0;
  if (s->razor) { share = 0.15 * luck_mult(r); share = (1.0 <= share) ? 1.0 : share; }
  double main = has0 ? 1.0 / (double)nl : 0.0;
  deal(s, r, q, N_RAKE, raw, now, (double)nl, 0, main, share, -1, 1.0, 0);
  push(s, now + s->rake_period, K_RAKE, 0);
}

/* feral_druid._simulate_feral(build, targets, spec, bound) -> total damage */
#if REPORT
double sim_bound(const Row* r, int bound, int* status_out, St* keep_s, Sco* keep_q) {
#else
double sim_bound(const Row* r, int bound, int* status_out) {
#endif
  St s;
  Sco q;
  q.nord = 0; q.seen = 0u;
#if REPORT
  s.nact = 0;
#endif
  if (r->targets > MAXT) { *status_out = 3; return 0.0; }
  s.targets = r->targets; s.status = 0; s.bound = bound;
  s.qn = 0; s.seq = 0u;
  s.shifted = SP_BEAR || SP_CAT;
  s.ferocity_on = SP_PRIMAL || (SP_BEAR && TM(r, T_GRIZZLY));
  s.lunar = SP_CAT && TM(r, T_LUNAR);
  s.ursoc = TM(r, T_URSOC) || ((r->mask & S_SHPAD) != 0);
  s.momentum = TM(r, T_MOMENTUM) != 0;
  s.rend = TM(r, T_REND) != 0;
  s.maim = TM(r, T_MAIM) != 0;
  s.wild = TM(r, T_WILD) != 0;
  s.razor = TM(r, T_RAZOR) != 0;
  s.frenzy = TM(r, T_FFRENZY) != 0;
  s.glass = GM(r, G_GLASS) || ((r->mask & S_GLAS) != 0);
  int st = 0;
  s.taken_plain = armor_taken(15.0 - r->armor_pen, &st);
  s.taken_maim = armor_taken(15.0 - r->armor_pen - 4.0, &st);
  if (st) { *status_out = st; return 0.0; }
  s.fer_max = s.ferocity_on ? (100.0 + r->mastery + (TM(r, T_PFURY) ? 25.0 : 0.0)) : 0.0;
  s.fer_rate = s.ferocity_on ? 12.0 * (1.0 + r->haste) * (1.0 + 0.01 * r->mastery) : 0.0;
  s.rake_period = 1.0 / (1.0 + r->haste + (TM(r, T_OPEN) ? 0.25 : 0.0));
  s.attack_inc = 0.0;
  if (SP_CAT) s.attack_inc += 0.05 + 0.005 * r->mastery;
  if (TM(r, T_SHRED)) s.attack_inc += 0.10;
  s.crit_bonus = 0.0;
  s.rating_bonus = 0.0;
  if (SP_CAT) {
    s.crit_bonus += 10.0;
    if (s.ursoc) s.crit_bonus += (25.0 <= r->armor) ? 25.0 : r->armor;
    if (s.lunar) s.rating_bonus += 0.15;
  }
  s.mana = r->mana_max; s.mana_time = 0.0; s.fer = 0.0; s.fer_time = 0.0;
  for (int k = 0; k < 3; k++) s.ready[k] = 0.0;
  for (int i = 0; i < MAXT; i++) s.rake[i] = -1.0;
  s.berserk_until = -1.0; s.roar_until = -1.0; s.maim_until = -1.0;
  s.bite_window = -1.0; s.swipe_window = -1.0; s.next_hit_bonus = 0.0;
  s.armed = 0; s.rake_clock = 0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  double hero_ready = 0.0, next_attack = 0.0;
  int guard = 0;
  while (guard < 200000) {
    guard += 1;
    if (s.status) break;
    double pk = peek(&s);
    double moment = (pk < next_attack) ? pk : next_attack;
    if (hero_ready <= moment && hero_ready < FIGHT) {
      int spell = -1;
      for (int b = 0; b < 3; b++) if (s.ready[b] <= hero_ready) { spell = b; break; }
      if (spell >= 0) {
        if (!pay(&s, r, cast_cost(spell), hero_ready)) { s.ready[spell] = hero_ready + 0.25; continue; }
        act(&s, hero_ready, spell);
        s.ready[spell] = hero_ready + cast_cd(r, &s, spell);
        on_cast(&s, r, spell, hero_ready);
        if ((r->mask & S_SULF) && !s.armed) s.armed = 1;
        push(&s, hero_ready + CAST_POINT, K_CAST, spell);
        double busy = hero_ready + CAST_TIME + r->cast_lock;
        hero_ready = busy;
        next_attack = (next_attack >= busy) ? next_attack : busy;
        continue;
      }
      double wake = FIGHT;
      int any = 0;
      for (int b = 0; b < 3; b++) {
        double t = s.ready[b];
        if (t > hero_ready + 1e-9) { if (!any || t < wake) wake = t; any = 1; }
      }
      if (!any) wake = FIGHT;
      if (wake <= moment) { hero_ready = wake; continue; }
      double mw = (wake < FIGHT) ? wake : FIGHT;
      hero_ready = (hero_ready >= mw) ? hero_ready : mw;
    }
    if (moment >= FIGHT) break;
    if (moment == next_attack && (s.qn == 0 || next_attack < peek(&s))) {
      on_attack(&s, r, &q, moment);
      next_attack = moment + attack_interval(r, &s, moment);
      continue;
    }
    int qi = peek_idx(&s);
    double now = s.q_w[qi];
    int kind = s.q_k[qi], payload = s.q_p[qi];
    s.qn--;
    s.q_w[qi] = s.q_w[s.qn]; s.q_s[qi] = s.q_s[s.qn]; s.q_k[qi] = s.q_k[s.qn]; s.q_p[qi] = s.q_p[s.qn];
    if (kind == K_CAST) resolve(&s, r, &q, payload, now);
    else on_rake(&s, r, &q, now);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < q.nord; i++) total += q.src[q.ord[i]];
#if REPORT
  recover(&s, r, FIGHT);
  *keep_s = s; *keep_q = q;
#endif
  return total;
}

/* feral_druid.simulate: with the Diamond Ring the best binding (first wins ties), else unbound */
#if REPORT
double fight(const Row* r, int* status_out, St* keep_s, Sco* keep_q, int* bound_out) {
  St ts; Sco tq;
#define SIM(b, st) sim_bound(r, b, st, &ts, &tq)
#define KEEP(b) do { *keep_s = ts; *keep_q = tq; *bound_out = (b); } while (0)
#else
double fight(const Row* r, int* status_out) {
#define SIM(b, st) sim_bound(r, b, st)
#define KEEP(b) do { } while (0)
#endif
  if (r->mask & S_RING) {
    double best = 0.0;
    int have = 0;
    for (int b = 0; b < 3; b++) {
      int st = 0;
      double d = SIM(b, &st) / FIGHT;
      if (st) { *status_out = st; return 0.0; }
      if (!have || d > best) { best = d; have = 1; KEEP(b); }
    }
    return best;
  }
  int st = 0;
  double d = SIM(-1, &st) / FIGHT;
  if (st) { *status_out = st; return 0.0; }
  KEEP(-1);
  return d;
}
#undef SIM
#undef KEEP

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  int nmag; __global const int* mag_kind; __global const int* mag_id; __global const double* mag_amt;
  int nphy; __global const int* phy_kind; __global const int* phy_id; __global const double* phy_amt;
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

int present(Tab* T, int kind, int id, const int* chosen, uint tmask, uint gmask) {
  if (kind == 0) { for (int si = 0; si < 6; si++) if (chosen[si] == id) return 1; return 0; }
  if (kind == 1) return (gmask >> id) & 1u;
  return (tmask >> id) & 1u;
}

/* feral_druid.sheet(build, spec): shadow.character(feral bases, white 32, no baked buffs, agility primary),
   then the feral attack damage, mana, swing, health and armour */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double intel = T->base[0], strength = T->base[1], agility = T->base[2];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 2.0 * (double)pts[5];
  double mana = 20.0 * (double)pts[1];
  double crit = (double)pts[6];
  double rating = 0.0;
  double haste = 0.01 * (double)pts[3];
  double aspd = 0.02 * (double)pts[4];
  ulong mask = 0;
  int n_core = 0, n_sulg = 0, sc = 0, sc65 = 0, dap = 0, has_shop = 0, has_drop = 0;
  for (int si = 0; si < 6; si++) {
    int p = chosen[si];
    if (p < 0) { first[si] = 0; continue; }  /* explicit pieces: empty slot */
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
    agility = agility + f[6];
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
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) agility += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  damage = 32.0 + 0.75 * intel + damage;
  mana = 175.0 + 7.0 * intel + mana;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  double agility_speed = 0.004 * agility;
  agility_speed = (1.0 <= agility_speed) ? 1.0 : agility_speed;
  double asum = aspd + agility_speed;
  asum = (4.0 <= asum) ? 4.0 : asum;
  aspd = (-0.8 >= asum) ? -0.8 : asum;
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
  double cast_lock = 0.0, armor_pen = 0.0, auto_pct = 1.0, regen_rate = 0.0, mp5 = 0.0;
  double keep = 1.0, rflat = 0.0, rmast = 0.0, persec = 0.0, aflat = 0.0, apct = 0.0, dpct = 0.0;
  double item_armor = 0.0, item_health = 0.0;
  int acrit = 0, nexec = 0;
  for (int si = 0; si < 6; si++) {
    if (!first[si]) continue;
    __global const double* u = T->uniq + (long)chosen[si] * NU;
    __global const double* a = T->pal + (long)chosen[si] * NPAL;
    cast_lock += u[1];
    if (u[2] != 0.0) dap = 1;
    armor_pen += u[3];
    auto_pct += u[8];
    if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
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
    item_armor += a[0];
    item_health += a[1];
  }
  double mag_sum = 0.0;
  for (int e = 0; e < T->nmag; e++)
    if (present(T, T->mag_kind[e], T->mag_id[e], chosen, tmask, gmask)) mag_sum += T->mag_amt[e];
  double phy_sum = 0.0;
  for (int e = 0; e < T->nphy; e++)
    if (present(T, T->phy_kind[e], T->phy_id[e], chosen, tmask, gmask)) phy_sum += T->phy_amt[e];
  double luck = 0.01 * (double)pts[9];
  for (int si = 0; si < 6; si++) if (first[si]) luck += T->uniq[(long)chosen[si] * NU + 13];
  if (GM(r, G_FORTUNE)) luck += 0.15;
  /* feral_druid.sheet */
  double item_damage = damage - 32.0 - 0.75 * intel;
  double ad = 32.0 + 0.75 * agility + item_damage;
  double mana_max = mana - 55.0;
  double stat = (1.20 + 0.10 * intel) * (1.0 + regen_rate);
  stat += mp5 / 5.0;
  stat += persec * mana_max;
  if (GM(r, G_REPL)) stat += 1.50 + 0.0075 * mana_max;
  double health = 250.0 + 15.0 * strength + item_health;
  if (SP_BEAR) health += 480.0;
  double armor = 1.0 + 0.1 * agility;
  armor += item_armor;
  r->intel = intel; r->str = strength; r->agi = agility; r->potency = potency; r->mastery = mastery; r->ad = ad;
  r->mana_max = mana_max; r->crit = (100.0 <= crit) ? 100.0 : crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->spell_mult = sc65 ? 1.65 : 1.50;
  r->flat_cdr = flat_cdr; r->cd_temp = cd_temp; r->cast_lock = cast_lock;
  r->auto_pct = auto_pct; r->armor_pen = armor_pen; r->luck = luck; r->attack_potency = dap ? 2.0 : 1.0;
  r->attack_base = (SP_CAT ? 1.4 : 1.7) * ((mask & S_GALA) ? 1.20 : 1.0);
  r->mana_regen = stat * 0.80;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->mag_sum = mag_sum; r->phy_sum = phy_sum; r->max_hp = health; r->armor = armor;
  r->spell_crit = sc; r->nexec = nexec; r->targets = targets;
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
    const int nmag, __global const int* mag_kind, __global const int* mag_id, __global const double* mag_amt, \
    const int nphy, __global const int* phy_kind, __global const int* phy_id, __global const double* phy_amt, \
    __global const double* pal, __global const double* base

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.nmag = nmag; T.mag_kind = mag_kind; T.mag_id = mag_id; T.mag_amt = mag_amt; \
  T.nphy = nphy; T.phy_kind = phy_kind; T.phy_id = phy_id; T.phy_amt = phy_amt; \
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
  int status = 0, group = 0, chosen[6], bound = -1;
  double d = 0.0;
  St ks; Sco kq; Row r;
  ks.nact = 0; ks.mana = 0.0; kq.nord = 0;
  if (!picks_ok(&T, picks, gid, chosen)) status = 1;
  else {
    sheet(&T, &r, chosen, tmasks[gid], gmasks[gid], pts, targets, &group);
    d = fight(&r, &status, &ks, &kq, &bound);
  }
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
  out_nord[gid] = kq.nord;
  for (int i = 0; i < NSRC; i++) {
    out_ord[(long)gid * NSRC + i] = (i < kq.nord) ? kq.ord[i] : -1;
    out_src[(long)gid * NSRC + i] = (i < kq.nord) ? kq.src[kq.ord[i]] : 0.0;
  }
  out_mana[gid] = (status == 0 && r.mana_max > 0.0) ? 100.0 * ks.mana / r.mana_max : 0.0;
  out_nact[gid] = ks.nact;
  for (int i = 0; i < MAXA; i++) {
    out_act_t[(long)gid * MAXA + i] = (i < ks.nact) ? ks.act_t[i] : 0.0;
    out_act_id[(long)gid * MAXA + i] = (i < ks.nact) ? ks.act_id[i] : -1;
  }
  __global double* o = out_stats + (long)gid * NSTAT;
  if (status == 0) {
    o[0] = r.intel; o[1] = r.str; o[2] = r.agi; o[3] = r.ad; o[4] = r.potency; o[5] = r.mastery; o[6] = r.crit;
    o[7] = r.rating; o[8] = r.haste; o[9] = r.aspd; o[10] = r.luck; o[11] = r.mana_max; o[12] = r.mana_regen;
    o[13] = r.attack_base / (1.0 + r.aspd); o[14] = r.cd_temp; o[15] = r.flat_cdr; o[16] = r.armor_pen;
    o[17] = r.max_hp; o[18] = r.armor; o[19] = (double)bound; o[20] = r.spell_crit ? 1.0 : 0.0;
  }
}
#endif
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I00D": 0, "I0BR": 1, "I07O": 2, "I0JO": 3, "I0QT": 4, "tlum": 5, "I0JA": 6, "I096": 7, "I03C": 8,
    "I00L": 9, "I00Y": 10, "I07P": 11, "I048": 12, "I0FW": 13, "I0RV": 14, "I0RW": 15, "I0RY": 16, "I0QN": 17,
    "I0PU": 18, "I0PS": 19,
}
TALENT_BITS = {
    "I0KJ": 0, "I0NO": 1, "I0MN": 2, "I0KL": 3, "I0PX": 4, "I0PZ": 5, "I0RU": 6, "I0Q0": 7, "I09M": 8,
    "I0KM": 9, "I0KI": 10, "I0PY": 11, "I0AE": 12, "I0RT": 13,
    # feral_druid.IGNORED_TALENTS and the talent pages: no effect on the fight
    "I0KN": 20, "I0KK": 21, "I0A1": 22, "I0RS": 23, "I0MD": 24, "I0MC": 25,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN", "I0OH"}
SPECS = {"primal": 0, "guardian": 1, "savage": 2}

# Level-15 Feral Druid O00R (map 2.5.2c), moved from the removed sunken_sim.feral_druid model
LEVEL = 15
FERAL_STR = int(14 + (LEVEL - 1) * 1.4)
FERAL_AGI = int(25 + (LEVEL - 1) * 2.5)
FERAL_INT = int(11 + (LEVEL - 1) * 1.1)
FERAL_BASE_HP = 250.0
HERO_CLASS = "FeralDruid"
TALENT_NAMES = {
    "I0KN": "Dreamwalker", "I0KJ": "Primal Fury", "I0NO": "Razor Claws", "I0MN": "Savage Roar", "I0KL": "Maim",
    "I0PX": "Feral Frenzy", "I0KK": "Guardian of Elune", "I0PZ": "Strength of the Wild", "I0RU": "Grizzly Bear",
    "I0Q0": "Savage Momentum", "I09M": "Rend and Tear", "I0A1": "Survival of the Fittest", "I0KM": "Son of Ursoc",
    "I0KI": "Open Wounds", "I0PY": "Shred", "I0AE": "Fresh Wound", "I0RS": "Primal Instinct",
    "I0RT": "Lunar Inspiration",
}
IGNORED_TALENTS = frozenset({"I0KN", "I0KK", "I0A1", "I0RS"})
DIAMOND = "I00D"
HEALTH_RE = re.compile(r"\+(\d+) (?:Maximum )?(?:Health|HP)\b", re.I)


def feral_druid_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the agility primary fold, item armour and item health."""
    from sunken_sim import pressure, shadow
    from sunken_sim.stacking import stack_fields

    if (shadow.LEVEL, pressure.AGI_ARMOR, pressure.STR_HP) != (LEVEL, 0.1, 15.0):
        raise ValueError("kernel constants assume level 15, 0.1 armour per AGI and 15 HP per STR")
    if (shadow.CAST_POINT, shadow.CAST_BACKSWING) != (0.15, 0.30):
        raise ValueError("kernel constants assume cast 0.15 + 0.30")
    AP.check()
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(FERAL_INT), float(FERAL_STR), float(FERAL_AGI), float(FERAL_BASE_HP)],
                           "Feral Druid")
    pieces = space.pieces
    n = len(pieces)
    fold = t["fold"].reshape(n, 2, C.NF).copy()
    pal = np.zeros((n, NPAL), dtype=np.float64)
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
        armor = item.armor
        if float(armor) != int(armor):
            raise ValueError(f"{code}: fractional item armour {armor}")
        pal[i] = [float(armor), float(sum(float(v) for v in HEALTH_RE.findall(item.tip or "")))]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class FeralDruidCL(C.ExactCL):
    hero = "feral_druid"
    PYTHON = False  # sunken_sim.feral_druid fight model removed 2026-11-27: fixtures + report mode
    KERNEL = KERNEL
    SOURCE_NAMES = ("Автоатака", "Swipe", "Savage Bite", "Rake", "Feral Frenzy", "Всплеск огня", "Sulfuras",
                    "Sulfuras (удар)")
    ACTION_NAMES = ("Swipe", "Savage Bite", "Stampeding Roar")
    STAT_KEYS = ("int", "str", "agi", "ad", "potency", "mastery", "crit", "rating", "haste", "attack_speed", "luck",
                 "mana_max", "mana_regen", "swing", "cd_temp", "flat_cdr", "armor_pen", "max_hp", "armor", "bound",
                 "spell_crit")
    BOOL_STATS = ("spell_crit",)
    NSRC, MAXA = 8, 160

    def report(self, codes, talents=(), glyphs=(), points: dict | None = None) -> dict:
        """class_cl report plus the Elemental Orb mode, the Diamond Ring binding and the ESC-only sheet lines."""
        from sunken_sim.shadow import ORB_MODE

        rep = super().report(codes, talents, glyphs, points)
        bound = int(rep["stats"].pop("bound"))
        rep["bound_spell"] = self.ACTION_NAMES[bound] if bound >= 0 else None
        rep["orb_mode"] = next((name for code, name in ORB_MODE.items() if code in set(codes)), None)
        rep["stats"]["healing_power"] = float(int((points or {}).get("healing_power", 0)))
        rep["stats"]["pet_damage"] = 0.015 * int((points or {}).get("pet_damage", 0))
        return rep
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ()  # the fight does not depend on Potency: a replayed fight scores like a fresh one
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "nmag", "mag_kind", "mag_id", "mag_amt", "nphy", "phy_kind", "phy_id", "phy_amt", "pal", "base")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32, "nmag": np.int32, "nphy": np.int32}

    @staticmethod
    def module():
        raise RuntimeError("feral_druid: the Python fight model was removed (2026-11-27)")

    def tables(self, space, items, sources):
        return feral_druid_tables(space, items, sources)

    def timeline_key(self, build):
        # feral_druid._timeline_key left out Potency / Health / Healing Power, which never change the fight;
        # the key is every other ESC point.
        from dataclasses import fields

        free = {"potency_points", "health_points", "healing_power_points"}
        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points")
                     and f.name not in free)


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
