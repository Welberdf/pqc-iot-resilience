"""python -m pqmodel profile.json [--sens N] [--seed S] [--scenario NAME] [--out result.json]"""
import argparse
import json

from . import model
from .sensitivity import sensitivity as run_sensitivity


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pqmodel")
    ap.add_argument("profile")
    ap.add_argument("--sens", type=int, default=0, help="number of Monte Carlo draws (0 = no sensitivity analysis)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--scenario", default="intermediate")
    ap.add_argument("--out", default=None, help="write the full result as JSON")
    a = ap.parse_args(argv)
    prof = model.load_profile(a.profile)
    res = model.evaluate_all(prof)
    out = {"profile": prof.get("name", a.profile), "evaluation": res}
    print(f"Profile: {prof.get('name', a.profile)}")
    print(f"{'Conf':<5}{'Level':<6}{'OV':>7}{'min v':>8}  Assurance note")
    for cfg, r in res.items():
        print(f"{cfg:<5}RL{r['level']:<4}{r['OV']:>7.3f}{r['min_v']:>8.3f}  {r['assurance']}")
    if "urgency" in prof and "Z" in prof:
        out["migration_plan"] = {s: model.migration_plan(prof, list(res)[0], s) for s in prof["Z"]}
    if a.sens:
        sr = run_sensitivity(prof, n=a.sens, seed=a.seed)
        out["sensitivity"] = sr
        print(f"\nSensitivity ({sr['n']} draws, seed {sr['seed']}): required stability {sr['required']:.0%}")
        for cfg in res:
            d = sr["level_distribution"][cfg]
            print(f"{cfg:<5}stability {sr['stability'][cfg]:.3f}  {'robust' if sr['robust'][cfg] else 'NOT robust'}  "
                  f"levels RL0..RL3 = " + " ".join(f"{x:.3f}" for x in d))
        print(f"Order by OV preserved in {sr['order_preserved']:.3f} of the draws")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, default=str)


if __name__ == "__main__":
    main()
