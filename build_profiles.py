"""Builds the profile files of the calculator from the result files of the notebook (E1-E6).

The budgets, the thresholds, the weights and the urgency inputs below are fixed here, BEFORE the calculator is run,
and are published with the results (Chapter 4: 'the budgets ... are published together with the results').

Usage: python build_profiles.py <results_dir> <out_dir>"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

IW10 = 10 * 1460          # TCP initial window (10 segments of 1460 B): the largest server flight should fit in it
SECTOR = 4096             # signature region of an image: one 4 KiB flash erase sector

# modes of the components of each configuration (Chapter 5, Table of configurations)
MODES = {
    "A": dict(ke="C", au="C", fw="C", fwscheme="ecdsa"),
    "B": dict(ke="H", au="C", fw="C", fwscheme="ecdsa"),
    "C": dict(ke="H", au="H", fw="C", fwscheme="ecdsa"),
    "D": dict(ke="H", au="H", fw="H", fwscheme="hybrid"),
    "E": dict(ke="P", au="P", fw="P", fwscheme="mldsa44"),
    "F": dict(ke="P", au="P", fw="P", fwscheme="lms"),
}
# transitions of the replacement drill (E5) and the components of the TLS service that each one replaces
DRILL = {"A": ("A→B", ("KE",)), "B": ("B→E", ("KE", "AU")), "D": ("D→E", ("KE", "AU"))}

# device/application profiles (provisional, fixed before the run). RAM budget = 25 % of the memory of the device
# (256, 128, 64 MiB). Link 2 and 3 (gateway--broker, broker--cloud) are infrastructure links evaluated under N0.
PROFILES = {
    "PA": dict(desc="Gateway-class device on a local network (N0), 256 MiB RAM, image of 4 MiB", net="N0", image_kib=4096,
               hs_ms=50, ram_kb=65536, verify_ms=100, update_s=5),
    "PB": dict(desc="Field device on a regional link (N1), 128 MiB RAM, image of 1 MiB", net="N1", image_kib=1024,
               hs_ms=200, ram_kb=32768, verify_ms=100, update_s=5),
    "PC": dict(desc="Field device on a poor link (N2), 64 MiB RAM, image of 1 MiB", net="N2", image_kib=1024,
               hs_ms=1000, ram_kb=16384, verify_ms=100, update_s=10),
}
INFRA = dict(net="N0", hs_ms=50, ram_kb=65536)
URGENCY = {"KE": dict(X=3, Y=15), "AU": dict(X=3, Y=2), "FW": dict(X=5, Y=15)}   # years
Z = {"optimistic": 25, "intermediate": 15, "pessimistic": 9}                          # years to a CRQC (scenarios)
COMPS = ("KE1", "AU1", "KE2", "AU2", "KE3", "AU3", "FW")


def build(res, out):
    res, out = Path(res), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    hs = pd.read_csv(res / "hs_modeled.csv")
    meas = json.loads((res / "measurements_for_model.json").read_text())
    fw = pd.read_csv(res / "fw_metrics.csv")
    upd = pd.read_csv(res / "fw_update_modeled.csv")
    drill = pd.read_csv(res / "drill.csv")
    drill_ok = {r.transicao: bool(r.sucesso) for r in drill.groupby("transicao").sucesso.all().reset_index().itertuples()}
    paths = []
    for pname, P in PROFILES.items():
        cfgs = {}
        for cfg, M in MODES.items():
            m = meas[cfg]["handshake"]
            comps = {}

            def hs_component(c, mode, net, hs_ms_budget):
                g = hs[(hs.config == cfg) & (hs.net == net)]
                return dict(mode=mode, runs=True,
                            metrics=dict(handshake_ms=float(g.total_us.median() / 1000), peak_ram_kb=float(m["peak_rss_kb"]),
                                         server_flight_bytes=float(m["s2c_bytes"])),
                            successes=int(g.ok.sum()), trials=int(len(g)))
            for i, net in ((1, P["net"]), (2, INFRA["net"]), (3, INFRA["net"])):
                comps[f"KE{i}"] = hs_component(f"KE{i}", M["ke"], net, None)
                comps[f"AU{i}"] = hs_component(f"AU{i}", M["au"], net, None)
            sch = M["fwscheme"]
            if sch == "lms":
                comps["FW"] = dict(mode=M["fw"], runs=False, metrics={}, successes=0, trials=0,
                                   note="LMS verification was not measured in this environment")
            else:
                f = fw[(fw.scheme == sch) & (fw.size_kib == P["image_kib"])].iloc[0]
                u = upd[(upd.scheme == sch) & (upd.size_kib == P["image_kib"]) & (upd.net == P["net"])]
                comps["FW"] = dict(mode=M["fw"], runs=True,
                                   metrics=dict(verify_ms=float(f.verify_med_us / 1000), sig_bytes=float(f.sig_bytes),
                                                peak_ram_kb=float(f.rss_peak_kb), update_s=float(u.total_us.median() / 1e6)),
                                   successes=int(u.ok.sum()), trials=int(len(u)))
            # agility: 1 where the replacement drill of E5 (functional, in software) replaced that component starting
            # from this configuration; 0.5 (declared, not verified) elsewhere, including the firmware signature
            ver = ()
            if cfg in DRILL and drill_ok.get(DRILL[cfg][0], False):
                ver = DRILL[cfg][1]
            for c in COMPS:
                comps[c]["agility"] = 1 if c[:2] in ver else 0.5
            cfgs[cfg] = comps
        budgets = {}
        for i, (net, hb, rb) in ((1, (P["net"], P["hs_ms"], P["ram_kb"])), (2, (INFRA["net"], INFRA["hs_ms"], INFRA["ram_kb"])),
                                 (3, (INFRA["net"], INFRA["hs_ms"], INFRA["ram_kb"]))):
            for k in ("KE", "AU"):
                budgets[f"{k}{i}"] = dict(handshake_ms=hb, peak_ram_kb=rb, server_flight_bytes=IW10)
        budgets["FW"] = dict(verify_ms=P["verify_ms"], sig_bytes=SECTOR, peak_ram_kb=P["ram_kb"], update_s=P["update_s"])
        prof = dict(name=pname, description=P["desc"], z=1.96, thresholds=dict(phi_F=0.5, phi_S=0.95),
                    weights={c: 1 / 7 for c in COMPS}, budgets=budgets,
                    urgency={c: URGENCY[c[:2]] for c in COMPS}, Z=Z, configurations=cfgs)
        p = out / f"profile_{pname}.json"
        p.write_text(json.dumps(prof, indent=2))
        paths.append(p)
    return paths


def h3_table(profile_path, fwdf, updf):
    """Feasibility of the firmware signature of each scheme (including SLH-DSA, which is not in A--F) under a profile."""
    from pqmodel.model import feasibility
    prof = json.loads(Path(profile_path).read_text())
    name = prof["name"]; P = PROFILES[name]
    rows = []
    for sch in ("ecdsa", "mldsa44", "slh", "hybrid"):
        f = fwdf[(fwdf.scheme == sch) & (fwdf.size_kib == P["image_kib"])].iloc[0]
        u = updf[(updf.scheme == sch) & (updf.size_kib == P["image_kib"]) & (updf.net == P["net"])]
        x = dict(verify_ms=float(f.verify_med_us / 1000), sig_bytes=float(f.sig_bytes), peak_ram_kb=float(f.rss_peak_kb),
                 update_s=float(u.total_us.median() / 1e6))
        rows.append(dict(profile=name, scheme=sch, F=feasibility(True, x, prof["budgets"]["FW"]), **x))
    return rows


if __name__ == "__main__":
    for p in build(sys.argv[1], sys.argv[2]):
        print("wrote", p)
