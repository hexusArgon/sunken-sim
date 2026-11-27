"""Shared incoming-hit layer of the exact OpenCL kernels (docs/defense-model.md).

The dummies attack the hero; effects of those hits (reflects, on-hit damage and buffs, evasion, mana), the
hero's expected health (hits, self-damage, the model heal, regeneration, lifesteal, Healing Type effects) and
the DamageIncrease pool are the same for every class, so they live here. A class kernel includes

    INC_ROW_FIELDS   inside its Row struct          INC_ST_FIELDS  inside its St struct
    INC_C1           after St (health, evasion, healing, pool helpers)
    INC_C2           after it defines the hooks below (hit stream, heals on attacks / casts)

and provides, before INC_C2:
    void item_dmg(const Row* r, St* s, int name, double raw, int i, double when, int magical, double count);
                                                                            count = expected damage instances
    void cls_taken(const Row* r, St* s, double now, double m, double axe);   class effects of one damage instance
    double cls_buffs(const Row* r, St* s, int i, double now);               buffs on dummy i (Ancient Voodoo Doll)
    double cls_heal_mod(const Row* r, St* s);                               class healing-received modifiers
    double cls_primary(const Row* r);                                       primary attribute
    N_REFL, N_SUNS, N_SOD, N_EVADE, N_BLOOD source ids, MAXT, LEVEL, CLS_INT_HERO (1 = Intelligence hero),
    recover(r, s, now), chance01(v), s->lm, s->mana, r->mana_max, r->intel, r->potency, r->targets.

Host side: ``inc_tables(space, items)`` gives the per-piece ``pimask`` (ulong) and ``pinc`` (NINC doubles) that
the class kernel folds (first copy of an item only) with ``INC_FOLD`` and finishes with ``inc_sheet``.
"""

from __future__ import annotations

import re

import numpy as np

# item -> bit of Row.imask
INC_BITS = {
    "I0BC": 0, "stre": 0,                    # Spiked Carapace A083: 10% of melee damage back
    "I0BD": 1, "I0GX": 1, "I0JK": 1,         # Thorns Aura A0NH: 10% of melee damage back
    "I02Q": 2,                               # Dragonscale Aura: 10% of attack damage taken
    "I04M": 3,                               # Sunstrider Crown: 15% of attack damage taken, magical
    "I0B5": 4,                               # Shield of Death: 8% x Luck, 125 on attack
    "I0GE": 5,                               # Warlord's Battlemask: 8% x Luck, +28% AS 6 s
    "I09X": 6,                               # Seal of the Black Empire: 25% x Luck, +1 Mastery (20)
    "I0F2": 7,                               # Plasma-Core Belt: +3 mana per attack against the hero
    "I015": 8,                               # Icecrown Ring: mana per attack, freezes the attacker
    "I06N": 9,                               # Nerubian Scales: 5% x Luck stun 1.5 s
    "I07C": 10,                              # Shado-Pan Faceguard: evasion + 100 spell damage on evade
    "I0IS": 11,                              # Gladiator's Insignia: evasion + 2.5% max HP on evade (Healing Type)
    "I06J": 12,                              # Dark Iron Ale: 18% evasion at <= 40% HP, regen by missing HP
    "I024": 13, "arsc": 14, "I079": 15, "fgun": 16,  # DamageIncrease pool by hero health
    "I05N": 17,                              # Bloodhowl: base attack cooldown x (1 - 0.30 missing)
    "I00J": 18,                              # Blade of the Fallen Seraph: +1% max HP per attack, self-damage
    "I0D4": 19,                              # Eversong Defender: 5% x Luck heal 8% max mana on attack
    "I05V": 20,   # Bloodlord's Regalia: stores Healing Type healing, bursts every 3 s
    "I025": 21,   # Titan's Breastplate: regeneration disabled (and -50% Healing Type, pinc)
    "I02K": 22,   # Cursed Skull: regeneration damages the hero instead
    "I02R": 23,   # Edge of the Red Court: lifesteal is Healing Type, +10 + level per lifesteal
    "I04H": 24,   # Goredrinker: lifesteal + 0.5% target max HP, at most 3% own max HP
    "I0NU": 25,   # Bloodreaver Scythe: Vampiric Aura 13% (owner), Seraph's aura 10%
    "I0D0": 26,   # Dragon Figurine: +1% healing received per armor
    "I0EC": 27,   # Bloodstone: Sanguine Aura, 2.5% of damage enemies take (doubled < 40%)
    "I074": 28,   # Seal of Vampirism: damage dealt 3% x Luck -> +40 health
    "I0IB": 29,   # Masochist Mask: attacks against the hero restore 0.3% max HP
    "I0P3": 30,   # Primalist Ring: +0.5% (Strength heroes 0.4%) Physical Type damage per point of HP regeneration
    "I06C": 31,   # Staff of Idrassil: damage taken -> Blessing 5 s, 1% + 1% max HP per second
    "I0SL": 32,   # Jade Forest Mantle: 20% x Luck heal 40% of damage taken
    "engr": 33,   # Amber's Gaze: spellcasts restore 50 (doubled < 40%)
    "I0UH": 34,   # Earthliving Weapon: attacks restore 10 + 20% primary + 3% max mana
    "I058": 35,   # Moon Scythe: attacks restore 3.5% max mana
    "I0HY": 36,   # Idol of the Forest: Healing Aura +10 HP regeneration
    "I02B": 37,   # Signet of the Scourge: Unholy Aura +5 HP regeneration (+15% regen, pinc)
    "sor1": 38,   # Crusader's Chestplate: spellcasts restore their mana cost
    "I0HN": 39,   # Tribal Staff: Healing Aura +10 regen; spellcasts restore 25% primary
    "I0SR": 40,   # Seraphim Staff: spellcasts restore 25 + 75% primary
    "I066": 41,   # Crown of the Highlord: spellcasts restore 3% max HP
    "I07N": 42,   # Holy Scepter: spellcasts restore 2% max HP
    "I0CZ": 43,   # Giantsbane: DamageIncrease + 0.75% per point of target armor
    "wneu": 44,   # Chaos Shard: 12 to every attacker
    "I0BM": 45,   # Mantle of the Pathfinder-like (PreDamage_Reduce 0.90, 50 magic damage on evade)
    "lgdh": 46,   # Ice Cleaver: 18% x Luck Ice Nova on attack; chilling 3% / freezing 6% max mana magical damage
    "I0NS": 47,   # Elemental Orb (Frost): attacks Chill the target 4 s (gg_trg_Chill)
    "I0SU": 48,   # Dark Veil Mantle: evading an attack restores 4% max mana
}

# per-piece doubles (pinc), first copy only
NINC = 16
# evasion hit-chance factors of PreDamage_Reduce (multiplicative)
HIT_FACTOR = {"I07A": 0.88, "I07C": 0.87, "I0IS": 0.84, "I0SU": 0.84, "I0DL": 0.82, "evtl": 0.95, "rwiz": 0.95,
              "rump": 0.95, "dust": 0.95, "I051": 0.92, "I0BM": 0.90, "I0U9": 0.90}
RECV_MOD = {"I0C4": 0.15, "I06I": 0.18, "I05V": 0.10, "fgrd": -0.30, "I025": -0.50, "oven": 0.12}
OWN_EXTRA = {"I06I": 0.12}            # Husk of Nordrassil: 30% for the hero's own Healing Type effects
HT_ATTACK = {"I0NE": (0.0, 0.03), "I06F": (10.0, 0.01)}  # attacks restore flat + % max HP (Healing Type)
REGEN_MAXHP = {"I06L": 0.01, "modt": 0.01}
HEAL_FLAT = {"I07D": 8.0, "I062": 5.0, "rde3": 3.0, "I03N": 5.0}
HEAL_FLAT_INT = {"I062": 0.05}
HEAL_POT = {"I0EZ": 0.5}
POOL_FLAT = {"I0AM": 0.03}            # Voodoo Doll
VOODOO = {"spsh": 1.0}                # Ancient Voodoo Doll

# Builds with any of these items depend on the incoming-hit model.
INCOMING_ITEMS = frozenset(INC_BITS) | set(HIT_FACTOR) | set(RECV_MOD) | set(HT_ATTACK) | set(REGEN_MAXHP) \
    | set(HEAL_FLAT) | set(HEAL_POT) | set(POOL_FLAT) | set(VOODOO)


def inc_columns(item) -> list:
    code, tip = item.rawcode, item.tip
    num = lambda raw: float(raw.replace(",", "."))
    regen = sum(num(v) for v in re.findall(r"\+(\d+(?:[.,]\d+)?) Health per [Ss]econd", tip))
    regen_pct = sum(num(v) for v in re.findall(r"Increases your Health Regeneration by (\d+(?:[.,]\d+)?)%", tip)) / 100.0
    power = sum(num(v) for v in re.findall(r"\+(\d+(?:[.,]\d+)?)% Healing Power", tip)) / 100.0
    steal = sum(num(v) for v in re.findall(r"\+(\d+(?:[.,]\d+)?)% Lifesteal", tip)) / 100.0
    flat, pct = HT_ATTACK.get(code, (0.0, 0.0))
    return [regen, regen_pct, power, steal, RECV_MOD.get(code, 0.0), OWN_EXTRA.get(code, 0.0), pct, flat,
            REGEN_MAXHP.get(code, 0.0), HEAL_FLAT.get(code, 0.0), HEAL_FLAT_INT.get(code, 0.0), HEAL_POT.get(code, 0.0),
            POOL_FLAT.get(code, 0.0), VOODOO.get(code, 0.0), HIT_FACTOR.get(code, 1.0),
            float(getattr(item, "armor", 0) or 0)]


def inc_tables(space, items) -> dict:
    n = len(space.pieces)
    pimask = np.zeros(n, dtype=np.uint64)
    pinc = np.zeros((n, NINC), dtype=np.float64)
    for i, piece in enumerate(space.pieces):
        item = items[piece.code]
        if piece.code in INC_BITS:
            pimask[i] = np.uint64(1 << INC_BITS[piece.code])
        pinc[i] = inc_columns(item)
    return {"pimask": pimask, "pinc": np.ascontiguousarray(pinc.reshape(-1))}


def _defines() -> str:
    names = {0: "SPIKE", 1: "THORN", 2: "DSCALE", 3: "SUN", 4: "SOD", 5: "BMASK", 6: "SEAL", 7: "PCB", 8: "ICE",
             9: "NERUB", 10: "EV13", 11: "EV16A", 12: "ALE", 13: "CRIM", 14: "IGM", 15: "FURN", 16: "BLS", 17: "BHOWL",
             18: "SERA", 19: "EVD", 20: "BLOOD", 21: "TITAN", 22: "CSKULL", 23: "REDC", 24: "GORE", 25: "BREAV",
             26: "FIGUR", 27: "SANG", 28: "SVAMP", 29: "MASO", 30: "PRIM", 31: "IDRA", 32: "JADE", 33: "AMBER",
             34: "EARTH", 35: "MOON", 36: "HAURA", 37: "UNHOLY", 38: "CRUS", 39: "TRIBAL", 40: "SERAPH", 41: "HIGHL",
             42: "HOLYS", 43: "GIANT", 44: "CHAOS", 45: "PATH", 46: "ICLE", 47: "FORB", 48: "DVEIL"}
    return "\n".join(f"#define I_{name} (1UL<<{bit})" for bit, name in sorted(names.items())) + "\n"


INC_ROW_FIELDS = r"""
  ulong imask;
  double regen, regen_pct, heal_power, lifesteal, recv_mod, own_extra, ht_atk_pct, ht_atk_flat, heal_flat, heal_flat_int;
  double heal_pot, pool_flat, voodoo, armor_hero, regen_hp, hitmul, item_armor;
"""

INC_ST_FIELDS = r"""
  double hp_max, hp_health, hp_next_heal, hp_cap; int hp_on, hits_on;
  double db[MAXT], dm[MAXT][INC_NG];
  double dinc;
  double bm_t[INC_NBM], bm_q[INC_NBM]; int bm_n;
  double seal[21];
  double ice_ready;
  double rg_t, bl_store, ida_end, ida_next;
  double tnow;  /* moment of the event being processed (class hooks without a time argument) */
"""

INC_HEAD = "#define INC_NG 8\n#define INC_NBM 160\n" + _defines() + r"""
/* incoming-hit effects that make the hit stream matter (class kernels add their own) */
#define I_HP_DEP (I_ALE | I_CRIM | I_IGM | I_FURN | I_BLS | I_BHOWL | I_BLOOD | I_ICE)
#define I_HIT_DEP (I_SPIKE | I_THORN | I_DSCALE | I_SUN | I_SOD | I_BMASK | I_SEAL | I_PCB | I_ICE | I_EVD | I_CHAOS | I_DVEIL \
    | I_EV13 | I_PATH)  /* on-evade damage: Shado-Pan Faceguard, I0BM (2026-11-27: was missing) */
#define INC_FOLD(r, a) do { (r)->regen += (a)[0]; (r)->regen_pct += (a)[1]; (r)->heal_power += (a)[2]; \
    (r)->lifesteal += (a)[3]; (r)->recv_mod += (a)[4]; (r)->own_extra += (a)[5]; (r)->ht_atk_pct += (a)[6]; \
    (r)->ht_atk_flat += (a)[7]; (r)->regen_hp += (a)[8]; (r)->heal_flat += (a)[9]; (r)->heal_flat_int += (a)[10]; \
    (r)->heal_pot += (a)[11]; (r)->pool_flat += (a)[12]; (r)->voodoo += (a)[13]; (r)->hitmul *= (a)[14]; \
    (r)->item_armor += (a)[15]; } while (0)
"""

INC_C1 = r"""
/* ---- incoming hits (docs/defense-model.md; user model 2026-11-17/20/21/27) ----------------------------
 * Dummy j (0..targets-1) attacks the hero every 1 s, first at 0.2 * (j % 5 + 1) s; dummies 0 .. melee-1
 * are melee, melee = round(targets * 122 / 176). A hit is 5% of max HP (no damage reduction). The hero
 * heals 75% of max HP every 3 s (Healing Type; from itself for Intelligence heroes, else from an ally),
 * never above the heal ceiling, never below 1 HP. Chance effects are expectations: a stun moves that share
 * of the dummy's next attack 1.5 s later instead of 1 s, an Icecrown freeze 2.5 s. Health is the expected
 * health. */
void inc_sheet_init(Row* r) {
  r->imask = 0; r->regen = 0.0; r->regen_pct = 0.0; r->heal_power = 0.0; r->lifesteal = 0.0; r->recv_mod = 0.0;
  r->own_extra = 0.0; r->ht_atk_pct = 0.0; r->ht_atk_flat = 0.0; r->heal_flat = 0.0; r->heal_flat_int = 0.0;
  r->heal_pot = 0.0; r->pool_flat = 0.0; r->voodoo = 0.0; r->armor_hero = 0.0; r->regen_hp = 0.0; r->hitmul = 1.0;
  r->item_armor = 0.0;
}

/* after the class folded hp: auras, % max HP regeneration; returns the HP regeneration stat */
double inc_sheet_finish(Row* r, double hp) {
  r->regen += ((r->imask & (I_HAURA | I_TRIBAL)) ? 10.0 : 0.0) + ((r->imask & I_UNHOLY) ? 5.0 : 0.0);
  r->regen_hp = r->regen_hp * hp;
  if (r->imask & I_TITAN) return 0.0;
  return r->regen * (1.0 + r->regen_pct) + r->regen_hp;
}

int melee_count(int targets) { return (2 * targets * 122 + 176) / 352; }

double hero_ratio(St* s, double t) {
  (void)t;
  if (!s->hp_on) return 1.0;
  return s->hp_health / s->hp_max;
}

void hp_add(St* s, double delta) {
  double h = s->hp_health + delta;
  if (delta > 0.0) {
    double ceiling = s->hp_max * s->hp_cap;
    if (s->hp_health >= ceiling) return;
    h = (h < ceiling) ? h : ceiling;
  }
  s->hp_health = (h > 1.0) ? h : 1.0;
}

double dummy_next(const St* s, int j, int* k) {
  for (int i = 0; i < INC_NG; i++) if (s->dm[j][i] > 0.0) { *k = i; return s->db[j] + 0.5 * (double)i; }
  *k = -1;
  return 1.0e9;
}

void dummy_push(St* s, int j, int k, double mass) {
  if (k < INC_NG && mass > 0.0) s->dm[j][k] += mass;
}

double seal_mean(const St* s) {
  double e = 0.0;
  for (int k = 1; k <= 20; k++) e += (double)k * s->seal[k];
  return e;
}

#define MAST(r, s) ((r)->mastery + (((r)->imask & I_SEAL) ? seal_mean(s) : 0.0))

double bm_active(St* s, double t) {
  double q = 1.0;
  int w = 0;
  for (int i = 0; i < s->bm_n; i++) {
    if (t < s->bm_t[i] + 6.0) { s->bm_t[w] = s->bm_t[i]; s->bm_q[w] = s->bm_q[i]; w++; q *= s->bm_q[i]; }
  }
  s->bm_n = w;
  return 1.0 - q;
}

/* DamageIncrease_Amount by hero health (PreDamage_Increase): Crimson Fury / Immortal Gladiator's Mask
 * +15% at <= 40%, The Furnace + missing% / 500, Belt of Living Strength +12% at >= 75%. */
void dinc_update(const Row* r, St* s) {
  if (!(r->imask & (I_CRIM | I_IGM | I_FURN | I_BLS))) { s->dinc = 0.0; return; }
  double pct = 100.0 * hero_ratio(s, 0.0);
  double d = 0.0;
  if ((r->imask & I_CRIM) && pct <= 40.0) d += 0.15;
  if ((r->imask & I_IGM) && pct <= 40.0) d += 0.15;
  if (r->imask & I_FURN) d += ((100.0 - pct) / 50.0) / 10.0;
  if ((r->imask & I_BLS) && pct >= 75.0) d += 0.12;
  s->dinc = d;
}

/* evasion: product of the hit-chance factors of PreDamage_Reduce */
double cls_hit(const Row* r, St* s, double now);
double hit_chance(const Row* r, St* s, double now) {
  double h = r->hitmul;
  if ((r->imask & I_ALE) && hero_ratio(s, 0.0) <= 0.40) h *= 0.82;
  return h * cls_hit(r, s, now);
}

/* Healing (trigger Healing): Healing Type amount (+ the healer's flat item adds) x (1 + received modifiers
 * [+ the healer owner's Healing Power] [+ Husk's own-heal extra] + class modifiers); Bloodlord's Regalia
 * stores 100% of own (healer == target) and 20% of other Healing Type healing. count = expected number of
 * such heals (each one gets the flat adds and the >= 1 check). flat: the healer is the hero (its items);
 * power: the healer belongs to the hero's player; own: healer == target. */
double cls_heal_mod(const Row* r, St* s);
double cls_heal_flat(const Row* r, St* s);
void cls_own_heal(const Row* r, St* s, double total);
void heal_mod(const Row* r, St* s, double amount, double count, int flat, int power, int own) {
  if (!s->hp_on || amount <= 0.0 || count <= 0.0) return;
  if (flat) amount += r->heal_flat + r->heal_flat_int * r->intel + r->heal_pot * r->potency;
  amount += cls_heal_flat(r, s);
  double m = (power && own) ? r->recv_mod + (r->heal_power + r->own_extra)
           : power ? r->recv_mod + r->heal_power : r->recv_mod + 0.0;
  if (r->imask & I_FIGUR) m += 0.01 * r->armor_hero;
  m += cls_heal_mod(r, s);
  if (m < -1.0) return;
  amount *= 1.0 + m;
  double total = amount * count;
  if (own) cls_own_heal(r, s, total);
  if (r->imask & I_BLOOD) s->bl_store += (own ? 1.0 : 0.20) * total;
  if (amount >= 1.0) hp_add(s, total);
}

void heal_ht(const Row* r, St* s, double amount, int self) { heal_mod(r, s, amount, 1.0, self, self, self); }

void heal_plain(St* s, double amount) {
  if (s->hp_on && amount > 0.0) hp_add(s, amount);
}

/* HP regeneration between events; Titan's Breastplate disables it, Cursed Skull turns it into damage. */
void regen_adv(const Row* r, St* s, double t) {
  if (!s->hp_on) return;
  double dt = t - s->rg_t;
  s->rg_t = t;
  if (dt <= 0.0 || (r->imask & I_TITAN)) return;
  double pct = r->regen_pct;
  if (r->imask & I_ALE) pct += (100.0 * (1.0 - hero_ratio(s, t)) / 3.0) / 100.0;
  double rate = r->regen * (1.0 + pct) + r->regen_hp;
  if (rate <= 0.0) return;
  hp_add(s, (r->imask & I_CSKULL) ? -rate * dt : rate * dt);
}

/* DamageIncrease_Amount: 1 + hero-health entries + Voodoo Doll + Ancient Voodoo Doll (4% + 2% per other
 * buff on the target) + Giantsbane 0.75% per point of target armor. */
double cls_buffs(const Row* r, St* s, int i, double now);
double pool_of(const Row* r, St* s, int i, double now, double armor) {
  if (!(r->imask & I_GIANT) && r->pool_flat == 0.0 && r->voodoo == 0.0 && s->dinc == 0.0) return 1.0;
  double d = 1.0 + s->dinc + r->pool_flat;
  if (r->imask & I_GIANT) d += (0.03 / 4.0) * armor;
  if (r->voodoo != 0.0) d += 0.04 + 0.02 * cls_buffs(r, s, i, now);
  return d;
}

/* Sanguine Aura / Seal of Vampirism on damage dealt (call with the damage of one hit and its expected count) */
void inc_dealt(const Row* r, St* s, double when, double dealt, double count) {
  if (!s->hp_on) return;
  if (r->imask & I_SVAMP) heal_plain(s, count * chance01(0.03 * s->lm) * 40.0);
  if (r->imask & I_SANG) heal_plain(s, 0.025 * ((hero_ratio(s, when) < 0.40) ? 2.0 : 1.0) * dealt);
}

void inc_init(const Row* r, St* s, int targets, int cls_hp, int cls_hits) {
  s->dinc = 0.0;
  s->rg_t = 0.0; s->bl_store = 0.0; s->ida_end = -1.0; s->ida_next = 1.0e9;
  s->hp_max = r->hp; s->hp_health = r->hp; s->hp_cap = (r->imask & I_CRIM) ? 0.38 : 1.0;
  s->hp_on = (r->hp > 1.0) && ((r->imask & I_HP_DEP) || cls_hp);
  s->hits_on = s->hp_on || (r->imask & I_HIT_DEP) || cls_hits;
  s->hp_next_heal = 3.0;
  s->bm_n = 0; s->ice_ready = 0.0;
  for (int k = 0; k <= 20; k++) s->seal[k] = 0.0;
  s->seal[0] = 1.0;
  for (int j = 0; j < MAXT; j++) {
    s->db[j] = 0.2 * (double)(j % 5 + 1);
    for (int k = 0; k < INC_NG; k++) s->dm[j][k] = 0.0;
    if (j < targets) s->dm[j][0] = 1.0;
  }
}
"""

INC_C2 = r"""
/* Ice Cleaver (OnChill / OnFreeze, CC_Hero = the hero): every chill 3%, every freeze 6% of max mana as magical
 * damage to the chilled / frozen unit; w = expected number of such applications. Classes call it for their own
 * chills and freezes (Frost Orb, Ice Nova, class spells); the Icecrown Ring freeze of an attacker is here. */
void inc_ice(const Row* r, St* s, int t, double now, double w, int freeze) {
  if ((r->imask & I_ICLE) && w > 0.0)
    item_dmg(r, s, N_ICE, (freeze ? 0.06 : 0.03) * r->mana_max * w, t, now, 1, w);
}

/* PreDamage_Enemies (PreDamageEvent 4, before evasion): one damage instance of mass m taken at now.
 * axe = the class's Axe-Mastery-like chance of this instance (passed through to cls_taken). */
void taken_event(const Row* r, St* s, double now, double m, double axe) {
  if (m <= 0.0) return;
  if ((r->imask & I_IDRA) && s->hp_on) {
    if (now >= s->ida_end) s->ida_next = now + 1.0;
    s->ida_end = now + 5.0;
  }
  cls_taken(r, s, now, m, axe);
  if (r->imask & I_BMASK) {
    /* same moment: one window, the misses multiply (exact) */
    if (s->bm_n > 0 && s->bm_t[s->bm_n - 1] == now) s->bm_q[s->bm_n - 1] *= 1.0 - m * chance01(0.08 * s->lm);
    else {
      if (s->bm_n >= INC_NBM) bm_active(s, now);
      if (s->bm_n < INC_NBM) { s->bm_t[s->bm_n] = now; s->bm_q[s->bm_n] = 1.0 - m * chance01(0.08 * s->lm); s->bm_n++; }
      else if (!s->status) s->status = 2;
    }
  }
  if (r->imask & I_SEAL) {
    double p = m * chance01(0.25 * s->lm);
    for (int k = 19; k >= 0; k--) { double move = s->seal[k] * p; s->seal[k] -= move; s->seal[k + 1] += move; }
  }
}

/* One attack of dummy j, mass m, at now (Hero_Attacked, PreDamage 4, evasion, landing, OnDamage). */
void cls_attacked(const Row* r, St* s, int j, double now, double m);
void cls_evade(const Row* r, St* s, int j, double now, double evaded);
void dummy_attack(const Row* r, St* s, int j, double m, double now) {
  s->tnow = now;
  int melee = j < melee_count(r->targets);
  double hit = 0.05 * s->hp_max;
  recover(r, s, now);
  double gain = 0.0;
  if (r->imask & I_PCB) gain += 3.0;
  if (r->imask & I_ICE) gain += 2.0 + (0.01 / 5.0) * r->mana_max;
  if (gain > 0.0) { double v = s->mana + m * gain; s->mana = (v < r->mana_max) ? v : r->mana_max; }
  if (r->imask & I_EVD) heal_plain(s, m * chance01(0.05 * s->lm) * 0.08 * r->mana_max);
  if (r->imask & I_MASO) heal_plain(s, m * 0.003 * s->hp_max);
  if (r->imask & I_SOD) item_dmg(r, s, N_SOD, 125.0 * m * chance01(0.08 * s->lm), j, now, 0, m * chance01(0.08 * s->lm));
  if (r->imask & I_CHAOS) item_dmg(r, s, N_REFL, 12.0 * m, j, now, 0, m);
  taken_event(r, s, now, m, chance01(0.05 * s->lm));
  cls_attacked(r, s, j, now, m);
  double land = m * hit_chance(r, s, now);
  double evaded = m - land;
  if (evaded > 0.0) {
    if (r->imask & I_DVEIL) { double v = s->mana + evaded * 0.04 * r->mana_max; s->mana = (v < r->mana_max) ? v : r->mana_max; }
    cls_evade(r, s, j, now, evaded);
  }
  if ((r->imask & I_EV13) && evaded > 0.0) item_dmg(r, s, N_EVADE, 100.0 * evaded, j, now, 0, evaded);
  if ((r->imask & I_PATH) && evaded > 0.0) item_dmg(r, s, N_EVADE, 50.0 * evaded, j, now, 1, evaded);
  if ((r->imask & I_EV16A) && evaded > 0.0) heal_ht(r, s, evaded * 0.025 * s->hp_max, 1);
  if (land > 0.0) {
    if (melee) {
      double back = 0.0, nb = 0.0;
      if (r->imask & I_SPIKE) { back += 0.10; nb += 1.0; }
      if (r->imask & I_THORN) { back += 0.10; nb += 1.0; }
      if (back > 0.0) item_dmg(r, s, N_REFL, back * hit * land, j, now, 0, nb * land);
    }
    if (r->imask & I_DSCALE) item_dmg(r, s, N_REFL, 0.10 * hit * land, j, now, 0, land);
    if (r->imask & I_SUN) {
      double each = 0.15 * hit * land / (double)r->targets;
      for (int i = 0; i < r->targets; i++) item_dmg(r, s, N_SUNS, each, i, now, 1, land / (double)r->targets);
    }
    if (s->hp_on) hp_add(s, -land * hit);
    if (r->imask & I_JADE) heal_ht(r, s, land * chance01(0.20 * s->lm) * 0.40 * hit, 1);
  }
  int k0 = 0;
  double t0 = dummy_next(s, j, &k0);
  (void)t0;
  s->dm[j][k0] -= m;
  if (s->dm[j][k0] < 1e-12) s->dm[j][k0] = 0.0;
  double frozen = 0.0;
  if ((r->imask & I_ICE) && now >= s->ice_ready) {
    frozen = m;
    s->ice_ready = now + ((hero_ratio(s, now) <= 0.40) ? 12.0 : 20.0);
  }
  double stun = (r->imask & I_NERUB) ? (m - frozen) * chance01(0.05 * s->lm) : 0.0;
  inc_ice(r, s, j, now, frozen, 1);
  dummy_push(s, j, k0 + 5, frozen);
  dummy_push(s, j, k0 + 3, stun);
  dummy_push(s, j, k0 + 2, m - frozen - stun);
  int lead = 0;
  while (lead < INC_NG && s->dm[j][lead] <= 0.0) lead++;
  if (lead > 0 && lead < INC_NG) {
    for (int i = 0; i < INC_NG; i++) s->dm[j][i] = (i + lead < INC_NG) ? s->dm[j][i + lead] : 0.0;
    s->db[j] += 0.5 * (double)lead;
  }
}

/* Spellcasts: Crown of the Highlord 3% max HP, Holy Scepter 2% max HP, Amber's Gaze 50 (doubled < 40%),
 * Crusader's Chestplate the mana cost, Tribal Staff 25% primary, Seraphim Staff 25 + 75% primary. */
void cast_heal(const Row* r, St* s, double now, double cost) {
  if (!s->hp_on) return;
  if (r->imask & I_HIGHL) heal_ht(r, s, 0.03 * s->hp_max, 1);
  if (r->imask & I_HOLYS) heal_plain(s, 0.02 * s->hp_max);
  if (r->imask & I_AMBER) heal_ht(r, s, 50.0 * ((hero_ratio(s, now) < 0.40) ? 2.0 : 1.0), 1);
  if (r->imask & I_CRUS) heal_ht(r, s, cost, 1);
  if (r->imask & I_TRIBAL) heal_ht(r, s, 0.25 * cls_primary(r), 1);
  if (r->imask & I_SERAPH) heal_ht(r, s, 25.0 + 0.75 * cls_primary(r), 1);
}

/* After an auto attack that dealt `dealt` to its target: lifesteal (AfterDamage_Global) and on-attack heals. */
void cls_lifesteal(const Row* r, St* s, double amount);
void attack_heal(const Row* r, St* s, double now, double dealt) {
  if (!s->hp_on) return;
  double ls = r->lifesteal;
  if (r->imask & I_BREAV) ls += 0.13;
  else if (r->imask & I_SERA) ls += 0.10;
  double heal = ls * dealt;
  if (r->imask & I_REDC) heal += 10.0 + LEVEL;
  if (r->imask & I_GORE) {
    double part = (0.01 / 2.0) * 5300.0, cap = 0.03 * s->hp_max;
    heal += (part > cap) ? cap : part;
  }
  if (heal >= 1.0 && hero_ratio(s, now) < 1.0) {
    s->tnow = now;
    if (r->imask & I_REDC) heal_ht(r, s, heal, 1);
    else {
      /* Crimson Fury: no lifesteal above 38% health (the trigger skips it) */
      if (!((r->imask & I_CRIM) && hero_ratio(s, now) > 0.38)) cls_lifesteal(r, s, heal);
      heal_plain(s, heal);
    }
  }
  if (r->ht_atk_pct != 0.0 || r->ht_atk_flat != 0.0) heal_ht(r, s, r->ht_atk_flat + r->ht_atk_pct * s->hp_max, 1);
  if (r->imask & I_EARTH) heal_ht(r, s, 10.0 + 0.20 * cls_primary(r) + 0.03 * r->mana_max, 1);
  if (r->imask & I_MOON) heal_ht(r, s, 0.035 * r->mana_max, 1);
}

/* The next incoming event: dummy hit, model heal, Idrassil tick. */
double inc_next(St* s, int targets, int* hit_j, int* hit_k) {
  double next = 1.0e9;
  *hit_j = -1; *hit_k = -1;
  if (s->hits_on) {
    for (int j = 0; j < targets; j++) {
      int k;
      double t = dummy_next(s, j, &k);
      if (t < next) { next = t; *hit_j = j; *hit_k = k; }
    }
  }
  if (s->hp_on && s->hp_next_heal < next) next = s->hp_next_heal;
  if (s->hp_on && s->ida_next < s->ida_end && s->ida_next < next) next = s->ida_next;
  return next;
}

/* Run the incoming event at `moment` (inc_next's value). */
void inc_event(const Row* r, St* s, double moment, int hit_j, int hit_k, int targets) {
  s->tnow = moment;
  if (s->hp_on && s->ida_next < s->ida_end && moment == s->ida_next) {
    heal_ht(r, s, 0.02 * s->hp_max, 1);
    s->ida_next += 1.0;
  } else if (hit_j >= 0 && moment == s->db[hit_j] + 0.5 * (double)hit_k) {
    dummy_attack(r, s, hit_j, s->dm[hit_j][hit_k], moment);
  } else {
    heal_ht(r, s, 0.75 * s->hp_max, CLS_INT_HERO);
    s->hp_next_heal += 3.0;
    /* Bloodlord's Regalia: every 3 s, 20% of the stored healing x (1 + 0.06 x level) to every enemy in 500 */
    if (r->imask & I_BLOOD) {
      double dmg = 0.20 * s->bl_store * (1.0 + 0.06 * LEVEL);
      if (dmg >= 1.0) for (int i = 0; i < targets; i++) item_dmg(r, s, N_BLOOD, dmg, i, moment, 0, 1.0);
      s->bl_store = 0.0;
    }
  }
  dinc_update(r, s);
}
"""
