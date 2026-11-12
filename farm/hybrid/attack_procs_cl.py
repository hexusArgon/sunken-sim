"""OpenCL mirror of sunken_sim.attack_procs (Battle Frenzy + Silent Messenger during the fight).

Kernels paste ``C`` after their pragmas and keep one ``AP`` in their fight state.
Silent Messenger is item I0QN only (the one crit -> attack speed item); the host checks
that with ``check()`` and passes its values as SILENT_AS / SILENT_DUR.
"""

from __future__ import annotations

C = r"""
#define APK 8
#define SILENT_AS 0.28
#define SILENT_DUR 3.0
typedef struct {
  double fe[APK], fm[APK], se[APK], sc[APK];
  double p, cas, cdur;
  int fn, sn;
} AP;

void ap_init(AP* a, double p, double cas, double cdur) {
  a->p = p; a->cas = (cdur > 0.0) ? cas : 0.0; a->cdur = cdur; a->fn = 0; a->sn = 0;
}

double frenzy_chance(double luck) {
  double v = 0.18 * (1.0 + luck);
  return (v < 1.0) ? v : 1.0;
}

double ap_fon(const AP* a, double now) {
  double s = 0.0;
  for (int i = 0; i < a->fn; i++) if (now < a->fe[i]) s += a->fm[i];
  return s;
}

double ap_son(const AP* a, double now) {
  double off = 1.0;
  for (int i = 0; i < a->sn; i++) if (now < a->se[i]) off *= 1.0 - a->sc[i];
  return 1.0 - off;
}

double ap_bonus(const AP* a, double now) {
  double b = 0.0;
  if (a->p > 0.0) b += 0.32 * ap_fon(a, now);
  if (a->cas > 0.0) b += a->cas * ap_son(a, now);
  return b;
}

/* clamp(-0.8, 4) of base + bonus, as min(4.0, max(-0.8, x)) */
double ap_speed(double x) {
  double v = (x > -0.8) ? x : -0.8;
  return (v < 4.0) ? v : 4.0;
}

void ap_attack(AP* a, double now, double crit) {
  if (a->p > 0.0) {
    int n = 0;
    for (int i = 0; i < a->fn; i++)
      if (a->fe[i] > now) { a->fe[n] = a->fe[i]; a->fm[n] = a->fm[i]; n++; }
    a->fn = n;
    double add = a->p * (1.0 - ap_fon(a, now));
    if (add > 0.0) {
      if (a->fn < APK) { a->fe[a->fn] = now + 5.0; a->fm[a->fn] = add; a->fn++; }
      else {
        /* APK + 1 entries: the APK kept ones and the new one */
        double e[APK + 1], m[APK + 1];
        for (int i = 0; i < APK; i++) { e[i] = a->fe[i]; m[i] = a->fm[i]; }
        e[APK] = now + 5.0; m[APK] = add;
        int j = 0;
        for (int i = 1; i < APK + 1; i++) if (m[i] < m[j]) j = i;
        int k = (j + 1 < APK + 1) ? j + 1 : j - 1;
        m[k] += m[j];
        int w = 0;
        for (int i = 0; i < APK + 1; i++) if (i != j) { a->fe[w] = e[i]; a->fm[w] = m[i]; w++; }
        a->fn = APK;
      }
    }
  }
  if (a->cas > 0.0) {
    int n = 0;
    for (int i = 0; i < a->sn; i++)
      if (a->se[i] > now) { a->se[n] = a->se[i]; a->sc[n] = a->sc[i]; n++; }
    a->sn = n;
    double c = (crit > 0.0) ? crit : 0.0;
    c = (c < 100.0) ? c : 100.0;
    c = c / 100.0;
    if (c > 0.0) {
      if (a->sn < APK) { a->se[a->sn] = now + a->cdur; a->sc[a->sn] = c; a->sn++; }
      else {
        for (int i = 1; i < APK; i++) { a->se[i - 1] = a->se[i]; a->sc[i - 1] = a->sc[i]; }
        a->se[APK - 1] = now + a->cdur; a->sc[APK - 1] = c;
      }
    }
  }
}
"""


def check() -> None:
    """The kernels hard-code Silent Messenger as the only crit -> attack speed item."""
    from sunken_sim import library

    found = {it.rawcode: (it.crit_as, it.crit_as_duration) for it in library.load_items() if it.crit_as}
    if found != {"I0QN": (0.28, 3.0)}:
        raise ValueError(f"crit -> attack speed items changed: {found}")
