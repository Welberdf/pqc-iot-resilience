"""Monte Carlo sensitivity analysis of the classification (Section 4.5).

In each draw: weights ~ Dirichlet(concentration * baseline weights); each budget multiplied by a factor
U[1-budget_rel, 1+budget_rel]; phi_F multiplied by U[1-phi_rel, 1+phi_rel]; the tolerated share of failures
(1 - phi_S) multiplied by U[1-phi_rel, 1+phi_rel]. The same measurements are used in every draw."""
import random

from .model import COMPONENTS, _weights, effective_mode, evaluate, level, assurance_note, wilson_lower


def _prepare(profile):
    """Per configuration and component: ratios b_m / x_m, S_c, mode, agility, runs (independent of the draw)."""
    z = profile.get("z", 1.96)
    prep = {}
    for cfg, comps in profile["configurations"].items():
        prep[cfg] = {}
        for c in COMPONENTS:
            d = comps[c]
            ratios = []
            if d.get("runs", True):
                for m, b in profile["budgets"][c].items():
                    ratios.append((m, b, d["metrics"][m]))
            prep[cfg][c] = dict(mode=d["mode"], A=d.get("agility", 1), runs=d.get("runs", True),
                                S=wilson_lower(d.get("successes", 0), d.get("trials", 0), z), ratios=ratios)
    return prep


def _order(ovs):
    return tuple(sorted(ovs, key=lambda k: (-round(ovs[k], 9), k)))


def sensitivity(profile, n=10000, seed=1, budget_rel=0.25, phi_rel=0.2, conc=20.0, required=0.95):
    rng = random.Random(seed)
    base_w = _weights(profile)
    th = profile.get("thresholds", {})
    phi_f0, phi_s0 = th.get("phi_F", 0.5), th.get("phi_S", 0.95)
    prep = _prepare(profile)
    cfgs = list(profile["configurations"])
    base = {cfg: evaluate(profile, cfg) for cfg in cfgs}
    base_level = {cfg: base[cfg]["level"] for cfg in cfgs}
    base_order = _order({cfg: base[cfg]["OV"] for cfg in cfgs})
    same_level = {cfg: 0 for cfg in cfgs}
    dist = {cfg: [0, 0, 0, 0] for cfg in cfgs}
    same_order = 0
    for _ in range(n):
        g = [rng.gammavariate(conc * base_w[c], 1.0) for c in COMPONENTS]
        sg = sum(g)
        w = {c: g[i] / sg for i, c in enumerate(COMPONENTS)}
        bf = {c: {m: rng.uniform(1 - budget_rel, 1 + budget_rel) for m in profile["budgets"][c]} for c in COMPONENTS}
        phi_f = phi_f0 * rng.uniform(1 - phi_rel, 1 + phi_rel)
        phi_s = 1.0 - (1.0 - phi_s0) * rng.uniform(1 - phi_rel, 1 + phi_rel)
        ovs = {}
        for cfg in cfgs:
            modes, agil, ov = {}, {}, 0.0
            for c in COMPONENTS:
                p = prep[cfg][c]
                if not p["runs"]:
                    f = 0.0
                else:
                    f = min(1.0, min((1.0 if x <= 0 else min(1.0, bf[c][m] * b / x)) for m, b, x in p["ratios"]))
                modes[c] = effective_mode(p["mode"], f, p["S"], phi_f, phi_s)
                agil[c] = p["A"]
                ov += w[c] * min(f, p["S"])
            lv = level(modes, agil)
            dist[cfg][lv] += 1
            same_level[cfg] += (lv == base_level[cfg])
            ovs[cfg] = ov
        same_order += (_order(ovs) == base_order)
    stability = {cfg: same_level[cfg] / n for cfg in cfgs}
    return dict(n=n, seed=seed, baseline_level=base_level, baseline_order=list(base_order),
                stability=stability, robust={cfg: stability[cfg] >= required for cfg in cfgs},
                level_distribution={cfg: [x / n for x in dist[cfg]] for cfg in cfgs},
                order_preserved=same_order / n, required=required,
                parameters=dict(budget_rel=budget_rel, phi_rel=phi_rel, concentration=conc))
