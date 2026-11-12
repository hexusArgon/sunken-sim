"""Exact float64 OpenCL kernel for Paladin fights (Retribution, Protection, Holy).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.paladin.stats_of`` (strength primary, own typed adds, luck from
tooltips), run ``paladin._fight_events`` and score each event as
``paladin.score_events`` the moment it is emitted.  Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

MAXO = 64
NPAL = 10

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 retribution, 1 protection, 2 holy */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_RET (SPEC == 0)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 10
#define MAXO 64
#define MAXH 96
#define NSRC 10

#define S_SULF (1UL<<0)
#define S_ORB  (1UL<<1)
#define S_GALA (1UL<<2)
#define S_SULG (1UL<<3)
#define S_TLUM (1UL<<4)
#define S_JUDG (1UL<<5)
#define S_BELL (1UL<<6)
#define S_GLAS (1UL<<7)
#define S_FLSK (1UL<<8)
#define S_I03C (1UL<<9)
#define S_I00L (1UL<<10)
#define S_I00Y (1UL<<11)
#define S_HARN (1UL<<12)
#define S_ATIE (1UL<<13)
#define S_CORE (1UL<<14)
#define S_UNSI (1UL<<15)
#define S_SILM (1UL<<16)

#define T_TOLL (1u<<0)
#define T_KNOW (1u<<1)
#define T_DHAM (1u<<2)
#define T_STORM (1u<<3)
#define T_ZEAL (1u<<4)
#define T_HOJ (1u<<5)
#define T_HMAS (1u<<6)
#define T_CRUS (1u<<7)

#define G_UNSL (1u<<0)
#define G_GLASS (1u<<1)
#define G_FORT (1u<<2)
#define G_SUPR (1u<<3)
#define G_ANIM (1u<<4)
#define G_MIND (1u<<5)
#define G_FORTUNE (1u<<6)
#define G_REPL (1u<<7)
#define G_FREN (1u<<8)

#define TM(r, x) (TALENTS && ((r)->tmask & (x)))
#define GM(r, x) (TALENTS && ((r)->gmask & (x)))

/* sources */
#define N_HAMMER 0
#define N_CS 1
#define N_STORM 2
#define N_AUTO 3
#define N_FURY 4
#define N_SPLASH 5
#define N_SULF 6
#define N_ECHO 7
#define N_HOJ 8
#define N_STUN 9

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, armor_pen, spell_mult, auto_pct, attack_potency, cd_temp, flat_cdr;
  double luck, mana_max, mana_regen, cast_lock, stun_hit;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  int spell_crit, nexec, targets, glass;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double taken, attack_c, spell_c, knowledge, echo_ch;
} Sco;

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

inline double exec_factor(const Row* r, double t) {
  double hp = target_hp(t);
  double f = 1.0;
  for (int i = 0; i < r->nexec; i++)
    if (hp <= r->ex_thr[i]) f *= 1.0 + r->ex_pct[i];
  return f;
}

inline void add_src(Sco* q, int id, double amount) {
  uint bit = 1u << id;
  if (q->seen & bit) q->src[id] = q->src[id] + amount;
  else { q->seen |= bit; q->ord[q->nord++] = id; q->src[id] = 0.0 + amount; }
}

inline double typed_bonus(const Row* sc, const Sco* q, int magical, double when, double mastery_now) {
  double bonus = 1.0 + (magical ? sc->magic_add : sc->phys_add);
  if (sc->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(when);
  if (magical && (sc->mask & S_TLUM)) bonus += 0.05 + 0.005 * mastery_now;
  if (sc->glass) bonus *= 1.15;
  if (magical) bonus *= q->knowledge;
  return bonus;
}

/* paladin.score_events for one event */
void emit(const Row* sc, Sco* q, int name, double raw, int magical, double count, double when, double pot_scale,
          double mastery_now, int auto_scale) {
  double amount;
  if (name == N_SPLASH) {
    amount = raw * q->taken * exec_factor(sc, when);
  } else if (name == N_ECHO) {
    amount = raw * q->taken * exec_factor(sc, when) * q->echo_ch;
  } else {
    amount = raw + sc->potency * pot_scale;
    amount *= typed_bonus(sc, q, magical, when, mastery_now);
    amount *= magical ? q->spell_c : q->attack_c;
    amount *= q->taken * exec_factor(sc, when);
    if (auto_scale) amount *= sc->auto_pct;
  }
  add_src(q, name, amount * count);
}

typedef struct {
  double h_start[MAXH], h_end[MAXH], h_next[MAXH], h_w[MAXH];
  int h_idx[MAXH]; uchar due[MAXH];
  int nh;
  double mana, mana_time;
  AP ap;
} St;

inline void recover(St* s, const Row* tl, double now) {
  if (now > s->mana_time && s->mana < tl->mana_max) {
    double v = s->mana + tl->mana_regen * (now - s->mana_time);
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
  s->mana_time = now;
}

int pay(St* s, const Row* tl, double cost, double now) {
  recover(s, tl, now);
  if (s->mana < cost) return 0;
  s->mana -= cost;
  double back = cost * tl->cast_refund + tl->cast_refund_flat + tl->cast_refund_mastery * tl->mastery;
  double v = s->mana + back;
  s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  return 1;
}

inline void damage_mana(St* s, const Row* tl, double count) {
  if (tl->damage_mana_pct != 0.0) {
    double v = s->mana + tl->damage_mana_pct * tl->mana_max * count;
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
}

inline double cooldown_of(double base, double haste, const Row* tl) {
  double v = (base * tl->cd_temp - tl->flat_cdr) / (1.0 + haste);
  return (v > 0.5) ? v : 0.5;
}

inline double hammer_count(const St* s, double now) {
  double w = 0.0;
  for (int i = 0; i < s->nh; i++) if (s->h_start[i] <= now && now < s->h_end[i]) w = w + s->h_w[i];
  return w;
}

void keep_hammers(St* s, double moment) {
  int k = 0;
  for (int i = 0; i < s->nh; i++) {
    if (s->h_end[i] > moment + 1e-9) {
      s->h_start[k] = s->h_start[i]; s->h_end[k] = s->h_end[i]; s->h_next[k] = s->h_next[i];
      s->h_w[k] = s->h_w[i]; s->h_idx[k] = s->h_idx[i]; k++;
    }
  }
  s->nh = k;
}

/* paladin._fight_events on the timeline sheet, each event scored on the scored sheet */
double fight(const Row* tl, const Row* sc, __global const double* orbit, int olen, int* status) {
  St s; Sco q;
  int st = 0;
  q.taken = armor_taken(15.0 - sc->armor_pen, &st);
  if (st) { *status = st; return 0.0; }
  q.attack_c = crit_factor(sc->crit, 2.0 + sc->rating);
  q.spell_c = sc->spell_crit ? crit_factor(sc->crit, sc->spell_mult + sc->rating) : 1.0;
  q.knowledge = (SP_RET && TM(sc, T_KNOW)) ? (1.0 + 0.003 * sc->intel) : 1.0;
  q.echo_ch = 0.10 * (1.0 + sc->luck);
  q.nord = 0; q.seen = 0u;
  const int targets = tl->targets;
  const double tg = (double)targets;
  double haste = tl->haste;
  double mastery_bonus = 0.0;
  int zeal_charges = 0;
  double zeal_until = -1.0, cs_until = -1.0, next_attack = 0.0, next_cs = 0.0, next_hammer = 0.0, next_hoj = 0.0, busy = 0.0;
  int fury_attacks = 0, crusade = 0, armed = 0;
  s.nh = 0;
  double hammer_duration = TM(tl, T_DHAM) ? 12.0 : 9.0;
  s.mana = tl->mana_max; s.mana_time = 0.0;
  ap_init(&s.ap, GM(tl, G_FREN) ? frenzy_chance(tl->luck) : 0.0, (tl->mask & S_SILM) ? SILENT_AS : 0.0,
          (tl->mask & S_SILM) ? SILENT_DUR : 0.0);
  const int sulf = (tl->mask & S_SULF) != 0;
  double toll = (TM(tl, T_TOLL) || (tl->mask & S_BELL)) ? 0.25 * (1.0 + tl->luck) : 0.0;
  const int hoj = TM(tl, T_HOJ) != 0;
  const int zeal = TM(tl, T_ZEAL) != 0;
  int guard = 0;
  while (next_attack < FIGHT || next_cs < FIGHT || next_hammer < FIGHT || s.nh > 0) {
    guard += 1;
    if (guard > 200000) break;
    double hit_at = FIGHT;
    for (int i = 0; i < s.nh; i++)
      if (s.h_next[i] < s.h_end[i]) hit_at = (s.h_next[i] < hit_at) ? s.h_next[i] : hit_at;
    double expire = FIGHT;
    for (int i = 0; i < s.nh; i++) if (i == 0 || s.h_end[i] < expire) expire = s.h_end[i];
    double moment = next_attack;
    if (next_cs < moment) moment = next_cs;
    if (next_hammer < moment) moment = next_hammer;
    double hj = hoj ? next_hoj : FIGHT;
    if (hj < moment) moment = hj;
    if (hit_at < moment) moment = hit_at;
    if (expire < moment) moment = expire;
    if (moment >= FIGHT) break;
    int any_due = 0;
    for (int i = 0; i < s.nh; i++) {
      s.due[i] = (s.h_next[i] <= moment && moment < s.h_end[i]) ? 1 : 0;
      if (s.due[i]) any_due = 1;
    }
    if (any_due && hit_at <= moment + 1e-9) {
      recover(&s, tl, moment);
      for (int i = 0; i < s.nh; i++) {
        if (!s.due[i]) continue;
        double w = s.h_w[i];
        emit(sc, &q, N_HAMMER, (5.0 + 10.0 + 0.45 * tl->str) * w, 1, tg, moment, 1.0, tl->mastery + mastery_bonus, 0);
        damage_mana(&s, tl, tg);
        s.h_idx[i] += 1;
        s.h_next[i] = (s.h_idx[i] < olen) ? (s.h_start[i] + orbit[s.h_idx[i]]) : s.h_end[i];
        if (TM(tl, T_HMAS)) {
          double v = mastery_bonus + 2.0 * w * tg;
          mastery_bonus = (30.0 <= v) ? 30.0 : v;
        }
        if (hoj) {
          double v = next_hoj - 0.10 * w * tg;
          next_hoj = (moment >= v) ? moment : v;
        }
      }
      keep_hammers(&s, moment);
      continue;
    }
    if (fabs(moment - expire) <= 1e-9) { keep_hammers(&s, moment); continue; }
    if (moment == next_attack && next_attack < busy) { next_attack = busy; continue; }
    if (moment == next_attack) {
      recover(&s, tl, moment);
      double swing = 1.85 * ((tl->mask & S_GALA) ? 1.20 : 1.0);
      if (SP_RET) {
        double f = 1.0 - 0.03 * hammer_count(&s, moment);
        swing *= (0.2 >= f) ? 0.2 : f;
      }
      ap_attack(&s.ap, moment, tl->crit);
      double speed = ap_speed(tl->aspd + ap_bonus(&s.ap, moment));
      if (zeal_charges && moment <= zeal_until) {
        double v = speed + 0.80;
        speed = (4.0 <= v) ? 4.0 : v;
        zeal_charges -= 1;
      }
      double interval = swing / (1.0 + speed);
      double mnow = tl->mastery + mastery_bonus;
      if (cs_until >= moment) {
        double raw = 90.0 + 30.0 + 2.75 * tl->str;
        if (SP_RET) raw *= 1.10 + 0.01 * mnow;
        if (tl->mask & S_JUDG) raw *= 1.0 + 0.05 * hammer_count(&s, moment);
        emit(sc, &q, N_CS, raw, 1, 1.0, moment, 1.0, mnow, 0);
        damage_mana(&s, tl, 1.0);
        cs_until = -1.0;
        if (TM(tl, T_STORM)) {
          double storm = 20.0 + tl->str + tl->intel + mnow;
          if (!SP_RET) storm *= 0.5;
          emit(sc, &q, N_STORM, storm, 1, tg, moment, 1.0, mnow, 0);
          damage_mana(&s, tl, tg);
        }
      }
      double white = 13.0 + 0.75 * tl->str + tl->damage;
      emit(sc, &q, N_AUTO, white, 0, 1.0, moment, tl->attack_potency, mnow, 1);
      double gain = tl->attack_mana + tl->attack_mana_pct * tl->mana_max;
      if (tl->attack_mana_crit != 0.0) {
        double cc = (tl->crit < 100.0) ? tl->crit : 100.0;
        gain *= 1.0 + cc / 100.0;
      }
      double v = s.mana + gain;
      s.mana = (v < tl->mana_max) ? v : tl->mana_max;
      damage_mana(&s, tl, 1.0);
      fury_attacks += 1;
      if (!hoj && fury_attacks >= 3) {
        fury_attacks = 0;
        emit(sc, &q, N_FURY, 5.0 + 25.0 + 2.0 * tl->str, 1, 1.0, moment, 1.0, mnow, 0);
        damage_mana(&s, tl, 1.0);
      }
      if (tl->mask & S_ORB) {
        emit(sc, &q, N_SPLASH, 20.0 + 0.35 * tl->str, 0, tg, moment, 0.0, mnow, 0);
        damage_mana(&s, tl, tg);
      }
      if (sulf) {
        if (armed) {
          armed = 0;
          emit(sc, &q, N_SULF, tl->str, 1, tg, moment, 0.0, mnow, 0);
          damage_mana(&s, tl, tg);
        }
        emit(sc, &q, N_ECHO, 13.0 + 0.75 * tl->str + tl->damage, 0, 1.0, moment, 0.0, mnow, 0);
      }
      if (TM(tl, T_CRUS) && crusade < 20) {
        crusade = (20 < crusade + 2) ? 20 : crusade + 2;
        haste = tl->haste + (double)crusade / 100.0;
      }
      next_attack = moment + interval;
      continue;
    }
    if (moment < busy) {
      if (moment == next_cs) next_cs = busy;
      else if (moment == next_hammer) next_hammer = busy;
      else if (moment == next_hoj) next_hoj = busy;
      else break;
      continue;
    }
    if (moment == next_cs) {
      if (!pay(&s, tl, 15.0, moment)) { next_cs = moment + 0.25; continue; }
      cs_until = moment + 4.0;
      if (sulf) armed = 1;
      if (zeal) { zeal_charges = 2; zeal_until = moment + 4.0; }
      busy = moment + CAST_POINT + CAST_BACKSWING + tl->cast_lock;
      next_cs = moment + cooldown_of(6.0, haste, tl);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    if (moment == next_hammer) {
      if (!pay(&s, tl, 5.0, moment)) { next_hammer = moment + 0.25; continue; }
      double weights[2] = {1.0, toll};
      double starts[2] = {moment + CAST_POINT, moment + CAST_POINT + 0.5};
      for (int k = 0; k < 2; k++) {
        if (k == 1 && toll == 0.0) break;
        if (weights[k] <= 0.0) continue;
        if (s.nh >= MAXH) { *status = 2; return 0.0; }
        double first = (olen > 0) ? orbit[0] : hammer_duration;
        int i = s.nh++;
        s.h_start[i] = starts[k]; s.h_end[i] = starts[k] + hammer_duration; s.h_idx[i] = 0;
        s.h_next[i] = starts[k] + first; s.h_w[i] = weights[k];
      }
      if (sulf) armed = 1;
      if (zeal) { zeal_charges = 2; zeal_until = moment + 4.0; }
      busy = moment + CAST_POINT + CAST_BACKSWING + tl->cast_lock;
      next_hammer = moment + cooldown_of(4.5, haste, tl);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    if (hoj && moment == next_hoj) {
      if (!pay(&s, tl, 0.0, moment)) { next_hoj = moment + 0.25; continue; }
      double raw = (60.0 + 1.75 * tl->str) * (1.0 + 0.01 * tl->intel);
      double mnow = tl->mastery + mastery_bonus;
      emit(sc, &q, N_HOJ, raw, 1, 1.0, moment, 1.0, mnow, 0);
      if (tl->stun_hit != 0.0) emit(sc, &q, N_STUN, tl->stun_hit, 0, 1.0, moment, 0.0, mnow, 0);
      if (sulf) armed = 1;
      if (zeal) { zeal_charges = 2; zeal_until = moment + 4.0; }
      busy = moment + CAST_POINT + CAST_BACKSWING + tl->cast_lock;
      next_hoj = moment + cooldown_of(18.0, haste, tl);
      next_attack = (next_attack >= busy) ? next_attack : busy;
      continue;
    }
    break;
  }
  double total = 0.0;
  for (int i = 0; i < q.nord; i++) total += q.src[q.ord[i]];
  return total / FIGHT;
}

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  __global const double* pal; __global const double* base; __global const double* orbit; __global const int* olen;
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

/* paladin.stats_of(build) */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double strength = T->base[1], agility = T->base[2], intel = T->base[0];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 0.0;
  double crit = (double)pts[6];
  double rating = 0.0, haste = 0.0, aspd = 0.0, magic_add = 0.0, phys_add = 0.0, mana_flat = 0.0;
  double armor_pen = 0.0, auto_pct = 1.0, attack_potency = 1.0;
  double luck = 0.01 * (double)pts[9];
  haste += 0.01 * (double)pts[3];
  aspd += 0.02 * (double)pts[4];
  damage += 2.0 * (double)pts[5];
  mana_flat += 20.0 * (double)pts[1];
  ulong mask = 0;
  int n_core = 0, n_sulg = 0, sc = 0, sc65 = 0, has_shop = 0, has_drop = 0, nexec = 0;
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
      if (u[11] != 0.0) sc = 1;
      if (u[12] != 0.0) sc65 = 1;
      if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
      auto_pct += u[8];
      if (u[2] != 0.0) attack_potency = 2.0;
      mana_flat += f[10];
      for (int j = 0; j < 4; j++) luck += a[5 + j];
    }
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) strength += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  if (GM(r, G_UNSL) && !(mask & S_UNSI)) { magic_add += 0.18; phys_add += 0.18; }
  double agility_speed = 0.004 * agility;
  agility_speed = (1.0 <= agility_speed) ? 1.0 : agility_speed;
  double asum = aspd + agility_speed;
  asum = (-0.8 >= asum) ? -0.8 : asum;
  aspd = (4.0 <= asum) ? 4.0 : asum;
  double flat_cdr = GM(r, G_MIND) ? 0.20 : 0.0;
  if (mask & S_FLSK) flat_cdr += 0.50;
  if (mask & S_I03C) flat_cdr += 0.50;
  if (mask & S_I00L) flat_cdr += 1.50;
  if (mask & S_I00Y) flat_cdr -= 1.00;
  double cd_temp = 1.0;
  if (mask & S_HARN) cd_temp *= 0.92;
  if (mask & S_ATIE) cd_temp *= 0.87;
  cd_temp *= 1.0 + 0.12 * (double)n_core + 0.10 * (double)n_sulg;
  if (GM(r, G_FORTUNE)) luck += 0.15;
  double mana_max = 120.0 + 7.0 * intel + mana_flat;
  double cast_lock = 0.0, regen_rate = 0.0, mp5 = 0.0, stun_hit = 0.0;
  double keep = 1.0, rflat = 0.0, rmast = 0.0, persec = 0.0, aflat = 0.0, apct = 0.0, dpct = 0.0;
  int acrit = 0;
  for (int si = 0; si < 6; si++) {
    if (!first[si]) continue;
    __global const double* u = T->uniq + (long)chosen[si] * NU;
    __global const double* a = T->pal + (long)chosen[si] * NPAL;
    cast_lock += u[1];
    stun_hit += a[9];
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
  double regen = stat * 0.80;
  if (TM(r, T_KNOW)) regen += 0.03 * intel * 0.80;
  r->str = strength; r->agi = agility; r->intel = intel; r->potency = potency; r->mastery = mastery; r->damage = damage;
  r->crit = crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->magic_add = magic_add; r->phys_add = phys_add; r->armor_pen = armor_pen;
  r->spell_mult = sc65 ? 1.65 : 1.50; r->auto_pct = auto_pct; r->attack_potency = attack_potency;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = regen;
  r->cast_lock = cast_lock; r->stun_hit = stun_hit;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->spell_crit = sc; r->nexec = nexec; r->targets = targets;
  r->glass = (GM(r, G_GLASS) || (mask & S_GLAS)) ? 1 : 0;
}

double row_value(Tab* T, long index, uint tmask, uint gmask, const int* pts, const int* tlpts, int targets,
                 int* status, int* group) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row sc;
  sheet(T, &sc, chosen, tmask, gmask, pts, targets, group);
  int same = 1;
  for (int j = 0; j < NP; j++) if (pts[j] != tlpts[j]) { same = 0; break; }
  Row tl;
  if (same) tl = sc;
  else { int g2 = 0; sheet(T, &tl, chosen, tmask, gmask, tlpts, targets, &g2); }
  int dh = TM(&tl, T_DHAM) ? 1 : 0;
  return fight(&tl, &sc, T->orbit + dh * MAXO, T->olen[dh], status);
}

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    __global const double* pal, __global const double* base, __global const double* orbit, __global const int* olen

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.pal = pal; T.base = base; T.orbit = orbit; T.olen = olen;

__kernel void cls_bare(const long start, const int n, const int targets, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = 0;
  int status = 0, group = 0;
  double d = row_value(&T, start + gid, 0u, 0u, pts, pts, targets, &status, &group);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
}

__kernel void cls_rows(const int n, const int targets, __global const long* chunks, __global const uint* tmasks,
    __global const uint* gmasks, __global const int* points, __global const int* tlpoints, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP], tlp[NP];
  for (int j = 0; j < NP; j++) { pts[j] = points[(long)gid * NP + j]; tlp[j] = tlpoints[(long)gid * NP + j]; }
  int status = 0, group = 0;
  double d = row_value(&T, chunks[gid], tmasks[gid], gmasks[gid], pts, tlp, targets, &status, &group);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
}
"""
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I0BR": 0, "I07O": 1, "I0JO": 2, "I0QT": 3, "tlum": 4, "I0QX": 5, "I0R0": 6, "I0JA": 7,
    "I096": 8, "I03C": 9, "I00L": 10, "I00Y": 11, "I07P": 12, "I048": 13, "I0FW": 14, "I0AV": 15,
    "I0QN": 16,
}
TALENT_BITS = {
    "I09Y": 0, "I09R": 1, "I064": 2, "I04C": 3, "I01J": 4, "I0NG": 5, "I0G8": 6, "I0NC": 7,
    # read nowhere in sunken_sim.paladin: no effect on the fight
    "I0OT": 16, "I069": 17, "I09L": 18, "I0I1": 19, "I09Z": 20, "I0OR": 21, "I0OQ": 22, "I0OU": 23,
    "I0OS": 24, "I0ND": 25,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0H0": 7, "I0GZ": 8}
# glyphs that sunken_sim.paladin (stats_of, _mana_regen, the fight) never reads
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN"}
SPECS = {"retribution": 0, "protection": 1, "holy": 2}


def paladin_tables(space, items, sources) -> dict:
    """class_cl.character_tables plus the paladin-only per-piece columns and the hammer orbits."""
    import re

    from sunken_sim import paladin, shadow
    from sunken_sim.stacking import stack_fields

    if (paladin.SWING, paladin.WHITE_BASE, paladin.BASE_MANA, paladin.RANK) != (1.85, 13.0, 120.0, 1):
        raise ValueError("kernel constants assume the 2026-11-10 paladin")
    if (paladin.CS_COOLDOWN, paladin.CS_BUFF, paladin.HAMMER_COOLDOWN, paladin.CS_MANA, paladin.HAMMER_MANA,
            paladin.HOJ_MANA, paladin.HOJ_COOLDOWN) != (6.0, 4.0, 4.5, 15.0, 5.0, 0.0, 18.0):
        raise ValueError("kernel constants assume the 2026-11-10 paladin")
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(paladin.BASE_INT), float(paladin.BASE_STR), float(paladin.BASE_AGI)], "Paladin")
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
        pal[i] = [
            shadow.MAGICAL_ADDS.get(code, 0.0),
            shadow.PHYSICAL_ADDS.get(code, 0.0),
            item.source_pct / 100.0,
            item.damage_pct / 100.0 - item.source_pct / 100.0,
            1.0 if (code in shadow.MAGICAL_ADDS or code in shadow.PHYSICAL_ADDS) else 0.0,
            *C.pad(lucks, 0.0, "luck", code),
            float(getattr(item, "stun_hit_damage", 0.0) or 0.0),
        ]
    orbit = np.zeros((2, MAXO), dtype=np.float64)
    olen = np.zeros(2, dtype=np.int32)
    for k, key in enumerate(((9.0, 100.0), (12.0, 150.0))):
        hits = paladin._ORBIT[key]
        if len(hits) > MAXO:
            raise ValueError("hammer orbit longer than the kernel table")
        orbit[k, : len(hits)] = hits
        olen[k] = len(hits)
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    t["orbit"] = np.ascontiguousarray(orbit.reshape(-1))
    t["olen"] = olen
    return t


class PaladinCL(C.ExactCL):
    hero = "paladin"
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ("health", "healing_power")  # ESC points left out of the timeline key
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "pal", "base", "orbit", "olen")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32}

    @staticmethod
    def module():
        from sunken_sim import paladin

        return paladin

    def tables(self, space, items, sources):
        return paladin_tables(space, items, sources)

    def timeline_key(self, build):
        from sunken_sim import paladin

        return paladin._timeline_key(build, paladin.stats_of(build), self.spec, self.targets)


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
