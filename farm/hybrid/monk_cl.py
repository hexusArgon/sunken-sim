"""Exact float64 OpenCL kernel for Monk fights (Windwalker, Brewmaster, Mistweaver).

One work-item scores one fight: unrank the six items, fold the sheet like
``sunken_sim.monk.stats_of`` (strength primary, Inner Harmony, Frenzied Assault) and run
all 24 rotation policies of ``monk.simulate`` (hold x plain_mist x brew_first), keeping the
best (``dps > best + 1e-9``), with Ledger sums in insertion order (eight seeded sources, then
Sulfuras / Sulfuras echo in order of first write). Windwalker Power Strike echoes are a
small (time, chance) queue popped in tuple order; Battle Frenzy / Silent Messenger:
farm.hybrid.attack_procs_cl.

``monk.simulate`` has no timeline cache, so every row is its own fight.
Rows the kernel cannot score (more than MAXT targets, negative armour, echo queue overflow)
return a non-zero status and are re-scored by the Python oracle. Host side: farm.hybrid.class_cl.
"""

from __future__ import annotations

import numpy as np

from farm.hybrid import attack_procs_cl as AP
from farm.hybrid import class_cl as C

NPAL = 6

KERNEL = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable
#pragma OPENCL FP_CONTRACT OFF

#ifndef TALENTS
#define TALENTS 1
#endif
/* spec: 0 windwalker, 1 brewmaster, 2 mistweaver */
#ifndef SPEC
#define SPEC 0
#endif
#define SP_WW (SPEC == 0)

#define FIGHT 30.0
#define CAST_POINT 0.15
#define CAST_BACKSWING 0.30
#define MAXE 6
#define NF 15
#define NU 48
#define NP 11
#define NPAL 6
#define NSRC 10
#define MAXT 8
#define MAXQ 8
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
#define S_GAZE (1UL<<14)
#define S_WARS (1UL<<15)
#define S_SILM (1UL<<16)

#define T_AXUEN (1u<<0)
#define T_ANIU (1u<<1)
#define T_ACHI (1u<<2)
#define T_MART (1u<<3)
#define T_FOF (1u<<4)
#define T_WAY (1u<<5)
#define T_INNER (1u<<6)
#define T_LEGACY (1u<<7)
#define T_FRENZ (1u<<8)
#define T_JAB (1u<<9)
#define T_FLURRY (1u<<10)

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

/* Ledger: eight seeded sources, then Sulfuras / echo in order of first write */
#define N_AUTO 0
#define N_FB 1
#define N_PS 2
#define N_PSW 3
#define N_CEL 4
#define N_WT 5
#define N_WRATH 6
#define N_FIRE 7
#define N_SULF 8
#define N_ECHO 9

/* stances / avatars */
#define X_NONE 0
#define X_XUEN 1
#define X_CHIJI 2
#define X_NIUZAO 3
#define X_YULON 4

/* keys, monk order ("ps", "cw", "fb", "rm") */
#define K_PS 0
#define K_CW 1
#define K_FB 2
#define K_RM 3

typedef struct {
  double str, agi, intel, potency, mastery, damage, crit, rating, haste, aspd;
  double magic_add, phys_add, armor_pen, spell_mult, auto_pct, attack_potency, cd_temp, flat_cdr, increase;
  double luck, mana_max, mana_regen, cast_lock;
  double cast_refund, cast_refund_flat, cast_refund_mastery, attack_mana, attack_mana_pct, attack_mana_crit, damage_mana_pct;
  double ex_thr[MAXE], ex_pct[MAXE];
  int nexec, targets, glass, spell_crit;
  uint tmask, gmask;
  ulong mask;
} Row;

typedef struct {
  double src[NSRC]; int ord[NSRC]; int nord; uint seen;
  double q_w[MAXQ], q_c[MAXQ]; int qn;
  double nxt[4];
  double mana, mana_time, ps_buff_until, wrath_until, fof, bx_until, by_until, taken;
  double strength, agility, mastery_i;
  int stance, emp, jab, fb_attack, avatar, ps_avatar, armed, status, targets;
  int hold, plain_mist, brew_first;
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

double haste_at(const Row* r, const St* s, double now) {
  return r->haste + ((now < s->by_until) ? 0.18 : 0.0);
}

double cooldown_of(double base, double haste, const Row* r) {
  double v = (base * r->cd_temp - r->flat_cdr - 0.0) / (1.0 + haste);
  return (v > 0.5) ? v : 0.5;
}

double typed(const Row* r, int magical, double now) {
  double bonus = 1.0 + (magical ? r->magic_add : r->phys_add);
  if (r->mask & S_SULG) bonus += 0.13 + 0.25 * target_hp(now);
  if (magical && (r->mask & S_TLUM)) bonus += 0.05 + 0.005 * r->mastery;
  if (r->glass) bonus *= 1.15;
  return bonus * (1.0 + r->increase);
}

void cut_wrath(const Row* r, St* s, double crits, double now) {
  if ((r->mask & S_WARS) && crits > 0.0 && s->nxt[K_CW] > now) {
    double v = s->nxt[K_CW] - 0.30 * crits;
    s->nxt[K_CW] = (v > now) ? v : now;
  }
}

/* magical spell damage from the Monk; returns dealt per hit */
double magic(const Row* r, St* s, int name, double raw, double now, double count) {
  double amount = (raw + r->potency) * typed(r, 1, now);
  double crits = 0.0;
  if (r->spell_crit) {
    amount *= crit_factor(r->crit, r->spell_mult + r->rating);
    crits = chance01(r->crit / 100.0) * count;
  }
  double dealt = amount * s->taken * exec_factor(r, now);
  add_src(s, name, dealt * count);
  note_damage_mana(r, s, count);
  if (TM(r, T_FOF)) {
    double v = s->fof + 0.10 * dealt * count;
    s->fof = (v < 750.0) ? v : 750.0;
  }
  cut_wrath(r, s, crits, now);
  return dealt;
}

/* physical attack through PreDamage_Increase: FoF add, crit, Red Crane */
double attack_hit(const Row* r, St* s, int name, double raw, double now, int red_crane, double potency_scale) {
  double amount = raw + r->potency * potency_scale;
  if (s->fof > 0.0) { amount += s->fof; s->fof = 0.0; }
  amount *= typed(r, 0, now);
  double chance = r->crit;
  double rating = 2.0 + r->rating;
  double crits;
  if (red_crane) {
    amount *= (1.0 + chance / 100.0) * rating;
    crits = 1.0;
  } else {
    amount *= crit_factor(chance, rating);
    crits = chance01(chance / 100.0);
  }
  double dealt = amount * s->taken * exec_factor(r, now);
  add_src(s, name, dealt);
  note_damage_mana(r, s, 1.0);
  cut_wrath(r, s, crits, now);
  return dealt;
}

double ps_damage(const St* s) {
  double value = (60.0 * RANK + 1.0 * s->strength) * (1.0 + 0.005 * s->agility);
  if (SP_WW) value *= 1.05 + 0.008 * s->mastery_i;
  return value;
}

void white_tiger(const Row* r, St* s, double amount, double now) {
  magic(r, s, N_WT, 2.0 * amount, now, (double)s->targets);
}

void power_strike(const Row* r, St* s, double now, int proc, double weight) {
  double damage = ps_damage(s);
  if (proc) damage *= 0.50;
  else if (SP_WW) {
    if (s->qn >= MAXQ) { if (!s->status) s->status = 5; }
    else { s->q_w[s->qn] = now + 0.50; s->q_c[s->qn] = chance01(0.40 * (1.0 + r->luck)); s->qn++; }
  }
  if (s->ps_avatar == X_CHIJI && !proc) {
    s->ps_avatar = X_NONE;
    white_tiger(r, s, 0.15 * damage, now);
    damage *= 1.40;
  }
  if (proc) magic(r, s, N_PSW, damage, now, weight);
  else magic(r, s, N_PS, damage, now, 1.0);
  if (!proc && (s->ps_avatar == X_NIUZAO || s->ps_avatar == X_YULON)) s->ps_avatar = X_NONE;
  if ((r->mask & S_GAZE) && !proc) white_tiger(r, s, 0.15 * damage, now);
}

int emp_max(const Row* r) { return TM(r, T_MART) ? 3 : 2; }

void spend_emp(const Row* r, St* s, double now) {
  s->emp -= 1;
  if (s->emp <= 0) { s->emp = 0; s->stance = X_NONE; }
  if (TM(r, T_JAB)) {
    s->jab += 1;
    if (s->jab == 5) { s->jab = 0; power_strike(r, s, now, 0, 1.0); }
  }
}

void set_stance(const Row* r, St* s, int v) { s->stance = v; s->emp = emp_max(r); }

void celestial(const Row* r, St* s, double now, int code) {
  if (!(s->stance == X_XUEN || SP_WW)) return;
  double amount = 0.15 * ps_damage(s);
  if (s->stance == X_XUEN && !code) {
    spend_emp(r, s, now);
    white_tiger(r, s, amount, now);
  } else if (SP_WW) {
    magic(r, s, N_CEL, amount, now, 1.0);
  }
  if (TM(r, T_FLURRY) && SP_WW) magic(r, s, N_CEL, amount, now, chance01(0.40 * (1.0 + r->luck)));
}

void wrath_of_xuen(const Row* r, St* s, double dealt, double now) {
  if (now < s->wrath_until) {
    s->wrath_until = -1.0;
    magic(r, s, N_WRATH, 20.0 + 1.0 * s->strength + 0.50 * dealt, now, (double)s->targets);
  }
}

double dcs(const Row* r, const St* s) { return 14.0 + 0.75 * s->strength + r->damage; }

double attack_interval(const Row* r, const St* s, double now) {
  double swing = 1.85 * ((r->mask & S_GALA) ? 1.20 : 1.0);
  double speed = r->aspd + ap_bonus(&s->ap, now);
  if (s->stance != X_NONE) speed += 0.40;
  if (now < s->bx_until) speed += 0.40;
  speed = ap_speed(speed);
  return swing / (1.0 + speed);
}

double gcd(const Row* r, const St* s, double now) {
  return (TM(r, T_LEGACY) ? 1.0 : 1.5) / (1.0 + haste_at(r, s, now));
}

int allowed(const Row* r, const St* s, int key, double now) {
  double cast_time = CAST_POINT + CAST_BACKSWING;
  if ((s->stance == X_XUEN || s->stance == X_CHIJI) && s->emp > 0) {
    if (s->hold == 3) {
      if (emp_max(r) - s->emp < 2) return 0;
    } else if (s->hold == 4) {
      if (key == K_FB || key == K_RM) return 0;
    } else if (s->hold <= 2) {
      double limit = (s->hold == 1) ? 1.4 : (s->hold == 2) ? 0.7 : FIGHT;
      if (now - s->nxt[key] < limit) return 0;
    }
  }
  if (key == K_RM && !s->plain_mist && !(s->avatar == X_XUEN || s->avatar == X_CHIJI)) return 0;
  if (s->brew_first && key == K_CW && s->avatar == X_XUEN && s->nxt[K_FB] <= now + gcd(r, s, now) + cast_time) return 0;
  if (key == K_PS && now < s->ps_buff_until) return 0;
  if ((key == K_FB || key == K_RM) && s->avatar == X_CHIJI) return 0;
  if (key == K_RM && s->avatar == X_XUEN && s->nxt[K_FB] <= now + gcd(r, s, now) + cast_time) return 0;
  return 1;
}

double max3(double a, double b, double c) {
  double m = (b > a) ? b : a;
  return (c > m) ? c : m;
}

/* monk._simulate(build, targets, spec, policy) -> dps */
double sim_policy(const Row* r, int hold, int plain_mist, int brew_first, int* status_out) {
  St s;
  if (r->targets > MAXT) { *status_out = 3; return 0.0; }
  s.targets = r->targets; s.status = 0; s.armed = 0;
  s.hold = hold; s.plain_mist = plain_mist; s.brew_first = brew_first;
  s.nord = 8; s.seen = 0xFFu;
  for (int i = 0; i < 8; i++) { s.ord[i] = i; s.src[i] = 0.0; }
  s.strength = (double)(int)r->str;
  s.agility = (double)(int)r->agi;
  s.mastery_i = (double)(int)r->mastery;
  {
    double armor = 15.0 - r->armor_pen;
    if (armor < 0.0) { *status_out = 4; return 0.0; }
    s.taken = (armor > 0.0) ? 1.0 - (armor * 0.04) / (1.0 + 0.04 * armor) : 1.0;
  }
  s.mana = r->mana_max; s.mana_time = 0.0;
  s.stance = X_NONE; s.emp = 0; s.jab = 0; s.ps_buff_until = -1.0; s.fb_attack = 0;
  s.avatar = X_NONE; s.ps_avatar = X_NONE; s.wrath_until = -1.0; s.fof = 0.0;
  s.bx_until = -1.0; s.by_until = -1.0; s.qn = 0;
  for (int k = 0; k < 4; k++) s.nxt[k] = 0.0;
  ap_init(&s.ap, GM(r, G_FREN) ? frenzy_chance(r->luck) : 0.0, (r->mask & S_SILM) ? SILENT_AS : 0.0,
          (r->mask & S_SILM) ? SILENT_DUR : 0.0);
  double cast_time = CAST_POINT + CAST_BACKSWING;
  double next_attack = 0.0, busy = 0.0, clock = 0.0;
  int guard = 0;
  while (1) {
    guard += 1;
    if (guard > 400000) break;
    if (s.status) break;
    double attack_at = max3(next_attack, busy, clock);
    double cast_at = FAR;
    int choice = -1;
    for (int key = 0; key < 4; key++) {
      double ready = max3(s.nxt[key], busy, clock);
      if (ready < cast_at - 1e-9 && allowed(r, &s, key, ready)) { cast_at = ready; choice = key; }
    }
    double pending_at = FAR;
    for (int i = 0; i < s.qn; i++) if (s.q_w[i] < pending_at) pending_at = s.q_w[i];
    double moment = attack_at;
    if (cast_at < moment) moment = cast_at;
    if (pending_at < moment) moment = pending_at;
    if (moment >= FIGHT) break;
    clock = moment;
    if (moment == pending_at) {
      int b = 0;
      for (int i = 1; i < s.qn; i++)
        if (s.q_w[i] < s.q_w[b] || (s.q_w[i] == s.q_w[b] && s.q_c[i] < s.q_c[b])) b = i;
      double c = s.q_c[b];
      for (int i = b + 1; i < s.qn; i++) { s.q_w[i - 1] = s.q_w[i]; s.q_c[i - 1] = s.q_c[i]; }
      s.qn--;
      power_strike(r, &s, moment, 1, c);
      continue;
    }
    if (cast_at <= attack_at && choice >= 0 && moment == cast_at) {
      int key = choice;
      if (!pay(r, &s, 12.0, moment)) { s.nxt[key] = moment + 0.25; continue; }
      double hit_at = moment + CAST_POINT;
      busy = moment + cast_time + r->cast_lock;
      if (r->mask & S_SULF) { if (!s.armed) s.armed = 1; }
      if (key == K_PS) {
        if (s.avatar != X_NONE) { s.ps_avatar = s.avatar; s.avatar = X_NONE; }
        if (TM(r, T_AXUEN)) { s.ps_avatar = X_NONE; s.avatar = X_XUEN; }
        if (TM(r, T_WAY)) set_stance(r, &s, (SPEC == 0) ? X_CHIJI : (SPEC == 1) ? X_NIUZAO : X_YULON);
        else set_stance(r, &s, X_XUEN);
        s.ps_buff_until = hit_at + 4.0;
      } else if (key == K_CW) {
        s.avatar = X_NONE;
        if (SP_WW) s.wrath_until = hit_at + 3.0;
        if (TM(r, T_ACHI)) { s.ps_avatar = X_NONE; s.avatar = X_CHIJI; }
        set_stance(r, &s, X_CHIJI);
      } else if (key == K_FB) {
        s.fb_attack = 1;
        if (s.avatar == X_XUEN) {
          s.avatar = X_NONE;
          double amount = 0.15 * ps_damage(&s);
          white_tiger(r, &s, amount, hit_at);
          white_tiger(r, &s, amount, hit_at);
        } else if (s.avatar != X_NONE) {
          s.avatar = X_NONE;
        }
        if (TM(r, T_ANIU)) { s.ps_avatar = X_NONE; s.avatar = X_NIUZAO; }
        set_stance(r, &s, X_NIUZAO);
      } else {
        if (s.avatar == X_XUEN) s.bx_until = hit_at + 6.0;
        else if (s.avatar == X_CHIJI) s.by_until = hit_at + 6.0;
        s.avatar = X_NONE;
        set_stance(r, &s, X_YULON);
      }
      s.nxt[key] = moment + cooldown_of(6.0, haste_at(r, &s, moment), r);
      double spread = moment + gcd(r, &s, moment);
      for (int other = 0; other < 4; other++)
        if (other != key && s.nxt[other] < spread) s.nxt[other] = spread;
      next_attack = (busy > next_attack) ? busy : next_attack;
      continue;
    }
    moment = attack_at;
    recover(r, &s, moment);
    double power = dcs(r, &s);
    if (moment < s.ps_buff_until) {
      s.ps_buff_until = -1.0;
      power_strike(r, &s, moment, 0, 1.0);
    }
    if (s.fb_attack) {
      s.fb_attack = 0;
      double fb_dealt = attack_hit(r, &s, N_FB, 25.0 * RANK + 0.50 * power, moment, 0, 1.0);
      celestial(r, &s, moment, 1);
      wrath_of_xuen(r, &s, fb_dealt, moment);
    }
    celestial(r, &s, moment, 0);
    if (s.stance == X_NIUZAO || s.stance == X_YULON) spend_emp(r, &s, moment);
    int red_crane = 0;
    if (s.stance == X_CHIJI) { red_crane = 1; spend_emp(r, &s, moment); }
    double before = s.src[N_AUTO];
    double dealt = attack_hit(r, &s, N_AUTO, power, moment, red_crane, r->attack_potency);
    if (r->auto_pct != 1.0) s.src[N_AUTO] = before + (s.src[N_AUTO] - before) * r->auto_pct;
    wrath_of_xuen(r, &s, dealt, moment);
    gain_mana(r, &s, attack_mana_gain(r));
    if (r->mask & S_ORB) {
      double splash = (20.0 + 0.35 * r->str) * (double)s.targets * s.taken * exec_factor(r, moment);
      add_src(&s, N_FIRE, splash);
      note_damage_mana(r, &s, (double)s.targets);
    }
    if (r->mask & S_SULF) {
      double execute = exec_factor(r, moment);
      if (s.armed) {
        s.armed = 0;
        double splash = r->str * typed(r, 1, moment) * s.taken * execute * (double)s.targets;
        if (r->spell_crit) splash *= crit_factor(r->crit, r->spell_mult + r->rating);
        add_src(&s, N_SULF, splash);
        note_damage_mana(r, &s, (double)s.targets);
      }
      double echo = power * s.taken * execute * (0.10 * (1.0 + r->luck));
      add_src(&s, N_ECHO, echo);
    }
    ap_attack(&s.ap, moment, red_crane ? 100.0 : r->crit);
    next_attack = moment + attack_interval(r, &s, moment);
  }
  if (s.status) { *status_out = s.status; return 0.0; }
  double total = 0.0;
  for (int i = 0; i < s.nord; i++) total += s.src[s.ord[i]];
  return total / FIGHT;
}

/* monk.simulate: best of the 24 policies, (hold, plain_mist, brew_first) in monk.POLICIES order */
double fight(const Row* r, int* status_out) {
  double best = 0.0;
  int have = 0;
  for (int hold = 0; hold < 6; hold++)
    for (int pm = 1; pm >= 0; pm--)
      for (int bf = 1; bf >= 0; bf--) {
        int st = 0;
        double d = sim_policy(r, hold, pm, bf, &st);
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

/* monk.stats_of(build) */
void sheet(Tab* T, Row* r, const int* chosen, uint tmask, uint gmask, const int* pts, int targets, int* group) {
  int first[6];
  double strength = T->base[1], agility = T->base[2], intel = T->base[0];
  double potency = 0.5 * (double)pts[7];
  double mastery = (double)pts[8];
  double damage = 0.0;
  double crit = (double)pts[6];
  double rating = 0.0, haste = 0.0, aspd = 0.0, magic_add = 0.0, phys_add = 0.0, mana_flat = 0.0;
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
      if (u[11] != 0.0) spell_crit = 1;
      if (u[12] != 0.0) spell_mult = 1.65;
      if (u[10] > 0.0) { r->ex_thr[nexec] = u[9]; r->ex_pct[nexec] = u[10]; nexec++; }
      auto_pct += u[8];
      if (u[2] != 0.0) attack_potency = 2.0;
      mana_flat += f[10];
      luck += a[5];
    }
  }
  r->tmask = tmask; r->gmask = gmask; r->mask = mask;
  *group = (has_shop && has_drop) ? 3 : has_shop ? 1 : has_drop ? 2 : 0;
  if (TM(r, T_INNER)) { strength += 5.0; agility += 5.0; intel += 5.0; }
  if (GM(r, G_FORT)) strength += 34.0;
  if (GM(r, G_SUPR)) mastery += 20.0;
  if (GM(r, G_ANIM)) { crit += 12.0; rating += 0.15; }
  if (GM(r, G_MIND)) haste += 0.07;
  if (GM(r, G_UNSL) && !(mask & S_UNSI)) { magic_add += 0.18; phys_add += 0.18; }
  if (GM(r, G_FORTUNE)) luck += 0.15;
  if (TM(r, T_FRENZ)) aspd += 0.10 + 0.01 * (double)(int)mastery;
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
  double increase = 0.0;
  if (TM(r, T_INNER)) {
    int lo = (int)strength;
    if ((int)agility < lo) lo = (int)agility;
    if ((int)intel < lo) lo = (int)intel;
    increase = (0.05 / 25.0) * (double)lo;
  }
  r->str = strength; r->agi = agility; r->intel = intel; r->potency = potency; r->mastery = mastery; r->damage = damage;
  r->crit = crit; r->rating = rating; r->haste = haste; r->aspd = aspd;
  r->magic_add = magic_add; r->phys_add = phys_add; r->armor_pen = armor_pen;
  r->spell_crit = spell_crit; r->spell_mult = spell_mult;
  r->auto_pct = auto_pct; r->attack_potency = attack_potency; r->increase = increase;
  r->cd_temp = cd_temp; r->flat_cdr = flat_cdr; r->luck = luck; r->mana_max = mana_max; r->mana_regen = stat * 0.80;
  r->cast_lock = cast_lock;
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
    "I00Y": 9, "I07P": 10, "I048": 11, "I0FW": 12, "I0AV": 13, "I0UA": 14, "I0UC": 15, "I0QN": 16,
}
TALENT_BITS = {
    "I0U6": 0, "I0PP": 1, "I0U8": 2, "I0KW": 3, "I0KX": 4, "I0HX": 5, "I0L0": 6, "I0KZ": 7, "I0PQ": 8,
    "I0PO": 9, "I0PR": 10,
    # monk.IGNORED_TALENTS and the talent pages: no effect on the fight
    "I0MD": 20, "I0MC": 21, "I0U7": 22, "I0L2": 23, "I0PN": 24, "I0L1": 25, "I09U": 26, "I04Y": 27, "I0KY": 28,
}
GLYPH_BITS = {"I0AV": 0, "I0JA": 1, "I07B": 2, "I0EK": 3, "I0HC": 4, "I0OF": 5, "I0EJ": 6, "I0GZ": 7, "I0H0": 8}
NO_EFFECT = {"I0H3", "I0H5", "I0H6", "I0EN", "I0OH"}
SPECS = {"windwalker": 0, "brewmaster": 1, "mistweaver": 2}


def monk_tables(space, items, sources) -> dict:
    """class_cl.character_tables with the strength primary fold and the Monk per-piece columns."""
    from sunken_sim import monk as M, shadow
    from sunken_sim.stacking import stack_fields

    want_policies = tuple((h, p, b) for h in ("all", "all1.4", "all0.7", "spent2", "filler", "none")
                          for p in (True, False) for b in (True, False))
    if (M.WHITE_BASE, M.SWING, M.BASE_MANA, M.RANK, M.SPELL_CD, M.SPELL_MANA, M.PS_BUFF, M.WRATH_XUEN_BUFF, M.BLESSING,
            M.BLESSING_XUEN_AS, M.BLESSING_YULON_CDR, M.STANCE_AS, M.WW_PROC_DELAY, M.CHIJI_CW_CUT, M.POLICIES,
            M.BASE_STR, M.BASE_AGI, M.BASE_INT, shadow.LEVEL) != \
            (14.0, 1.85, 120.0, 1, 6.0, 12.0, 4.0, 3.0, 6.0, 0.40, 0.18, 0.40, 0.50, 0.30, want_policies, 57, 31, 31, 15):
        raise ValueError("kernel constants assume the 2026-11-14 monk")
    if (shadow.CAST_POINT, shadow.CAST_BACKSWING) != (0.15, 0.30):
        raise ValueError("kernel constants assume cast 0.15 + 0.30")
    AP.check()
    t = C.character_tables(space, items, sources, SPECIAL_BITS, TALENT_BITS, GLYPH_BITS, NO_EFFECT,
                           [float(M.BASE_INT), float(M.BASE_STR), float(M.BASE_AGI), float(M.BASE_HP)], "Monk")
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
        pal[i] = [
            shadow.MAGICAL_ADDS.get(code, 0.0),
            shadow.PHYSICAL_ADDS.get(code, 0.0),
            item.source_pct / 100.0,
            item.damage_pct / 100.0 - item.source_pct / 100.0,
            1.0 if (code in shadow.MAGICAL_ADDS or code in shadow.PHYSICAL_ADDS) else 0.0,
            shadow.item_luck(item),
        ]
    t["fold"] = np.ascontiguousarray(fold.reshape(-1))
    t["pal"] = np.ascontiguousarray(pal.reshape(-1))
    return t


class MonkCL(C.ExactCL):
    hero = "monk"
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
        from sunken_sim import monk

        return monk

    def tables(self, space, items, sources):
        return monk_tables(space, items, sources)

    def timeline_key(self, build):
        from dataclasses import fields

        return tuple((f.name, getattr(build, f.name)) for f in fields(build) if f.name.endswith("_points"))


oracle = C.oracle
parity = C.parity
parity_full = C.parity_full
random_builds = C.random_builds
self_check = C.self_check
