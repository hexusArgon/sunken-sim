"""Exact float64 OpenCL kernel for Druid fights (Restoration, Balance). GPU only.

The Druid (E009, intellect caster) only. The Feral Druid (O00R) is a separate class
(farm.hybrid.feral_druid_cl) and is not modelled here.

One work-item scores one fight: unrank the six items (or take explicit pieces), fold the sheet
(``shadow.character`` with the druid bases, white 11, no baked buffs, 2.0 s swing, Druidism potency),
run the event loop (every Diamond Ring binding, first wins ties; heap of (time, order)) and score every
event the moment it is emitted. The Python model (sunken_sim.druid) was removed on 2026-11-27 after
bit-exact parity: farm/hybrid/fixtures/druid.json holds the frozen fights, report mode (-DREPORT=1)
gives sources, casts, mana left, the binding and the stat sheet. Host side: farm.hybrid.class_cl; the
sheet, unrank and kernels are shared with farm.hybrid.shaman_cl.
"""

from __future__ import annotations

import re

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C
from farm.hybrid import incoming_cl as INC
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
_SHEET = _SHEET.replace("""    int p = chosen[si];
    int f1 = 1;""", """    int p = chosen[si];
    if (p < 0) { first[si] = 0; continue; }  /* explicit pieces: empty slot */
    int f1 = 1;""")
assert "11.0 + 0.75 * intel" in _SHEET and "2.0 * ((mask & S_GALA)" in _SHEET and "empty slot" in _SHEET
# incoming layer (druid only): Row fields, the item tables and the hero health / armour in the sheet
_ROW = _ROW.replace("  ulong mask;\n} Row;", "  ulong mask;\n  double hp; int pool_on;\n@INC_ROW_FIELDS@\n} Row;")
_SHEET = (_SHEET
          .replace("  __global const double* base;\n} Tab;",
                   "  __global const double* base; __global const ulong* pimask; __global const double* pinc;\n"
                   "  __global const double* phealth;\n} Tab;")
          .replace("  ulong mask = 0;\n", "  ulong mask = 0;\n  inc_sheet_init(r);\n  double health_flat = 0.0;\n", 1)
          .replace("    ulong m = T->pmask[p];\n    mask |= m;\n", "    ulong m = T->pmask[p];\n    mask |= m;\n    r->imask |= T->pimask[p];\n", 1)
          .replace("    cast_lock += u[1];\n", "    cast_lock += u[1];\n    health_flat += T->phealth[chosen[si]];\n"
                   "    INC_FOLD(r, T->pinc + (long)chosen[si] * NINC);\n", 1)
          .replace("  r->spell_crit = sc; r->nexec = nexec; r->targets = targets;\n}",
                   "  r->spell_crit = sc; r->nexec = nexec; r->targets = targets;\n"
                   "  /* incoming layer: E009 230 HP + 15 STR + items, armour 5 + 0.1 AGI + items (Dragon Figurine) */\n"
                   "  double hp = (230.0 + 15.0 * strength) + health_flat;\n"
                   "  r->hp = hp;\n"
                   "  r->armor_hero = (5.0 + 0.1 * agility) + r->item_armor;\n"
                   "  (void)inc_sheet_finish(r, hp);  /* Primalist Ring: Physical Type only, no druid damage has it */\n"
                   "  r->pool_on = ((r->imask & (I_GIANT | I_CRIM | I_IGM | I_FURN | I_BLS)) || r->pool_flat != 0.0"
                   " || r->voodoo != 0.0) ? 1 : 0;\n}", 1))
assert "INC_FOLD(r, T->pinc" in _SHEET and "r->imask |= T->pimask[p]" in _SHEET and "r->pool_on" in _SHEET and "phealth;" in _SHEET
_KERNELS = _cut(_S.KERNEL, "#define TAB_ARGS", "SENTINEL") if "SENTINEL" in _S.KERNEL else _S.KERNEL[_S.KERNEL.index("#define TAB_ARGS"):]
_KERNELS = (_KERNELS.replace("    __global const double* base\n", "    __global const double* base, __global const ulong* pimask, __global const double* pinc, \\\n"
                             "    __global const double* phealth\n", 1)
            .replace("T.base = base;", "T.base = base; T.pimask = pimask; T.pinc = pinc; T.phealth = phealth;", 1))
assert "T.phealth = phealth" in _KERNELS

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
#define MAXT 8
#define CLS_INT_HERO 1  /* Intelligence hero: the model heal is the druid's own (healer E009) */
#define LEVEL 15
@INC_HEAD@
/* INC_OFF 1 (tests only): no incoming hits and no hero health, as before 2026-11-27 */
#ifndef INC_OFF
#define INC_OFF 0
#endif
/* REPORT 1: the report kernel also keeps the final fight state (sources in Ledger order, casts, mana) */
#ifndef REPORT
#define REPORT 0
#endif
#define MAXA 160

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
#define NSRC 16

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
#define S_VOID (1UL<<21)   /* Voidseeker Hood I07Y: Magical Type damage ignores 2 armour */
#define S_ICLV (1UL<<22)   /* Iron Cleaver I055: Physical Type damage ignores 3 armour */

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
#define T_MANAHEAL (1u<<10)  /* I0K5: Healing Type heals by the druid restore 2.5% of the amount as mana */
#define T_REGEN (1u<<11)     /* I0P4: heals 12% x Luck Regenesis 6 s, +25% healing taken */
#define T_HEALTWICE (1u<<12) /* I08S: heals 12% x Luck trigger an additional time */
#define T_DMGHEAL (1u<<13)   /* I08Q: damage dealt heals the most wounded hero 3 + 0.2% max mana (x Starsurge) */

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
/* incoming-hit sources (farm/hybrid/incoming_cl.py) */
#define N_REFL 10
#define N_SUNS 11
#define N_SOD 12
#define N_EVADE 13
#define N_BLOOD 14
#define N_ICE 15

/* armour kinds (ArmorDamage_Increase): item penetration only on the auto attack; every druid spell is
 * ATTACK_TYPE_NORMAL (Spells); summons get no item penetration */
#define P_PLAIN 0   /* untyped, ENHANCED, summons */
#define P_MAG 1     /* Magical Type spells: Voidseeker Hood */
#define P_ATK 2     /* the auto attack: item penetration + Iron Cleaver */
#define P_PHYS 3    /* Physical Type, not an attack: Iron Cleaver */
#define BS 8

""" + _ROW + r"""

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double tk[4][2], echo_ch;  /* armour factor by kind, [0] armour 15, [1] Wisp Guardian armour 12 */
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
  double lm;
  double rn_e[BS + 1], rn_m[BS + 1]; int rn_n; double rn_t, rn_lo;          /* Regenesis on the druid */
  double ch_e[MAXT][BS + 1], ch_m[MAXT][BS + 1]; int ch_n[MAXT]; double ch_t[MAXT], ch_lo[MAXT];  /* Chill */
  const Row* sc; Sco* q;
@INC_ST_FIELDS@
#if REPORT
  double act_t[MAXA]; int act_id[MAXA]; int nact;
#endif
} St;

/* actions: druid.BOUND_NAME of the cast button (host ACTION_NAMES, ids = B_*) */
void act(St* s, double now, int id) {
#if REPORT
  if (s->nact < MAXA) { s->act_t[s->nact] = now; s->act_id[s->nact] = id; }
  s->nact++;
#else
  (void)s; (void)now; (void)id;
#endif
}

/* ---- expiry_buff._Buff (Regenesis, Chill) ---- */
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
  if (armor < 0.0) return 2.0 - pow(1.0 - 0.04, -armor);  /* shadow.armor_taken */
  return 1.0;
}

/* CalculateArmorPenetration: p1 item penetration, p2 Voidseeker / Iron Cleaver: x m(A-p1) x m(A-p2) / m(A) */
double pen_taken(double armor, double p1, double p2) {
  int st = 0;
  if (p2 <= 0.0) return armor_taken(armor - p1, &st);
  double m = (p1 > 0.0) ? armor_taken(armor - p1, &st) : armor_taken(armor, &st);
  return m / armor_taken(armor, &st) * armor_taken(armor - p2, &st);
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

inline void drecover(St* s, const Row* tl, double now) {
  if (now > s->mana_time && s->mana < tl->mana_max) {
    double v = s->mana + tl->mana_regen * (now - s->mana_time);
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
  s->mana_time = (s->mana_time >= now) ? s->mana_time : now;
}

void recover(const Row* r, St* s, double now) { drecover(s, r, now); }
double chance01(double v) { return (v < 1.0) ? v : 1.0; }

@INC_C1@

int pay(St* s, const Row* tl, double cost, double now) {
  drecover(s, tl, now);
  if (s->mana < cost) return 0;
  s->mana -= cost;
  double back = cost * tl->cast_refund + tl->cast_refund_flat + tl->cast_refund_mastery * MAST(tl, s);
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

#define CH_ARGS(s, t) (s)->ch_e[t], (s)->ch_m[t], &(s)->ch_n[t], &(s)->ch_t[t], &(s)->ch_lo[t]
#define CH_MASS(s, t, now) bmass((s)->ch_e[t], (s)->ch_m[t], (s)->ch_n[t], (s)->ch_t[t], (s)->ch_lo[t], now)

/* Ancient Voodoo Doll: the debuffs on dummy t the kernel tracks (Wisp Guardian, Entangling Roots, Chill) */
double cls_buffs(const Row* r, St* s, int t, double now) {
  double n = (t == 0) ? main_wisp(s, now) : wisp_count(s, now) / (double)s->targets;
  if (rooted(s, now)) n += 1.0;
  if (r->imask & (I_FORB | I_ICLE)) n += CH_MASS(s, t, now);
  return n;
}

/* DamageIncrease_Amount entries of the incoming layer for a share with / without Wisp Guardian (armour 12 / 15) */
double pool_share(const Row* r, St* s, double now, int has_wisp) {
  if (!r->pool_on) return 1.0;
  double d = s->dinc + r->pool_flat;
  if (r->imask & I_GIANT) d += (0.03 / 4.0) * (has_wisp ? 12.0 : 15.0);
  if (r->voodoo != 0.0) d += 0.04 + 0.02 * ((has_wisp ? 1.0 : 0.0) + (rooted(s, now) ? 1.0 : 0.0) + CH_MASS(s, 0, now));
  return 1.0 + d;
}

/* druid.score_events, normal event; pk = armour kind */
double score_ev(St* s, const Row* sc, Sco* q, int name, double raw, double now, double count, double mscale, int attack,
                int has_wisp, double extra) {
  double amount = (raw * mscale + sc->potency) * magical(sc, now, MAST(sc, s), extra);
  amount *= q->tk[attack ? P_ATK : P_MAG][has_wisp];
  if (attack) amount *= crit_factor(sc->crit, 2.0 + sc->rating);
  else if (sc->spell_crit) amount *= crit_factor(sc->crit, sc->spell_mult + sc->rating);
  amount *= exec_factor(sc, now) * count;
  if (sc->pool_on) amount *= pool_share(sc, s, now, has_wisp);
  if (amount != 0.0) add_src(q, name, amount);
  return amount;
}

void heal_druid(const Row* r, St* s, double now, double amount, double count);

/* every damage instance of the druid's player: damage mana, I08Q heal, Sanguine / Seal of Vampirism */
void after_damage(St* s, const Row* tl, double now, double count) {
  if (tl->damage_mana_pct != 0.0) {
    double v = s->mana + tl->damage_mana_pct * tl->mana_max * count;
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
  if (s->hp_on && TM(tl, T_DMGHEAL)) heal_druid(tl, s, now, 3.0 + 0.002 * tl->mana_max * s->surge, count);
}

void deal(St* s, const Row* tl, const Row* sc, Sco* q, int name, double raw, double now, double count, int attack,
          double wisp_share, double mscale) {
  if (count <= 0.0 || now >= FIGHT) return;
  double ws = (1.0 <= wisp_share) ? 1.0 : wisp_share;
  ws = (0.0 >= ws) ? 0.0 : ws;
  double shares[2] = {ws, 1.0 - ws};
  double dealt = 0.0;
  for (int k = 0; k < 2; k++) {
    double share = shares[k];
    if (share <= 0.0) continue;
    int has_wisp = (k == 0);
    double extra = 0.0;
    if (TM(tl, T_WRATH)) {
      extra += has_wisp ? 0.15 : 0.0;
      extra += rooted(s, now) ? 0.10 : 0.0;
    }
    dealt += score_ev(s, sc, q, name, raw, now, count * share, mscale, attack, has_wisp, extra);
  }
  after_damage(s, tl, now, count);
  if (s->hp_on) inc_dealt(tl, s, now, dealt / count, count);
}

/* item_dmg of the incoming layer: a damage instance of the druid per count on dummy t (Potency per instance;
 * magical: the Magical Type multiplier, Voidseeker, spell crit; else untyped: Glass Cannon only) */
void item_dmg(const Row* r, St* s, int name, double raw, int t, double when, int magical_type, double count) {
  if (count <= 0.0 || when >= FIGHT) return;
  const Row* sc = s->sc;
  double ws = (t == 0) ? main_wisp(s, when) : wisp_count(s, when) / (double)s->targets;
  double dealt = 0.0;
  for (int k = 0; k < 2; k++) {
    double share = (k == 0) ? ws : 1.0 - ws;
    if (share <= 0.0) continue;
    double amount = raw / count + sc->potency;
    if (magical_type) {
      double extra = 0.0;
      if (TM(sc, T_WRATH)) extra += ((k == 0) ? 0.15 : 0.0) + (rooted(s, when) ? 0.10 : 0.0);
      amount *= magical(sc, when, MAST(sc, s), extra);
      if (sc->spell_crit) amount *= crit_factor(sc->crit, sc->spell_mult + sc->rating);
    } else if (GM(sc, G_GLASS)) amount *= 1.15;
    amount *= s->q->tk[magical_type ? P_MAG : P_PLAIN][k == 0] * exec_factor(sc, when) * count * share;
    if (sc->pool_on) amount *= pool_share(sc, s, when, k == 0);
    if (amount != 0.0) add_src(s->q, name, amount);
    dealt += amount;
  }
  after_damage(s, r, when, count);
  if (s->hp_on) inc_dealt(r, s, when, dealt / count, count);
}

void cls_taken(const Row* r, St* s, double now, double m, double axe) { (void)r; (void)s; (void)now; (void)m; (void)axe; }
double cls_hit(const Row* r, St* s, double now) { (void)r; (void)s; (void)now; return 1.0; }
void cls_attacked(const Row* r, St* s, int j, double now, double m) { (void)r; (void)s; (void)j; (void)now; (void)m; }
void cls_evade(const Row* r, St* s, int j, double now, double evaded) { (void)r; (void)s; (void)j; (void)now; (void)evaded; }
double cls_primary(const Row* r) { return r->intel; }
void cls_lifesteal(const Row* r, St* s, double amount) { (void)r; (void)s; (void)amount; }
/* every heal in the fight is the druid's (healer E009, not regeneration): +5 + 3% INT (Trig_Healing) */
double cls_heal_flat(const Row* r, St* s) { (void)s; return 5.0 + 0.03 * (double)(int)r->intel; }
/* I0P4 Regenesis on the druid: +25% healing taken while it lasts */
double cls_heal_mod(const Row* r, St* s) {
  if (!TM(r, T_REGEN)) return 0.0;
  return 0.25 * bmass(s->rn_e, s->rn_m, s->rn_n, s->rn_t, s->rn_lo, s->tnow);
}
/* Trig_Healing with healer the druid: I0K5 mana 2.5% of the amount, I0P4 Regenesis 12% x Luck, I08S 12% x Luck one
 * more application (the druid below 100% health) */
void cls_own_heal(const Row* r, St* s, double total) {
  if (TM(r, T_MANAHEAL)) {
    drecover(s, r, s->tnow);
    double v = s->mana + 0.025 * total;
    s->mana = (v < r->mana_max) ? v : r->mana_max;
  }
  if (TM(r, T_REGEN)) {
    double c = chance01(0.12 * s->lm);
    if (c > 0.0) bmaybe(s->rn_e, s->rn_m, &s->rn_n, &s->rn_t, &s->rn_lo, s->tnow, 6.0, c, c);
  }
  if (TM(r, T_HEALTWICE) && s->hp_health < s->hp_max) hp_add(s, chance01(0.12 * s->lm) * total);
}

@INC_C2@

void heal_druid(const Row* r, St* s, double now, double amount, double count) {
  s->tnow = now;
  heal_mod(r, s, amount, count, 1, 1, 1);
}

inline double balance_scale(const Row* tl, St* s) { return SP_BAL ? (1.05 + 0.007 * MAST(tl, s)) : 1.0; }
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
  deal(s, tl, sc, q, N_STARFALL, raw, now, 1.0, 0, spread_share(s, now), balance_scale(tl, s));
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
    deal(s, tl, sc, q, N_STARFIRE, raw, now, 1.0, 0, main_wisp(s, now), balance_scale(tl, s));
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
  drecover(s, tl, now);
  s->tnow = now;
  double auto_count = (tl->auto_pct != 1.0) ? tl->auto_pct : 1.0;
  /* Blade of the Fallen Seraph: +1% max HP attack damage */
  double ad = tl->ad + ((tl->imask & I_SERA) ? 0.01 * s->hp_max : 0.0);
  double before = q->src[N_AUTO] * ((q->seen & (1u << N_AUTO)) ? 1.0 : 0.0);
  deal(s, tl, sc, q, N_AUTO, ad, now, auto_count, 1, main_wisp(s, now), 1.0);
  if (s->hp_on) attack_heal(tl, s, now, q->src[N_AUTO] - before);
  if (tl->imask & I_SERA) {
    if (s->hp_on) hp_add(s, -0.01 * s->hp_max);
    taken_event(tl, s, now, 1.0, 0.0);
    if (s->hp_on) dinc_update(tl, s);
  }
  double gain = tl->attack_mana + tl->attack_mana_pct * tl->mana_max;
  if (tl->attack_mana_crit != 0.0) {
    double cc = (tl->crit < 100.0) ? tl->crit : 100.0;
    gain *= 1.0 + cc / 100.0;
  }
  double v = s->mana + gain;
  s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  int tg = s->targets;
  /* Frost Orb chills the attacked dummy (4 s), Ice Cleaver's Ice Nova (18% x Luck) every dummy */
  if (tl->imask & I_FORB) { bsure(CH_ARGS(s, 0), now, 4.0); inc_ice(tl, s, 0, now, 1.0, 0); }
  if (tl->imask & I_ICLE) {
    double c = chance01(0.18 * s->lm);
    for (int t = 0; t < tg; t++) {
      if (c > 0.0) bmaybe(CH_ARGS(s, t), now, 4.0, c, c);
      inc_ice(tl, s, t, now, c, 0);
    }
  }
  if (tl->mask & S_ORB) {
    /* Fire Orb splash (DAMAGE_TYPE_NORMAL, Spells, no type): Potency per dummy, Glass Cannon, the DamageIncrease pool,
     * Wisp Guardian armour, damage procs; no type bonus, no crit */
    double ws = wisp_count(s, now) / (double)tg;
    double dealt = 0.0;
    for (int k = 0; k < 2; k++) {
      double share = (k == 0) ? ws : 1.0 - ws;
      if (share <= 0.0) continue;
      double amount = (20.0 + 0.35 * tl->intel + sc->potency) * (GM(sc, G_GLASS) ? 1.15 : 1.0);
      amount *= q->tk[P_PLAIN][k == 0] * exec_factor(sc, now) * (double)tg * share;
      if (sc->pool_on) amount *= pool_share(sc, s, now, k == 0);
      if (amount != 0.0) add_src(q, N_SPLASH, amount);
      dealt += amount;
    }
    after_damage(s, tl, now, (double)tg);
    if (s->hp_on) inc_dealt(tl, s, now, dealt / (double)tg, (double)tg);
  }
  if (tl->mask & S_SULF) {
    if (s->armed) {
      s->armed = 0;
      double raw = tl->intel;
      if (raw != 0.0) {
        double amount = raw * (double)tg * magical(sc, now, MAST(sc, s), 0.0);
        if (sc->spell_crit) amount *= crit_factor(sc->crit, sc->spell_mult + sc->rating);
        amount *= q->tk[P_MAG][0] * exec_factor(sc, now);
        if (amount != 0.0) add_src(q, N_SULF, amount);
      }
    }
    double raw = ad;
    if (raw != 0.0) {
      /* DAMAGE_TYPE_ENHANCED: no penetration, no DamageIncrease pool */
      double amount = raw * 1.0 * q->tk[P_PLAIN][0] * exec_factor(sc, now) * q->echo_ch;
      if (amount != 0.0) add_src(q, N_SULF_ECHO, amount);
    }
  }
}

/* druid._simulate_druid(build, targets, spec, bound) on the timeline sheet, scored on the scored sheet */
#if REPORT
double fight(const Row* tl, const Row* sc, int bound, int* status_out, St* keep_s, Sco* keep_q) {
#else
double fight(const Row* tl, const Row* sc, int bound, int* status_out) {
#endif
  St s; Sco q;
#if REPORT
  s.nact = 0;
#endif
  int st = 0;
  for (int w = 0; w < 2; w++) {
    double a = 15.0 - (w ? 3.0 : 0.0);  /* Wisp Guardian: -3 armour on the target */
    q.tk[P_PLAIN][w] = armor_taken(a, &st);
    q.tk[P_MAG][w] = (sc->mask & S_VOID) ? pen_taken(a, 0.0, 2.0) : q.tk[P_PLAIN][w];
    q.tk[P_ATK][w] = pen_taken(a, sc->armor_pen, (sc->mask & S_ICLV) ? 3.0 : 0.0);
    q.tk[P_PHYS][w] = (sc->mask & S_ICLV) ? pen_taken(a, 0.0, 3.0) : q.tk[P_PLAIN][w];
  }
  if (st) { *status_out = st; return 0.0; }
  q.echo_ch = 0.10 * (1.0 + sc->luck);
  q.nord = 0; q.seen = 0u;
  s.status = 0; s.bound = bound; s.targets = tl->targets; s.armed = 0;
  s.qn = 0; s.seq = 0u; s.nf = 0; s.nw = 0;
  s.mana = tl->mana_max; s.mana_time = 0.0; s.root_until = -1.0;
  s.surge = TM(tl, T_SURGE) ? 1.5 : 1.0;
  s.lm = 1.0 + tl->luck; s.tnow = 0.0; s.sc = sc; s.q = &q;
  s.rn_n = 0; s.rn_t = 0.0; s.rn_lo = INFINITY;
  for (int t = 0; t < MAXT; t++) { s.ch_n[t] = 0; s.ch_t[t] = 0.0; s.ch_lo[t] = INFINITY; }
  /* incoming hits: I0K5 turns the druid's own heals (the model heal from itself, I08Q) into mana */
  inc_init(tl, &s, tl->targets, TM(tl, T_MANAHEAL) != 0, 0);
#if INC_OFF
  s.hits_on = 0; s.hp_on = 0;
#endif
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
    int hit_j = -1, hit_k = -1;
    double next_inc = (s.hits_on || s.hp_on) ? inc_next(&s, s.targets, &hit_j, &hit_k) : 1.0e9;
    if (next_inc < moment) moment = next_inc;
    if (hero_ready <= moment && hero_ready < FIGHT) {
      int spell = choose(&s, hero_ready);
      if (spell >= 0) {
        if (!pay(&s, tl, cast_cost(spell), hero_ready)) { s.ready[spell] = hero_ready + 0.25; continue; }
        act(&s, hero_ready, spell);
        s.tnow = hero_ready;
        cast_heal(tl, &s, hero_ready, cast_cost(spell));
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
    s.tnow = moment;
    if (s.hp_on) regen_adv(tl, &s, moment);
    if (moment == next_inc) {
      inc_event(tl, &s, moment, hit_j, hit_k, s.targets);
      continue;
    }
    if (moment == next_attack && (s.qn == 0 || next_attack < peek(&s))) {
      on_attack(&s, tl, sc, &q, moment);
      double base = tl->attack_base;
      if (tl->imask & I_BHOWL) base *= 1.0 - (1.0 - hero_ratio(&s, moment)) * 0.30;
      double bm = (tl->imask & I_BMASK) ? 0.28 * bm_active(&s, moment) : 0.0;
      if (s.ap.p > 0.0 || s.ap.cas > 0.0) {
        ap_attack(&s.ap, moment, tl->crit);
        double sp = ap_speed(tl->aspd + ap_bonus(&s.ap, moment) + bm);
        next_attack = moment + base / (1.0 + sp);
      } else if (bm != 0.0) {
        next_attack = moment + base / (1.0 + ap_speed(tl->aspd + bm));
      } else {
        next_attack = moment + base / (1.0 + tl->aspd);
      }
      continue;
    }
    double now, pd; int kind, pi;
    pop(&s, &now, &kind, &pd, &pi);
    if (kind == K_CAST) {
      resolve(&s, tl, sc, &q, pi, now);
    } else if (kind == K_ECHO) {
      deal(&s, tl, sc, &q, N_ECHO_SF, pd, now, 1.0, 0, main_wisp(&s, now), balance_scale(tl, &s));
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
        /* summons: no item penetration */
        double amount = 12.0 * 1.0 * q.tk[P_PLAIN][0] * exec_factor(sc, now);
        if (amount != 0.0) add_src(&q, N_TREANTS, amount);
        if (rooted(&s, now)) root_tick(&s, tl, sc, &q, now, 1.0, main_wisp(&s, now));
        if (now + 1.65 <= expire + 1e-9) push(&s, now + 1.65, K_TREANT, expire, 0);
      }
    }
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < q.nord; i++) total += q.src[q.ord[i]];
#if REPORT
  drecover(&s, tl, FIGHT);
  *keep_s = s; *keep_q = q;
#endif
  return total / FIGHT;
}

""" + _SHEET + r"""
#if !REPORT
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
#endif

""" + _KERNELS.replace("__kernel void cls_bare", "#if !REPORT\n__kernel void cls_bare", 1) + r"""
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

/* druid.simulate: the sheet (Druidism potency), then the best Diamond Ring binding (first wins ties) */
#if REPORT
double pick_value(Tab* T, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* status, int* group,
                  Row* out, St* keep_s, Sco* keep_q, int* bound_out) {
#else
double pick_value(Tab* T, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* status, int* group) {
#endif
  Row sc;
  sheet(T, &sc, chosen, tmask, gmask, pts, targets, group);
  if (TM(&sc, T_DRUIDISM)) sc.potency += 2.0 + sc.mana_max / 200.0;
  int buttons[4];
  int nb;
  if (SP_BAL) { buttons[0] = B_STARFIRE; buttons[1] = B_STARFALL; buttons[2] = B_ENTANGLE; buttons[3] = B_WISP; nb = 4; }
  else { buttons[0] = B_STARFIRE; buttons[1] = B_ENTANGLE; buttons[2] = B_WISP; nb = 3; }
  int ring = (sc.mask & S_RING) != 0;
  int nv = ring ? nb : 1;
  double best = 0.0;
#if REPORT
  *out = sc;
  St ts; Sco tq;
#endif
  for (int i = 0; i < nv; i++) {
#if REPORT
    double d = fight(&sc, &sc, ring ? buttons[i] : -1, status, &ts, &tq);
#else
    double d = fight(&sc, &sc, ring ? buttons[i] : -1, status);
#endif
    if (*status) return 0.0;
    if (i == 0 || d > best) {
      best = d;
#if REPORT
      *keep_s = ts; *keep_q = tq; *bound_out = ring ? buttons[i] : -1;
#endif
    }
  }
  return best;
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
  else d = pick_value(&T, chosen, tmasks[gid], gmasks[gid], pts, targets, &status, &group);
  out_dps[gid] = d; out_group[gid] = (uchar)group; out_status[gid] = (uchar)status;
}
#else
#define NSTAT 19
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
  else d = pick_value(&T, chosen, tmasks[gid], gmasks[gid], pts, targets, &status, &group, &r, &ks, &kq, &bound);
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
    o[17] = (double)bound; o[18] = r.spell_crit ? 1.0 : 0.0;
  }
}
#endif
"""
KERNEL = (KERNEL.replace("@INC_HEAD@", INC.INC_HEAD + "#define NINC %d\n" % INC.NINC)
          .replace("@INC_ROW_FIELDS@", INC.INC_ROW_FIELDS).replace("@INC_ST_FIELDS@", INC.INC_ST_FIELDS)
          .replace("@INC_C1@", INC.INC_C1).replace("@INC_C2@", INC.INC_C2))
KERNEL = KERNEL.replace("#pragma OPENCL FP_CONTRACT OFF\n", "#pragma OPENCL FP_CONTRACT OFF\n" + AP.C, 1)

SPECIAL_BITS = {
    "I00D": 0, "I0BR": 1, "I07O": 2, "I0JO": 3, "I0QT": 4, "I096": 5, "I03C": 6, "I00L": 7,
    "I00Y": 8, "I07P": 9, "I048": 10, "I03L": 11, "tlum": 12, "I0FW": 13,
    "I0R1": 14, "I0R3": 15, "I0R4": 16,
    "I0QN": 20, "I07Y": 21, "I055": 22,
}
TALENT_BITS = {
    "I0K0": 0, "I0P8": 1, "I0JY": 2, "I0P5": 3, "I0JZ": 4, "I0P7": 5, "I08O": 6, "I0K4": 7, "I0K1": 8, "I0MS": 9,
    # healing talents that act through the druid's own heals (2026-11-27: the model heal is the druid's own)
    "I0K5": 10, "I0P4": 11, "I08S": 12, "I08Q": 13,
    # IGNORED_TALENTS (Wild Growth / Nourish / allies, never cast in the fight): no effect on the fight
    "I0K2": 17, "I02F": 18, "I0K3": 19, "I0ML": 20,
}
GLYPH_BITS = _S.GLYPH_BITS
NO_EFFECT = {"I0EN"}
SPECS = {"restoration": 0, "balance": 1}

# Level-15 Druid E009 (map 2.5.2c), moved from the removed sunken_sim.druid model
LEVEL = 15
DRUID_STR = int(14 + (LEVEL - 1) * 1.4)
DRUID_AGI = int(8 + (LEVEL - 1) * 0.8)
DRUID_INT = int(28 + (LEVEL - 1) * 2.8)
DRUID_WHITE = 11.0
DRUID_SWING = 2.0
HERO_CLASS = "Druid"  # item pool class for E009
TALENT_NAMES = {
    "I0K5": "Mana from Healing (I0K5)", "I0K2": "I0K2 (лечение)", "I02F": "I02F (при получении урона)",
    "I0K4": "Starfire Echo (I0K4)", "I0K3": "I0K3 (лечение)", "I0K1": "Starfall Missile (I0K1)",
    "I0K0": "Starsurge (I0K0)", "I0P8": "Nature's Wrath (I0P8)", "I0JZ": "Entangle (I0JZ)", "I0P5": "Wisp (I0P5)",
    "I0ML": "I0ML (союзники)", "I0MS": "Druidism (I0MS)", "I0JY": "Starlight (I0JY)", "I0P4": "Regenesis (I0P4)",
    "I0P7": "Force of Nature (I0P7)", "I08O": "Wisp Spread (I08O)", "I08Q": "Healing from Damage (I08Q)", "I08S": "Double Heal (I08S)",
}
IGNORED_TALENTS = frozenset({"I0K2", "I02F", "I0K3", "I0ML"})
DIAMOND = "I00D"
# B_* order of the kernel; druid.BOUND_NAME
BUTTON_NAMES = ("Starfire", "Starfall", "Mass Entanglement", "Wisp Guardian")


class DruidCL(C.ExactCL):
    hero = "druid"
    PYTHON = False  # sunken_sim.druid fight model removed 2026-11-27: fixtures + report mode
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ("health", "healing_power")  # ESC points left out of the timeline key
    TABLE_KEYS = _S.ShamanCL.TABLE_KEYS + ("pimask", "pinc", "phealth")
    SCALARS = _S.ShamanCL.SCALARS
    SOURCE_NAMES = ("Автоатака", "Starfire", "Starfire (эхо)", "Starfall", "Mass Entanglement", "Treants",
                    "Wisp Guardian", "Всплеск огня", "Sulfuras", "Sulfuras (удар)",
                    "Отражение урона", "Sunstrider Crown", "Shield of Death", "Shado-Pan Faceguard",
                    "Bloodlord's Regalia", "Ice Cleaver")
    ACTION_NAMES = BUTTON_NAMES
    STAT_KEYS = ("int", "str", "agi", "ad", "potency", "mastery", "crit", "rating", "haste", "attack_speed", "luck",
                 "mana_max", "mana_regen", "swing", "cd_temp", "flat_cdr", "armor_pen", "bound", "spell_crit")
    BOOL_STATS = ("spell_crit",)
    NSRC, MAXA = 16, 160

    def report(self, codes, talents=(), glyphs=(), points: dict | None = None) -> dict:
        """class_cl report plus the Elemental Orb mode, the Diamond Ring binding and the ESC-only sheet lines."""
        from sunken_sim.shadow import ORB_MODE

        rep = super().report(codes, talents, glyphs, points)
        bound = int(rep["stats"].pop("bound"))
        rep["bound_spell"] = BUTTON_NAMES[bound] if bound >= 0 else None
        rep["orb_mode"] = next((name for code, name in ORB_MODE.items() if code in set(codes)), None)
        rep["stats"]["healing_power"] = float(int((points or {}).get("healing_power", 0)))
        rep["stats"]["pet_damage"] = 0.015 * int((points or {}).get("pet_damage", 0))
        return rep

    @staticmethod
    def module():
        raise RuntimeError("druid: the Python fight model was removed (2026-11-27)")

    def tables(self, space, items, sources):
        t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                               [float(DRUID_INT), float(DRUID_STR), float(DRUID_AGI)], "Druid")
        t.update(INC.inc_tables(space, items))
        t["phealth"] = np.array([float(sum(int(v) for v in re.findall(r"\+(\d+) Health\b", items[p.code].tip)))
                                 for p in space.pieces], dtype=np.float64)
        return t

    def timeline_key(self, build):
        # druid.simulate replayed a fight only across Health / Healing Power points, which never change it:
        # the key is every other ESC point (with the Diamond Ring the same key for every binding).
        from dataclasses import fields

        free = {f"{a}_points" for a in self.KEY_FREE}
        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points")
                     and f.name not in free)


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check


# Talents / items whose effect depends on the incoming-hit model (docs/defense-model.md)
INCOMING_TALENTS = frozenset({"I0K5", "I0P4", "I08S", "I08Q"})
INCOMING_ITEMS = INC.INCOMING_ITEMS
# map fixes after the Python model was removed: penetration only on the auto attack (Wisp armour kept), Voidseeker /
# Iron Cleaver, Fire Orb splash through the class damage, Ice Cleaver
MODEL_FIX_ITEMS = frozenset({"I031", "I0DU", "I0IU", "I0JU", "I0NT", "I0QN", "I0QV", "I07Y", "I055", "I07O", "lgdh"})
