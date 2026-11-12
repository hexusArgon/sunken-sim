"""Exact float64 OpenCL kernel for Priest fights (Shadow, Discipline, Holy).

One work-item scores one fight: unrank the six items of a chunk, fold the sheet
the way ``sunken_sim.shadow.character`` does (talents, glyphs, ESC points and
the baked Frenzy / on-crit attack-speed uptimes included), run
``shadow._fight_events`` for the job's spec (every Diamond Ring binding) and
score the event stream two ways:

* ``score_events`` - what ``shadow.simulate(...).dps`` returns (item-only scan,
  talent and glyph choice);
* ``compile_events`` + ``score_compiled`` - what ``farm.score._priest`` uses to
  rank ESC points.

Both are accumulated while the events happen, in the order Python appends them,
so every sum is the same sequence of float64 operations.

Exactness: float64 everywhere, ``FP_CONTRACT OFF``, the operation order of the
Python oracle.  ``math.exp`` (the Silent Messenger on-crit haste uptime) is
never computed on the device: the kernel looks the exact argument up in a table
that the host fills with the host Python's own ``math.exp``; a missing argument
is reported, computed on the host and the row is run again.

The ESC search in ``farm.score._priest`` reuses cached timelines
(``shadow._TIMELINE``).  Its key leaves out a few inputs of the fight (luck for
Cosmic Horrors, crit for Magic Shiv, mastery for mastery refunds), so a trial
can be scored on the events of an earlier trial with the same key.
``PriestCL.refine`` replays that: each ESC row carries the points of the first
trial that had its key, the fight runs on those, the score uses the row's own.
"""

from __future__ import annotations

import contextlib
import itertools
import math
import os

import numpy as np

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 shadow, 1 discipline, 2 holy (one program per spec) */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_SHADOW (SPEC == 0)
#define SP_DISC (SPEC == 1)
#define SP_HOLY (SPEC == 2)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXT 8
#define SWK 8  /* shadow.SWP_SLOTS */
#define MAXQ 64
#define MAXW 80
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NS 6
#define NSRC 16
#define NMB 7
#define EB 24

/* item specials (piece mask) */
#define S_RING (1UL<<0)
#define S_SULF (1UL<<1)
#define S_ORB  (1UL<<2)
#define S_GALA (1UL<<3)
#define S_SULG (1UL<<4)
#define S_FLSK (1UL<<5)
#define S_I03C (1UL<<6)
#define S_I00L (1UL<<7)
#define S_I00Y (1UL<<8)
#define S_HARN (1UL<<9)
#define S_ATIE (1UL<<10)
#define S_SOUL (1UL<<11)
#define S_TLUM (1UL<<12)
#define S_CORE (1UL<<13)

/* talents */
#define T_TORM (1u<<0)
#define T_LINK (1u<<1)
#define T_INSA (1u<<2)
#define T_CATH (1u<<3)
#define T_COSM (1u<<4)
#define T_CLAI (1u<<5)
#define T_PRAY (1u<<6)
#define T_NAAR (1u<<7)
#define T_RENW (1u<<8)
#define T_RADI (1u<<9)
#define T_SPAN (1u<<10)

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

#ifdef NOINLINE
#define NI __attribute__((noinline))
#else
#define NI
#endif

#define TM(r, x) (TALENTS && ((r)->tmask & (x)))
#define GM(r, x) (TALENTS && ((r)->gmask & (x)))

/* spells */
#define SW_SWP 0
#define SW_MS  1
#define SW_VR  2
#define SW_DI  3
#define SW_RAD 4
#define SW_REN 5

/* recorded event kinds */
#define K_AUTO 0
#define K_MIND 1
#define K_VOID 2
#define K_NAARU 3
#define K_SWP 4
#define K_SWPI 5
#define K_THUNDER 6
#define K_RAD 7
#define K_BLAZE 8
#define K_SMITE 9
#define K_SPLASH 10
#define K_SULF 11
#define K_ECHO 12
#define K_HELL 13

/* score_events sources, in no particular order (the sum follows first-insertion order) */
#define SRC_AUTO 0
#define SRC_STAB 1
#define SRC_MIND 2
#define SRC_VOID 3
#define SRC_NAARU 4
#define SRC_SWP 5
#define SRC_SWPI 6
#define SRC_THUNDER 7
#define SRC_RAD 8
#define SRC_BLAZE 9
#define SRC_SMITE 10
#define SRC_SPLASH 11
#define SRC_SULF 12
#define SRC_ECHO 13
#define SRC_HELL 14
#define SRC_BLOOD 15

/* compile_events magic_base kinds */
#define MB_MIND 0
#define MB_VOID 1
#define MB_NAARU 2
#define MB_THUNDER 3
#define MB_SWPI 4
#define MB_BLAZE 5
#define MB_SMITE 6

/* pending events */
#define E_SWING 0
#define E_FIN0 1
#define E_SWP 7
#define E_VOID 8
#define E_NAARU 9
#define E_HELL 10
#define E_BLAZE 11

typedef struct {
  double intel, str, potency, mastery, ad, mana_max, crit, rating, haste, aspd;
  double spell_mult, flat_cdr, cd_temp, stun_ps, cast_lock;
  double attack_potency, auto_pct, armor_pen, soul_rate, stab_chance, stab_ratio, luck;
  double attack_base, swing, swp_period, mana_regen, cast_refund, cast_refund_flat, cast_refund_mastery;
  double attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double mag_sum, phys_sum;
  double ex_thr[MAXE], ex_pct[MAXE];
  int spell_crit, nexec, targets;
  uint tmask, gmask;
  ulong mask;
} Row;

/* score_events constants of the scored sheet, plus the per-source sums */
typedef struct {
  double spell_c, attack_c, tick_base, instant_raw, mind_raw, void_raw, naaru_raw, nuke_raw, stored;
  double blaze_raw, smite_raw, thunder_raw, splash_raw, echo_k, soul_k, stab_raw, stab_ch;
  double explosion, glass, hell_raw, amp_val;
  double src[NSRC];
  int ord[NSRC];
  int nord;
  uint seen;
} Sco;

/* compile_events accumulators */
typedef struct {
  double auto_w, soul_w, splash, sulf_b, sulf_s, echo, rad_b, rad_s, rad_pb, rad_ps;
  double mb[NMB], ms[NMB];
  double swp_b, swp_s, swp_pb, swp_ps, hell_exec, hell_raw, blood;
} Comp;

typedef struct {
  double hq_w[MAXQ]; uint hq_s[MAXQ]; int hq_k[MAXQ];
  double ready[NS], spell_cd[NS];
  double swp_e[MAXT][SWK + 1], swp_m[MAXT][SWK + 1]; int swp_n[MAXT];
  double ws[MAXW], we[MAXW];
  double mana, mana_time, naaru_until, blaze_until, renew_until, hero_ready, busy_until, duration;
  double eb_w[EB], eb_h[EB]; int eb_k[EB];
  uint seq;
  int hn, nw, armed, status, nb;
  int has[NS];
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

inline double exec_factor(const Row* r, double t) {
  double hp = target_hp(t);
  double f = 1.0;
  for (int i = 0; i < r->nexec; i++)
    if (hp <= r->ex_thr[i]) f *= 1.0 + r->ex_pct[i];
  return f;
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

inline void add_src(Sco* q, int id, double amount) {
  uint bit = 1u << id;
  if (q->seen & bit) {
    q->src[id] = q->src[id] + amount;
  } else {
    q->seen |= bit;
    q->ord[q->nord++] = id;
    q->src[id] = 0.0 + amount;
  }
}

/* shadow.score_events constants for the scored sheet (potency/crit/mastery/luck of that sheet) */
NI void sco_init(const Row* sc, Sco* q) {
  double intel = sc->intel;
  q->spell_c = sc->spell_crit ? crit_factor(sc->crit, sc->spell_mult + sc->rating) : 1.0;
  q->attack_c = crit_factor(sc->crit, 2.0 + sc->rating);
  double mastery = SP_SHADOW ? (1.10 + 0.006 * sc->mastery) : 1.0;
  q->tick_base = (15.0 + 0.30 * intel) * mastery;
  q->instant_raw = (75.0 + 1.50 * intel) * mastery;
  q->mind_raw = (80.0 + 1.50 * intel) * (1.0 + 0.01 * sc->ad);
  q->void_raw = (85.0 + 0.15 * sc->mana_max) * (1.0 + 0.007 * intel);
  q->naaru_raw = (25.0 + 0.40 * intel) * (SP_DISC ? 0.75 : 1.0);
  double rbase = 120.0 + 1.20 * intel + 0.10 * sc->mana_max;
  if (SP_DISC) {
    double scaled = rbase * (1.10 + 0.008 * sc->mastery);
    q->nuke_raw = scaled * 0.80;
    q->stored = scaled * 0.60;
  } else {
    q->nuke_raw = 0.0;
    q->stored = rbase;
  }
  q->blaze_raw = (SP_HOLY ? 0.04 : 0.08) * q->stored;
  q->smite_raw = 50.0 + 0.80 * intel + 0.80 * sc->str;
  q->thunder_raw = 35.0 + 2.0 * intel;
  q->splash_raw = 20.0 + 0.35 * intel;
  q->echo_k = sc->ad * (0.10 * (1.0 + sc->luck));
  q->soul_k = sc->soul_rate * 5300.0;
  q->stab_ch = sc->stab_chance * (1.0 + sc->luck);
  q->stab_raw = sc->stab_ratio * sc->ad;
  q->glass = GM(sc, G_GLASS) ? 1.15 : 1.0;
  double ex = 0.03 * (20.0 + 1.6 * intel + sc->potency);
  if (GM(sc, G_GLASS)) ex *= 1.15;
  q->explosion = ex;
  int t = sc->targets;
  q->hell_raw = (t == 1) ? 96.0 : ((t >= 4) ? 24.0 : 48.0);
  q->amp_val = 1.05 + 0.0008 * sc->str;
  q->nord = 0;
  q->seen = 0u;
}

/* score_events and compile_events terms of one recorded event on the scored sheet */
NI void score_ev(const St* s, const Row* sc, Sco* q, Comp* c, int comp, double when, int kind, double hits) {
  double execute = exec_factor(sc, when);
  double amp = 1.0;
  if (s->nw > 0 && TM(sc, T_RADI)) {
    for (int i = 0; i < s->nw; i++)
      if (s->ws[i] < when && when <= s->we[i]) { amp = q->amp_val; break; }
  }
  double hp = target_hp(when);
  double ta = sc->mag_sum;
  if (sc->mask & S_SULG) ta += 0.13 + 0.25 * hp;
  double bonus = 1.0 + ta;
  double slope = 0.0;
  if (sc->mask & S_TLUM) { bonus += 0.05; slope = 0.005; }
  if (TM(sc, T_INSA)) { bonus *= 1.15; slope *= 1.15; }
  if (TM(sc, T_CATH)) bonus += 0.30 * hp;
  if (GM(sc, G_GLASS)) { bonus *= 1.15; slope *= 1.15; }
  double pa = sc->phys_sum;
  if (sc->mask & S_SULG) pa += 0.13 + 0.25 * hp;
  double pbonus = 1.0 + pa;
  if (GM(sc, G_GLASS)) pbonus *= 1.15;

  double magical = (bonus + slope * sc->mastery) * amp;
  double physical = pbonus * amp;
  double pot = sc->potency;
  int blood = 1;
  switch (kind) {
    case K_AUTO: {
      double soul = q->soul_k * hp;
      double amount = (sc->ad + pot * sc->attack_potency + soul) * physical * execute * sc->auto_pct * q->attack_c * hits;
      add_src(q, SRC_AUTO, amount);
      if (sc->stab_chance != 0.0) {
        double stab = (q->stab_raw + pot * sc->attack_potency) * physical * execute * sc->auto_pct * q->attack_c
                      * 1.25 * q->stab_ch * hits;
        add_src(q, SRC_STAB, stab);
      }
    } break;
    case K_MIND: add_src(q, SRC_MIND, (q->mind_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_VOID: add_src(q, SRC_VOID, (q->void_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_NAARU: add_src(q, SRC_NAARU, (q->naaru_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_SWP: {
      double lf = TM(sc, T_LINK) ? (1.15 + 0.10 * hits) : 1.0;
      add_src(q, SRC_SWP, (q->tick_base + pot) * lf * magical * q->spell_c * hits * execute);
    } break;
    case K_SWPI: add_src(q, SRC_SWPI, (q->instant_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_THUNDER: add_src(q, SRC_THUNDER, (q->thunder_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_RAD: add_src(q, SRC_RAD, (q->nuke_raw + pot * hits) * magical * q->spell_c * execute); break;
    case K_BLAZE: add_src(q, SRC_BLAZE, (q->blaze_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_SMITE: add_src(q, SRC_SMITE, (q->smite_raw + pot) * magical * q->spell_c * hits * execute); break;
    case K_SPLASH: add_src(q, SRC_SPLASH, q->splash_raw * hits * amp * execute); blood = 0; break;
    case K_SULF: add_src(q, SRC_SULF, sc->intel * magical * q->spell_c * hits * execute); break;
    case K_ECHO: add_src(q, SRC_ECHO, q->echo_k * hits * execute); blood = 0; break;
    case K_HELL: add_src(q, SRC_HELL, (q->hell_raw + pot) * hits * q->glass * amp * execute); break;
  }
  if (blood && GM(sc, G_BLOOD)) add_src(q, SRC_BLOOD, q->explosion * amp * execute);

#if TALENTS
  if (comp) {
    double cb = bonus * amp;
    double cs = slope * amp;
    switch (kind) {
      case K_AUTO: {
        double w = execute * pbonus * amp * hits;
        c->auto_w += w;
        c->soul_w += w * hp;
      } break;
      case K_SPLASH: c->splash += hits * amp * execute; break;
      case K_SULF: c->sulf_b += cb * hits * execute; c->sulf_s += cs * hits * execute; break;
      case K_ECHO: c->echo += hits * execute; break;
      case K_RAD:
        c->rad_b += cb * execute; c->rad_s += cs * execute;
        c->rad_pb += cb * hits * execute; c->rad_ps += cs * hits * execute;
        break;
      case K_MIND: c->mb[MB_MIND] += cb * hits * execute; c->ms[MB_MIND] += cs * hits * execute; break;
      case K_VOID: c->mb[MB_VOID] += cb * hits * execute; c->ms[MB_VOID] += cs * hits * execute; break;
      case K_NAARU: c->mb[MB_NAARU] += cb * hits * execute; c->ms[MB_NAARU] += cs * hits * execute; break;
      case K_THUNDER: c->mb[MB_THUNDER] += cb * hits * execute; c->ms[MB_THUNDER] += cs * hits * execute; break;
      case K_SWPI: c->mb[MB_SWPI] += cb * hits * execute; c->ms[MB_SWPI] += cs * hits * execute; break;
      case K_BLAZE: c->mb[MB_BLAZE] += cb * hits * execute; c->ms[MB_BLAZE] += cs * hits * execute; break;
      case K_SMITE: c->mb[MB_SMITE] += cb * hits * execute; c->ms[MB_SMITE] += cs * hits * execute; break;
      case K_SWP: {
        double lf = TM(sc, T_LINK) ? (1.15 + 0.10 * hits) : 1.0;
        c->swp_b += lf * hits * cb * execute;
        c->swp_s += lf * hits * cs * execute;
        c->swp_pb += lf * hits * cb * execute;
        c->swp_ps += lf * hits * cs * execute;
      } break;
      case K_HELL: c->hell_raw = q->hell_raw; c->hell_exec += hits * amp * execute; break;
    }
    if (GM(sc, G_BLOOD) && kind != K_ECHO) c->blood += amp * execute;
  }
#endif
}

/* _fight_events.record: the event is kept for scoring at the end of this step (every event of a
   step has the step's time, and a Radiance window opened in the step starts at that time, so it
   cannot cover them); the Belt of Ulduar mana is applied at once on the timeline sheet. */
void record(St* s, const Row* tl, const Row* sc, Sco* q, Comp* c, int comp,
            double when, int kind, double hits) {
  if (s->nb >= EB) { s->status = 8; return; }
  s->eb_w[s->nb] = when; s->eb_k[s->nb] = kind; s->eb_h[s->nb] = hits; s->nb++;
  if (tl->damage_mana_pct != 0.0) {
    double v = s->mana + tl->damage_mana_pct * tl->mana_max;
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
}

void flush(St* s, const Row* sc, Sco* q, Comp* c, int comp) {
  for (int i = 0; i < s->nb; i++) score_ev(s, sc, q, c, comp, s->eb_w[i], s->eb_k[i], s->eb_h[i]);
  s->nb = 0;
}

/* shadow.score_compiled / FIGHT is applied by the caller */
NI double score_compiled(const Row* sc, const Comp* c, int* status) {
  double crit = sc->crit, potency = sc->potency, mastery_stat = sc->mastery, luck = sc->luck, intel = sc->intel;
  double spell_c = sc->spell_crit ? crit_factor(crit, sc->spell_mult + sc->rating) : 1.0;
  double attack_c = crit_factor(crit, 2.0 + sc->rating);
  double mastery = SP_SHADOW ? (1.10 + 0.006 * mastery_stat) : 1.0;
  double tick_base = (15.0 + 0.30 * intel) * mastery;
  double instant_raw = (75.0 + 1.50 * intel) * mastery;
  double total = (sc->ad + potency * sc->attack_potency) * sc->auto_pct * attack_c * c->auto_w;
  total += sc->soul_rate * 5300.0 * sc->auto_pct * attack_c * c->soul_w;
  total += (20.0 + 0.35 * intel) * c->splash;
  double sulf_mag = c->sulf_b + c->sulf_s * mastery_stat;
  total += intel * spell_c * sulf_mag;
  total += sc->ad * (0.10 * (1.0 + luck)) * c->echo;
  double mind_raw = (80.0 + 1.50 * intel) * (1.0 + 0.01 * sc->ad);
  double void_raw = (85.0 + 0.15 * sc->mana_max) * (1.0 + 0.007 * intel);
  total += (mind_raw + potency) * spell_c * (c->mb[MB_MIND] + c->ms[MB_MIND] * mastery_stat);
  total += (void_raw + potency) * spell_c * (c->mb[MB_VOID] + c->ms[MB_VOID] * mastery_stat);
  double naaru_raw = (25.0 + 0.40 * intel) * (SP_DISC ? 0.75 : 1.0);
  total += (naaru_raw + potency) * spell_c * (c->mb[MB_NAARU] + c->ms[MB_NAARU] * mastery_stat);
  total += (35.0 + 2.0 * intel + potency) * spell_c * (c->mb[MB_THUNDER] + c->ms[MB_THUNDER] * mastery_stat);
  double rbase = 120.0 + 1.20 * intel + 0.10 * sc->mana_max;
  double nuke_raw, stored;
  if (SP_DISC) {
    double scaled = rbase * (1.10 + 0.008 * mastery_stat);
    nuke_raw = scaled * 0.80;
    stored = scaled * 0.60;
  } else {
    nuke_raw = 0.0;
    stored = rbase;
  }
  double rad_mag = c->rad_b + c->rad_s * mastery_stat;
  double rad_pot = c->rad_pb + c->rad_ps * mastery_stat;
  total += spell_c * (nuke_raw * rad_mag + potency * rad_pot);
  double blaze_raw = (SP_HOLY ? 0.04 : 0.08) * stored;
  total += (blaze_raw + potency) * spell_c * (c->mb[MB_BLAZE] + c->ms[MB_BLAZE] * mastery_stat);
  double smite_raw = 50.0 + 0.80 * intel + 0.80 * sc->str;
  total += (smite_raw + potency) * spell_c * (c->mb[MB_SMITE] + c->ms[MB_SMITE] * mastery_stat);
  total += (instant_raw + potency) * spell_c * (c->mb[MB_SWPI] + c->ms[MB_SWPI] * mastery_stat);
  double swp_link = c->swp_b + c->swp_s * mastery_stat;
  double swp_pot = c->swp_pb + c->swp_ps * mastery_stat;
  total += spell_c * (tick_base * swp_link + potency * swp_pot);
  double glass = GM(sc, G_GLASS) ? 1.15 : 1.0;
  if (c->hell_exec != 0.0) total += (c->hell_raw + potency) * glass * c->hell_exec;
  if (c->blood != 0.0) total += 0.03 * (20.0 + 1.6 * intel + potency) * glass * c->blood;
  total *= armor_taken(15.0 - sc->armor_pen, status);
  if (sc->stab_chance != 0.0 && c->auto_w != 0.0) {
    double chance = sc->stab_chance * (1.0 + luck);
    double raw = sc->stab_ratio * sc->ad;
    double stab = (raw + potency * sc->attack_potency) * sc->auto_pct * attack_c * 1.25 * chance * c->auto_w;
    total += stab * armor_taken(15.0, status);
  }
  return total;
}

/* _cast_spells(build, spec): the Diamond Ring loop order */
int cast_spells(const Row* r, int* out) {
  int n = 0;
  if (SP_SHADOW) { out[n++] = SW_SWP; out[n++] = SW_MS; out[n++] = SW_VR; out[n++] = SW_DI; return n; }
  if (SP_DISC) { out[n++] = SW_SWP; out[n++] = SW_MS; out[n++] = SW_RAD; out[n++] = SW_DI; }
  else { out[n++] = SW_MS; if (TM(r, T_RADI)) out[n++] = SW_RAD; }
  if (TM(r, T_RENW)) out[n++] = SW_REN;
  return n;
}

inline void recover_mana(St* s, const Row* tl, double now) {
  if (now > s->mana_time && s->mana < tl->mana_max) {
    double v = s->mana + tl->mana_regen * (now - s->mana_time);
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
  s->mana_time = now;
}

/* SW:P per target: expiry points with probabilities (shadow.simulate swp_e / swp_m) */
double swp_on(const St* s, int i, double now) {
  double total = 0.0;
  for (int k = 0; k < s->swp_n[i]; k++) if (now < s->swp_e[i][k]) total += s->swp_m[i][k];
  return total;
}

double swp_kept(const St* s, int i, double at) {
  double total = 0.0;
  for (int k = 0; k < s->swp_n[i]; k++) if (s->swp_e[i][k] >= at) total += s->swp_m[i][k];
  return total;
}

double swp_last(const St* s, int i) {
  if (s->swp_n[i] == 0) return 0.0;
  double v = s->swp_e[i][0];
  for (int k = 1; k < s->swp_n[i]; k++) if (s->swp_e[i][k] > v) v = s->swp_e[i][k];
  return v;
}

int swp_any(const St* s, int targets, double now) {
  for (int i = 0; i < targets; i++)
    for (int k = 0; k < s->swp_n[i]; k++) if (now < s->swp_e[i][k]) return 1;
  return 0;
}

int weakest_swp(const St* s, int targets, double now) {
  int best = 0;
  double bk = swp_kept(s, 0, now + 1.0), bl = swp_last(s, 0);
  for (int i = 1; i < targets; i++) {
    double k = swp_kept(s, i, now + 1.0), l = swp_last(s, i);
    if (k < bk || (k == bk && l < bl)) { best = i; bk = k; bl = l; }
  }
  return best;
}

void swp_maybe(St* s, int i, double now, double p) {
  int c = 0;
  for (int k = 0; k < s->swp_n[i]; k++) {
    if (now < s->swp_e[i][k]) { s->swp_e[i][c] = s->swp_e[i][k]; s->swp_m[i][c] = s->swp_m[i][k] * (1.0 - p); c++; }
  }
  double until = now + s->duration;
  if (c > 0 && s->swp_e[i][c - 1] == until) s->swp_m[i][c - 1] = s->swp_m[i][c - 1] + p;
  else { s->swp_e[i][c] = until; s->swp_m[i][c] = p; c++; }
  while (c > SWK) {
    int k = 0;
    for (int j = 1; j < c - 1; j++) if (s->swp_m[i][j] < s->swp_m[i][k]) k = j;
    s->swp_m[i][k + 1] = s->swp_m[i][k + 1] + s->swp_m[i][k];
    for (int j = k; j < c - 1; j++) { s->swp_e[i][j] = s->swp_e[i][j + 1]; s->swp_m[i][j] = s->swp_m[i][j + 1]; }
    c--;
  }
  s->swp_n[i] = c;
}

void swp_apply(St* s, const Row* tl, const Row* sc, Sco* q, Comp* c, int comp, double now, int index) {
  double on = swp_on(s, index, now);
  if (on > 0.0) record(s, tl, sc, q, c, comp, now, K_SWPI, on);
  if (!swp_any(s, tl->targets, now)) push(s, now + tl->swp_period, E_SWP);
  s->swp_e[index][0] = now + s->duration;
  s->swp_m[index][0] = 1.0;
  s->swp_n[index] = 1;
}

void naaru_hit(St* s, const Row* tl, const Row* sc, Sco* q, Comp* c, int comp, double now) {
  record(s, tl, sc, q, c, comp, now, K_NAARU, 1.0);
  if (TM(tl, T_NAAR)) {
    double v = s->ready[SW_MS] - (SP_DISC ? 0.20 : 0.40);
    s->ready[SW_MS] = (v > now) ? v : now;
  }
}

NI void resolve(St* s, const Row* tl, const Row* sc, Sco* q, Comp* c, int comp, int name, double now) {
  double thunder = 0.18 * (double)tl->targets;
  if (name == SW_MS) {
    record(s, tl, sc, q, c, comp, now, K_MIND, 1.0);
    if (TM(tl, T_TORM) && s->has[SW_SWP]) swp_apply(s, tl, sc, q, c, comp, now, 0);
    if (GM(tl, G_THUN)) record(s, tl, sc, q, c, comp, now, K_THUNDER, thunder);
  } else if (name == SW_VR) {
    push(s, now + (TM(tl, T_COSM) ? 1.5 : 2.0), E_VOID);
    if (GM(tl, G_THUN)) record(s, tl, sc, q, c, comp, now, K_THUNDER, thunder);
  } else if (name == SW_SWP) {
    int w = weakest_swp(s, tl->targets, now);
    swp_apply(s, tl, sc, q, c, comp, now, w);
    if (GM(tl, G_THUN)) record(s, tl, sc, q, c, comp, now, K_THUNDER, thunder);
  } else if (name == SW_DI) {
    s->naaru_until = now + 10.0;
    push(s, now + 1.0, E_NAARU);
  } else if (name == SW_RAD) {
    if (SP_DISC) record(s, tl, sc, q, c, comp, now, K_RAD, (double)tl->targets);
    if (TM(tl, T_RADI)) {
      double span = TM(tl, T_SPAN) ? 6.0 : 4.0;
      if (s->blaze_until <= now) push(s, now + 1.0, E_BLAZE);
      s->blaze_until = now + span;
      if (s->nw >= MAXW) { s->status = 5; return; }
      s->ws[s->nw] = now; s->we[s->nw] = s->blaze_until; s->nw++;
    }
    if (GM(tl, G_THUN)) record(s, tl, sc, q, c, comp, now, K_THUNDER, thunder);
  } else if (name == SW_REN) {
    if (s->renew_until > now) record(s, tl, sc, q, c, comp, now, K_SMITE, (double)tl->targets);
    s->renew_until = now + 9.0;
    if (GM(tl, G_THUN)) record(s, tl, sc, q, c, comp, now, K_THUNDER, thunder);
  }
  if (name != SW_DI && TM(tl, T_PRAY) && now < s->naaru_until) naaru_hit(s, tl, sc, q, c, comp, now);
}

int choose(St* s, const Row* tl, double now) {
  int order[NS + 1];
  int n = 0;
  int any = 0;
  if (s->has[SW_SWP]) {
    for (int i = 0; i < tl->targets; i++) if (swp_kept(s, i, now + 1.0) < 0.5) { any = 1; break; }
  }
  if (any) order[n++] = SW_SWP;
  if (SP_SHADOW) { order[n++] = SW_DI; order[n++] = SW_MS; order[n++] = SW_VR; }
  else {
    if (s->has[SW_DI]) order[n++] = SW_DI;
    if (s->has[SW_RAD]) order[n++] = SW_RAD;
    if (s->has[SW_MS]) order[n++] = SW_MS;
    if (s->has[SW_REN]) order[n++] = SW_REN;
  }
  const double costs[NS] = {15.0, 25.0, 40.0, 30.0, 35.0, 20.0};
  for (int i = 0; i < n; i++) {
    int name = order[i];
    if (s->ready[name] <= now && s->mana >= costs[name]) {
      if (name == SW_DI && s->naaru_until > now) continue;
      return name;
    }
  }
  return -1;
}

void begin_cast(St* s, const Row* tl, int name, double now) {
  const double costs[NS] = {15.0, 25.0, 40.0, 30.0, 35.0, 20.0};
  recover_mana(s, tl, now);
  double spent = costs[name];
  s->mana -= spent;
  double back = spent * tl->cast_refund + tl->cast_refund_flat + tl->cast_refund_mastery * tl->mastery;
  double v = s->mana + back;
  s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  s->ready[name] = now + s->spell_cd[name];
  if (tl->mask & S_SULF) s->armed = 1;
  s->busy_until = now + CAST_POINT + CAST_BACKSWING + tl->cast_lock;
  s->hero_ready = s->busy_until;
  push(s, now + CAST_POINT, E_FIN0 + name);
}

/* shadow._fight_events on the timeline sheet; returns score_events total / FIGHT on the scored sheet */
NI double fight(const Row* tl, const Row* sc, int bound, Comp* c, int comp, int* status_out) {
  St s; Sco q;
  sco_init(sc, &q);
#if TALENTS
  if (comp) {
    c->auto_w = 0.0; c->soul_w = 0.0; c->splash = 0.0; c->sulf_b = 0.0; c->sulf_s = 0.0; c->echo = 0.0;
    c->rad_b = 0.0; c->rad_s = 0.0; c->rad_pb = 0.0; c->rad_ps = 0.0;
    for (int k = 0; k < NMB; k++) { c->mb[k] = 0.0; c->ms[k] = 0.0; }
    c->swp_b = 0.0; c->swp_s = 0.0; c->swp_pb = 0.0; c->swp_ps = 0.0;
    c->hell_exec = 0.0; c->hell_raw = 0.0; c->blood = 0.0;
  }
#endif
  int spells[NS];
  int ns = cast_spells(tl, spells);
  for (int i = 0; i < NS; i++) { s.has[i] = 0; s.ready[i] = 0.0; s.spell_cd[i] = 0.0; }
  double di_cd = 16.0 - (TM(tl, T_PRAY) ? 1.0 : 0.0) - (TM(tl, T_NAAR) ? 1.0 : 0.0);
  const double base_cd[NS] = {6.0, 8.0, 10.0, di_cd, 8.0, 6.0};
  for (int i = 0; i < ns; i++) {
    int name = spells[i];
    double temp = tl->cd_temp * ((bound == name) ? 0.70 : 1.0);
    double v = (base_cd[name] * temp - tl->flat_cdr) / (1.0 + tl->haste);
    s.spell_cd[name] = (v > 0.5) ? v : 0.5;
    s.has[name] = 1;
  }
  s.mana = tl->mana_max;
  s.mana_time = 0.0;
  for (int i = 0; i < MAXT; i++) s.swp_n[i] = 0;
  s.naaru_until = 0.0; s.blaze_until = 0.0; s.renew_until = 0.0;
  s.hero_ready = 0.0; s.busy_until = 0.0;
  s.duration = TM(tl, T_LINK) ? 12.0 : 10.0;
  s.seq = 0u; s.hn = 0; s.nw = 0; s.armed = 0; s.status = 0; s.nb = 0;
  push(&s, 0.0, E_SWING);
  if (GM(tl, G_HELL)) push(&s, 0.0, E_HELL);
  int targets = tl->targets;

  int guard = 0;
  while (s.hn > 0) {
    if (s.status) break;
    if (++guard > 200000) { s.status = 6; break; }
    double event_time = s.hq_w[0];
    while (s.hero_ready <= event_time && s.hero_ready < FIGHT) {
      recover_mana(&s, tl, s.hero_ready);
      int name = choose(&s, tl, s.hero_ready);
      if (name < 0) break;
      begin_cast(&s, tl, name, s.hero_ready);
    }
    double when; int kind;
    pop(&s, &when, &kind);
    if (when >= FIGHT) break;
    if (kind == E_SWING) {
      if (when < s.busy_until) {
        push(&s, s.busy_until, E_SWING);
      } else {
        record(&s, tl, sc, &q, c, comp, when, K_AUTO, 1.0);
        double gain = tl->attack_mana + tl->attack_mana_pct * tl->mana_max;
        if (tl->attack_mana_crit != 0.0) {
          double cc = (100.0 < tl->crit) ? 100.0 : tl->crit;
          gain *= 1.0 + cc / 100.0;
        }
        double v = s.mana + gain;
        s.mana = (v < tl->mana_max) ? v : tl->mana_max;
        if (tl->mask & S_SULF) {
          if (s.armed) {
            s.armed = 0;
            record(&s, tl, sc, &q, c, comp, when, K_SULF, (double)targets);
          }
          record(&s, tl, sc, &q, c, comp, when, K_ECHO, 1.0);
        }
        if (tl->mask & S_ORB) record(&s, tl, sc, &q, c, comp, when, K_SPLASH, (double)targets);
        double st = when + tl->stun_ps;
        if (st > s.hero_ready) s.hero_ready = st;
        push(&s, when + tl->swing + tl->stun_ps, E_SWING);
      }
    } else if (kind >= E_FIN0 && kind < E_FIN0 + NS) {
      resolve(&s, tl, sc, &q, c, comp, kind - E_FIN0, when);
    } else if (kind == E_SWP) {
      double active = 0.0;
      for (int i = 0; i < targets; i++) active = active + swp_on(&s, i, when);
      if (active > 1e-9) {
        record(&s, tl, sc, &q, c, comp, when, K_SWP, active);
        push(&s, when + tl->swp_period, E_SWP);
      }
    } else if (kind == E_VOID) {
      record(&s, tl, sc, &q, c, comp, when, K_VOID, (double)targets);
      if (TM(tl, T_COSM)) {
        double pv = 0.25 * (1.0 + tl->luck);
        double p = (pv < 1.0) ? pv : 1.0;
        for (int i = 0; i < targets; i++) {
          double on = swp_on(&s, i, when);
          if (on > 0.0) record(&s, tl, sc, &q, c, comp, when, K_SWPI, p * on);
          if (!swp_any(&s, targets, when) && p > 0.0) push(&s, when + tl->swp_period, E_SWP);
          swp_maybe(&s, i, when, p);
        }
      }
    } else if (kind == E_NAARU) {
      if (when <= s.naaru_until) {
        naaru_hit(&s, tl, sc, &q, c, comp, when);
        if (when + 1.0 <= s.naaru_until) push(&s, when + 1.0, E_NAARU);
      }
    } else if (kind == E_HELL) {
      record(&s, tl, sc, &q, c, comp, when, K_HELL, (double)targets);
      push(&s, when + 1.25, E_HELL);
    } else if (kind == E_BLAZE) {
      if (when <= s.blaze_until) {
        record(&s, tl, sc, &q, c, comp, when, K_BLAZE, (double)targets);
        if (when + 1.0 <= s.blaze_until) push(&s, when + 1.0, E_BLAZE);
      }
    }
    if (s.nb) flush(&s, sc, &q, c, comp);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  int st = 0;
  double taken = armor_taken(15.0 - sc->armor_pen, &st);
  double taken_stab = armor_taken(15.0, &st);
  if (st) { *status_out = st; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < q.nord; i++) {
    int id = q.ord[i];
    total += q.src[id] * ((id == SRC_STAB) ? taken_stab : taken);
  }
  return total / FIGHT;
}

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  int nmag; __global const int* mag_kind; __global const int* mag_id; __global const double* mag_amt;
  int nphy; __global const int* phy_kind; __global const int* phy_id; __global const double* phy_amt;
  __global const double* base; __global const ulong* ek; __global const double* ev; int ne;
} Tab;

/* farm chunk -> six piece ids; 0 on success */
NI int unrank(Tab* T, long index, int* chosen) {
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

/* math.exp of the host Python, looked up by the exact argument bits */
double exp_lookup(Tab* T, double x, int* status, ulong* miss) {
  ulong key = as_ulong(x);
  int lo = 0, hi = T->ne;
  while (lo < hi) {
    int mid = (lo + hi) >> 1;
    if (T->ek[mid] < key) lo = mid + 1; else hi = mid;
  }
  if (lo < T->ne && T->ek[lo] == key) return T->ev[lo];
  *status = 7;
  *miss = key;
  return 0.0;
}

/* shadow.character(build) with bake_timed_buffs=True; 0 or a status */
NI int sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group, ulong* miss) {
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
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (GM(r, G_FORT)) intel += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  damage = 10.0 + 0.75 * intel + damage;
  mana = 175.0 + 7.0 * intel + mana;
  if (TM(r, T_CLAI)) crit += 8.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  double agility_speed = 0.004 * agility;
  agility_speed = (1.0 <= agility_speed) ? 1.0 : agility_speed;
  double asum = aspd + agility_speed;
  asum = (4.0 <= asum) ? 4.0 : asum;
  aspd = (-0.8 >= asum) ? -0.8 : asum;
  double attack_base = 2.0 * ((mask & S_GALA) ? 1.20 : 1.0);
  double luck = 0.01 * (double)pts[9];
  for (int si = 0; si < 6; si++) if (first[si]) luck += T->uniq[(long)chosen[si] * NU + 13];
  if (GM(r, G_FORTUNE)) luck += 0.15;
  if (GM(r, G_FREN)) {
    double unbuffed = attack_base / (1.0 + aspd);
    double fc = 0.18 * (1.0 + luck);
    fc = (fc < 1.0) ? fc : 1.0;
    double uptime = 5.0 / (5.0 + unbuffed / fc);
    double a = aspd + 0.32 * uptime;
    a = (4.0 <= a) ? 4.0 : a;
    aspd = (-0.8 >= a) ? -0.8 : a;
  }
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
  double stab_ch = 0.0, stab_ra = 0.0, auto_pct = 1.0, regen_rate = 0.0, mp5 = 0.0;
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
  if (crit_as > 0.0 && crit > 0.0 && crit_as_dur > 0.0) {
    double base_speed = aspd;
    for (int it = 0; it < 2; it++) {
      double swing = attack_base / (1.0 + aspd);
      double cc = (100.0 < crit) ? 100.0 : crit;
      double rate = cc / 100.0 / swing;
      int st = 0;
      double e = exp_lookup(T, (-rate) * crit_as_dur, &st, miss);
      if (st) return st;
      double uptime = 1.0 - e;
      double a = base_speed + crit_as * uptime;
      a = (4.0 <= a) ? 4.0 : a;
      aspd = (-0.8 >= a) ? -0.8 : a;
    }
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

  r->intel = intel; r->str = strength; r->potency = potency; r->mastery = mastery; r->ad = damage;
  r->mana_max = mana; r->crit = (100.0 <= crit) ? 100.0 : crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->spell_mult = sc65 ? 1.65 : 1.50;
  r->flat_cdr = flat_cdr; r->cd_temp = cd_temp; r->stun_ps = stun_ps; r->cast_lock = cast_lock;
  r->attack_potency = dap ? 2.0 : 1.0; r->auto_pct = auto_pct; r->armor_pen = armor_pen;
  r->soul_rate = (mask & S_SOUL) ? 0.003 : 0.0; r->stab_chance = stab_ch; r->stab_ratio = stab_ra;
  r->luck = luck;
  r->attack_base = attack_base;
  r->swing = attack_base / (1.0 + aspd);
  r->swp_period = 1.0 / (1.0 + haste);
  r->mana_regen = stat * 0.80;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->mag_sum = mag_sum; r->phys_sum = phys_sum;
  r->spell_crit = sc; r->nexec = nexec; r->targets = targets;
  return 0;
}

/* mode 0: shadow.simulate(...).dps; mode 1: farm.score._priest ESC score (compile + score_compiled) */
double row_value(Tab* T, long index, uint tmask, uint gmask, const int* pts, const int* tlpts, int mode, int targets,
                 int* status, int* group, ulong* miss) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row sc;
  int st = sheet(T, &sc, chosen, tmask, gmask, pts, targets, group, miss);
  if (st) { *status = st; return 0.0; }
  int same = 1;
  for (int j = 0; j < NP; j++) if (pts[j] != tlpts[j]) { same = 0; break; }
  Row tl;
  if (same) {
    tl = sc;
  } else {
    int g2 = 0;
    st = sheet(T, &tl, chosen, tmask, gmask, tlpts, targets, &g2, miss);
    if (st) { *status = st; return 0.0; }
  }
#if TALENTS
  int comp = mode == 1;
#else
  int comp = 0;
#endif
  Comp best_c, c;
  double best = 0.0;
  int spells[NS];
  int ring = (sc.mask & S_RING) != 0;
  int nv = ring ? cast_spells(&sc, spells) : 1;
  for (int i = 0; i < nv; i++) {
    double d = fight(&tl, &sc, ring ? spells[i] : -1, &c, comp, status);
    if (*status) return 0.0;
    if (i == 0 || d > best) {
      best = d;
      if (comp) best_c = c;
    }
  }
  if (!comp) return best;
  double total = score_compiled(&sc, &best_c, status);
  return total / FIGHT;
}

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    const int nmag, __global const int* mag_kind, __global const int* mag_id, __global const double* mag_amt, \
    const int nphy, __global const int* phy_kind, __global const int* phy_id, __global const double* phy_amt, \
    __global const double* base, __global const ulong* ek, __global const double* ev, const int ne

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.nmag = nmag; T.mag_kind = mag_kind; T.mag_id = mag_id; T.mag_amt = mag_amt; \
  T.nphy = nphy; T.phy_kind = phy_kind; T.phy_id = phy_id; T.phy_amt = phy_amt; \
  T.base = base; T.ek = ek; T.ev = ev; T.ne = ne;

__kernel void priest_bare(const long start, const int n, const int targets, TAB_ARGS,
    __global double* out_dps, __global uchar* out_group, __global uchar* out_status, __global ulong* out_miss)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP];
  for (int j = 0; j < NP; j++) pts[j] = 0;
  int status = 0, group = 0;
  ulong miss = 0;
  double d = row_value(&T, start + gid, 0u, 0u, pts, pts, 0, targets, &status, &group, &miss);
  out_dps[gid] = d;
  out_group[gid] = (uchar)group;
  out_status[gid] = (uchar)status;
  out_miss[gid] = miss;
}

__kernel void priest_rows(const int n, const int targets, const int mode, __global const long* chunks,
    __global const uint* tmasks, __global const uint* gmasks, __global const int* points, __global const int* tlpoints,
    TAB_ARGS, __global double* out_dps, __global uchar* out_group, __global uchar* out_status, __global ulong* out_miss)
{
  int gid = get_global_id(0);
  if (gid >= n) return;
  TAB_INIT
  int pts[NP], tlp[NP];
  for (int j = 0; j < NP; j++) { pts[j] = points[(long)gid * NP + j]; tlp[j] = tlpoints[(long)gid * NP + j]; }
  int status = 0, group = 0;
  ulong miss = 0;
  double d = row_value(&T, chunks[gid], tmasks[gid], gmasks[gid], pts, tlp, mode, targets, &status, &group, &miss);
  out_dps[gid] = d;
  out_group[gid] = (uchar)group;
  out_status[gid] = (uchar)status;
  out_miss[gid] = miss;
}
"""

SPECIAL_BITS = {
    "I00D": 0, "I0BR": 1, "I07O": 2, "I0JO": 3, "I0QT": 4, "I096": 5, "I03C": 6, "I00L": 7,
    "I00Y": 8, "I07P": 9, "I048": 10, "I03L": 11, "tlum": 12, "I0FW": 13,
}
TALENT_BITS = {
    "I0KF": 0, "I0HL": 1, "I0PU": 2, "I0PS": 3, "I0HP": 4, "I0SA": 5, "I0SB": 6, "I0SC": 7,
    "I0KG": 8, "I0MJ": 9, "I0KH": 10,
}
GLYPH_BITS = {
    "I07B": 0, "I0AV": 1, "I0EK": 2, "I0GZ": 3, "I0H3": 4, "I0H5": 5, "I0H6": 6, "I0HC": 7,
    "I0JA": 8, "I0OF": 9, "I0H0": 10, "I0EJ": 11,
}
# Codes the priest oracle never reads: picking them changes nothing in the fight.
NO_EFFECT = {"I0EN"}
SPECS = {"shadow": 0, "discipline": 1, "holy": 2}
NF = 15
NU = 48
NP = 11
MULTI = 4
EXP_MISS = 7
MAX_EXP_ROUNDS = 8


def _pad(values, fill, what, code):
    values = list(values)
    if len(values) > MULTI:
        raise ValueError(f"{code}: more than {MULTI} {what} entries in the tooltip")
    return values + [fill] * (MULTI - len(values))


def tables(space, items: dict, sources: dict) -> dict:
    """Per-piece arrays in the exact form the kernel folds. Pure function of the catalog."""
    from sunken_sim import shadow
    from sunken_sim.stacking import stack_fields

    pieces = space.pieces
    codes = [p.code for p in pieces]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate rawcodes in the chunk space")
    if space.slots != 6:
        raise ValueError("kernel expects six slots")
    if shadow.LEVEL != 15 or shadow.FIGHT != 30.0 or shadow.MEDIAN_MONSTER_HP != 5300.0:
        raise ValueError("kernel constants assume shadow.LEVEL 15, a 30 s fight and 5300 monster HP")
    if shadow.DUMMY_ARMOR != 15.0 or shadow.ARMOR_FACTOR != 0.04 or shadow.CHAOS_UNARMORED != 1.25:
        raise ValueError("kernel constants assume 15 armour, factor 0.04 and chaos 1.25")
    clash = set(codes) & (set(TALENT_BITS) | set(GLYPH_BITS))
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
            shadow.item_luck(item),
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
            raise ValueError(f"talent/glyph {c} is not modelled by the Priest kernel")
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
        "base": np.asarray([shadow.BASE_INT, shadow.BASE_STR, shadow.BASE_AGI], dtype=np.float64),
    }


TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
              "nmag", "mag_kind", "mag_id", "mag_amt", "nphy", "phy_kind", "phy_id", "phy_amt", "base")
SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32, "nmag": np.int32, "nphy": np.int32}


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


# ---------------------------------------------------------------- Python reference
class _NoStore(dict):
    """A shadow._TIMELINE that never keeps anything: every simulate() runs its own fight."""

    def __setitem__(self, key, value):
        pass


@contextlib.contextmanager
def uncached():
    from sunken_sim import shadow

    old = shadow._TIMELINE
    shadow._TIMELINE = _NoStore()
    try:
        yield
    finally:
        shadow._TIMELINE = old


def make_build(space, items: dict, chunk: int, talents=(), glyphs=(), points: dict | None = None):
    from sunken_sim.esc import apply_points
    from sunken_sim.shadow import Build

    codes = space.decode(chunk)[0]
    build = Build(frozenset(talents), frozenset(glyphs), tuple(items[c] for c in codes), 0, 0, 0, 0)
    return apply_points(build, points) if points else build


def py_value(spec: str, targets: int, build, build_tl=None, mode: int = 0) -> float:
    """What the kernel computes, in Python: the fight on build_tl's sheet, the score on build's.

    mode 0 is shadow.simulate(build).dps, mode 1 the farm.score._priest ESC score.
    With build_tl=None both are the same build (no cached timeline in play).
    """
    from sunken_sim import shadow

    build_tl = build if build_tl is None else build_tl
    stats = shadow.character(build)
    st_tl = stats if build_tl is build else shadow.character(build_tl)
    variants = shadow._cast_spells(build, spec) if shadow._wears(build, "I00D") else [None]
    best = None
    for bound in variants:
        events, _actions, windows, _left = shadow._fight_events(build_tl, st_tl, spec, targets, bound)
        total, _sources = shadow.score_events(events, build, stats, spec=spec, windows=windows)
        dps = total / shadow.FIGHT
        if best is None or dps > best[0]:
            best = (dps, events, windows)
    if mode == 0:
        return best[0]
    compiled = shadow.compile_events(best[1], build, stats, spec, best[2])
    return shadow.score_compiled(compiled, stats, stats["potency"], min(100.0, stats["crit"]), stats["mastery"],
                                 stats["luck"]) / shadow.FIGHT


def esc_score(spec: str, targets: int, build) -> float:
    """farm.score._priest's score closure for one build, with no timeline reuse."""
    from farm.hybrid.mage_priest_resources import canonical_final_dps

    with uncached():
        return canonical_final_dps("priest", spec, targets, build)


def timeline_key(spec: str, targets: int, build):
    """The shadow._TIMELINE key(s) simulate() would look up for this build."""
    from sunken_sim import shadow

    stats = shadow.character(build)
    if shadow._wears(build, "I00D"):
        return tuple(shadow._timeline_key(build, stats, spec, targets, b) for b in shadow._cast_spells(build, spec))
    return shadow._timeline_key(build, stats, spec, targets, None)


# ---------------------------------------------------------------- device engine
class PriestCL:
    """Compiled kernels plus device-resident catalog tables for one Priest spec and chunk space."""

    hero = "priest"

    def __init__(self, space, items: dict, sources: dict, targets: int, device=None, spec: str = "shadow") -> None:
        from farm.hybrid.mage_cl import _import_cl, pick_device

        if spec not in SPECS:
            raise ValueError(f"priest spec {spec!r} is not modelled by the kernel")
        cl = _import_cl()
        self.cl = cl
        self.spec = spec
        self.space = space
        self.items = items
        self.device = device or pick_device(cl)
        self.ctx = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.ctx)
        opts = ["-cl-std=CL1.2", f"-DSPEC={SPECS[spec]}"]
        # Same arithmetic either way; real calls only shorten compile times.
        if os.environ.get("FARM_CL_NOINLINE", "").strip() == "1":
            opts.append("-DNOINLINE=1")
        self.p_bare = cl.Program(self.ctx, KERNEL).build(options=opts + ["-DTALENTS=0"])
        self.p_full = cl.Program(self.ctx, KERNEL).build(options=opts + ["-DTALENTS=1"])
        self.k_bare = cl.Kernel(self.p_bare, "priest_bare")
        self.k_bare_rows = cl.Kernel(self.p_bare, "priest_rows")
        self.k_rows = cl.Kernel(self.p_full, "priest_rows")
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
        self.exp_keys = np.zeros(0, dtype=np.uint64)
        self.exp_vals = np.zeros(0, dtype=np.float64)
        self._exp_upload()
        self._cap = 0
        self.name = f"{self.device.name.strip()} ({self.device.platform.name.strip()})"
        self.counts = {"bare_rows": 0, "rows": 0, "oracle_rows": 0, "refined": 0, "exp_values": 0, "exp_reruns": 0}

    # -- math.exp table -------------------------------------------------
    def _exp_upload(self) -> None:
        cl = self.cl
        mf = cl.mem_flags
        keys = self.exp_keys if len(self.exp_keys) else np.zeros(1, dtype=np.uint64)
        vals = self.exp_vals if len(self.exp_vals) else np.zeros(1, dtype=np.float64)
        self.ek = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(keys))
        self.ev = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(vals))

    def _exp_args(self):
        return [self.ek, self.ev, np.int32(len(self.exp_keys))]

    def exp_add(self, keys) -> int:
        """Add math.exp of the float64 arguments with these bit patterns (the host Python's libm)."""
        keys = np.unique(np.asarray(keys, dtype=np.uint64))
        if len(self.exp_keys):
            keys = keys[~np.isin(keys, self.exp_keys)]
        if not len(keys):
            return 0
        args = keys.view(np.float64)
        vals = np.array([math.exp(float(x)) for x in args], dtype=np.float64)
        at = np.searchsorted(self.exp_keys, keys)
        self.exp_keys = np.insert(self.exp_keys, at, keys)
        self.exp_vals = np.insert(self.exp_vals, at, vals)
        if len(self.exp_keys) >= (1 << 31) - 1:
            raise RuntimeError("exp table too large")
        self._exp_upload()
        self.counts["exp_values"] = len(self.exp_keys)
        return len(keys)

    # -- launches -------------------------------------------------------
    def _ensure(self, n: int) -> None:
        if n <= self._cap:
            return
        cl = self.cl
        mf = cl.mem_flags
        self._cap = max(n, 1 << 16)
        self.out_dps = cl.Buffer(self.ctx, mf.WRITE_ONLY, 8 * self._cap)
        self.out_group = cl.Buffer(self.ctx, mf.WRITE_ONLY, self._cap)
        self.out_status = cl.Buffer(self.ctx, mf.WRITE_ONLY, self._cap)
        self.out_miss = cl.Buffer(self.ctx, mf.WRITE_ONLY, 8 * self._cap)

    def _read(self, n):
        dps = np.empty(n, dtype=np.float64)
        group = np.empty(n, dtype=np.uint8)
        status = np.empty(n, dtype=np.uint8)
        miss = np.empty(n, dtype=np.uint64)
        cl = self.cl
        cl.enqueue_copy(self.queue, dps, self.out_dps)
        cl.enqueue_copy(self.queue, group, self.out_group)
        cl.enqueue_copy(self.queue, status, self.out_status)
        cl.enqueue_copy(self.queue, miss, self.out_miss)
        self.queue.finish()
        return dps, group, status, miss

    def _launch_rows(self, kernel, mode, chunks, tmasks, gmasks, points, tlpoints):
        cl = self.cl
        n = len(chunks)
        self._ensure(n)
        mf = cl.mem_flags

        def buf(a):
            return cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(a))

        # The buffers must outlive the launch: a kernel argument does not keep its buffer alive.
        args = [buf(np.asarray(chunks, dtype=np.int64)), buf(np.asarray(tmasks, dtype=np.uint32)),
                buf(np.asarray(gmasks, dtype=np.uint32)), buf(np.asarray(points, dtype=np.int32).reshape(n, NP)),
                buf(np.asarray(tlpoints, dtype=np.int32).reshape(n, NP))]
        kernel.set_args(np.int32(n), np.int32(self.targets), np.int32(mode), *args,
                        *self.tab_args, *self._exp_args(), self.out_dps, self.out_group, self.out_status, self.out_miss)
        cl.enqueue_nd_range_kernel(self.queue, kernel, (n,), None)
        out = self._read(n)
        del args
        return out

    def _settle(self, dps, group, status, miss, rerun) -> None:
        """Fill the exp table for rows that missed and run them again until none miss."""
        for _ in range(MAX_EXP_ROUNDS):
            idx = np.nonzero(status == EXP_MISS)[0]
            if not len(idx):
                return
            self.exp_add(miss[idx])
            d, g, s, m = rerun(idx)
            dps[idx] = d
            group[idx] = g
            status[idx] = s
            miss[idx] = m
            self.counts["exp_reruns"] += len(idx)

    def bare(self, start: int, n: int):
        """(dps float64[n], group uint8[n], status uint8[n]) for item-only chunks [start, start+n)."""
        cl = self.cl
        self._ensure(n)
        self.k_bare.set_args(np.int64(start), np.int32(n), np.int32(self.targets), *self.tab_args, *self._exp_args(),
                             self.out_dps, self.out_group, self.out_status, self.out_miss)
        cl.enqueue_nd_range_kernel(self.queue, self.k_bare, (n,), None)
        dps, group, status, miss = self._read(n)
        self.counts["bare_rows"] += n
        zeros = np.zeros((1, NP), dtype=np.int32)

        def rerun(idx):
            k = len(idx)
            pts = np.repeat(zeros, k, axis=0)
            return self._launch_rows(self.k_bare_rows, 0, start + idx.astype(np.int64), np.zeros(k, np.uint32),
                                     np.zeros(k, np.uint32), pts, pts)

        self._settle(dps, group, status, miss, rerun)
        return dps, group, status

    def rows(self, chunks, tmasks, gmasks, points, tlpoints=None, mode: int = 0):
        """Explicit fights: chunk, talent mask, glyph mask, ESC points (ESC_ATTRS order), timeline points."""
        n = len(chunks)
        if n == 0:
            return np.empty(0), np.empty(0, np.uint8), np.empty(0, np.uint8)
        chunks = np.asarray(chunks, dtype=np.int64)
        tmasks = np.asarray(tmasks, dtype=np.uint32)
        gmasks = np.asarray(gmasks, dtype=np.uint32)
        points = np.asarray(points, dtype=np.int32).reshape(n, NP)
        tlpoints = points if tlpoints is None else np.asarray(tlpoints, dtype=np.int32).reshape(n, NP)
        dps, group, status, miss = self._launch_rows(self.k_rows, mode, chunks, tmasks, gmasks, points, tlpoints)
        self.counts["rows"] += n

        def rerun(idx):
            return self._launch_rows(self.k_rows, mode, chunks[idx], tmasks[idx], gmasks[idx], points[idx], tlpoints[idx])

        self._settle(dps, group, status, miss, rerun)
        return dps, group, status

    # -- Python reference for declined rows -----------------------------
    def oracle_bare(self, chunk: int) -> float:
        return py_value(self.spec, self.targets, make_build(self.space, self.items, chunk))

    def oracle_fight(self, chunk: int, talents, glyphs, points: dict, tl_points: dict | None = None, mode: int = 0) -> float:
        build = make_build(self.space, self.items, chunk, talents, glyphs, points)
        build_tl = None if tl_points is None else make_build(self.space, self.items, chunk, talents, glyphs, tl_points)
        return py_value(self.spec, self.targets, build, build_tl, mode)

    def scores(self, chunk: int, builds: list, mode: int = 0) -> list[float]:
        """Exact values for (talents, glyphs, points dict[, timeline points dict]) of one chunk."""
        from sunken_sim.esc import ESC_ATTRS

        chunks = [chunk] * len(builds)
        tm = [talent_mask(b[0]) for b in builds]
        gm = [glyph_mask(b[1]) for b in builds]
        pts = [[int(b[2].get(a, 0)) for a in ESC_ATTRS] for b in builds]
        tlp = [[int((b[3] if len(b) > 3 and b[3] is not None else b[2]).get(a, 0)) for a in ESC_ATTRS] for b in builds]
        dps, _group, status = self.rows(chunks, tm, gm, pts, tlp, mode)
        out = [float(v) for v in dps]
        for j in np.nonzero((status != 0) | ~np.isfinite(dps))[0]:
            b = builds[int(j)]
            out[int(j)] = self.oracle_fight(chunk, b[0], b[1], b[2], b[3] if len(b) > 3 else None, mode)
            self.counts["oracle_rows"] += 1
        return out

    def refine(self, chunk: int, equipped: tuple, talent_codes, glyph_codes, picks_without, picks_with, glyph_picks):
        """farm.score.finish_sextuple for this Priest spec, every fight on the device.

        The ESC trials replay simulate()'s timeline cache within the sextuple: a
        trial whose key was seen before runs on the first such trial's points.
        """
        from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points, points_payload
        from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS, Build

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
        base = Build(frozenset(best_talents), frozenset(best_glyphs), equipped, 0, 0, 0, 0)
        seen: dict = {}

        def timeline(points: dict) -> dict:
            key = timeline_key(self.spec, self.targets, apply_points(base, points))
            return seen.setdefault(key, dict(points))

        # sunken_sim.esc.greedy_points, one device launch per step
        counts = empty_points()
        pointed = self.scores(chunk, [(best_talents, best_glyphs, counts, timeline(counts))], mode=1)[0]
        for _ in range(SKILL_POINTS):
            names = [a for a in ESC_ATTRS if counts[a] < ESC_CAP]
            trials = []
            for name in names:
                trial = dict(counts)
                trial[name] += 1
                trials.append((best_talents, best_glyphs, trial, timeline(trial)))
            values = self.scores(chunk, trials, mode=1)
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


# ---------------------------------------------------------------- parity against the real Python entry points
def oracle(space, items: dict, targets: int, index: int, spec: str) -> float:
    """farm.score.item_dps for one chunk, every fight run (no timeline reuse)."""
    from farm.score import item_dps

    codes = space.decode(index)[0]
    with uncached():
        return item_dps("priest", spec, targets, tuple(items[c] for c in codes))


def parity(engine: PriestCL, space, items: dict, sources: dict, targets: int, indices) -> dict:
    """Bit-exact comparison of the bare scan against farm.score.item_dps (dps and source group)."""
    from farm.hybrid.mage_cl import GROUP_NAMES
    from farm.runner import build_group

    indices = [int(i) for i in indices]
    bad = []
    fallback = 0
    if not indices:
        return {"rows": 0, "mismatches": 0, "status_rows": 0, "examples": [], "ok": True}
    for index in indices:
        dps, group, status = engine.bare(index, 1)
        ref = oracle(space, items, targets, index, engine.spec)
        if status[0]:
            fallback += 1
            continue
        codes = space.decode(index)[0]
        ref_group = build_group([sources.get(c, "drop") for c in codes])
        if float(dps[0]).hex() != float(ref).hex() or GROUP_NAMES[int(group[0])] != ref_group:
            bad.append({"chunk": index, "kernel": float(dps[0]), "oracle": float(ref)})
    return {"rows": len(indices), "mismatches": len(bad), "status_rows": fallback, "examples": bad[:5], "ok": not bad}


def random_builds(space, count: int, seed: int) -> list:
    """(chunk, talents, glyphs, points) drawn like refinement: legal picks, ESC under cap 20, total <= 30."""
    from farm.hybrid.mage_cl import random_builds as _random_builds

    return _random_builds(space, count, seed)


def parity_full(engine: PriestCL, space, items: dict, targets: int, builds, mode: int = 0) -> dict:
    """Bit-exact comparison of talent/glyph/ESC fights: mode 0 against shadow.simulate(...).dps,
    mode 1 against farm.score._priest's ESC score."""
    from sunken_sim import shadow
    from sunken_sim.esc import ESC_ATTRS

    chunks = [b[0] for b in builds]
    dps, _g, status = engine.rows(chunks, [talent_mask(b[1]) for b in builds], [glyph_mask(b[2]) for b in builds],
                                  [[b[3][a] for a in ESC_ATTRS] for b in builds], None, mode)
    bad = []
    fallback = 0
    for (chunk, talents, glyphs, points), value, st in zip(builds, dps, status):
        if st:
            fallback += 1
            continue
        build = make_build(space, items, chunk, talents, glyphs, points)
        if mode == 0:
            with uncached():
                ref = shadow.simulate(build, targets, spec=engine.spec, use_history=False).dps
        else:
            ref = esc_score(engine.spec, targets, build)
        if float(value).hex() != float(ref).hex():
            bad.append({"chunk": chunk, "talents": talents, "glyphs": glyphs, "points": {k: v for k, v in points.items() if v},
                        "kernel": float(value), "oracle": float(ref)})
    return {"rows": len(builds), "mismatches": len(bad), "status_rows": fallback, "examples": bad[:5], "ok": not bad}


def parity_timeline(engine: PriestCL, space, items: dict, targets: int, builds, seed: int) -> dict:
    """Rows whose fight runs on other points than their score (the replayed timeline cache)."""
    import random

    from sunken_sim.esc import ESC_ATTRS

    rng = random.Random(seed)
    tl = []
    for _chunk, _t, _g, points in builds:
        other = dict(points)
        for _ in range(rng.randrange(1, 4)):
            a = rng.choice(ESC_ATTRS)
            other[a] = max(0, min(20, other[a] + rng.choice((-2, -1, 1, 2))))
        tl.append(other)
    mode = 1
    dps, _g, status = engine.rows([b[0] for b in builds], [talent_mask(b[1]) for b in builds],
                                  [glyph_mask(b[2]) for b in builds], [[b[3][a] for a in ESC_ATTRS] for b in builds],
                                  [[p[a] for a in ESC_ATTRS] for p in tl], mode)
    bad = []
    fallback = 0
    for (chunk, talents, glyphs, points), other, value, st in zip(builds, tl, dps, status):
        if st:
            fallback += 1
            continue
        ref = engine.oracle_fight(chunk, talents, glyphs, points, other, mode)
        if float(value).hex() != float(ref).hex():
            bad.append({"chunk": chunk, "kernel": float(value), "oracle": float(ref)})
    return {"rows": len(builds), "mismatches": len(bad), "status_rows": fallback, "examples": bad[:5], "ok": not bad}


def self_check(engine: PriestCL, space, items: dict, sources: dict, targets: int, rows: int, full: int, seed: int):
    """(bare parity, fight parity): random chunks, then random talent/glyph/ESC fights scored both ways
    (simulate().dps and the ESC score) and with a replayed timeline."""
    from farm.hybrid.mage_cl import sample

    check = parity(engine, space, items, sources, targets, sample(space, rows, seed))
    builds = random_builds(space, full, seed + 1)
    parts = [parity_full(engine, space, items, targets, builds, 0), parity_full(engine, space, items, targets, builds, 1),
             parity_timeline(engine, space, items, targets, builds, seed + 2)]
    fights = {
        "rows": sum(p["rows"] for p in parts),
        "mismatches": sum(p["mismatches"] for p in parts),
        "status_rows": sum(p["status_rows"] for p in parts),
        "examples": [e for p in parts for e in p["examples"]][:5],
        "ok": all(p["ok"] for p in parts),
    }
    return check, fights


def find_chunk(space, codes) -> int:
    """Chunk index of a six-item multiset (the space ranks item multiplicity vectors in order)."""
    order = [p.code for p in space.pieces]

    def vec(cs):
        return tuple(sum(1 for c in cs if c == o) for o in order)

    target = vec(codes)
    lo, hi = (space.count_without, space.total) if "I0IC" in codes else (0, space.count_without)
    while lo < hi:
        mid = (lo + hi) // 2
        if vec(space.decode(mid)[0]) < target:
            lo = mid + 1
        else:
            hi = mid
    if sorted(space.decode(lo)[0]) != sorted(codes):
        raise KeyError(f"{codes} is not a chunk of this space")
    return lo


def finish_reference(spec: str, targets: int, equipped: tuple, space):
    """farm.score.finish_sextuple as one CPU worker runs it on a fresh timeline cache."""
    from farm.score import finish_sextuple
    from sunken_sim import shadow

    old = shadow._TIMELINE
    shadow._TIMELINE = {}
    try:
        return finish_sextuple("priest", spec, targets, equipped, space.talents, space.glyphs, space.picks_without,
                               space.picks_with, space.glyph_picks)
    finally:
        shadow._TIMELINE = old
