"""Exact float64 OpenCL kernel for Shaman fights (Restoration, Enhancement, Elemental).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.shaman.sheet`` (``shadow.character`` with the shaman bases, white
13, no baked buffs; 1.85 s swing), run the event loop of
``sunken_sim.shaman.simulate`` (every Diamond Ring binding) and score the events
as ``shaman.score_events`` while they happen.  Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import class_cl as C

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 restoration, 1 enhancement, 2 elemental */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_RESTO (SPEC == 0)
#define SP_ENH (SPEC == 1)
#define SP_ELEM (SPEC == 2)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define MAXS 96
#define MAXB 96
#define MAXP 8
#define NSRC 12

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
#define S_EPAU (1UL<<14)
#define S_WOLF (1UL<<15)
#define S_TRIB (1UL<<16)
#define S_TENS (1UL<<17)
#define S_BELT (1UL<<18)
#define S_MULG (1UL<<19)

#define T_OVER (1u<<0)
#define T_WARD (1u<<1)
#define T_FLASH (1u<<2)
#define T_FURY (1u<<3)
#define T_FUSION (1u<<4)
#define T_WRATH (1u<<5)
#define T_THUNDER (1u<<6)
#define T_SPIRITC (1u<<7)
#define T_INFUS (1u<<8)
#define T_BLOOD (1u<<9)
#define T_MOLTEN (1u<<10)
#define T_TOTEMM (1u<<11)
#define T_STRIKE (1u<<12)

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

/* buttons */
#define B_CHAIN 0
#define B_SHIELD 1
#define B_SPIRIT 2
#define B_LAVA 3
#define B_TOTEM 4

/* sources */
#define N_AUTO 0
#define N_CHAIN 1
#define N_LESSER 2
#define N_STORMF 3
#define N_SHIELD 4
#define N_LAVA 5
#define N_MAGMA 6
#define N_SPIRIT 7
#define N_THUNDER 8
#define N_SPLASH 9
#define N_SULF 10
#define N_ECHO 11

typedef struct {
  double intel, str, agi, potency, mastery, ad, mana_max, crit, rating, haste, aspd;
  double spell_mult, flat_cdr, cd_temp, cast_lock;
  double auto_pct, armor_pen, luck;
  double attack_base, mana_regen, cast_refund, cast_refund_flat, cast_refund_mastery;
  double attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double mag_sum;
  double ex_thr[MAXE], ex_pct[MAXE];
  int spell_crit, nexec, targets;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double taken, attack_c0, echo_ch;
} Sco;

typedef struct {
  double mana, mana_time, hero_ready, next_attack, next_chain, next_shield, next_spirit, next_lava, next_totem;
  double chain_until, shield_until, charges, next_incoming, totem_until, next_bolt, fusion_until;
  double bl_s[MAXB], bl_e[MAXB], bl_c[MAXB];
  double sp_exp[MAXS], sp_next[MAXS], sp_inf[MAXS];
  double pd_t[MAXP]; int pd_k[MAXP];
  int nbl, nsp, npd, fusion_seen, attack_count, armed, status, bound;
  int max_charges, cast_charges, spirit_pack, chain_count, lesser_count;
  double totem_life;
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

/* _magical_multiplier(codes, now, mastery) for shaman codes */
inline double magical(const Row* r, double t, double mastery) {
  double ta = r->mag_sum;
  if (r->mask & S_SULG) ta += 0.13 + 0.25 * target_hp(t);
  double bonus = 1.0 + ta;
  double slope = 0.0;
  if (r->mask & S_TLUM) { bonus += 0.05; slope = 0.005; }
  if (GM(r, G_GLASS)) { bonus *= 1.15; slope *= 1.15; }
  return bonus + slope * mastery;
}

inline double luck_mult(const Row* tl) { return 1.0 + tl->luck; }
inline double proc(const Row* tl, double percent) {
  double v = percent / 100.0 * luck_mult(tl);
  return (v < 1.0) ? v : 1.0;
}
inline int totem_up(const St* s, double now) { return now < s->totem_until; }
inline double mastery_of(const St* s, const Row* tl, double now) {
  double bonus = (TM(tl, T_WRATH) && totem_up(s, now)) ? 6.0 : 0.0;
  return tl->mastery + bonus;
}
inline double crit_bonus_of(const St* s, const Row* tl, double now) {
  return (TM(tl, T_WRATH) && totem_up(s, now)) ? 8.0 : 0.0;
}
inline int fusion_up(const St* s, double now) { return now < s->fusion_until; }

/* shaman.blood_factor: Bloodlust is on when at least one proc window covers now */
double blood_factor(const St* s, double now) {
  double off = 1.0;
  for (int i = 0; i < s->nbl; i++)
    if (s->bl_s[i] <= now && now < s->bl_e[i]) off *= 1.0 - s->bl_c[i];
  return 1.0 - 0.18 * (1.0 - off);
}

/* score of one "deal" event, as score_events */
void score_deal(const Row* sc, Sco* q, int name, double raw, double now, double count, int attack, int mag,
                double mastery, double crit_bonus, int fusion, int auto_scale) {
  if (count <= 0.0) return;
  double cs = sc->crit + crit_bonus;
  double crit = (cs < 100.0) ? cs : 100.0;
  double amount = raw + ((name == N_SULF) ? 0.0 : sc->potency);
  if (mag) amount *= magical(sc, now, mastery);
  if (attack) amount *= crit_factor(crit, 2.0 + sc->rating);
  else if (sc->spell_crit) amount *= crit_factor(crit, sc->spell_mult + sc->rating);
  if (fusion) amount *= 1.25;
  amount *= q->taken * exec_factor(sc, now);
  if (auto_scale) amount *= sc->auto_pct;
  add_src(q, name, amount * count);
}

void deal(St* s, const Row* tl, const Row* sc, Sco* q, int name, double raw, double now, double count,
          int attack, int mag, int from_thunder, int auto_scale) {
  if (count <= 0.0 || now >= FIGHT) return;
  score_deal(sc, q, name, raw, now, count, attack, mag, mastery_of(s, tl, now), crit_bonus_of(s, tl, now),
             fusion_up(s, now), auto_scale);
  if (tl->damage_mana_pct != 0.0) {
    double v = s->mana + tl->damage_mana_pct * tl->mana_max * count;
    s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  }
  if (TM(tl, T_THUNDER) && !from_thunder) {
    double chance = proc(tl, 2.0);
    if (chance > 0.0) {
      /* deal("Thunderstorm", ...) with from_thunder=True: no further recursion */
      double c2 = count * chance * (double)tl->targets;
      if (!(c2 <= 0.0 || now >= FIGHT)) {
        score_deal(sc, q, N_THUNDER, 30.0 + 1.80 * tl->intel, now, c2, 0, 1, mastery_of(s, tl, now),
                   crit_bonus_of(s, tl, now), fusion_up(s, now), 0);
        if (tl->damage_mana_pct != 0.0) {
          double v = s->mana + tl->damage_mana_pct * tl->mana_max * c2;
          s->mana = (v < tl->mana_max) ? v : tl->mana_max;
        }
      }
    }
  }
}

inline double shield_raw(const St* s, const Row* tl, double now) {
  double raw = 20.0 + 0.30 * tl->intel;
  if (SP_ELEM) raw *= 1.05 + 0.006 * mastery_of(s, tl, now);
  if (TM(tl, T_WARD)) raw *= 1.10;
  return raw;
}
inline double chain_raw(const St* s, const Row* tl, double now) {
  double raw = 70.0 + 1.60 * tl->intel;
  if (SP_ENH) raw *= 1.08 + 0.005 * mastery_of(s, tl, now);
  return raw;
}

inline double monster_hit_at(double now) {
  double step = 0.2;
  long index = (long)((now + 1e-9) / step);
  double hit = (double)index * step;
  if (hit + 1e-9 < now) hit += step;
  return hit;
}
inline void arm_incoming(St* s, double now) {
  double hit = monster_hit_at(now);
  if (s->next_incoming >= FIGHT || hit < s->next_incoming) s->next_incoming = hit;
}

void add_flash(St* s, const Row* tl, double now, double hits) {
  if (!TM(tl, T_FLASH) || hits <= 0.0) return;
  double gained = hits * proc(tl, 15.0);
  if (gained <= 0.0) return;
  if (now >= s->shield_until) {
    s->charges = 0.0;
    s->shield_until = now + 20.0;
    arm_incoming(s, now);
  }
  double v = s->charges + gained;
  double mc = (double)s->max_charges;
  s->charges = (v < mc) ? v : mc;
}

void chain_package(St* s, const Row* tl, const Row* sc, Sco* q, double now, double scale, int count, int name, double weight) {
  if (count <= 0 || weight <= 0.0) return;
  double raw = chain_raw(s, tl, now);
  double primary = raw * (TM(tl, T_OVER) ? 1.40 : 1.0) * scale;
  deal(s, tl, sc, q, name, primary, now, weight, 0, 1, 0, 0);
  if (count > 1) deal(s, tl, sc, q, name, raw * scale, now, weight * (double)(count - 1), 0, 1, 0, 0);
  add_flash(s, tl, now, weight * (double)count);
}

void note_fusion(St* s, const Row* tl, int bit, double now) {
  if (!TM(tl, T_FUSION) || (s->fusion_seen & bit)) return;
  s->fusion_seen |= bit;
  int n = 0;
  for (int b = 0; b < 4; b++) if (s->fusion_seen & (1 << b)) n++;
  if (n < 3) return;
  s->fusion_seen = 0;
  s->fusion_until = now + 4.0;
}

void note_bloodlust(St* s, const Row* tl, double now) {
  if (!(TM(tl, T_BLOOD) || (tl->mask & S_TRIB))) return;
  double chance = proc(tl, 30.0);
  if (chance <= 0.0) return;
  double duration = SP_RESTO ? 5.0 : 8.0;
  if (s->nbl >= MAXB) { s->status = 5; return; }
  s->bl_s[s->nbl] = now; s->bl_e[s->nbl] = now + duration; s->bl_c[s->nbl] = chance; s->nbl++;
}

void summon(St* s, double now, int count) {
  double step = 1.4 * blood_factor(s, now);
  for (int i = 0; i < count; i++) {
    if (s->nsp >= MAXS) { s->status = 6; return; }
    s->sp_exp[s->nsp] = now + 12.0; s->sp_next[s->nsp] = now + step; s->sp_inf[s->nsp] = -1.0; s->nsp++;
  }
}

inline double cooldown(const St* s, const Row* tl, double base, int key) {
  double temp = tl->cd_temp * ((s->bound == key) ? 0.70 : 1.0);
  double v = (base * temp - tl->flat_cdr) / (1.0 + tl->haste);
  return (v > 0.5) ? v : 0.5;
}

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

/* pending.sort() order of (time, name): names sort chain < lava < shield < spirit < totem */
inline int name_rank(int k) { return k == B_CHAIN ? 0 : k == B_LAVA ? 1 : k == B_SHIELD ? 2 : k == B_SPIRIT ? 3 : 4; }

void cast(St* s, const Row* tl, int name, double now) {
  const double costs[5] = {20.0, 25.0, 35.0, 20.0, 40.0};
  if (!pay(s, tl, costs[name], now)) {
    if (name == B_CHAIN) s->next_chain = now + 0.25;
    else if (name == B_SHIELD) s->next_shield = now + 0.25;
    else if (name == B_SPIRIT) s->next_spirit = now + 0.25;
    else if (name == B_LAVA) s->next_lava = now + 0.25;
    else s->next_totem = now + 0.25;
    return;
  }
  if (name == B_CHAIN) s->next_chain = now + cooldown(s, tl, 7.0, B_CHAIN);
  else if (name == B_SHIELD) {
    double base = 13.0 - ((tl->mask & S_TENS) ? 3.0 : 0.0);
    s->next_shield = now + cooldown(s, tl, base, B_SHIELD);
  } else if (name == B_SPIRIT) s->next_spirit = now + cooldown(s, tl, 15.0, B_SPIRIT);
  else if (name == B_LAVA) {
    double base = 8.0 - (TM(tl, T_FURY) ? 1.2 : 0.0);
    s->next_lava = now + cooldown(s, tl, base, B_LAVA);
  } else {
    double base = 16.0 - (TM(tl, T_TOTEMM) ? 5.0 : 0.0);
    s->next_totem = now + cooldown(s, tl, base, B_TOTEM);
  }
  if (tl->mask & S_SULF) s->armed = 1;
  if (s->npd >= MAXP) { s->status = 2; return; }
  double t = now + CAST_POINT;
  int i = s->npd++;
  while (i > 0 && (s->pd_t[i - 1] > t || (s->pd_t[i - 1] == t && name_rank(s->pd_k[i - 1]) > name_rank(name)))) {
    s->pd_t[i] = s->pd_t[i - 1]; s->pd_k[i] = s->pd_k[i - 1]; i--;
  }
  s->pd_t[i] = t; s->pd_k[i] = name;
  const double cast_time = CAST_POINT + CAST_BACKSWING;
  double busy = now + cast_time + tl->cast_lock;
  s->hero_ready = busy;
  s->next_attack = (busy > s->next_attack) ? busy : s->next_attack;
}

void resolve(St* s, const Row* tl, const Row* sc, Sco* q, int name, double now) {
  if (name == B_CHAIN) {
    note_fusion(s, tl, 1, now);
    note_bloodlust(s, tl, now);
    s->chain_until = now + 4.0;
    if (TM(tl, T_INFUS)) {
      double until = now + 3.0;
      for (int i = 0; i < s->nsp; i++) if (now < s->sp_exp[i]) s->sp_inf[i] = until;
    }
  } else if (name == B_SHIELD) {
    note_fusion(s, tl, 2, now);
    note_bloodlust(s, tl, now);
    s->shield_until = now + 20.0;
    s->charges = (double)s->cast_charges;
    arm_incoming(s, now);
    if (tl->mask & S_BELT) s->next_lava = now;
  } else if (name == B_SPIRIT) {
    note_fusion(s, tl, 4, now);
    note_bloodlust(s, tl, now);
    summon(s, now, s->spirit_pack);
  } else if (name == B_LAVA) {
    note_fusion(s, tl, 4, now);
    note_bloodlust(s, tl, now);
    double spent = (now < s->shield_until) ? s->charges : 0.0;
    if (spent > 0.0) {
      deal(s, tl, sc, q, N_SHIELD, shield_raw(s, tl, now), now, spent, 0, 1, 0, 0);
      s->charges = 0.0;
      s->shield_until = -1.0;
      if (TM(tl, T_MOLTEN) && spent >= 1.0) {
        double v = s->next_shield - 4.0;
        s->next_shield = (v > now) ? v : now;
      }
    }
    double raw = 100.0 + 2.50 * tl->intel;
    raw *= 1.0 + 0.008 * mastery_of(s, tl, now);
    if (TM(tl, T_FURY)) raw *= 1.18;
    raw *= 1.0 + 0.08 * spent;
    deal(s, tl, sc, q, N_LAVA, raw, now, 1.0, 0, 1, 0, 0);
  } else {
    note_fusion(s, tl, 8, now);
    note_bloodlust(s, tl, now);
    s->totem_until = now + s->totem_life;
    s->next_bolt = SP_ELEM ? (now + 1.5) : FIGHT;
  }
}

int next_ready(const St* s, double now, double* out) {
  double times[4];
  times[0] = (s->chain_until > s->next_chain) ? s->chain_until : s->next_chain;
  times[1] = s->next_shield;
  times[2] = (s->totem_until > s->next_totem) ? s->totem_until : s->next_totem;
  times[3] = SP_ELEM ? s->next_lava : s->next_spirit;
  int found = 0;
  double best = 0.0;
  for (int i = 0; i < 4; i++) {
    if (times[i] > now + 1e-9) {
      if (!found || times[i] < best) { best = times[i]; found = 1; }
    }
  }
  *out = best;
  return found;
}

int choose(const St* s, double now) {
  int lava_ready = SP_ELEM && s->next_lava <= now;
  int shield_ready = s->next_shield <= now;
  int need_shield = now >= s->shield_until || s->charges < 1.0;
  int chain_ready = s->next_chain <= now && now >= s->chain_until;
  int spirit_ready = (!SP_ELEM) && s->next_spirit <= now;
  int totem_ready = s->next_totem <= now && now >= s->totem_until;
  if (SP_ELEM && lava_ready && s->charges >= 1.0 && now < s->shield_until) return B_LAVA;
  if (SP_ELEM && need_shield && shield_ready) return B_SHIELD;
  if (chain_ready) return B_CHAIN;
  if ((!SP_ELEM) && need_shield && shield_ready) return B_SHIELD;
  if (spirit_ready) return B_SPIRIT;
  if (totem_ready) return B_TOTEM;
  if (lava_ready) return B_LAVA;
  if (shield_ready && need_shield) return B_SHIELD;
  return -1;
}

void on_attack(St* s, const Row* tl, const Row* sc, Sco* q, double now) {
  recover(s, tl, now);
  if (s->chain_until >= now) {
    s->chain_until = -1.0;
    chain_package(s, tl, sc, q, now, 1.0, s->chain_count, N_CHAIN, 1.0);
    if (SP_ENH && totem_up(s, now)) chain_package(s, tl, sc, q, now, 0.30, s->lesser_count, N_STORMF, 1.0);
  }
  double chance = 8.0 + 0.15 * tl->agi;
  if (SP_ENH) chance += 10.0;
  if (tl->mask & S_EPAU) chance += 8.0;
  if (TM(tl, T_STRIKE)) chance *= 1.20;
  double lesser_p = proc(tl, chance);
  if (lesser_p > 0.0) {
    chain_package(s, tl, sc, q, now, 0.50, s->lesser_count, N_LESSER, lesser_p);
    if (SP_ENH && totem_up(s, now)) chain_package(s, tl, sc, q, now, 0.30, s->lesser_count, N_STORMF, lesser_p);
  }
  if (now < s->shield_until && s->charges > 0.0) {
    double spent = (1.0 < s->charges) ? 1.0 : s->charges;
    s->charges -= spent;
    deal(s, tl, sc, q, N_SHIELD, shield_raw(s, tl, now), now, spent, 0, 1, 0, 0);
    if (s->charges <= 1e-9) { s->charges = 0.0; s->shield_until = -1.0; }
  }
  deal(s, tl, sc, q, N_AUTO, tl->ad, now, 1.0, 1, 1, 0, 1);
  double gain = tl->attack_mana + tl->attack_mana_pct * tl->mana_max;
  if (tl->attack_mana_crit != 0.0) {
    double cc = (100.0 < tl->crit) ? 100.0 : tl->crit;
    gain *= 1.0 + cc / 100.0;
  }
  double v = s->mana + gain;
  s->mana = (v < tl->mana_max) ? v : tl->mana_max;
  if (tl->mask & S_ORB) {
    double raw = 20.0 + 0.35 * tl->intel;
    add_src(q, N_SPLASH, raw * (double)tl->targets * q->taken * exec_factor(sc, now));
  }
  if (tl->mask & S_SULF) {
    if (s->armed) {
      s->armed = 0;
      score_deal(sc, q, N_SULF, tl->intel, now, (double)tl->targets, 0, 1, mastery_of(s, tl, now),
                 crit_bonus_of(s, tl, now), fusion_up(s, now), 0);
    }
    add_src(q, N_ECHO, tl->ad * q->taken * exec_factor(sc, now) * q->echo_ch);
  }
  s->attack_count += 1;
  if (TM(tl, T_SPIRITC) && !SP_ELEM && s->attack_count >= 4) {
    s->attack_count = 0;
    summon(s, now, 1);
  }
  int alive = 0;
  for (int i = 0; i < s->nsp; i++) if (now < s->sp_exp[i]) alive++;
  double sa = 0.10 * (double)alive;
  sa = (0.40 < sa) ? 0.40 : sa;
  double sp = tl->aspd + sa;
  sp = (-0.8 >= sp) ? -0.8 : sp;
  sp = (4.0 <= sp) ? 4.0 : sp;
  s->next_attack = now + tl->attack_base * blood_factor(s, now) / (1.0 + sp);
}

void on_incoming(St* s, const Row* tl, const Row* sc, Sco* q, double now) {
  if (now >= s->shield_until || s->charges <= 0.0) { s->next_incoming = FIGHT; return; }
  double spent = (1.0 < s->charges) ? 1.0 : s->charges;
  s->charges -= spent;
  deal(s, tl, sc, q, N_SHIELD, shield_raw(s, tl, now), now, spent, 0, 1, 0, 0);
  if (s->charges <= 1e-9) {
    s->charges = 0.0; s->shield_until = -1.0; s->next_incoming = FIGHT;
  } else {
    s->next_incoming = monster_hit_at(now + 0.75);
  }
}

void on_spirit(St* s, const Row* tl, const Row* sc, Sco* q, int i, double now) {
  if (now >= s->sp_exp[i]) { s->sp_next[i] = FIGHT; return; }
  double hit = 8.0 + floor(0.25 * tl->ad);
  double crit = 10.0 + ((TM(tl, T_WRATH) && totem_up(s, now)) ? 8.0 : 0.0);
  /* score_events "spirit" */
  double amount = hit * crit_factor(crit, 2.0);
  if (fusion_up(s, now)) amount *= 1.25;
  amount *= q->taken * exec_factor(sc, now);
  add_src(q, N_SPIRIT, amount);
  if (TM(tl, T_THUNDER)) {
    double chance = proc(tl, 2.0);
    if (chance > 0.0) deal(s, tl, sc, q, N_THUNDER, 30.0 + 1.80 * tl->intel, now, chance * (double)tl->targets, 0, 1, 1, 0);
  }
  double infused = (now < s->sp_inf[i]) ? 1.5 : 1.0;
  double cp = (100.0 < crit) ? 100.0 : crit;
  double crit_p = cp / 100.0;
  double base_p = 0.15 * infused * luck_mult(tl);
  double m1 = (base_p < 1.0) ? base_p : 1.0;
  double b2 = base_p * 1.5;
  double m2 = (b2 < 1.0) ? b2 : 1.0;
  double lesser_p = (1.0 - crit_p) * m1 + crit_p * m2;
  if (lesser_p > 0.0) chain_package(s, tl, sc, q, now, 0.50, s->lesser_count, N_LESSER, lesser_p);
  s->sp_next[i] = now + 1.4 * blood_factor(s, now);
}

void on_bolt(St* s, const Row* tl, const Row* sc, Sco* q, double now) {
  if (now >= s->totem_until) { s->next_bolt = FIGHT; return; }
  double raw = 20.0 + 0.50 * tl->intel + mastery_of(s, tl, now);
  deal(s, tl, sc, q, N_MAGMA, raw, now, 1.0, 0, 1, 0, 0);
  double cut = 0.50 * proc(tl, 50.0);
  if (cut > 0.0) {
    double lava_left = s->next_lava - now;
    double shield_left = s->next_shield - now;
    if (lava_left > shield_left && lava_left > 0.0) { double v = s->next_lava - cut; s->next_lava = (v > now) ? v : now; }
    else if (shield_left > 0.0) { double v = s->next_shield - cut; s->next_shield = (v > now) ? v : now; }
    else if (lava_left > 0.0) { double v = s->next_lava - cut; s->next_lava = (v > now) ? v : now; }
  }
  s->next_bolt = now + 1.5;
}

/* shaman.simulate(build, targets, spec, bound) on the timeline sheet, scored on the scored sheet */
double fight(const Row* tl, const Row* sc, int bound, int* status_out) {
  St s; Sco q;
  int st = 0;
  q.taken = armor_taken(15.0 - sc->armor_pen, &st);
  if (st) { *status_out = st; return 0.0; }
  q.echo_ch = 0.10 * (1.0 + sc->luck);
  q.nord = 0; q.seen = 0u;
  s.bound = bound; s.status = 0;
  s.mana = tl->mana_max; s.mana_time = 0.0; s.hero_ready = 0.0; s.next_attack = 0.0;
  s.next_chain = 0.0; s.next_shield = 0.0; s.next_spirit = 0.0; s.next_lava = 0.0; s.next_totem = 0.0;
  s.chain_until = -1.0; s.shield_until = -1.0; s.charges = 0.0; s.next_incoming = FIGHT;
  s.totem_until = -1.0; s.next_bolt = FIGHT; s.fusion_until = -1.0;
  s.nbl = 0; s.nsp = 0; s.npd = 0; s.fusion_seen = 0; s.attack_count = 0; s.armed = 0;
  int ward = TM(tl, T_WARD) ? 3 : 0;
  s.cast_charges = 8 + ward; s.max_charges = 12 + ward;
  s.spirit_pack = (tl->mask & S_WOLF) ? 3 : 2;
  s.totem_life = 12.0 + ((tl->mask & S_MULG) ? 4.0 : 0.0);
  s.chain_count = (tl->targets < 6) ? tl->targets : 6;
  s.lesser_count = (tl->targets < 3) ? tl->targets : 3;

  int guard = 0;
  while (guard < 200000) {
    guard += 1;
    if (s.status) break;
    int k = 0;
    for (int i = 0; i < s.nsp; i++) {
      if (s.sp_next[i] < s.sp_exp[i] && s.sp_next[i] < FIGHT) {
        s.sp_exp[k] = s.sp_exp[i]; s.sp_next[k] = s.sp_next[i]; s.sp_inf[k] = s.sp_inf[i]; k++;
      }
    }
    s.nsp = k;
    double nss = FIGHT;
    for (int i = 0; i < s.nsp; i++) if (i == 0 || s.sp_next[i] < nss) nss = s.sp_next[i];
    if (s.nsp == 0) nss = FIGHT;
    if (s.next_bolt >= s.totem_until) s.next_bolt = FIGHT;
    if (s.next_incoming >= s.shield_until) s.next_incoming = FIGHT;
    double next_effect = s.npd ? s.pd_t[0] : FIGHT;
    double moment = s.next_attack;
    if (nss < moment) moment = nss;
    if (s.next_bolt < moment) moment = s.next_bolt;
    if (s.next_incoming < moment) moment = s.next_incoming;
    if (next_effect < moment) moment = next_effect;
    if (s.npd && next_effect <= moment && next_effect < FIGHT) {
      int name = s.pd_k[0];
      for (int i = 1; i < s.npd; i++) { s.pd_t[i - 1] = s.pd_t[i]; s.pd_k[i - 1] = s.pd_k[i]; }
      s.npd--;
      resolve(&s, tl, sc, &q, name, next_effect);
      continue;
    }
    if (s.hero_ready <= moment && s.hero_ready < FIGHT) {
      int spell = choose(&s, s.hero_ready);
      if (spell >= 0) { cast(&s, tl, spell, s.hero_ready); continue; }
      double wake;
      if (next_ready(&s, s.hero_ready, &wake) && wake <= moment) { s.hero_ready = wake; continue; }
    }
    if (moment >= FIGHT) break;
    if (moment == s.next_attack) { on_attack(&s, tl, sc, &q, moment); continue; }
    if (moment == s.next_incoming) { on_incoming(&s, tl, sc, &q, moment); continue; }
    if (moment == s.next_bolt) { on_bolt(&s, tl, sc, &q, moment); continue; }
    for (int i = 0; i < s.nsp; i++) if (s.sp_next[i] == moment) on_spirit(&s, tl, sc, &q, i, moment);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < q.nord; i++) total += q.src[q.ord[i]];
  return total / FIGHT;
}

#define IDX(item, slots, leg, orb, amp) (((((long)(item) * 7 + (slots)) * 2 + (leg)) * 2 + (orb)) * 2 + (amp))

typedef struct {
  __global const long* dp0; __global const long* dp1; long count_without; long total;
  int npieces; __global const int* pkind; __global const int* pamp;
  __global const double* fold; __global const double* uniq; __global const ulong* pmask; __global const int* psrc;
  int nmag; __global const int* mag_kind; __global const int* mag_id; __global const double* mag_amt;
  __global const double* base;
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

int present(Tab* T, int kind, int id, const int* chosen, uint tmask, uint gmask) {
  if (kind == 0) { for (int si = 0; si < 6; si++) if (chosen[si] == id) return 1; return 0; }
  if (kind == 1) return (gmask >> id) & 1u;
  return (tmask >> id) & 1u;
}

/* shaman.sheet(build): shadow.character(bases, white 13, bake_timed_buffs=False), 1.85 s swing */
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
  damage = 13.0 + 0.75 * intel + damage;
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
  int acrit = 0, nexec = 0;
  for (int si = 0; si < 6; si++) {
    if (!first[si]) continue;
    __global const double* u = T->uniq + (long)chosen[si] * NU;
    cast_lock += u[1];
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
  }
  double mag_sum = 0.0;
  for (int e = 0; e < T->nmag; e++)
    if (present(T, T->mag_kind[e], T->mag_id[e], chosen, tmask, gmask)) mag_sum += T->mag_amt[e];
  double stat = (1.20 + 0.10 * intel) * (1.0 + regen_rate);
  stat += mp5 / 5.0;
  stat += persec * mana;
  if (GM(r, G_REPL)) stat += 1.50 + 0.0075 * mana;
  r->intel = intel; r->str = strength; r->agi = agility; r->potency = potency; r->mastery = mastery; r->ad = damage;
  r->mana_max = mana; r->crit = (100.0 <= crit) ? 100.0 : crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->spell_mult = sc65 ? 1.65 : 1.50;
  r->flat_cdr = flat_cdr; r->cd_temp = cd_temp; r->cast_lock = cast_lock;
  r->auto_pct = auto_pct; r->armor_pen = armor_pen;
  double luck = 0.01 * (double)pts[9];
  for (int si = 0; si < 6; si++) if (first[si]) luck += T->uniq[(long)chosen[si] * NU + 13];
  if (GM(r, G_FORTUNE)) luck += 0.15;
  r->luck = luck;
  r->attack_base = 1.85 * ((mask & S_GALA) ? 1.20 : 1.0);
  r->mana_regen = stat * 0.80;
  r->cast_refund = 1.0 - keep; r->cast_refund_flat = rflat; r->cast_refund_mastery = rmast;
  r->attack_mana = aflat; r->attack_mana_pct = apct; r->attack_mana_crit = acrit ? 1.0 : 0.0; r->damage_mana_pct = dpct;
  r->mag_sum = mag_sum;
  r->spell_crit = sc; r->nexec = nexec; r->targets = targets;
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
  int buttons[4];
  if (SP_ELEM) { buttons[0] = B_CHAIN; buttons[1] = B_SHIELD; buttons[2] = B_LAVA; buttons[3] = B_TOTEM; }
  else { buttons[0] = B_CHAIN; buttons[1] = B_SHIELD; buttons[2] = B_SPIRIT; buttons[3] = B_TOTEM; }
  int ring = (sc.mask & S_RING) != 0;
  int nv = ring ? 4 : 1;
  double best = 0.0;
  for (int i = 0; i < nv; i++) {
    double d = fight(&tl, &sc, ring ? buttons[i] : -1, status);
    if (*status) return 0.0;
    if (i == 0 || d > best) best = d;
  }
  return best;
}

#define TAB_ARGS \
    __global const long* dp0, __global const long* dp1, const long count_without, const long total, \
    const int npieces, __global const int* pkind, __global const int* pamp, \
    __global const double* fold, __global const double* uniq, __global const ulong* pmask, __global const int* psrc, \
    const int nmag, __global const int* mag_kind, __global const int* mag_id, __global const double* mag_amt, \
    __global const double* base

#define TAB_INIT \
  Tab T; T.dp0 = dp0; T.dp1 = dp1; T.count_without = count_without; T.total = total; \
  T.npieces = npieces; T.pkind = pkind; T.pamp = pamp; T.fold = fold; T.uniq = uniq; T.pmask = pmask; T.psrc = psrc; \
  T.nmag = nmag; T.mag_kind = mag_kind; T.mag_id = mag_id; T.mag_amt = mag_amt; T.base = base;

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

SPECIAL_BITS = {
    "I00D": 0, "I0BR": 1, "I07O": 2, "I0JO": 3, "I0QT": 4, "I096": 5, "I03C": 6, "I00L": 7,
    "I00Y": 8, "I07P": 9, "I048": 10, "I03L": 11, "tlum": 12, "I0FW": 13,
    "I0O9": 14, "I0S7": 15, "I0O8": 16, "I0S8": 17, "I0O6": 18, "I0S9": 19,
}
TALENT_BITS = {
    "I0F1": 0, "I03T": 1, "I0NN": 2, "I0MB": 3, "I0OA": 4, "I0EX": 5, "I03V": 6, "I0ME": 7,
    "I0F4": 8, "I0FB": 9, "I0MA": 10, "I0EU": 11, "I0AG": 12,
    # read nowhere in sunken_sim.shaman: no effect on the fight
    "I0FA": 20, "I0EY": 21, "I0ER": 22, "I0EB": 23, "I03U": 24,
}
GLYPH_BITS = {
    "I07B": 0, "I0AV": 1, "I0EK": 2, "I0GZ": 3, "I0H3": 4, "I0H5": 5, "I0H6": 6, "I0HC": 7,
    "I0JA": 8, "I0OF": 9, "I0H0": 10, "I0EJ": 11,
}
NO_EFFECT = {"I0EN"}
SPECS = {"restoration": 0, "enhancement": 1, "elemental": 2}
BOUNDS = ("chain", "shield", "spirit", "lava", "totem")


class ShamanCL(C.ExactCL):
    hero = "shaman"
    KERNEL = KERNEL
    SPECS = SPECS
    TALENT_BITS = TALENT_BITS
    GLYPH_BITS = GLYPH_BITS
    NO_EFFECT = NO_EFFECT
    KEY_FREE = ("health", "healing_power")  # ESC points left out of the timeline key
    TABLE_KEYS = ("dp0", "dp1", "count_without", "total", "npieces", "pkind", "pamp", "fold", "uniq", "pmask", "psrc",
                  "nmag", "mag_kind", "mag_id", "mag_amt", "base")
    SCALARS = {"count_without": np.int64, "total": np.int64, "npieces": np.int32, "nmag": np.int32}

    @staticmethod
    def module():
        from sunken_sim import shaman

        return shaman

    def tables(self, space, items, sources):
        from sunken_sim import shaman

        if shaman.SWING != 1.85 or shaman.WHITE_BASE != 13.0 or shaman.TOTEM_LIFE != 12.0:
            raise ValueError("kernel constants assume the 2026-11-10 shaman")
        return C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                                  [shaman.BASE_INT, shaman.BASE_STR, shaman.BASE_AGI], "Shaman")

    def timeline_key(self, build):
        from sunken_sim import shaman

        stats = shaman.sheet(build)
        if shaman._wears(build, shaman.DIAMOND):
            return tuple(shaman._timeline_key(build, stats, self.spec, self.targets, b) for b in shaman.buttons(self.spec))
        return shaman._timeline_key(build, stats, self.spec, self.targets, None)


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
