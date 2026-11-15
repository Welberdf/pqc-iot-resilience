"""Indicators and classification of the resilience model (Chapter 4).

Components (Table 4.1): KE1, AU1 (device--gateway), KE2, AU2 (gateway--broker), KE3, AU3 (broker--cloud), FW.
Modes: "C" classical, "H" hybrid, "P" post-quantum."""
import json
import math

COMPONENTS = ("KE1", "AU1", "KE2", "AU2", "KE3", "AU3", "FW")
Z95 = 1.96


def kind(c):
    """Function class of a component: KE, AU or FW."""
    return c[:2] if c[:2] in ("KE", "AU") else "FW"


def wilson_lower(k, n, z=Z95):
    """Continuity S_c: lower limit of the Wilson score interval for k successes in n trials (Equation 4.4)."""
    if n <= 0:
        return 0.0
    p = k / n
    den = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    rad = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - rad) / den)


def urgency(x, y, z):
    """Migration urgency U_c (Equation 4.1): 1 if X_c + Y_c > Z, otherwise 0."""
    return 1 if x + y > z else 0


def feasibility(runs, metrics, budgets):
    """Feasibility F_c (Equation 4.2).

    0 if the configuration cannot be executed on the device; otherwise the minimum over the metrics of
    min(1, b_m / x_m). A metric without a budget is not constrained; a budget without a measurement is an error."""
    if not runs:
        return 0.0
    ratios = []
    for m, b in budgets.items():
        if m not in metrics:
            raise KeyError(f"budget for '{m}' but no measurement of it")
        x = metrics[m]
        ratios.append(1.0 if x <= 0 else min(1.0, b / x))
    if not ratios:
        raise ValueError("no metric with a budget: feasibility is undefined")
    return min(ratios)


def effective_mode(kappa, f, s, phi_f, phi_s):
    """Effective mode (Equation 4.5): a hybrid/post-quantum mode counts only if the component is operational."""
    if kappa == "C" or (f >= phi_f and s >= phi_s):
        return kappa
    return "C"


def level(modes, agility):
    """Resilience level 0..3 from the effective modes and the agility of each component (Table 4.2).

    The level is the highest one whose condition is satisfied, and it is limited by the least migrated function class."""
    if any(modes[c] == "C" for c in modes if kind(c) == "KE"):
        return 0
    if any(modes[c] == "C" for c in modes if kind(c) == "AU"):
        return 1
    if modes["FW"] == "C" or any(agility[c] == 0 for c in modes):
        return 2
    return 3


def assurance_note(modes):
    """Assurance note: distinguishes hybrid from purely post-quantum components (reported, not scored)."""
    ms = {m for m in modes.values() if m != "C"}
    if not ms:
        return "No post-quantum protection"
    if ms == {"H"}:
        return "Hybrid only"
    if ms == {"P"}:
        return "Pure post-quantum components"
    return "Hybrid and pure post-quantum components"


def load_profile(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _weights(profile):
    w = profile.get("weights")
    if not w:
        return {c: 1.0 / len(COMPONENTS) for c in COMPONENTS}
    s = sum(w.values())
    return {c: w[c] / s for c in COMPONENTS}


def component_indicators(profile, cfg, c, budgets=None, phi_f=None, phi_s=None):
    """F_c, S_c, v_c and effective mode of component c in configuration cfg."""
    z = profile.get("z", Z95)
    th = profile.get("thresholds", {})
    phi_f = th.get("phi_F", 0.5) if phi_f is None else phi_f
    phi_s = th.get("phi_S", 0.95) if phi_s is None else phi_s
    d = profile["configurations"][cfg][c]
    b = profile["budgets"][c] if budgets is None else budgets[c]
    f = feasibility(d.get("runs", True), d.get("metrics", {}), b)
    s = wilson_lower(d.get("successes", 0), d.get("trials", 0), z)
    v = min(f, s)
    kap = effective_mode(d["mode"], f, s, phi_f, phi_s)
    return dict(mode=d["mode"], effective=kap, F=f, S=s, v=v, A=d.get("agility", 1), runs=d.get("runs", True),
                note=d.get("note", ""))


def evaluate(profile, cfg, weights=None, budgets=None, phi_f=None, phi_s=None):
    """Indicators of all components, level, index OV (Equation 4.7), minimum of v_c and assurance note."""
    w = _weights(profile) if weights is None else weights
    comp = {c: component_indicators(profile, cfg, c, budgets, phi_f, phi_s) for c in COMPONENTS}
    modes = {c: comp[c]["effective"] for c in COMPONENTS}
    agil = {c: comp[c]["A"] for c in COMPONENTS}
    ov = sum(w[c] * comp[c]["v"] for c in COMPONENTS)
    return dict(config=cfg, components=comp, level=level(modes, agil), OV=ov,
                min_v=min(comp[c]["v"] for c in COMPONENTS), assurance=assurance_note(modes))


def evaluate_all(profile):
    return {cfg: evaluate(profile, cfg) for cfg in profile["configurations"]}


def migration_plan(profile, cfg, scenario="intermediate"):
    """Order of migration (Section 4.6): decreasing urgency U_c, then increasing agility A_c, then increasing F_c."""
    zval = profile["Z"][scenario]
    ev = evaluate(profile, cfg)
    rows = []
    for c in COMPONENTS:
        u = urgency(profile["urgency"][c]["X"], profile["urgency"][c]["Y"], zval)
        rows.append((c, u, ev["components"][c]["A"], ev["components"][c]["F"]))
    rows.sort(key=lambda r: (-r[1], r[2], r[3], COMPONENTS.index(r[0])))
    return [dict(component=r[0], U=r[1], A=r[2], F=r[3]) for r in rows]
