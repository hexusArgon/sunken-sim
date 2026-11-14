"""Exact float64 OpenCL kernel for Necromancer fights (Bone, Blood, Essence).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.necromancer.stats_of`` (intellect primary, Pet Damage, summon crit, Final Service
health) and run every policy of ``necromancer.simulate`` (Transfusion on / off x Raise Dead on /
off; Essence only with Raise Dead), keeping the best, with Ledger sums in insertion order.
Skeletons are a list in spawn order (the weighted Skeletal Archer carries its weight), the
event queue pops the smallest (time, seq). The Python closures that call each other
(hit -> Corpse Explosion passive -> hit) are split into a no-passive copy used inside an
explosion, where ``guard_ce`` makes the passive a no-op; Serration is a loop of three levels.
Battle Frenzy / Silent Messenger: farm.hybrid.attack_procs_cl.

``necromancer.simulate`` has no timeline cache, so every row is its own fight.
Rows the kernel cannot score (more than MAXT targets, negative armour, queue or skeleton
overflow) return a non-zero status and are re-scored by the Python oracle.
Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 14

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 bone, 1 blood, 2 essence */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_BONE (SPEC == 0)
#define SP_BLOOD (SPEC == 1)
#define SP_ESS (SPEC == 2)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 14
#define NSRC 19
#define MAXT 8
#define MAXQ 16
#define MAXS 64
#define MAXB 8
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
#define S_SILM (1UL<<14)
#define S_BFURY (1UL<<15)
#define S_MOTW (1UL<<16)
#define S_THORN (1UL<<17)
#define S_TOMBX (1UL<<18)
#define S_GLOBX (1UL<<19)
#define S_SCYP (1UL<<20)
#define S_CECD (1UL<<21)
#define S_CETK (1UL<<22)

#define T_BBOMB (1u<<0)
#define T_SWIFT (1u<<1)
#define T_SANG (1u<<2)
#define T_GRAVE (1u<<3)
#define T_ARCHER (1u<<4)
#define T_EFB (1u<<5)
#define T_SERR (1u<<6)
#define T_REAPER (1u<<7)
#define T_EXSW (1u<<8)
#define T_BREAP (1u<<9)
#define T_HOUR (1u<<10)
#define T_LFD (1u<<11)
#define T_BSAC (1u<<12)
#define T_CALL (1u<<13)
#define T_DARK (1u<<14)
#define T_BLOODY (1u<<15)
#define T_LORD (1u<<16)

#define G_UNSL (1u<<0)
#define G_GLASS (1u<<1)
#define G_FORT (1u<<2)
#define G_SUPR (1u<<3)
#define G_ANIM (1u<<4)
#define G_MIND (1u<<5)
#define G_FORTUNE (1u<<6)
#define G_FREN (1u<<7)
#define G_REPL (1u<<8)
#define G_BFURY (1u<<9)

#define TM(r, x) (TALENTS && ((r)->tmask & (x)))
#define GM(r, x) (TALENTS && ((r)->gmask & (x)))

/* Ledger: only Автоатака is seeded; every other source in order of first write */
#define N_AUTO 0
#define N_CEP 1
#define N_GSP 2
#define N_GS 3
#define N_BLOODY 4
#define N_CE 5
#define N_TOMB 6
#define N_SKEL 7
#define N_ARCH 8
#define N_ASSA 9
#define N_EXEC 10
#define N_MAGE 11
#define N_ECHOX 12
#define N_SERR 13
#define N_BBOMB 14
#define N_TEETH 15
#define N_FIRE 16
#define N_SULF 17
#define N_ECHO 18

/* skeleton kinds */
#define U_WARRIOR 0
#define U_ARCHER 1
#define U_ASSASSIN 2
#define U_EXECUTOR 3
#define U_MAGE 4

/* events */
#define E_RD 0
#define E_GS 1
#define E_CE 2

/* keys */
#define K_GS 0
#define K_CE 1
#define K_TOMB 2
#define K_TRANS 3
#define K_TEETH 4

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, armor_pen, spell_mult, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, hp, pet_damage, summon_crit, summon_rating;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  int nexec, targets, glass, spell_crit;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double q_w[MAXQ]; uint q_s[MAXQ]; uchar q_k[MAXQ]; int qn; uint seq;
  double k_next[MAXS], k_end[MAXS], k_pen[MAXS], k_spec[MAXS], k_w[MAXS]; uchar k_kind[MAXS]; int kn;
  double tombs[MAXB]; int tn;
  double nxt[5], full_cd[5];
  double mana, mana_time, hp, last_gs, swift_until, globe_until, tomb_timer;
  double hero_taken, summon_taken, pen_taken, intel_i, mastery_i;
  int teeth_lvl, rd_ticks, guard_ce, armed, status, targets, use_raise;
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
  if (armor < 0.0) { if (!s->status) s->status = 4; return 1.0; }
  return 1.0;
}

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

int pay(const Row* r, St* s, double cost, double now, int refund) {
  recover(r, s, now);
  if (s->mana < cost) return 0;
  s->mana -= cost;
  if (refund) gain_mana(r, s, cost * r->cast_refund + r->cast_refund_flat + r->cast_refund_mastery * r->mastery);
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

void lose_hp(St* s, double amount) {
  double v = s->hp - amount;
  s->hp = (v > 1.0) ? v : 1.0;
}

void heal(const Row* r, St* s, double amount) {
  double v = s->hp + amount;
  s->hp = (v < r->hp) ? v : r->hp;
}

void push(St* s, double when, int kind) {
  s->seq += 1u;
  if (s->qn >= MAXQ) { if (!s->status) s->status = 5; return; }
  int i = s->qn++;
  s->q_w[i] = when; s->q_s[i] = s->seq; s->q_k[i] = (uchar)kind;
}

double typed(const Row* r, int magical, double now) {
  double bonus = 1.0 + (magical ? r->magic_add : r->phys_add);
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(now);
  if (magical && (r->mask & S_TLUM)) bonus += 0.05 + 0.005 * r->mastery;
  if (r->glass) bonus *= 1.15;
  return bonus;
}

/* Blood Sacrifice I057: +0.5% max HP per instance (x1.25 magical) while HP > 25% */
double sacrifice(const Row* r, St* s, int magical, double count) {
  if (!TM(r, T_BSAC) || s->hp <= 0.25 * r->hp) return 0.0;
  lose_hp(s, 0.005 * r->hp * count);
  return 0.005 * r->hp * (magical ? 1.25 : 1.0);
}

double dcs(const Row* r, const St* s) { return 14.0 + 0.75 * s->intel_i + r->damage; }

double explosion_raw(const Row* r, const St* s) {
  double value = 20.0 * RANK + 0.35 * s->intel_i + 0.01 * r->hp;
  if (SP_BLOOD) value *= 1.10 + 0.005 * s->mastery_i;
  return value;
}

/* hero_hit without the Corpse Explosion passive (the caller adds it, or is inside an explosion) */
double hero_core(const Row* r, St* s, int name, double raw, double now, int magical, int attack, double count,
                 double potency_scale) {
  double amount = raw + r->potency * potency_scale;
  amount += sacrifice(r, s, magical, count);
  amount *= typed(r, magical, now);
  if (TM(r, T_BREAP)) amount *= 0.88;
  if (attack) amount *= crit_factor(r->crit, 2.0 + r->rating);
  else if (r->spell_crit) amount *= crit_factor(r->crit, r->spell_mult + r->rating);
  double ex = exec_factor(r, now);
  double dealt = amount * s->hero_taken * ex;
  add_src(s, name, dealt * count);
  note_damage_mana(r, s, count);
  return dealt;
}

/* one summon_hit level without the passive and without Serration */
double summon_core(const Row* r, St* s, int name, double raw, double now, int magical, int attack, double count,
                   double crit_bonus, double pen_share) {
  double amount = raw + r->potency + sacrifice(r, s, magical, count);
  amount *= 1.0 + r->pet_damage;
  if (attack) amount *= crit_factor(r->summon_crit + crit_bonus, 2.0 + r->summon_rating);
  double taken = pen_share * s->pen_taken + (1.0 - pen_share) * s->summon_taken;
  double dealt = amount * taken * exec_factor(r, now);
  add_src(s, name, dealt * count);
  return dealt;
}

/* summon_hit inside an explosion (guard_ce: no passive), Serration levels 1..3 */
double summon_nce(const Row* r, St* s, int name, double raw, double now, int magical, int attack, double count,
                  double crit_bonus, double pen_share) {
  double dealt = summon_core(r, s, name, raw, now, magical, attack, count, crit_bonus, pen_share);
  if (TM(r, T_SERR)) {
    double c = count;
    for (int depth = 0; depth < 3; depth++) {
      c = chance01(0.05 * (1.0 + r->luck)) * c;
      summon_core(r, s, N_SERR, 15.0 * RANK + 0.75 * dcs(r, s), now, 0, 0, c, 0.0, 0.0);
    }
  }
  return dealt;
}

/* One Corpse Explosion passive (AoE, magical) by the Necromancer (summon = 0) or a summon */
void explode(const Row* r, St* s, double now, int summon, double weight, int name) {
  if (weight <= 0.0) return;
  int was = s->guard_ce;
  s->guard_ce = 1;
  if (!summon) hero_core(r, s, name, explosion_raw(r, s), now, 1, 0, (double)s->targets * weight, 1.0);
  else summon_nce(r, s, name, explosion_raw(r, s), now, 1, 0, (double)s->targets * weight, 0.0, 0.0);
  s->guard_ce = was;
}

/* Corpse Explosion passive: 1.5% (3% Blood) x luck per owner damage instance */
void ce_proc(const Row* r, St* s, double count, double now) {
  if (s->guard_ce || count <= 0.0) return;
  double chance = chance01((SP_BLOOD ? 3.0 : 1.5) / 100.0 * (1.0 + r->luck));
  explode(r, s, now, 0, chance * count, N_CEP);
}

double hero_hit(const Row* r, St* s, int name, double raw, double now, int magical, int attack, double count,
                double potency_scale) {
  double dealt = hero_core(r, s, name, raw, now, magical, attack, count, potency_scale);
  ce_proc(r, s, count, now);
  return dealt;
}

double summon_hit(const Row* r, St* s, int name, double raw, double now, int magical, int attack, double count,
                  double crit_bonus, double pen_share) {
  double dealt = summon_core(r, s, name, raw, now, magical, attack, count, crit_bonus, pen_share);
  ce_proc(r, s, count, now);
  if (TM(r, T_SERR)) {
    double c = count;
    for (int depth = 0; depth < 3; depth++) {
      c = chance01(0.05 * (1.0 + r->luck)) * c;
      summon_core(r, s, N_SERR, 15.0 * RANK + 0.75 * dcs(r, s), now, 0, 0, c, 0.0, 0.0);
      ce_proc(r, s, c, now);
    }
  }
  return dealt;
}

/* Grim Scythe passive on Necromancer attack damage (magical, per target) */
void gs_passive(const Row* r, St* s, double count, double now) {
  double raw = 10.0 + 10.0 * RANK + 0.55 * s->intel_i;
  recover(r, s, now);
  if (TM(r, T_REAPER) && s->mana > 0.20 * r->mana_max) {
    raw += 0.02 * r->mana_max;
    double v = s->mana - 0.002 * r->mana_max * count;
    s->mana = (v > 0.0) ? v : 0.0;
  }
  if (SP_ESS) raw *= 1.10 + 0.01 * s->mastery_i;
  if (TM(r, T_EXSW)) raw *= 1.10;
  s->last_gs = raw;
  hero_hit(r, s, N_GSP, raw, now, 1, 0, count, 1.0);
}

double skeleton_raw(const Row* r, const St* s) {
  return 6.0 + (double)(int)(4.0 * RANK + 0.20 * dcs(r, s));
}

void add_skeleton(St* s, int kind, double now, double life, double pen, double w) {
  if (s->kn >= MAXS) { if (!s->status) s->status = 6; return; }
  int i = s->kn++;
  s->k_kind[i] = (uchar)kind; s->k_next[i] = now; s->k_end[i] = now + life; s->k_pen[i] = pen; s->k_spec[i] = -1.0;
  s->k_w[i] = w;
}

void spawn(const Row* r, St* s, int kind, double now) {
  double life = 11.0 + (TM(r, T_HOUR) ? 3.0 : 0.0);
  double pen = SP_BONE ? chance01((5.0 + s->mastery_i) / 100.0) : 0.0;
  add_skeleton(s, kind, now, life, pen, 1.0);
  if (TM(r, T_ARCHER)) {
    double weight = chance01(0.25 * (1.0 + r->luck));
    if (weight > 0.0) add_skeleton(s, U_ARCHER, now, life, pen, weight);
  }
}

void remove_skeleton(St* s, int i) {
  for (int j = i + 1; j < s->kn; j++) {
    s->k_kind[j - 1] = s->k_kind[j]; s->k_next[j - 1] = s->k_next[j]; s->k_end[j - 1] = s->k_end[j];
    s->k_pen[j - 1] = s->k_pen[j]; s->k_spec[j - 1] = s->k_spec[j]; s->k_w[j - 1] = s->k_w[j];
  }
  s->kn--;
}

double attack_interval(const Row* r, const St* s, double now) {
  double swing = 1.85 * ((r->mask & S_GALA) ? 1.20 : 1.0);
  double speed = r->aspd + 0.08 * (double)(s->teeth_lvl - 1) + ap_bonus(&s->ap, now);
  if (now < s->swift_until) speed += 0.30;
  if (TM(r, T_SANG) && now < s->globe_until) speed += 0.23;
  speed = ap_speed(speed);
  return swing / (1.0 + speed);
}

double tomb_first(int count) { return (1.80 - 0.20 * RANK) / (1.0 + ((count > 1) ? 0.35 : 0.0)); }

double tomb_period(const Row* r, int count) {
  double rate = 1.0 + ((count > 1) ? 0.5 : 0.0);
  if (TM(r, T_CALL)) rate += 0.35 + 0.05 * r->potency;
  return 1.5 / rate;
}

double cooldown_of(double base, double haste, const Row* r, double flat) {
  double v = (base * r->cd_temp - r->flat_cdr - flat) / (1.0 + haste);
  return (v > 0.5) ? v : 0.5;
}

double max3(double a, double b, double c) {
  double m = (b > a) ? b : a;
  return (c > m) ? c : m;
}

/* necromancer._simulate(build, targets, spec, policy) -> dps */
double sim_policy(const Row* r, int use_trans, int use_raise, int* status_out) {
  St s;
  if (r->targets > MAXT) { *status_out = 3; return 0.0; }
  s.targets = r->targets; s.status = 0; s.armed = 0;
  s.use_raise = use_raise && !SP_ESS;
  s.nord = 1; s.seen = 1u; s.ord[0] = N_AUTO; s.src[N_AUTO] = 0.0;
  s.intel_i = (double)(int)r->intel;
  s.mastery_i = (double)(int)r->mastery;
  s.hero_taken = armor_mult(&s, 15.0 - r->armor_pen);
  s.summon_taken = armor_mult(&s, 15.0);
  s.pen_taken = armor_mult(&s, 15.0 - 8.0);
  if (s.status) { *status_out = s.status; return 0.0; }
  s.mana = r->mana_max; s.mana_time = 0.0; s.hp = r->hp;
  s.last_gs = 0.0; s.swift_until = -1.0; s.globe_until = -1.0; s.teeth_lvl = 1; s.rd_ticks = 0; s.guard_ce = 0;
  s.qn = 0; s.seq = 0u; s.kn = 0; s.tn = 0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  double cast_time = CAST_POINT + CAST_BACKSWING;
  /* order = ["tomb", "ce", "gs"] + ["teeth"] if essence + ["trans"] if use_trans */
  int order[5];
  int norder = 0;
  order[norder++] = K_TOMB; order[norder++] = K_CE; order[norder++] = K_GS;
  if (SP_ESS) order[norder++] = K_TEETH;
  if (use_trans) order[norder++] = K_TRANS;
  for (int k = 0; k < 5; k++) { s.nxt[k] = 0.0; s.full_cd[k] = 0.0; }
  s.tomb_timer = FAR;
  if (s.use_raise) push(&s, 1.0 / (1.0 + r->haste), E_RD);
  double next_attack = 0.0, busy = 0.0, clock = 0.0;
  int loops = 0;
  while (1) {
    loops += 1;
    if (loops > 400000) break;
    if (s.status) break;
    double attack_at = max3(next_attack, busy, clock);
    double cast_at = FAR;
    int choice = -1;
    for (int o = 0; o < norder; o++) {
      int key = order[o];
      double ready = max3(s.nxt[key], busy, clock);
      if (ready < cast_at - 1e-9) { cast_at = ready; choice = key; }
    }
    double pending_at = FAR;
    for (int i = 0; i < s.qn; i++) if (s.q_w[i] < pending_at) pending_at = s.q_w[i];
    {
      int w = 0;
      for (int i = 0; i < s.kn; i++) {
        if (s.k_end[i] > clock - 1e-9) {
          if (w != i) {
            s.k_kind[w] = s.k_kind[i]; s.k_next[w] = s.k_next[i]; s.k_end[w] = s.k_end[i];
            s.k_pen[w] = s.k_pen[i]; s.k_spec[w] = s.k_spec[i]; s.k_w[w] = s.k_w[i];
          }
          w++;
        }
      }
      s.kn = w;
    }
    double summon_at = FAR;
    int sk = -1;
    for (int i = 0; i < s.kn; i++)
      if (s.k_next[i] < s.k_end[i] && s.k_next[i] < summon_at) { summon_at = s.k_next[i]; sk = i; }
    double moment = attack_at;
    if (cast_at < moment) moment = cast_at;
    if (pending_at < moment) moment = pending_at;
    if (summon_at < moment) moment = summon_at;
    if (s.tomb_timer < moment) moment = s.tomb_timer;
    if (moment >= FIGHT) break;
    clock = moment;
    if (moment == pending_at) {
      int b = 0;
      for (int i = 1; i < s.qn; i++)
        if (s.q_w[i] < s.q_w[b] || (s.q_w[i] == s.q_w[b] && s.q_s[i] < s.q_s[b])) b = i;
      int kind = s.q_k[b];
      s.qn--;
      s.q_w[b] = s.q_w[s.qn]; s.q_s[b] = s.q_s[s.qn]; s.q_k[b] = s.q_k[s.qn];
      if (kind == E_RD) {
        recover(r, &s, moment);
        if (s.mana >= 2.0 + 1.5 * RANK && pay(r, &s, 2.0 + 1.5 * RANK, moment, 0)) s.rd_ticks += 1;
        int need = SP_BONE ? 4 : 6;
        while (s.rd_ticks >= need) { s.rd_ticks -= need; spawn(r, &s, U_WARRIOR, moment); }
        push(&s, moment + 1.0 / (1.0 + r->haste), E_RD);
      } else if (kind == E_GS) {
        double raw = 60.0 * RANK - 20.0 + 1.5 * s.intel_i + 0.04 * r->hp;
        if (TM(r, T_EXSW)) raw *= 1.20;
        hero_hit(r, &s, N_GS, raw, moment, 1, 0, (double)s.targets, 1.0);
        if (r->mask & S_SCYP) gs_passive(r, &s, (double)s.targets * chance01(0.50 * (1.0 + r->luck)), moment);
        if (TM(r, T_BLOODY)) explode(r, &s, moment, 0, chance01(0.60 * (1.0 + r->luck)), N_BLOODY);
        if (TM(r, T_SWIFT)) s.swift_until = moment + 4.0;
        for (int i = 0; i < s.kn; i++) if (s.k_kind[i] != U_MAGE) s.k_spec[i] = moment + 4.0;
      } else {
        explode(r, &s, moment, 0, 1.0, N_CE);
      }
      continue;
    }
    if (moment == s.tomb_timer) {
      int w = 0;
      for (int i = 0; i < s.tn; i++) if (s.tombs[i] > moment) s.tombs[w++] = s.tombs[i];
      s.tn = w;
      if (w == 0) { s.tomb_timer = FAR; continue; }
      double raw = 8.0 * RANK + 0.01 * r->hp + 0.01 * r->mana_max;
      if (SP_BONE) summon_hit(r, &s, N_TOMB, raw, moment, 0, 0, (double)s.targets, 0.0, 0.0);
      else hero_hit(r, &s, N_TOMB, raw, moment, 0, 0, (double)s.targets, 1.0);
      s.tomb_timer = moment + tomb_period(r, w);
      continue;
    }
    if (sk >= 0 && moment == summon_at && summon_at < attack_at && summon_at < cast_at) {
      int kind = s.k_kind[sk];
      double raw = skeleton_raw(r, &s);
      if (moment < s.k_spec[sk]) raw += 0.15 * s.last_gs;
      int label = (kind == U_WARRIOR) ? N_SKEL : (kind == U_ARCHER) ? N_ARCH : (kind == U_ASSASSIN) ? N_ASSA
                  : (kind == U_EXECUTOR) ? N_EXEC : N_MAGE;
      double dealt = summon_hit(r, &s, label, raw, moment, kind == U_MAGE, 1, s.k_w[sk],
                                (kind == U_ASSASSIN) ? 50.0 : 0.0, s.k_pen[sk]);
      if (kind == U_EXECUTOR) {
        hero_hit(r, &s, N_ECHOX, 0.75 * dealt, moment, 1, 1, 1.0, 1.0);
        gs_passive(r, &s, 1.0, moment);
      }
      if (kind == U_MAGE && s.nxt[K_CE] > moment) {
        double v = s.nxt[K_CE] - 0.5;
        s.nxt[K_CE] = (v > moment) ? v : moment;
      }
      double swing = (kind == U_ASSASSIN) ? 1.53 : (kind == U_ARCHER) ? 1.2 : 1.8;
      s.k_next[sk] = moment + swing;
      continue;
    }
    if (cast_at <= attack_at && choice >= 0 && moment == cast_at) {
      int key = choice;
      double cost = (key == K_GS || key == K_TEETH) ? 20.0 : 25.0;
      if (!pay(r, &s, cost, moment, 1)) { s.nxt[key] = moment + 0.25; continue; }
      double hit_at = moment + CAST_POINT;
      busy = moment + cast_time + r->cast_lock;
      if (r->mask & S_SULF) { if (!s.armed) s.armed = 1; }
      double haste = r->haste;
      if (TM(r, T_DARK)) haste += 0.05 + 0.01 * ((100.0 - 100.0 * s.hp / r->hp) / 2.0);
      if (key == K_GS) {
        push(&s, hit_at + 0.20, E_GS);
      } else if (key == K_CE) {
        lose_hp(&s, 0.08 * s.hp);
        int ticks = 3 + (SP_BLOOD ? 1 : 0) + ((r->mask & S_CETK) ? 1 : 0);
        for (int i = 0; i < ticks; i++) push(&s, hit_at + (double)(i + 1) * 1.2 / (double)ticks, E_CE);
        if (TM(r, T_BBOMB)) {
          /* group = sorted(group skeletons, key=end) (stable); consume weight 3 */
          int idx[MAXS];
          int ng = 0;
          for (int i = 0; i < s.kn; i++) {
            if (s.k_kind[i] == U_MAGE) continue;
            int j = ng++;
            while (j > 0 && s.k_end[idx[j - 1]] > s.k_end[i]) { idx[j] = idx[j - 1]; j--; }
            idx[j] = i;
          }
          double need = 3.0;
          uchar gone[MAXS];
          for (int i = 0; i < s.kn; i++) gone[i] = 0;
          for (int g = 0; g < ng; g++) {
            if (need <= 1e-12) break;
            int i = idx[g];
            double take = (s.k_w[i] < need) ? s.k_w[i] : need;
            need -= take;
            s.k_w[i] -= take;
            if (s.k_w[i] <= 1e-12) gone[i] = 1;
            explode(r, &s, hit_at, 1, take, N_BBOMB);
          }
          int w = 0;
          for (int i = 0; i < s.kn; i++) {
            if (gone[i]) continue;
            if (w != i) {
              s.k_kind[w] = s.k_kind[i]; s.k_next[w] = s.k_next[i]; s.k_end[w] = s.k_end[i];
              s.k_pen[w] = s.k_pen[i]; s.k_spec[w] = s.k_spec[i]; s.k_w[w] = s.k_w[i];
            }
            w++;
          }
          s.kn = w;
        }
      } else if (key == K_TOMB) {
        if (s.tn >= MAXB) { if (!s.status) s.status = 7; continue; }
        s.tombs[s.tn++] = hit_at + (TM(r, T_GRAVE) ? 13.0 : 10.0);
        int w = 0;
        for (int i = 0; i < s.tn; i++) if (s.tombs[i] > hit_at) s.tombs[w++] = s.tombs[i];
        s.tn = w;
        s.tomb_timer = hit_at + tomb_first(s.tn);
        int count = (TM(r, T_GRAVE) ? 3 : 2) + ((r->mask & S_TOMBX) ? 1 : 0);
        for (int c = 0; c < count; c++) spawn(r, &s, U_WARRIOR, hit_at);
        if (TM(r, T_LORD)) spawn(r, &s, SP_BONE ? U_ASSASSIN : SP_BLOOD ? U_MAGE : U_EXECUTOR, hit_at);
      } else if (key == K_TEETH) {
        lose_hp(&s, 0.08 * s.hp);
        double raw = 20.0 + 0.80 * s.intel_i + 0.05 * r->hp;
        hero_hit(r, &s, N_TEETH, raw, hit_at, 0, 1, (double)s.targets, 1.0);
        for (int t = 0; t < s.targets; t++) ap_attack(&s.ap, hit_at, r->crit);
        gs_passive(r, &s, (double)s.targets, hit_at);
        heal(r, &s, 0.04 * r->hp * (double)s.targets);
        s.teeth_lvl = (s.teeth_lvl + s.targets < 7) ? s.teeth_lvl + s.targets : 7;
      } else {
        int globes = 1 + ((r->mask & S_GLOBX) ? 1 : 0);
        for (int g = 0; g < globes; g++) {
          heal(r, &s, 0.15 * r->hp);
          s.globe_until = hit_at + 6.0;
          if (TM(r, T_EFB)) {
            gain_mana(r, &s, 0.05 * r->mana_max);
            for (int o = 0; o < norder; o++) {
              int other = order[o];
              if (s.nxt[other] > hit_at) {
                double v = s.nxt[other] - 0.06 * s.full_cd[other];
                s.nxt[other] = (v > hit_at) ? v : hit_at;
              }
            }
          }
          if (TM(r, T_LFD) && s.use_raise) s.rd_ticks += 2;
        }
      }
      double base = (key == K_GS) ? 6.0 : (key == K_CE) ? 12.0 : (key == K_TOMB) ? 13.0 : (key == K_TRANS) ? 5.0 : 6.0;
      double cd = cooldown_of(base, haste, r, (key == K_CE) ? ((r->mask & S_CECD) ? 2.0 : 0.0) : 0.0);
      s.full_cd[key] = cd;
      if (key != K_TRANS) {
        double v = moment + cd;
        s.nxt[key] = (v > s.nxt[key]) ? v : s.nxt[key];
      } else {
        s.nxt[key] = moment + cd;
      }
      next_attack = (busy > next_attack) ? busy : next_attack;
      continue;
    }
    /* Necromancer auto-attack (magic attack type) */
    moment = attack_at;
    recover(r, &s, moment);
    double power = dcs(r, &s);
    double before = s.src[N_AUTO];
    hero_hit(r, &s, N_AUTO, power, moment, 1, 1, 1.0, r->attack_potency);
    if (r->auto_pct != 1.0) s.src[N_AUTO] = before + (s.src[N_AUTO] - before) * r->auto_pct;
    gs_passive(r, &s, 1.0, moment);
    gain_mana(r, &s, attack_mana_gain(r));
    if (r->mask & S_ORB) {
      double splash = (20.0 + 0.35 * r->intel) * (double)s.targets * s.hero_taken * exec_factor(r, moment);
      add_src(&s, N_FIRE, splash);
      note_damage_mana(r, &s, (double)s.targets);
    }
    if (r->mask & S_SULF) {
      double execute = exec_factor(r, moment);
      if (s.armed) {
        s.armed = 0;
        double splash = r->intel * typed(r, 1, moment) * s.hero_taken * execute * (double)s.targets;
        if (r->spell_crit) splash *= crit_factor(r->crit, r->spell_mult + r->rating);
        add_src(&s, N_SULF, splash);
        note_damage_mana(r, &s, (double)s.targets);
      }
      double echo = power * s.hero_taken * execute * (0.10 * (1.0 + r->luck));
      add_src(&s, N_ECHO, echo);
    }
    ap_attack(&s.ap, moment, r->crit);
    next_attack = moment + attack_interval(r, &s, moment);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < s.nord; i++) total += s.src[s.ord[i]];
  return total / FIGHT;
}

/* necromancer.simulate: (Transfusion, Raise Dead) in POLICIES order, Essence without the no-Raise-Dead ones */
double fight(const Row* r, int* status_out) {
  double best = 0.0;
  int have = 0;
  for (int tr = 1; tr >= 0; tr--)
    for (int rd = 1; rd >= 0; rd--) {
      if (SP_ESS && !rd) continue;
      int st = 0;
      double d = sim_policy(r, tr, rd, &st);
      if (st) { *status_out = st; return 0.0; }
      if (!have || d > best + 1e-9) { best = d; have = 1; }
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

/* necromancer.stats_of(build) */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double strength = T->base[1], agility = T->base[2], intel = T->base[0];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 0.0;
  double crit = (double)pts[6];
  double rating = 0.0, haste = 0.0, aspd = 0.0, magic_add = 0.0, phys_add = 0.0, mana_flat = 0.0, health_flat = 0.0;
  double pet_damage = 0.0;
  double armor_pen = 0.0, auto_pct = 1.0, attack_potency = 1.0, spell_mult = 1.50;
  int spell_crit = 0;
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
    intel = intel + f[6];
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
      luck += a[5];
      for (int j = 0; j < 4; j++) if (a[6 + j] != 0.0) health_flat += a[6 + j];
      for (int j = 0; j < 4; j++) if (a[10 + j] != 0.0) pet_damage += a[10 + j];
    }
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) intel += 34.0;
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
  double mana_max = 175.0 + 7.0 * intel + mana_flat;
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
  health_flat += 375.0;  /* Final Service long-term stacks, 25 per level */
  double hp = (T->base[3] + 15.0 * strength) + health_flat;
  double summon_crit = 0.0, summon_rating = 0.0;
  if (GM(r, G_BFURY) || (mask & S_BFURY)) summon_crit += 25.0;
  if (mask & S_MOTW) summon_crit += 7.0;
  if (mask & S_THORN) summon_rating += 0.20;
  r->str = strength; r->agi = agility; r->intel = intel; r->potency = potency; r->mastery = mastery; r->damage = damage;
  r->crit = crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->magic_add = magic_add; r->phys_add = phys_add; r->armor_pen = armor_pen;
  r->spell_crit = spell_crit; r->spell_mult = spell_mult;
  r->auto_pct = auto_pct; r->attack_potency = attack_potency;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock; r->hp = hp; r->pet_damage = pet_damage;
  r->summon_crit = summon_crit; r->summon_rating = summon_rating;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
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
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I0QN": 14, "I0OH": 15, "I06B": 16, "I05W": 17,
    "I0R5": 18, "I0R6": 19, "I0R7": 20, "I0R8": 21, "I0UN": 22,
}
TALENT_BITS = {
    "I09Q": 0, "I0LC": 1, "I0L8": 2, "I0LA": 3, "I0LB": 4, "I0LD": 5, "I0L9": 6, "I0LF": 7, "I086": 8,
    "I05T": 9, "I0FI": 10, "I0LE": 11, "I057": 12, "I0OK": 13, "I0OL": 14, "I0OM": 15, "I05Z": 16,
    # necromancer.IGNORED_TALENTS and the talent pages: no effect on the fight
    "I078": 20, "I0MD": 21, "I0MC": 22,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8,
              "I0OH": 9}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"bone": 0, "blood": 1, "essence": 2}


def necromancer_tables(space, items, sources) -> dict:
    """class_cl.character_tables (intellect primary) with the Necromancer per-piece columns."""
    import re

    from sunken_sim import necromancer as N, pressure, shadow

    if (N.WHITE_BASE, N.SWING, N.BASE_MANA, N.BASE_HP, N.RANK, N.FINAL_SERVICE_STACKS, N.GS_CD, N.GS_MANA, N.CE_CD,
            N.CE_MANA, N.TOMB_CD, N.TOMB_MANA, N.TRANS_CD, N.TRANS_MANA, N.TEETH_CD, N.TEETH_MANA, N.GS_DELAY,
            N.SWIFT_AS, N.SWIFT_DUR, N.SPECTRAL_DUR, N.GLOBE_DUR, N.SANGUINE_AS, N.SKELETON_LIFE, N.SWINGS,
            N.POLICIES, N.BASE_STR, N.BASE_AGI, N.BASE_INT, pressure.STR_HP, shadow.LEVEL) != \
            (14.0, 1.85, 175.0, 230.0, 1, 375, 6.0, 20.0, 12.0, 25.0, 13.0, 25.0, 5.0, 25.0, 6.0, 20.0, 0.20,
             0.30, 4.0, 4.0, 6.0, 0.23, 11.0,
             {"warrior": 1.8, "assassin": 1.53, "executor": 1.8, "mage": 1.8, "archer": 1.2},
             ((True, True), (True, False), (False, True), (False, False)), 33, 24, 62, 15.0, 15):
        raise ValueError("kernel constants assume the 2026-11-14 necromancer")
    if (shadow.CAST_POINT, shadow.CAST_BACKSWING) != (0.15, 0.30):
        raise ValueError("kernel constants assume cast 0.15 + 0.30")
    AP.check()
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(N.BASE_INT), float(N.BASE_STR), float(N.BASE_AGI), float(N.BASE_HP)],
                           "Necromancer")
    pieces = space.pieces
    n = len(pieces)
    fold = t["fold"].reshape(n, 2, C.NF).copy()
    pal = np.zeros((n, NPAL), dtype=np.float64)
    cv = shadow._copy_value
    for i, piece in enumerate(pieces):
        item = items[piece.code]
        code = item.rawcode
        for state, first in ((0, True), (1, False)):
            fold[i, state, 13] = cv(code, "haste", item.haste, first) / 100
        health = [float(int(raw)) for raw in re.findall(r"\+(\d+) Health\b", item.tip)]
        pet = [int(raw) / 100.0 for raw in re.findall(r"\+(\d+)% Pet Damage\b", item.tip)]
        if any(v == 0.0 for v in health + pet):
            raise ValueError(f"{code}: a zero Health / Pet Damage line")
        pal[i] = [
            shadow.MAGICAL_ADDS.get(code, 0.0),
            shadow.PHYSICAL_ADDS.get(code, 0.0),
            item.source_pct / 100.0,
            item.damage_pct / 100.0 - item.source_pct / 100.0,
            1.0 if (code in shadow.MAGICAL_ADDS or code in shadow.PHYSICAL_ADDS) else 0.0,
            shadow.item_luck(item),
            *C.pad(health, 0.0, "health", code),
            *C.pad(pet, 0.0, "pet damage", code),
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class NecromancerCL(C.ExactCL):
    hero = "necromancer"
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
        from sunken_sim import necromancer

        return necromancer

    def tables(self, space, items, sources):
        return necromancer_tables(space, items, sources)

    def timeline_key(self, build):
        from dataclasses import fields

        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points"))


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
