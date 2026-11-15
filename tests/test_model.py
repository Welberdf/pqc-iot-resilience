import itertools
import unittest

from pqmodel import (COMPONENTS, wilson_lower, urgency, feasibility, effective_mode, level, assurance_note,
                     evaluate, migration_plan, sensitivity)


def mk(modes, runs=None, successes=1000, trials=1000, agility=1, metrics=None, budget=100.0, x=50.0):
    """Profile with one configuration 'T' (modes: dict component -> C/H/P) and one metric per component."""
    runs = runs or {}
    cfg = {}
    for c in COMPONENTS:
        cfg[c] = dict(mode=modes[c], agility=(agility[c] if isinstance(agility, dict) else agility),
                      runs=runs.get(c, True), metrics=(metrics or {}).get(c, {"t": x}),
                      successes=successes, trials=trials)
    return dict(name="t", thresholds={"phi_F": 0.5, "phi_S": 0.95}, budgets={c: {"t": budget} for c in COMPONENTS},
                configurations={"T": cfg},
                urgency={c: {"X": 3, "Y": 10} for c in COMPONENTS}, Z={"early": 9, "intermediate": 15, "late": 25})


def modes_of(ke, au, fw):
    return {"KE1": ke, "KE2": ke, "KE3": ke, "AU1": au, "AU2": au, "AU3": au, "FW": fw}


class Wilson(unittest.TestCase):
    def test_reference_all_successes(self):
        self.assertAlmostEqual(wilson_lower(100, 100), 100 / (100 + 1.96 ** 2), places=12)
        self.assertAlmostEqual(wilson_lower(1000, 1000), 0.99617, places=5)
        self.assertAlmostEqual(wilson_lower(300, 300), 0.98736, places=5)

    def test_reference_value_partial(self):
        # Wilson 95 % interval for 8/10 successes: lower limit 0.4902 (Brown et al., 2001 formula)
        self.assertAlmostEqual(wilson_lower(8, 10), 0.4902, places=3)

    def test_zero_cases(self):
        self.assertEqual(wilson_lower(0, 0), 0.0)
        self.assertAlmostEqual(wilson_lower(0, 50), 0.0, places=12)

    def test_monotone_in_successes_and_trials(self):
        self.assertLess(wilson_lower(90, 100), wilson_lower(95, 100))
        self.assertLess(wilson_lower(20, 20), wilson_lower(2000, 2000))

    def test_minimum_trials_for_threshold(self):
        n = next(n for n in range(1, 500) if wilson_lower(n, n) >= 0.95)
        self.assertEqual(n, 73)


class Urgency(unittest.TestCase):
    def test_boundary_is_strict(self):
        self.assertEqual(urgency(5, 10, 15), 0)
        self.assertEqual(urgency(5.01, 10, 15), 1)
        self.assertEqual(urgency(1, 1, 15), 0)


class Feasibility(unittest.TestCase):
    def test_minimum_over_metrics(self):
        self.assertAlmostEqual(feasibility(True, {"a": 50, "b": 400}, {"a": 100, "b": 200}), 0.5)

    def test_within_budget_is_one(self):
        self.assertEqual(feasibility(True, {"a": 50}, {"a": 100}), 1.0)

    def test_cannot_run_is_zero(self):
        self.assertEqual(feasibility(False, {"a": 1}, {"a": 100}), 0.0)

    def test_missing_budget_is_not_constrained(self):
        self.assertEqual(feasibility(True, {"a": 50, "extra": 1e9}, {"a": 100}), 1.0)

    def test_budget_without_measurement_is_error(self):
        with self.assertRaises(KeyError):
            feasibility(True, {"a": 1}, {"a": 100, "b": 5})


class EffectiveMode(unittest.TestCase):
    def test_gate_feasibility(self):
        self.assertEqual(effective_mode("H", 0.49, 0.99, 0.5, 0.95), "C")
        self.assertEqual(effective_mode("H", 0.50, 0.99, 0.5, 0.95), "H")

    def test_gate_continuity(self):
        self.assertEqual(effective_mode("P", 1.0, 0.94, 0.5, 0.95), "C")
        self.assertEqual(effective_mode("P", 1.0, 0.95, 0.5, 0.95), "P")

    def test_classical_is_unchanged(self):
        self.assertEqual(effective_mode("C", 0.0, 0.0, 0.5, 0.95), "C")


class Levels(unittest.TestCase):
    def lv(self, ke, au, fw, **kw):
        return evaluate(mk(modes_of(ke, au, fw), **kw), "T")["level"]

    def test_schematic_configurations(self):
        self.assertEqual(self.lv("C", "C", "C"), 0)   # A
        self.assertEqual(self.lv("H", "C", "C"), 1)   # B
        self.assertEqual(self.lv("H", "C", "H"), 1)   # B, firmware in either mode
        self.assertEqual(self.lv("H", "H", "C"), 2)   # C
        self.assertEqual(self.lv("H", "H", "H"), 3)   # D
        self.assertEqual(self.lv("P", "P", "P"), 3)   # E

    def test_only_firmware_classical_is_rl2(self):
        self.assertEqual(self.lv("P", "P", "C"), 2)

    def test_agility_zero_blocks_rl3(self):
        ag = {c: 1 for c in COMPONENTS}; ag["AU2"] = 0
        self.assertEqual(self.lv("H", "H", "H", agility=ag), 2)
        ag["AU2"] = 0.5
        self.assertEqual(self.lv("H", "H", "H", agility=ag), 3)

    def test_weakest_link_single_classical_link(self):
        m = modes_of("H", "H", "H"); m["KE3"] = "C"
        self.assertEqual(evaluate(mk(m), "T")["level"], 0)

    def test_monotonic_over_all_classical_hybrid_combinations(self):
        def L(vec):
            return evaluate(mk(dict(zip(COMPONENTS, vec))), "T")["level"]
        for vec in itertools.product("CH", repeat=len(COMPONENTS)):
            base = L(vec)
            for i, m in enumerate(vec):
                if m == "C":
                    up = list(vec); up[i] = "H"
                    self.assertGreaterEqual(L(up), base, (vec, i))

    def test_feasibility_gate_lowers_level(self):
        # firmware hybrid but verification 3x over budget (F = 0.33 < 0.5): effective mode classical -> RL2
        ev = evaluate(mk(modes_of("H", "H", "H"), metrics={"FW": {"t": 300.0}}), "T")
        self.assertEqual(ev["level"], 2)
        self.assertEqual(ev["components"]["FW"]["effective"], "C")

    def test_low_continuity_lowers_level(self):
        self.assertEqual(self.lv("H", "H", "H", successes=90, trials=100), 0)

    def test_cannot_run_counts_as_classical(self):
        ev = evaluate(mk(modes_of("P", "P", "P"), runs={"FW": False}), "T")
        self.assertEqual(ev["level"], 2)
        self.assertEqual(ev["components"]["FW"]["F"], 0.0)


class Viability(unittest.TestCase):
    def test_ov_is_weighted_mean_of_min(self):
        prof = mk(modes_of("H", "H", "H"), successes=1000, trials=1000, metrics={"AU1": {"t": 200.0}})
        prof["weights"] = {c: (2.0 if c == "AU1" else 1.0) for c in COMPONENTS}
        ev = evaluate(prof, "T")
        s = wilson_lower(1000, 1000)
        expected = (2 * min(0.5, s) + 6 * min(1.0, s)) / 8
        self.assertAlmostEqual(ev["OV"], expected, places=12)
        self.assertAlmostEqual(ev["min_v"], 0.5, places=12)

    def test_assurance_notes(self):
        self.assertEqual(assurance_note(modes_of("C", "C", "C")), "No post-quantum protection")
        self.assertEqual(assurance_note(modes_of("H", "C", "C")), "Hybrid only")
        self.assertEqual(assurance_note(modes_of("P", "P", "P")), "Pure post-quantum components")
        self.assertEqual(assurance_note(modes_of("H", "P", "C")), "Hybrid and pure post-quantum components")


class Plan(unittest.TestCase):
    def test_order_by_urgency_agility_feasibility(self):
        prof = mk(modes_of("C", "C", "C"))
        prof["urgency"] = {c: {"X": 1, "Y": 1} for c in COMPONENTS}
        prof["urgency"]["KE1"] = {"X": 5, "Y": 20}      # urgent
        prof["urgency"]["FW"] = {"X": 5, "Y": 20}       # urgent
        prof["configurations"]["T"]["FW"]["agility"] = 0.5
        plan = migration_plan(prof, "T", "intermediate")
        self.assertEqual([p["component"] for p in plan[:2]], ["FW", "KE1"])   # same U, lower agility first
        self.assertTrue(all(p["U"] == 0 for p in plan[2:]))


class Sensitivity(unittest.TestCase):
    def test_reproducible(self):
        prof = mk(modes_of("H", "H", "H"), x=95.0)
        a = sensitivity(prof, n=300, seed=7)
        b = sensitivity(prof, n=300, seed=7)
        self.assertEqual(a["stability"], b["stability"])
        self.assertEqual(a["order_preserved"], b["order_preserved"])

    def test_far_from_thresholds_is_stable(self):
        a = sensitivity(mk(modes_of("H", "H", "H"), x=10.0), n=500, seed=1)
        self.assertEqual(a["stability"]["T"], 1.0)
        self.assertTrue(a["robust"]["T"])

    def test_near_threshold_is_not_robust(self):
        # firmware at x/b = 2.0 -> F = 0.5 exactly at phi_F: the level flips in about half of the draws
        prof = mk(modes_of("H", "H", "H"), metrics={"FW": {"t": 200.0}})
        a = sensitivity(prof, n=2000, seed=1)
        self.assertLess(a["stability"]["T"], 0.95)
        self.assertFalse(a["robust"]["T"])

    def test_distribution_sums_to_one(self):
        a = sensitivity(mk(modes_of("H", "C", "C"), x=90.0), n=200, seed=3)
        self.assertAlmostEqual(sum(a["level_distribution"]["T"]), 1.0, places=12)

    def test_continuity_threshold_varies_failure_share(self):
        # 0.987 (300/300) stays above every draw of phi_S in [0.94, 0.96]
        a = sensitivity(mk(modes_of("H", "H", "H"), successes=300, trials=300, x=10.0), n=300, seed=1)
        self.assertEqual(a["stability"]["T"], 1.0)


if __name__ == "__main__":
    unittest.main()
