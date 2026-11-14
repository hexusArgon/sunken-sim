"""Exact float64 OpenCL kernel for Hunter fights (Marksmanship, Beast Mastery, Survival).

One work-item scores one fight: unrank the six items, fold the sheet like ``sunken_sim.hunter.stats_of``
(agility primary, white 30, item luck / health / pet damage lines), run the event loop of
``hunter.simulate`` (pets, delayed traps and the Survival second Multi-Shot, the global Serpent Sting
timer) and score every event as ``hunter.score_events`` the moment it is emitted, sources in insertion
order. Every chance is a weight: Serpent Sting / trap wound / Lock and Load / both Prowess buffs are
``hunter._Window`` distributions mirrored entry by entry; Battle Frenzy / Silent Messenger:
farm.hybrid.attack_procs_cl.

``hunter._timeline_key`` holds every ESC point, so a replayed cache never differs from a fresh fight.
Rows the kernel cannot score (negative armour in use, list overflow, more than MAXT targets) return a
non-zero status and are re-scored by the Python oracle. Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 17
NNEG = 32

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 marksmanship, 1 beast_mastery, 2 survival */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_MM (SPEC == 0)
#define SP_BM (SPEC == 1)
#define SP_SV (SPEC == 2)
/* pets: hunter.PETS order */
#define P_SPIKE 0
#define P_HUFFER 1
#define P_GRYLLS 2
#define CUR_PET (SP_MM ? P_HUFFER : SP_BM ? P_SPIKE : P_GRYLLS)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define CAST_TIME (CAST_POINT + CAST_BACKSWING)
#define ASPECT 0.10
#define RANKF 1.0
#define WHITE_BASE 30.0
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 17
#define MAXT 8
#define WS 8
#define MAXPET 12
#define MAXPEND 8
#define NSRC 16
#define NNEG 32  /* shadow.armor_taken(-k), k = 1..NNEG, filled by the host */

#define S_SULF (1UL<<0)
#define S_ORB  (1UL<<1)
#define S_GALA (1UL<<2)
#define S_SULG (1UL<<3)
#define S_GLAS (1UL<<4)
#define S_FLSK (1UL<<5)
#define S_I03C (1UL<<6)
#define S_I00L (1UL<<7)
#define S_I00Y (1UL<<8)
#define S_HARN (1UL<<9)
#define S_ATIE (1UL<<10)
#define S_CORE (1UL<<11)
#define S_UNSI (1UL<<12)
#define S_SILM (1UL<<13)
#define S_SQUIV (1UL<<14)
#define S_TGLOV (1UL<<15)
#define S_RBOW (1UL<<16)
#define S_BHELM (1UL<<17)
#define S_MOTW (1UL<<18)
#define S_THORN (1UL<<19)
#define S_BEASTI (1UL<<20)

#define T_TALON (1u<<0)
#define T_UNLEASH (1u<<1)
#define T_TRAPL (1u<<2)
#define T_HYDRA (1u<<3)
#define T_LOCK (1u<<4)
#define T_HOWL (1u<<5)
#define T_TRUE (1u<<6)
#define T_WILDP (1u<<7)
#define T_VOLLEY (1u<<8)
#define T_WIND (1u<<9)
#define T_KILLER (1u<<10)
#define T_STEEL (1u<<11)
#define T_FLANK (1u<<12)
#define T_DIRE (1u<<13)
#define T_MONG (1u<<14)
#define T_SCENT (1u<<15)
#define T_UNMAT (1u<<16)
#define T_POISON (1u<<17)

#define G_UNSL (1u<<0)
#define G_GLASS (1u<<1)
#define G_FORT (1u<<2)
#define G_SUPR (1u<<3)
#define G_ANIM (1u<<4)
#define G_MIND (1u<<5)
#define G_FORTUNE (1u<<6)
#define G_FREN (1u<<7)
#define G_REPL (1u<<8)
#define G_BEAST (1u<<9)

#define TM(r, x) (TALENTS && ((r)->tmask & (x)))
#define GM(r, x) (TALENTS && ((r)->gmask & (x)))

/* cast keys: hunter order ("call", "wrath", "sting", "multi", "trap") */
#define K_CALL 0
#define K_WRATH 1
#define K_STING 2
#define K_MULTI 3
#define K_TRAP 4

/* pending kinds, in the string order of min(pending): "multi2" < "trap" */
#define PD_MULTI2 0
#define PD_TRAP 1

/* event kinds (hunter.KIND_*) */
#define KD_PHYS 0
#define KD_EXEC 1
#define KD_MAG 2

/* sources */
#define N_AUTO 0
#define N_STING 1
#define N_TICKS 2
#define N_MULTI 3
#define N_SPLIT 4
#define N_TRAP 5
#define N_PET0 6   /* + pet kind: Spike, Huffer, Grylls */
#define N_FIRE 9
#define N_HOWL 10
#define N_MAUL 11
#define N_SHRED 12
#define N_MARKS 13
#define N_SULF 14
#define N_ECHO 15

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, armor_pen, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, pet_damage, summon_crit, summon_rating;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  __global const double* negt;
  int nexec, targets, glass;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct { double e[WS + 1], m[WS + 1]; int n; } Win;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  Win stung[MAXT], wound[MAXT], lock, hprow, pprow;
  double th[4], tp[4]; int thneg[4];
  int pk[MAXPET]; double pnext[MAXPET], pend[MAXPET], pstart[MAXPET]; int np;
  double dt[MAXPEND]; int dk[MAXPEND], di[MAXPEND]; int nd;
  double nxt[5];
  double mana, mana_time, wrath_until, quill_until, quiver, split;
  int quill_count, howl_stacks, armed, status, targets;
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

/* max(0, min(1, v)) */
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

void add_src(St* q, int id, double amount) {
  uint bit = 1u << id;
  if (q->seen & bit) q->src[id] = q->src[id] + amount;
  else { q->seen |= bit; q->ord[q->nord++] = id; q->src[id] = 0.0 + amount; }
}

/* hunter.score_events for one event */
void emit(const Row* r, St* s, int name, double when, double weight, int kind) {
  double amount;
  if (kind == KD_PHYS) {
    double bonus = 1.0 + r->phys_add;
    if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(when);
    if (r->glass) bonus *= 1.15;
    amount = weight * bonus * exec_factor(r, when);
  } else if (kind == KD_MAG) {
    double ms = (1.0 + r->magic_add) * (r->glass ? 1.15 : 1.0);
    amount = weight * ms * exec_factor(r, when);
  } else {
    amount = weight * exec_factor(r, when);
  }
  if (amount != 0.0) add_src(s, name, amount);
}

/* ---- hunter._Window ---- */
double wmass(const Win* w, double now) {
  double total = 0.0;
  for (int k = 0; k < w->n; k++) if (now < w->e[k]) total += w->m[k];
  return total;
}

void wsure(Win* w, double now, double dur) { w->e[0] = now + dur; w->m[0] = 1.0; w->n = 1; }

void wmaybe(Win* w, double now, double dur, double p) {
  if (p >= 1.0) { wsure(w, now, dur); return; }
  if (p <= 0.0) return;
  int c = 0;
  for (int k = 0; k < w->n; k++) {
    if (now < w->e[k]) { w->e[c] = w->e[k]; w->m[c] = w->m[k] * (1.0 - p); c++; }
  }
  double until = now + dur;
  if (c > 0 && w->e[c - 1] == until) w->m[c - 1] = w->m[c - 1] + p;
  else { w->e[c] = until; w->m[c] = p; c++; }
  while (c > WS) {
    int k = 0;
    for (int j = 1; j < c - 1; j++) if (w->m[j] < w->m[k]) k = j;
    w->m[k + 1] = w->m[k + 1] + w->m[k];
    for (int j = k; j < c - 1; j++) { w->e[j] = w->e[j + 1]; w->m[j] = w->m[j + 1]; }
    c--;
  }
  w->n = c;
}

/* ---- fight helpers (hunter.simulate closures) ---- */
int wrath_on(const St* s, double now) { return now < s->wrath_until; }

double dcs(const Row* r, const St* s, double now) {
  double value = WHITE_BASE + 0.75 * r->agi + r->damage;
  if (wrath_on(s, now)) value *= 1.0 + (TM(r, T_WILDP) ? 0.35 : 0.20) + 0.05 * RANKF;
  return value;
}

double wrath_pct(const Row* r) {
  double value = 0.30 + 0.03 * RANKF;
  if (TM(r, T_WILDP)) value += 0.25;
  return value;
}

double potency_now(const Row* r, const St* s, double now) {
  double value = r->potency;
  if (TM(r, T_HYDRA)) value += 3.0 + 0.04 * dcs(r, s, now);
  return value;
}

/* expected armour factor: Sting and the trap wound as independent chances */
double taken_for(St* s, int index, double now, int hunter) {
  const double* a = hunter ? s->th : s->tp;
  double ps = wmass(&s->stung[index], now);
  double pw = wmass(&s->wound[index], now);
  if (ps == 0.0 && pw == 0.0) {
    if (hunter && s->thneg[0] && !s->status) s->status = 4;
    return a[0];
  }
  double c00 = (1.0 - ps) * (1.0 - pw), c10 = ps * (1.0 - pw), c01 = (1.0 - ps) * pw, c11 = ps * pw;
  if (hunter && !s->status && ((s->thneg[0] && c00 != 0.0) || (s->thneg[2] && c10 != 0.0)
                               || (s->thneg[1] && c01 != 0.0) || (s->thneg[3] && c11 != 0.0))) s->status = 4;
  return c00 * a[0] + c10 * a[2] + c01 * a[1] + c11 * a[3];
}

double hero_crit(const Row* r, const St* s, double now) {
  double chance = r->crit;
  if (TM(r, T_TRUE)) chance += 10.0;
  if (now < s->quill_until) chance += 20.0;
  return chance;
}

double hero_rating(const Row* r, const St* s, double now) {
  double rating = 2.0 + r->rating;
  if (TM(r, T_UNMAT)) rating += 0.25 + 0.15 * hero_crit(r, s, now) / 100.0;
  return rating;
}

void gain_mana(const Row* r, St* s, double amount) {
  double v = s->mana + amount;
  s->mana = (r->mana_max <= v) ? r->mana_max : v;
}

void recover(const Row* r, St* s, double now) {
  if (now > s->mana_time && s->mana < r->mana_max) {
    double v = s->mana + r->mana_regen * (now - s->mana_time);
    s->mana = (r->mana_max <= v) ? r->mana_max : v;
  }
  s->mana_time = now;
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

/* hunter hit (PreDamage_Increase); attack = probability the event is an attack; returns the crit share */
double hit(const Row* r, St* s, int name, double raw, double now, int index, double attack, int typed,
           double potency_scale, double count, int auto_hit) {
  double amount = raw + potency_now(r, s, now) * potency_scale;
  amount *= 1.0 + ASPECT;
  double armor = taken_for(s, index, now, 1);
  double share = 0.0;
  double pre_plain = amount * armor;
  double pre = pre_plain;
  if (attack > 0.0) {
    double inc = 1.0;
    if (TM(r, T_MONG)) inc += 0.10;
    if (TM(r, T_FLANK) && index == 0) inc += 0.15;
    double chance = hero_crit(r, s, now);
    double mult = hero_rating(r, s, now);
    double normal_pre = amount * inc * armor * crit_factor(chance, mult);
    double armed = TM(r, T_WIND) ? s->quiver * attack : 0.0;
    double boosted_pre = amount * inc * (1.0 + chance / 100.0) * armor * mult;
    double attack_pre = (1.0 - armed / attack) * normal_pre + (armed / attack) * boosted_pre;
    share = attack * ((1.0 - armed / attack) * chance01(chance / 100.0) + armed / attack);
    pre = (1.0 - attack) * pre_plain + attack * attack_pre;
    if (armed != 0.0) s->quiver -= armed * count;
    if (TM(r, T_POISON)) wmaybe(&s->stung[index], now, 10.0, attack * count);
  }
  double w = pre * count;
  if (w != 0.0) {
    if (auto_hit && r->auto_pct != 1.0) w = w * r->auto_pct;
    emit(r, s, name, now, w, typed ? KD_PHYS : KD_EXEC);
  }
  note_damage_mana(r, s, count);
  return share;
}

/* pet damage: Pet Damage %, Scent of Blood, Aspect, summon crit on attacks */
double pet_hit(const Row* r, St* s, int name, double raw, double now, int kind, int index, int attack, double weight) {
  double amount = raw * (1.0 + r->pet_damage) * (1.0 + ASPECT);
  double increase = 1.0;
  if (TM(r, T_SCENT) && target_hp(now) < 0.40) increase += 0.28;
  amount *= increase;
  double armor = taken_for(s, index, now, 0);
  double share = 0.0;
  double pre;
  if (attack) {
    double inc = 1.0;
    if (TM(r, T_FLANK) && kind == CUR_PET && index == 0) inc += 0.15;
    double chance = r->summon_crit + ((kind == P_SPIKE) ? 20.0 : 0.0);
    double rating = 2.0 + r->summon_rating + ((kind == P_SPIKE) ? 0.30 : 0.0);
    if (TM(r, T_UNMAT)) rating += 0.25 + 0.15 * hero_crit(r, s, now) / 100.0;
    share = chance01(chance / 100.0);
    pre = amount * inc * armor * crit_factor(chance, rating);
  } else {
    pre = amount * armor;
  }
  double w = pre * weight;
  if (w != 0.0) emit(r, s, name, now, w, KD_EXEC);
  return share;
}

void cut_cooldowns(St* s, double now, double fraction, double seconds) {
  /* keys ("sting", "multi", "wrath", "trap") */
  const int keys[4] = {K_STING, K_MULTI, K_WRATH, K_TRAP};
  for (int i = 0; i < 4; i++) {
    int key = keys[i];
    double left = s->nxt[key] - now;
    if (left > 0.0) {
      double v = left * (1.0 - fraction) - seconds;
      left = (0.0 >= v) ? 0.0 : v;
      s->nxt[key] = now + left;
    }
  }
}

void howl(const Row* r, St* s) {
  if (TM(r, T_HOWL) && s->howl_stacks < 3) s->howl_stacks += 1;
}

void trap(const Row* r, St* s, int index, double now, double count) {
  double raw = 40.0 + 1.20 * dcs(r, s, now) + 0.50 * r->agi;
  hit(r, s, N_TRAP, raw, now, index, 0.0, 1, 1.0, count, 0);
  wmaybe(&s->wound[index], now, 5.0, count);
}

void multishot(const Row* r, St* s, double now, int secondary) {
  int cap = TM(r, T_VOLLEY) ? 5 : 3;
  int hits = (s->targets < cap) ? s->targets : cap;
  double raw = 10.0 + 60.0 * RANKF + 0.70 * dcs(r, s, now) + 0.30 * r->agi;
  if (TM(r, T_VOLLEY)) raw *= 1.10;
  if (TM(r, T_MONG)) raw *= 1.10;
  if (secondary) raw *= 0.50;
  if (r->mask & S_RBOW) raw *= 1.25;
  double pierce = 0.0;
  if (TM(r, T_STEEL) || (r->mask & S_SQUIV)) pierce = chance01(0.30 * (1.0 + r->luck));
  for (int index = 0; index < hits; index++) {
    hit(r, s, N_MULTI, raw, now, index, pierce, pierce < 1.0, 1.0, 1.0, 0);
    if (TM(r, T_TRAPL)) {
      double chance = chance01(0.25 * (1.0 + r->luck) * (secondary ? 0.5 : 1.0));
      if (chance > 0.0) trap(r, s, index, now, chance);
    }
  }
}

double hunter_interval(const Row* r, const St* s, double now) {
  double swing = 1.60 * ((r->mask & S_GALA) ? 1.20 : 1.0);
  if (SP_MM) swing *= 1.0 - ASPECT;
  double speed = r->aspd;
  speed += 0.40 * wmass(&s->lock, now);
  speed += 0.20 * wmass(&s->hprow, now);
  if ((r->mask & S_BHELM) && wrath_on(s, now)) speed += 0.25;
  speed += ap_bonus(&s->ap, now);
  speed = ap_speed(speed);
  return swing / (1.0 + speed);
}

double pet_swing(int kind) { return (kind == P_SPIKE) ? 1.50 : (kind == P_HUFFER) ? 1.45 : 1.70; }

double pet_interval(const Row* r, const St* s, int i, double now) {
  int kind = s->pk[i];
  double swing = pet_swing(kind);
  if (TM(r, T_TALON)) swing *= 0.90;
  double speed = 0.0;
  if (SP_BM) speed += 0.10 + 0.008 * r->mastery;
  if (kind == CUR_PET) speed += 0.40 * wmass(&s->pprow, now);
  if (kind == CUR_PET && (r->mask & S_BHELM) && wrath_on(s, now)) speed += 0.25;
  if (kind == P_HUFFER && TM(r, T_DIRE)) {
    if (fmod(now - s->pstart[i], 20.0) < 12.0) speed += 0.40;
  }
  speed = ap_speed(speed);
  return swing / (1.0 + speed);
}

void pet_attack(const Row* r, St* s, int i, double now) {
  int kind = s->pk[i];
  double base = (kind == P_SPIKE) ? 9.0 : (kind == P_HUFFER) ? 4.0 : 17.0;
  double scale = (kind == P_SPIKE) ? 0.50 : (kind == P_HUFFER) ? 0.30 : 0.90;
  int name = N_PET0 + kind;
  double raw = (base + (double)(long)(scale * dcs(r, s, now))) + 1.0;
  if (kind == CUR_PET && wrath_on(s, now)) {
    double bw = wrath_pct(r) * (SP_BM ? 1.0 : 0.5);
    raw *= 1.0 + bw;
  }
  if (kind == P_GRYLLS && TM(r, T_DIRE)) raw *= 1.20;
  double main_raw = raw;
  if (kind == CUR_PET && s->howl_stacks > 0) {
    double value = (20.0 + 0.25 * r->agi + 0.50 * r->mastery) * (double)s->howl_stacks;
    s->howl_stacks = 0;
    if (SP_BM) main_raw += value;
    else hit(r, s, N_HOWL, value, now, 0, 0.0, 1, 1.0, 1.0, 0);
  }
  double share = pet_hit(r, s, name, main_raw, now, kind, 0, 1, 1.0);
  int events = 1;
  if (kind == P_HUFFER) {
    int top = (s->targets < 3) ? s->targets : 3;
    for (int index = 1; index < top; index++) {
      pet_hit(r, s, name, raw, now, kind, index, 1, 1.0);
      events += 1;
    }
    s->quill_count += events;
    while (s->quill_count >= 15) {
      s->quill_count -= 15;
      s->quill_until = now + 5.0;
    }
  }
  if (kind == P_GRYLLS) {
    double chance = chance01(0.20 * (1.0 + r->luck));
    if (chance > 0.0) hit(r, s, N_MAUL, 15.0 + 1.50 * dcs(r, s, now), now, 0, 0.0, 1, 1.0, chance, 0);
  }
  if (kind == P_SPIKE && TM(r, T_DIRE)) {
    double chance = chance01(0.20 * (1.0 + share) * (1.0 + r->luck));
    if (chance > 0.0) pet_hit(r, s, N_SHRED, 50.0 + 0.50 * dcs(r, s, now), now, kind, 0, 0, chance);
  }
  wmaybe(&s->hprow, now, 3.0, share);
  if (TM(r, T_TALON)) {
    double fraction = (kind == CUR_PET) ? 0.06 : 0.02;
    for (int e = 0; e < events; e++) cut_cooldowns(s, now, fraction, 0.0);
  }
}

double cooldown(const Row* r, double base, double flat) {
  double v = (base * r->cd_temp - r->flat_cdr - flat) / (1.0 + r->haste);
  return (0.5 >= v) ? 0.5 : v;
}

void add_pet(St* s, int kind, double next, double end, double start) {
  if (s->np >= MAXPET) { if (!s->status) s->status = 5; return; }
  int i = s->np++;
  s->pk[i] = kind; s->pnext[i] = next; s->pend[i] = end; s->pstart[i] = start;
}

void add_pending(St* s, double t, int kind, int index) {
  if (s->nd >= MAXPEND) { if (!s->status) s->status = 5; return; }
  int i = s->nd++;
  s->dt[i] = t; s->dk[i] = kind; s->di[i] = index;
}

/* hunter.simulate(build, targets, spec).dps */
double fight(const Row* r, int* status_out) {
  St s;
  if (r->targets > MAXT) { *status_out = 3; return 0.0; }
  s.nord = 0; s.seen = 0u; s.status = 0; s.targets = r->targets;
  for (int t = 0; t < MAXT; t++) { s.stung[t].n = 0; s.wound[t].n = 0; }
  s.lock.n = 0; s.hprow.n = 0; s.pprow.n = 0;
  for (int k = 0; k < 4; k++) {
    int sv = k >> 1, wv = k & 1;
    double ah = 15.0 - r->armor_pen - (double)sv * 4.0 - (double)wv * 3.0;
    double ap = 15.0 - 0.0 - (double)sv * 4.0 - (double)wv * 3.0;
    s.thneg[k] = 0;
    if (ah > 0.0) s.th[k] = 1.0 - (ah * 0.04) / (1.0 + 0.04 * ah);
    else if (ah == 0.0) s.th[k] = 1.0;
    else if (ah == (double)(long)ah && -ah <= (double)NNEG) s.th[k] = r->negt[(int)(-ah) - 1];
    else { s.th[k] = 1.0; s.thneg[k] = 1; }
    s.tp[k] = (ap > 0.0) ? 1.0 - (ap * 0.04) / (1.0 + 0.04 * ap) : 1.0;
  }
  s.np = 0; s.nd = 0;
  for (int k = 0; k < 5; k++) s.nxt[k] = 0.0;
  s.mana = r->mana_max; s.mana_time = 0.0;
  s.wrath_until = -1.0; s.quill_until = -1.0; s.quiver = 0.0; s.split = 0.0;
  s.quill_count = 0; s.howl_stacks = 0; s.armed = 0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  double next_attack = 0.0, next_tick = 1.0, busy = 0.0;
  int guard = 0;
  while (1) {
    guard += 1;
    if (guard > 400000) break;
    if (s.status) break;
    double attack_at = (next_attack >= busy) ? next_attack : busy;
    double cast_at = FIGHT * 10.0;
    int choice = -1;
    for (int key = 0; key < 5; key++) {
      double ready = (s.nxt[key] >= busy) ? s.nxt[key] : busy;
      if (ready < cast_at - 1e-9) { cast_at = ready; choice = key; }
    }
    double pet_at = FIGHT * 10.0;
    for (int i = 0; i < s.np; i++)
      if (s.pnext[i] < s.pend[i] && s.pnext[i] < pet_at) pet_at = s.pnext[i];
    double pending_at = FIGHT * 10.0;
    for (int i = 0; i < s.nd; i++) if (s.dt[i] < pending_at) pending_at = s.dt[i];
    double moment = attack_at;
    if (cast_at < moment) moment = cast_at;
    if (pet_at < moment) moment = pet_at;
    if (pending_at < moment) moment = pending_at;
    if (next_tick < moment) moment = next_tick;
    if (moment >= FIGHT) break;
    if (moment == pending_at) {
      int b = -1;
      for (int i = 0; i < s.nd; i++) {
        if (b < 0 || s.dt[i] < s.dt[b] || (s.dt[i] == s.dt[b] && (s.dk[i] < s.dk[b]
            || (s.dk[i] == s.dk[b] && s.di[i] < s.di[b])))) b = i;
      }
      int kind = s.dk[b], index = s.di[b];
      for (int i = b; i < s.nd - 1; i++) { s.dt[i] = s.dt[i + 1]; s.dk[i] = s.dk[i + 1]; s.di[i] = s.di[i + 1]; }
      s.nd--;
      if (kind == PD_TRAP) trap(r, &s, index, moment, 1.0);
      else multishot(r, &s, moment, 1);
      continue;
    }
    if (moment == next_tick) {
      double raw = 5.0 * RANKF + 0.10 * dcs(r, &s, moment);
      for (int index = 0; index < s.targets; index++) {
        double on = wmass(&s.stung[index], moment);
        if (on <= 0.0) continue;
        if (SP_BM) pet_hit(r, &s, N_TICKS, raw, moment, CUR_PET, index, 0, on);
        else hit(r, &s, N_TICKS, raw, moment, index, 0.0, 1, 1.0, on, 0);
        if (SP_SV) cut_cooldowns(&s, moment, 0.0, on * chance01((5.0 + 0.20 * r->mastery) / 100.0));
      }
      double interval = 1.0;
      if (TM(r, T_POISON)) interval /= 1.0 + 0.05 * r->potency;
      next_tick = moment + interval;
      continue;
    }
    if (moment == pet_at) {
      for (int i = 0; i < s.np; i++) {
        if (s.pnext[i] == moment && s.pnext[i] < s.pend[i]) {
          pet_attack(r, &s, i, moment);
          s.pnext[i] = moment + pet_interval(r, &s, i, moment);
        }
      }
      int w = 0;
      for (int i = 0; i < s.np; i++) {
        if (s.pnext[i] < s.pend[i]) {
          s.pk[w] = s.pk[i]; s.pnext[w] = s.pnext[i]; s.pend[w] = s.pend[i]; s.pstart[w] = s.pstart[i]; w++;
        }
      }
      s.np = w;
      continue;
    }
    if (cast_at <= attack_at && choice >= 0 && moment == cast_at) {
      int key = choice;
      double cost = (key == K_CALL) ? 30.0 : (key == K_WRATH) ? 20.0 : (key == K_STING) ? 15.0 : (key == K_MULTI) ? 10.0 : 20.0;
      if (!pay(r, &s, cost, moment)) { s.nxt[key] = moment + 0.25; continue; }
      double hit_at = moment + CAST_POINT;
      if ((r->mask & S_SULF) && !s.armed) s.armed = 1;
      if (TM(r, T_WIND)) s.quiver = 1.0;
      busy = moment + CAST_TIME + r->cast_lock;
      if (key == K_CALL) {
        int w = 0;
        for (int i = 0; i < s.np; i++) {
          if (s.pk[i] != CUR_PET) {
            s.pk[w] = s.pk[i]; s.pnext[w] = s.pnext[i]; s.pend[w] = s.pend[i]; s.pstart[w] = s.pstart[i]; w++;
          }
        }
        s.np = w;
        add_pet(&s, CUR_PET, hit_at, FIGHT * 10.0, hit_at);
        if (TM(r, T_UNLEASH)) {
          for (int kind = 0; kind < 3; kind++) {
            if (kind != CUR_PET) {
              double end = hit_at + 6.0 + 0.10 * r->intel;
              add_pet(&s, kind, hit_at, end, hit_at);
            }
          }
        }
        s.nxt[key] = moment + cooldown(r, 30.0, 0.0);
      } else if (key == K_WRATH) {
        s.wrath_until = hit_at + 8.0;
        howl(r, &s);
        double flat = TM(r, T_WILDP) ? 3.0 : 0.0;
        s.nxt[key] = moment + cooldown(r, 15.0, flat);
      } else if (key == K_STING) {
        double raw = 85.0 * RANKF + 0.85 * dcs(r, &s, hit_at) + 0.40 * r->agi;
        hit(r, &s, N_STING, raw, hit_at, 0, 0.0, 1, 1.0, 1.0, 0);
        wsure(&s.stung[0], hit_at, 10.0);
        if (r->mask & S_TGLOV) add_pending(&s, hit_at + 0.5, PD_TRAP, 0);
        howl(r, &s);
        double flat = (TM(r, T_KILLER) && wrath_on(&s, moment)) ? 1.5 : 0.0;
        s.nxt[key] = moment + cooldown(r, 8.0, flat);
      } else if (key == K_MULTI) {
        multishot(r, &s, hit_at, 0);
        if (SP_SV) add_pending(&s, hit_at + 0.5, PD_MULTI2, 0);
        howl(r, &s);
        double flat = (TM(r, T_KILLER) && wrath_on(&s, moment)) ? 1.5 : 0.0;
        s.nxt[key] = moment + cooldown(r, 7.0, flat);
      } else {
        add_pending(&s, hit_at + 0.5, PD_TRAP, 0);
        howl(r, &s);
        s.nxt[key] = moment + cooldown(r, 7.0, 0.0);
      }
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    /* hunter auto-attack */
    moment = attack_at;
    recover(r, &s, moment);
    double power = dcs(r, &s, moment);
    double raw = power;
    if (wrath_on(&s, moment)) {
      double white = WHITE_BASE + 0.75 * r->agi;
      raw = white * (1.0 + wrath_pct(r)) + r->damage;
    }
    double share = hit(r, &s, N_AUTO, raw, moment, 0, 1.0, 1, r->attack_potency, 1.0, 1);
    if (SP_MM) hit(r, &s, N_MARKS, 40.0 + 3.0 * r->mastery, moment, 0, 0.0, 0, 0.0, share, 0);
    double luck_mult = 1.0 + r->luck;
    if (TM(r, T_LOCK)) wmaybe(&s.lock, moment, 4.0, chance01(share * 0.35 * luck_mult));
    wmaybe(&s.pprow, moment, 3.0, share);
    if (s.split > 0.0) hit(r, &s, N_SPLIT, (0.45 + 0.05 * RANKF) * power, moment, 0, 1.0, 1, 1.0, s.split, 0);
    s.split = chance01(0.30 * (1.0 + 0.5 * share) * luck_mult);
    {
      double gain = r->attack_mana + r->attack_mana_pct * r->mana_max;
      if (r->attack_mana_crit != 0.0) gain *= 1.0 + ((100.0 <= r->crit) ? 100.0 : r->crit) / 100.0;
      gain_mana(r, &s, gain);
    }
    if (r->mask & S_ORB) {
      int idx = (1 < s.targets - 1) ? 1 : s.targets - 1;
      double splash_w = (20.0 + 0.35 * r->agi) * (double)s.targets * taken_for(&s, idx, moment, 1);
      if (splash_w != 0.0) emit(r, &s, N_FIRE, moment, splash_w, KD_EXEC);
      note_damage_mana(r, &s, (double)s.targets);
    }
    if (r->mask & S_SULF) {
      double taken = taken_for(&s, 0, moment, 1);
      if (s.armed) {
        s.armed = 0;
        double splash_w = r->agi * taken * (double)s.targets;
        if (splash_w != 0.0) emit(r, &s, N_SULF, moment, splash_w, KD_MAG);
        note_damage_mana(r, &s, (double)s.targets);
      }
      double echo_w = power * taken * (0.10 * (1.0 + r->luck));
      if (echo_w != 0.0) emit(r, &s, N_ECHO, moment, echo_w, KD_EXEC);
    }
    ap_attack(&s.ap, moment, hero_crit(r, &s, moment));
    next_attack = moment + hunter_interval(r, &s, moment);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < s.nord; i++) total += s.src[s.ord[i]];
  return total / FIGHT;
}

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  __global const double* pal; __global const double* base; __global const double* negt;
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

/* hunter.stats_of(build) */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double strength = T->base[1], agility = T->base[2], intel = T->base[0];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 0.0;
  double crit = (double)pts[6];
  double rating = 0.0, haste = 0.0, aspd = 0.0, magic_add = 0.0, phys_add = 0.0, mana_flat = 0.0, health_flat = 0.0;
  double armor_pen = 0.0, auto_pct = 1.0, attack_potency = 1.0, pet_damage = 0.0;
  double luck = 0.01 * (double)pts[9];
  haste += 0.01 * (double)pts[3];
  aspd += 0.02 * (double)pts[4];
  damage += 2.0 * (double)pts[5];
  mana_flat += 20.0 * (double)pts[1];
  pet_damage += 0.015 * (double)pts[10];
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
      for (int j = 0; j < 4; j++) pet_damage += a[13 + j];
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
  double summon_crit = 0.0, summon_rating = 0.0;
  if (GM(r, G_BEAST) || (mask & S_BEASTI)) summon_crit += 25.0;
  if (mask & S_MOTW) summon_crit += 7.0;
  if (mask & S_THORN) summon_rating += 0.20;
  r->str = strength; r->agi = agility; r->intel = intel; r->potency = potency; r->mastery = mastery; r->damage = damage;
  r->crit = crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->magic_add = magic_add; r->phys_add = phys_add; r->armor_pen = armor_pen;
  r->auto_pct = auto_pct; r->attack_potency = attack_potency;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock; r->pet_damage = pet_damage; r->summon_crit = summon_crit; r->summon_rating = summon_rating;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->nexec = nexec; r->targets = targets;
  r->glass = (GM(r, G_GLASS) || (mask & S_GLAS)) ? 1 : 0;
  r->negt = T->negt;
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
    __global const double* pal, __global const double* base, __global const double* negt

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.pal = pal; T.base = base; T.negt = negt;

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
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "I0JA": 4, "I096": 5, "I03C": 6, "I00L": 7, "I00Y": 8,
    "I07P": 9, "I048": 10, "I0FW": 11, "I0AV": 12, "I0QN": 13, "I0T6": 14, "I0T7": 15, "I0T8": 16, "I0T9": 17,
    "I06B": 18, "I05W": 19, "I0OH": 20,
}
TALENT_BITS = {
    "I03P": 0, "I0K8": 1, "I092": 2, "I02X": 3, "I0KD": 4, "I0T3": 5, "I0K9": 6, "I0KB": 7, "I0KC": 8,
    "I0K6": 9, "I03M": 10, "I03H": 11, "I02D": 12, "I0KA": 13, "I0O3": 14, "I0K7": 15, "I0T4": 16, "I0T5": 17,
    # talent pages: UI only
    "I0MD": 24, "I0MC": 25,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8,
              "I0OH": 9}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"marksmanship": 0, "beast_mastery": 1, "survival": 2}


def hunter_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the agility primary fold and the Hunter per-piece columns."""
    import re

    from sunken_sim import hunter as H, pressure, shadow
    from sunken_sim.stacking import stack_fields

    if (H.WHITE_BASE, H.SWING, H.BASE_MANA, H.BASE_HP, H.RANK, H.STING_CD, H.STING_MANA, H.MULTI_CD, H.MULTI_MANA,
            H.WRATH_CD, H.WRATH_MANA, H.WRATH_DUR, H.TRAP_CD, H.TRAP_MANA, H.TRAP_DELAY, H.CALL_CD, H.CALL_MANA,
            H.STING_DUR, H.WOUND_DUR, H.WOUND_ARMOR, H.STING_PEN, H.ASPECT, H.PROWESS_DUR, H.LOCK_DUR, H.QUILL_DUR,
            H.MULTI_SECONDARY_DELAY, H.WINDOW_SLOTS, H.PETS, H.SPEC_PET, shadow.LEVEL) != \
            (30.0, 1.60, 120.0, 230.0, 1, 8.0, 15.0, 7.0, 10.0, 15.0, 20.0, 8.0, 7.0, 20.0, 0.5, 30.0, 30.0, 10.0,
             5.0, 3.0, 4.0, 0.10, 3.0, 4.0, 5.0, 0.5, 8,
             {"spike": (9, 0.50, 1.50, "Spike"), "huffer": (4, 0.30, 1.45, "Huffer"), "grylls": (17, 0.90, 1.70, "Grylls")},
             {"marksmanship": "huffer", "beast_mastery": "spike", "survival": "grylls"}, 15):
        raise ValueError("kernel constants assume the 2026-11-14 hunter")
    if (shadow.CAST_POINT, shadow.CAST_BACKSWING, pressure.STR_HP) != (0.15, 0.30, 15.0):
        raise ValueError("kernel constants assume cast 0.15 + 0.30 and 15 health per strength")
    AP.check()
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(H.BASE_INT), float(H.BASE_STR), float(H.BASE_AGI), float(H.BASE_HP)], "Hunter")
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
        pets = [int(raw) / 100.0 for raw in re.findall(r"\+(\d+)% Pet Damage\b", item.tip)]
        pal[i] = [
            shadow.MAGICAL_ADDS.get(code, 0.0),
            shadow.PHYSICAL_ADDS.get(code, 0.0),
            item.source_pct / 100.0,
            item.damage_pct / 100.0 - item.source_pct / 100.0,
            1.0 if (code in shadow.MAGICAL_ADDS or code in shadow.PHYSICAL_ADDS) else 0.0,
            *C.pad(lucks, 0.0, "luck", code),
            *C.pad(health, 0.0, "health", code),
            *C.pad(pets, 0.0, "pet damage", code),
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    # negative armour (high armour penetration under Sting and the trap wound): the Python value itself
    t["negt"] = np.asarray([shadow.armor_taken(float(-k)) for k in range(1, NNEG + 1)], dtype=np.float64)
    return t


class HunterCL(C.ExactCL):
    hero = "hunter"
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ()  # hunter._timeline_key holds every ESC point
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "pal", "base", "negt")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32}

    @staticmethod
    def module():
        from sunken_sim import hunter

        return hunter

    def tables(self, space, items, sources):
        return hunter_tables(space, items, sources)

    def timeline_key(self, build):
        from sunken_sim import hunter

        return hunter._timeline_key(build, hunter.stats_of(build), self.spec, self.targets)


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
