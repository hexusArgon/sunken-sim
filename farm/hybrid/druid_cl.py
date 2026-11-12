"""Exact float64 OpenCL kernel for Druid fights (Restoration, Balance).

The Druid (E009, intellect caster, ``sunken_sim.druid``) only. The Feral Druid
(``sunken_sim.feral_druid``, O00R) is a separate class and is not modelled here.

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.druid.sheet`` (``shadow.character`` with the druid bases, white 11,
no baked buffs, 2.0 s swing, Druidism potency), run the event loop of
``druid._simulate_druid`` (every Diamond Ring binding; heap of (time, order))
and score every event as ``druid.score_events`` the moment it is emitted.
Host side: farm.hybrid.class_cl; the sheet, unrank and kernels are shared with
farm.hybrid.shaman_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C
from farm.hybrid import shaman_cl as _S


def _cut(text: str, start: str, end: str, inclusive: bool = False) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i: j + (len(end) if inclusive else 0)]


_ROW = _cut(_S.KERNEL, "typedef struct {\n  double intel, str, agi", "} Row;", inclusive=True)
_SHEET = _cut(_S.KERNEL, "#define IDX(item", "double row_value(")
_SHEET = (_SHEET.replace("damage = 13.0 + 0.75 * intel + damage;", "damage = 11.0 + 0.75 * intel + damage;")
          .replace("r->attack_base = 1.85 * ((mask & S_GALA) ? 1.20 : 1.0);",
                   "r->attack_base = 2.0 * ((mask & S_GALA) ? 1.20 : 1.0);")
          .replace("/* shaman.sheet(build): shadow.character(bases, white 13, bake_timed_buffs=False), 1.85 s swing */",
                   "/* druid.sheet(build): shadow.character(bases, white 11, bake_timed_buffs=False), 2.0 s swing */"))
assert "11.0 + 0.75 * intel" in _SHEET and "2.0 * ((mask & S_GALA)" in _SHEET
_KERNELS = _cut(_S.KERNEL, "#define TAB_ARGS", "SENTINEL") if "SENTINEL" in _S.KERNEL else _S.KERNEL[_S.KERNEL.index("#define TAB_ARGS"):]

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 restoration, 1 balance */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_BAL (SPEC == 1)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define MAXQ 256
#define MAXF 160
#define MAXW 200
#define NSRC 10

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
#define S_MOON (1UL<<14)
#define S_WISPI (1UL<<15)
#define S_TREANTI (1UL<<16)
#define S_SILM (1UL<<20)

#define T_SURGE (1u<<0)
#define T_WRATH (1u<<1)
#define T_STARL (1u<<2)
#define T_WISP (1u<<3)
#define T_ENT (1u<<4)
#define T_FORCE (1u<<5)
#define T_SPREAD (1u<<6)
#define T_ECHO (1u<<7)
#define T_MISSILE (1u<<8)
#define T_DRUIDISM (1u<<9)

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

/* buttons, in druid.buttons order of BOUND_NAME keys */
#define B_STARFIRE 0
#define B_STARFALL 1
#define B_ENTANGLE 2
#define B_WISP 3

/* clock kinds */
#define K_CAST 0
#define K_ECHO 1
#define K_STAR 2
#define K_MISSILE 3
#define K_ROOT 4
#define K_TREANT 5

/* sources */
#define N_AUTO 0
#define N_STARFIRE 1
#define N_ECHO_SF 2
#define N_STARFALL 3
#define N_ENT 4
#define N_TREANTS 5
#define N_WISP 6
#define N_SPLASH 7
#define N_SULF 8
#define N_SULF_ECHO 9

""" + _ROW + r"""

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double taken_plain, taken_wisp, echo_ch;
} Sco;

typedef struct {
  double q_w[MAXQ]; uint q_s[MAXQ]; int q_k[MAXQ]; double q_d[MAXQ]; int q_i[MAXQ];
  double f_end[MAXF];
  double w_end[MAXW], w_w[MAXW]; uchar w_main[MAXW];
  double ready[4]; int has[4];
  double mana, mana_time, root_until;
  uint seq;
  int qn, nf, nw, status, bound, targets, armed;
  double surge, wisp_life;
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

/* shadow._magical_multiplier(codes, when, mastery, extra) for druid codes */
inline double magical(const Row* r, double t, double mastery, double extra) {
  double ta = r->mag_sum;
  if (r->mask & S_SULG) ta += 0.13 + 0.25 * target_hp(t);
  double bonus = 1.0 + ta + extra;
  double slope = 0.0;
  if (r->mask & S_TLUM) { bonus += 0.05; slope = 0.005; }
  if (GM(r, G_GLASS)) { bonus *= 1.15; slope *= 1.15; }
  return bonus + slope * mastery;
}

/* ---- clock: heapq of (when, order, kind, payload) ---- */
void push(St* s, double when, int kind, double pd, int pi) {
  if (when >= FIGHT) return;
  s->seq += 1;
  if (s->qn >= MAXQ) { s->status = 2; return; }
  int i = s->qn++;
  uint sq = s->seq;
  while (i > 0) {
    int p = (i - 1) >> 1;
    if (when < s->q_w[p] || (when == s->q_w[p] && sq < s->q_s[p])) {
      s->q_w[i] = s->q_w[p]; s->q_s[i] = s->q_s[p]; s->q_k[i] = s->q_k[p]; s->q_d[i] = s->q_d[p]; s->q_i[i] = s->q_i[p];
      i = p;
    } else break;
  }
  s->q_w[i] = when; s->q_s[i] = sq; s->q_k[i] = kind; s->q_d[i] = pd; s->q_i[i] = pi;
}

void pop(St* s, double* when, int* kind, double* pd, int* pi) {
  *when = s->q_w[0]; *kind = s->q_k[0]; *pd = s->q_d[0]; *pi = s->q_i[0];
  int n = --s->qn;
  if (n == 0) return;
  double w = s->q_w[n]; uint sq = s->q_s[n]; int k = s->q_k[n]; double d = s->q_d[n]; int ii = s->q_i[n];
  int i = 0;
  while (1) {
    int l = 2 * i + 1;
    if (l >= n) break;
    int rr = l + 1;
    int m = l;
    if (rr < n && (s->q_w[rr] < s->q_w[l] || (s->q_w[rr] == s->q_w[l] && s->q_s[rr] < s->q_s[l]))) m = rr;
    if (s->q_w[m] < w || (s->q_w[m] == w && s->q_s[m] < sq)) {
      s->q_w[i] = s->q_w[m]; s->q_s[i] = s->q_s[m]; s->q_k[i] = s->q_k[m]; s->q_d[i] = s->q_d[m]; s->q_i[i] = s->q_i[m];
      i = m;
    } else break;
  }
  s->q_w[i] = w; s->q_s[i] = sq; s->q_k[i] = k; s->q_d[i] = d; s->q_i[i] = ii;
}

inline double peek(const St* s) { return s->qn ? s->q_w[0] : FIGHT; }

/* ---- fight helpers (druid._simulate_druid closures) ---- */
inline double luck_mult(const Row* tl) { return 1.0 + tl->luck; }
inline double proc(const Row* tl, double percent) {
  double v = percent / 100.0 * luck_mult(tl);
  return (v < 1.0) ? v : 1.0;
}

inline void recover(St* s, const Row* tl, double now) {
  if (now > s->mana_time && s->mana < tl->mana_max) {
    double v = s->mana + tl->mana_regen * (now - s->mana_time);
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
  s->mana_time = (s->mana_time >= now) ? s->mana_time : now;
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

inline double main_wisp(const St* s, double now) {
  double w = 0.0;
  for (int i = 0; i < s->nw; i++) if (s->w_main[i] && now < s->w_end[i]) w = w + s->w_w[i];
  return (1.0 < w) ? 1.0 : w;
}

inline double wisp_count(const St* s, double now) {
  double w = 0.0;
  for (int i = 0; i < s->nw; i++) if (now < s->w_end[i]) w = w + s->w_w[i];
  double t = (double)s->targets;
  return (t < w) ? t : w;
}

inline int rooted(const St* s, double now) { return now < s->root_until; }

/* druid.score_events, normal event */
void score_ev(const Row* sc, Sco* q, int name, double raw, double now, double count, double mscale, int attack,
              int has_wisp, double extra) {
  double amount = (raw * mscale + sc->potency) * magical(sc, now, sc->mastery, extra);
  amount *= has_wisp ? q->taken_wisp : q->taken_plain;
  if (attack) amount *= crit_factor(sc->crit, 2.0 + sc->rating);
  else if (sc->spell_crit) amount *= crit_factor(sc->crit, sc->spell_mult + sc->rating);
  amount *= exec_factor(sc, now) * count;
  if (amount != 0.0) add_src(q, name, amount);
}

void deal(St* s, const Row* tl, const Row* sc, Sco* q, int name, double raw, double now, double count, int attack,
          double wisp_share, double mscale) {
  if (count <= 0.0 || now >= FIGHT) return;
  double ws = (1.0 <= wisp_share) ? 1.0 : wisp_share;
  ws = (0.0 >= ws) ? 0.0 : ws;
  double shares[2] = {ws, 1.0 - ws};
  for (int k = 0; k < 2; k++) {
    double share = shares[k];
    if (share <= 0.0) continue;
    int has_wisp = (k == 0);
    double extra = 0.0;
    if (TM(tl, T_WRATH)) {
      extra += has_wisp ? 0.15 : 0.0;
      extra += rooted(s, now) ? 0.10 : 0.0;
    }
    score_ev(sc, q, name, raw, now, count * share, mscale, attack, has_wisp, extra);
  }
  if (tl->damage_mana_pct != 0.0) {
    double v = s->mana + tl->damage_mana_pct * tl->mana_max * count;
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
}

inline double balance_scale(const Row* tl) { return SP_BAL ? (1.05 + 0.007 * tl->mastery) : 1.0; }
inline double spread_share(const St* s, double now) { return wisp_count(s, now) / (double)s->targets; }

void root_tick(St* s, const Row* tl, const Row* sc, Sco* q, double now, double count, double share) {
  double raw = 10.0 + 0.015 * tl->mana_max * s->surge;
  double dbl = 1.0 + (TM(tl, T_ENT) ? proc(tl, 20.0) : 0.0);
  deal(s, tl, sc, q, N_ENT, raw, now, count * dbl, 0, share, 1.0);
}

void spawn_starfall(St* s, const Row* tl, double now, double duration) {
  if (s->nf >= MAXF) { s->status = 5; return; }
  int f = s->nf++;
  s->f_end[f] = now + duration;
  push(s, now + 1.0, K_STAR, 0.0, f);
  if (TM(tl, T_MISSILE)) push(s, now + 1.5, K_MISSILE, 0.0, f);
}

inline int active_starfalls(const St* s, double now) {
  int n = 0;
  for (int i = 0; i < s->nf; i++) if (now < s->f_end[i]) n++;
  return n;
}

void star_hit(St* s, const Row* tl, const Row* sc, Sco* q, double now) {
  double raw = 10.0 + 0.30 * tl->intel;
  if (TM(tl, T_STARL)) raw *= 1.15;
  deal(s, tl, sc, q, N_STARFALL, raw, now, 1.0, 0, spread_share(s, now), balance_scale(tl));
}

void add_wisp(St* s, double end, double w, int main) {
  if (s->nw >= MAXW) { s->status = 6; return; }
  int i = s->nw++;
  s->w_end[i] = end; s->w_w[i] = w; s->w_main[i] = (uchar)main;
}

void on_spellcast(St* s, const Row* tl, const Row* sc, Sco* q, double now) {
  double count = wisp_count(s, now);
  if (count > 0.0) {
    double raw = 30.0 + 0.10 * tl->mana_max * s->surge;
    if (TM(tl, T_WISP)) raw *= 1.25;
    double hits = count * (1.0 + ((tl->mask & S_WISPI) ? proc(tl, 25.0) : 0.0));
    deal(s, tl, sc, q, N_WISP, raw, now, hits, 0, 1.0, 1.0);
  }
  if (TM(tl, T_SPREAD)) {
    double chance = proc(tl, 30.0);
    if (chance > 0.0 && wisp_count(s, now) < (double)s->targets) add_wisp(s, now + s->wisp_life, chance, 0);
  }
}

inline double cooldown(const St* s, const Row* tl, double base, int key) {
  double temp = tl->cd_temp * ((s->bound == key) ? 0.70 : 1.0);
  double v = (base * temp - tl->flat_cdr - 0.0) / (1.0 + tl->haste);
  return (v > 0.5) ? v : 0.5;
}

inline double cast_cost(int name) {
  return name == B_STARFIRE ? 20.0 : name == B_STARFALL ? 30.0 : name == B_ENTANGLE ? 35.0 : 40.0;
}

double cast_cd(const St* s, const Row* tl, int name) {
  if (name == B_STARFIRE) {
    double base = 8.0 - (TM(tl, T_STARL) ? 1.5 : 0.0) - ((tl->mask & S_MOON) ? 2.0 : 0.0);
    return cooldown(s, tl, base, name);
  }
  if (name == B_STARFALL) return cooldown(s, tl, 14.0, name);
  if (name == B_ENTANGLE) return cooldown(s, tl, 10.0, name);
  return cooldown(s, tl, 12.0, name);
}

int choose(const St* s, double now) {
  int order[5];
  int n = 0;
  double mw = main_wisp(s, now);
  if (mw <= 0.0) order[n++] = B_WISP;
  order[n++] = B_STARFALL; order[n++] = B_STARFIRE; order[n++] = B_ENTANGLE; order[n++] = B_WISP;
  for (int i = 0; i < n; i++) {
    int name = order[i];
    if (s->has[name] && s->ready[name] <= now) {
      if (name == B_WISP && main_wisp(s, now) > 0.0 && wisp_count(s, now) >= (double)s->targets) continue;
      return name;
    }
  }
  return -1;
}

void resolve(St* s, const Row* tl, const Row* sc, Sco* q, int name, double now) {
  on_spellcast(s, tl, sc, q, now);
  if (name == B_WISP) {
    add_wisp(s, now + s->wisp_life, 1.0, main_wisp(s, now) <= 0.0);
  } else if (name == B_STARFALL) {
    spawn_starfall(s, tl, now, 7.0 + 0.002 * tl->mana_max * s->surge);
  } else if (name == B_STARFIRE) {
    if (SP_BAL) spawn_starfall(s, tl, now, 0.5 * (7.0 + 0.002 * tl->mana_max * s->surge));
    double raw = 120.0 + 1.5 * tl->intel + 0.05 * tl->mana_max * s->surge;
    raw *= 1.0 + 0.12 * (double)active_starfalls(s, now);
    deal(s, tl, sc, q, N_STARFIRE, raw, now, 1.0, 0, main_wisp(s, now), balance_scale(tl));
    if (TM(tl, T_ECHO)) push(s, now + 1.5, K_ECHO, raw * 0.35, 0);
  } else {
    double share = spread_share(s, now);
    if (rooted(s, now)) root_tick(s, tl, sc, q, now, (double)s->targets, share);
    if (TM(tl, T_ENT)) {
      double instant = 40.0 + 0.10 * tl->mana_max * s->surge;
      deal(s, tl, sc, q, N_ENT, instant, now, (double)s->targets, 0, share, 1.0);
    }
    int first = !rooted(s, now);
    s->root_until = now + 6.0;
    if (first) push(s, now + 1.0, K_ROOT, 0.0, 0);
    if (TM(tl, T_FORCE) || (tl->mask & S_TREANTI)) {
      for (int k = 0; k < 2; k++) push(s, now + 1.65, K_TREANT, now + 10.0, 0);
    }
  }
}

void on_attack(St* s, const Row* tl, const Row* sc, Sco* q, double now) {
  recover(s, tl, now);
  double auto_count = (tl->auto_pct != 1.0) ? tl->auto_pct : 1.0;
  deal(s, tl, sc, q, N_AUTO, tl->ad, now, auto_count, 1, main_wisp(s, now), 1.0);
  double gain = tl->attack_mana + tl->attack_mana_pct * tl->mana_max;
  if (tl->attack_mana_crit != 0.0) {
    double cc = (tl->crit < 100.0) ? tl->crit : 100.0;
    gain *= 1.0 + cc / 100.0;
  }
  double v = s->mana + gain;
  s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  int tg = s->targets;
  if (tl->mask & S_ORB) {
    double raw = (20.0 + 0.35 * tl->intel) * (double)tg;
    if (raw != 0.0) {
      double amount = raw * 1.0 * q->taken_plain * exec_factor(sc, now);
      if (amount != 0.0) add_src(q, N_SPLASH, amount);
    }
  }
  if (tl->mask & S_SULF) {
    if (s->armed) {
      s->armed = 0;
      double raw = tl->intel;
      if (raw != 0.0) {
        double amount = raw * (double)tg * magical(sc, now, sc->mastery, 0.0);
        if (sc->spell_crit) amount *= crit_factor(sc->crit, sc->spell_mult + sc->rating);
        amount *= q->taken_plain * exec_factor(sc, now);
        if (amount != 0.0) add_src(q, N_SULF, amount);
      }
    }
    double raw = tl->ad;
    if (raw != 0.0) {
      double amount = raw * 1.0 * q->taken_plain * exec_factor(sc, now) * q->echo_ch;
      if (amount != 0.0) add_src(q, N_SULF_ECHO, amount);
    }
  }
}

/* druid._simulate_druid(build, targets, spec, bound) on the timeline sheet, scored on the scored sheet */
double fight(const Row* tl, const Row* sc, int bound, int* status_out) {
  St s; Sco q;
  int st = 0;
  q.taken_plain = armor_taken(15.0 - sc->armor_pen, &st);
  q.taken_wisp = armor_taken(15.0 - sc->armor_pen - 3.0, &st);
  if (st) { *status_out = st; return 0.0; }
  q.echo_ch = 0.10 * (1.0 + sc->luck);
  q.nord = 0; q.seen = 0u;
  s.status = 0; s.bound = bound; s.targets = tl->targets; s.armed = 0;
  s.qn = 0; s.seq = 0u; s.nf = 0; s.nw = 0;
  s.mana = tl->mana_max; s.mana_time = 0.0; s.root_until = -1.0;
  s.surge = TM(tl, T_SURGE) ? 1.5 : 1.0;
  s.wisp_life = 8.0 + (TM(tl, T_WISP) ? 4.0 : 0.0);
  for (int b = 0; b < 4; b++) { s.ready[b] = 0.0; s.has[b] = 1; }
  if (!SP_BAL) s.has[B_STARFALL] = 0;
  ap_init(&s.ap, GM(tl, G_FREN) ? frenzy_chance(tl->luck) : 0.0, (tl->mask & S_SILM) ? SILENT_AS : 0.0,
          (tl->mask & S_SILM) ? SILENT_DUR : 0.0);
  const double cast_time = CAST_POINT + CAST_BACKSWING;
  double hero_ready = 0.0, next_attack = 0.0;
  int guard = 0;
  while (guard < 200000) {
    guard += 1;
    if (s.status) break;
    double pk = peek(&s);
    double moment = (pk < next_attack) ? pk : next_attack;
    if (hero_ready <= moment && hero_ready < FIGHT) {
      int spell = choose(&s, hero_ready);
      if (spell >= 0) {
        if (!pay(&s, tl, cast_cost(spell), hero_ready)) { s.ready[spell] = hero_ready + 0.25; continue; }
        s.ready[spell] = hero_ready + cast_cd(&s, tl, spell);
        if (tl->mask & S_SULF) s.armed = 1;
        push(&s, hero_ready + CAST_POINT, K_CAST, 0.0, spell);
        double busy = hero_ready + cast_time + tl->cast_lock;
        hero_ready = busy;
        next_attack = (next_attack >= busy) ? next_attack : busy;
        continue;
      }
      int found = 0;
      double wake = FIGHT;
      for (int b = 0; b < 4; b++) {
        if (!s.has[b]) continue;
        double t = s.ready[b];
        if (t > hero_ready + 1e-9) {
          if (!found || t < wake) { wake = t; found = 1; }
        }
      }
      if (!found) wake = FIGHT;
      if (wake <= moment) { hero_ready = wake; continue; }
      double mw = (wake < FIGHT) ? wake : FIGHT;
      hero_ready = (hero_ready >= mw) ? hero_ready : mw;
    }
    if (moment >= FIGHT) break;
    if (moment == next_attack && (s.qn == 0 || next_attack < peek(&s))) {
      on_attack(&s, tl, sc, &q, moment);
      if (s.ap.p > 0.0 || s.ap.cas > 0.0) {
        ap_attack(&s.ap, moment, tl->crit);
        double sp = ap_speed(tl->aspd + ap_bonus(&s.ap, moment));
        next_attack = moment + tl->attack_base / (1.0 + sp);
      } else {
        next_attack = moment + tl->attack_base / (1.0 + tl->aspd);
      }
      continue;
    }
    double now, pd; int kind, pi;
    pop(&s, &now, &kind, &pd, &pi);
    if (kind == K_CAST) {
      resolve(&s, tl, sc, &q, pi, now);
    } else if (kind == K_ECHO) {
      deal(&s, tl, sc, &q, N_ECHO_SF, pd, now, 1.0, 0, main_wisp(&s, now), balance_scale(tl));
    } else if (kind == K_STAR || kind == K_MISSILE) {
      double end = s.f_end[pi];
      if (now < end + 1e-9) {
        star_hit(&s, tl, sc, &q, now);
        double gap = (kind == K_STAR) ? 1.0 : 1.5;
        if (now + gap <= end + 1e-9) push(&s, now + gap, kind, 0.0, pi);
      }
    } else if (kind == K_ROOT) {
      if (rooted(&s, now + 1e-9)) {
        root_tick(&s, tl, sc, &q, now, (double)s.targets, spread_share(&s, now));
        push(&s, now + 1.0, K_ROOT, 0.0, 0);
      }
    } else {
      double expire = pd;
      if (now <= expire + 1e-9) {
        double amount = 12.0 * 1.0 * q.taken_plain * exec_factor(sc, now);
        if (amount != 0.0) add_src(&q, N_TREANTS, amount);
        if (rooted(&s, now)) root_tick(&s, tl, sc, &q, now, 1.0, main_wisp(&s, now));
        if (now + 1.65 <= expire + 1e-9) push(&s, now + 1.65, K_TREANT, expire, 0);
      }
    }
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < q.nord; i++) total += q.src[q.ord[i]];
  return total / FIGHT;
}

""" + _SHEET + r"""
double row_value(Tab* T, long index, uint tmask, uint gmask, const int* pts, const int* tlpts, int targets,
                 int* status, int* group) {
  int chosen[6];
  if (unrank(T, index, chosen)) { *status = 1; *group = 0; return 0.0; }
  Row sc;
  sheet(T, &sc, chosen, tmask, gmask, pts, targets, group);
  if (TM(&sc, T_DRUIDISM)) sc.potency += 2.0 + sc.mana_max / 200.0;
  int same = 1;
  for (int j = 0; j < NP; j++) if (pts[j] != tlpts[j]) { same = 0; break; }
  Row tl;
  if (same) tl = sc;
  else {
    int g2 = 0;
    sheet(T, &tl, chosen, tmask, gmask, tlpts, targets, &g2);
    if (TM(&tl, T_DRUIDISM)) tl.potency += 2.0 + tl.mana_max / 200.0;
  }
  int buttons[4];
  int nb;
  if (SP_BAL) { buttons[0] = B_STARFIRE; buttons[1] = B_STARFALL; buttons[2] = B_ENTANGLE; buttons[3] = B_WISP; nb = 4; }
  else { buttons[0] = B_STARFIRE; buttons[1] = B_ENTANGLE; buttons[2] = B_WISP; nb = 3; }
  int ring = (sc.mask & S_RING) != 0;
  int nv = ring ? nb : 1;
  double best = 0.0;
  for (int i = 0; i < nv; i++) {
    double d = fight(&tl, &sc, ring ? buttons[i] : -1, status);
    if (*status) return 0.0;
    if (i == 0 || d > best) best = d;
  }
  return best;
}

""" + _KERNELS
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I00D": 0, "I0BR": 1, "I07O": 2, "I0JO": 3, "I0QT": 4, "I096": 5, "I03C": 6, "I00L": 7,
    "I00Y": 8, "I07P": 9, "I048": 10, "I03L": 11, "tlum": 12, "I0FW": 13,
    "I0R1": 14, "I0R3": 15, "I0R4": 16,
    "I0QN": 20,
}
TALENT_BITS = {
    "I0K0": 0, "I0P8": 1, "I0JY": 2, "I0P5": 3, "I0JZ": 4, "I0P7": 5, "I08O": 6, "I0K4": 7, "I0K1": 8, "I0MS": 9,
    # druid.IGNORED_TALENTS (healing / survivability): no effect on the fight
    "I0K5": 16, "I0K2": 17, "I02F": 18, "I0K3": 19, "I0ML": 20, "I0P4": 21, "I08Q": 22, "I08S": 23,
}
GLYPH_BITS = _S.GLYPH_BITS
NO_EFFECT = {"I0EN"}
SPECS = {"restoration": 0, "balance": 1}


class DruidCL(C.ExactCL):
    hero = "druid"
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ("health", "healing_power")  # ESC points left out of the timeline key
    TABLE_KEYS = _S.ShamanCL.TABLE_KEYS
    SCALARS = _S.ShamanCL.SCALARS

    @staticmethod
    def module():
        from sunken_sim import druid

        return druid

    def tables(self, space, items, sources):
        from sunken_sim import druid

        if (druid.DRUID_WHITE, druid.DRUID_SWING, druid.STARFALL_GAP, druid.MISSILE_GAP, druid.ROOT_LIFE, druid.ROOT_GAP,
                druid.TREANT_LIFE, druid.TREANT_SWING, druid.TREANT_HIT, druid.WISP_LIFE, druid.WISP_ARMOR) != \
                (11.0, 2.0, 1.0, 1.5, 6.0, 1.0, 10.0, 1.65, 12.0, 8.0, 3.0):
            raise ValueError("kernel constants assume the 2026-11-11 druid")
        return C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                                  [druid.DRUID_INT, druid.DRUID_STR, druid.DRUID_AGI], "Druid")

    def timeline_key(self, build):
        from sunken_sim import druid

        stats = druid.sheet(build, self.spec)
        if druid._wears(build, druid.DIAMOND):
            return tuple(druid._timeline_key(build, stats, self.spec, self.targets, b) for b in druid.buttons(self.spec))
        return druid._timeline_key(build, stats, self.spec, self.targets, None)


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
