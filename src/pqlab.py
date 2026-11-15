"""pqlab - helpers for the PQC-IoT thesis experiments (Colab notebook).

Contents: Wilson lower bound, bootstrap CI, TCP/link model for the transmission part of a
handshake, pairwise statistics with Holm correction, factorial ANOVA with partial eta-squared.
Everything that is *modeled* (not measured) lives in this file and is labeled as such.
"""
import math
import numpy as np
import pandas as pd
from scipy import stats

# ----------------------------------------------------------------------------- continuity
def wilson_lower(k, n, z=1.96):
    """Lower limit of the Wilson score interval for k successes in n trials."""
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - adj) / d)

# ----------------------------------------------------------------------------- bootstrap
def bootstrap_ci(x, stat=np.median, B=10000, alpha=0.05, seed=1):
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(B, len(x)))
    s = stat(x[idx], axis=1)
    return float(stat(x)), float(np.quantile(s, alpha / 2)), float(np.quantile(s, 1 - alpha / 2))

# ----------------------------------------------------------------------------- link model (MODELED)
MSS = 1460          # bytes of TCP payload per segment
INIT_CWND = 10      # segments (RFC 6928)
RTO_MIN_US = 200_000
SYN_RTO_US = 1_000_000

def _rto_us(rtt_us):
    return max(RTO_MIN_US, 2 * rtt_us)

def flight_time_us(nbytes, link, rng):
    """Time to deliver one handshake flight of `nbytes` over a TCP connection in slow start.
    link = dict(rtt_ms, loss, bw_mbps). Losses cost one RTO each window that suffers any loss."""
    rtt = link["rtt_ms"] * 1000.0
    p = link["loss"]
    bw = link["bw_mbps"] * 1e6 / 8.0  # bytes/s
    segs = max(1, math.ceil(nbytes / MSS))
    cwnd, sent, t = INIT_CWND, 0, 0.0
    while sent < segs:
        w = min(cwnd, segs - sent)
        t += w * MSS / bw * 1e6                      # serialization of the window
        if p > 0 and rng.binomial(w, p) > 0:          # at least one loss in the window
            t += _rto_us(rtt)
        sent += w
        if sent < segs:
            t += rtt                                  # wait for ACKs before the next window
            cwnd *= 2
    return t + rtt / 2.0                              # one-way propagation

def tx_time_us(flight_bytes, link, rng, tcp_setup=True):
    """Modeled transmission/waiting time of a TLS 1.3 handshake (3 flights) on `link`."""
    rtt = link["rtt_ms"] * 1000.0
    t = 0.0
    if tcp_setup:
        t += rtt
        while rng.random() < link["loss"]:            # lost SYN: 1 s timeout
            t += SYN_RTO_US
    for b in flight_bytes[:3]:
        t += flight_time_us(b, link, rng)
    return t

def add_modeled_times(df, links, cpu_scale=None, seed=1, timeout_s=10.0):
    """Adds modeled link columns to a handshake DataFrame (one row per handshake and link).
    cpu_scale: dict profile->factor applied to MEASURED computation (default 1.0 = this machine).
    Returns long DataFrame with columns tx_us, total_us, ok (completed within timeout)."""
    cpu_scale = cpu_scale or {"R0": 1.0}
    rng = np.random.default_rng(seed)
    rows = []
    for lname, link in links.items():
        for prof, k in cpu_scale.items():
            for r in df.itertuples(index=False):
                fb = [r.f1_bytes, r.f2_bytes, r.f3_bytes]
                tx = tx_time_us(fb, link, rng)
                dev = r.client_cpu_us * k
                srv = r.server_cpu_us
                total = tx + dev + srv
                rows.append((r.config, r.iter, lname, prof, dev, srv, tx, tx + srv, total,
                             total <= timeout_s * 1e6))
    return pd.DataFrame(rows, columns=["config", "iter", "net", "profile", "dev_comp_us", "srv_comp_us",
                                       "tx_us", "wait_us", "total_us", "ok"])

# ----------------------------------------------------------------------------- statistics
def holm(pvals):
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj

def cliffs_delta(a, b):
    a, b = np.asarray(a), np.asarray(b)
    u = stats.mannwhitneyu(a, b, alternative="two-sided").statistic
    return 2 * u / (len(a) * len(b)) - 1

def compare_to_baseline(df, group_col, metric, baseline, B=5000, seed=1):
    """Median + bootstrap CI per group, delta vs baseline, Mann-Whitney with Holm, Cliff's delta."""
    base = df.loc[df[group_col] == baseline, metric].to_numpy()
    out, praw = [], []
    for g, sub in df.groupby(group_col, sort=True):
        x = sub[metric].to_numpy()
        med, lo, hi = bootstrap_ci(x, B=B, seed=seed)
        if g == baseline:
            out.append(dict(group=g, n=len(x), median=med, ci_lo=lo, ci_hi=hi, delta_vs_base=0.0, p=np.nan, cliffs_delta=0.0))
            praw.append(np.nan)
            continue
        p = stats.mannwhitneyu(x, base, alternative="two-sided").pvalue
        out.append(dict(group=g, n=len(x), median=med, ci_lo=lo, ci_hi=hi, delta_vs_base=med - float(np.median(base)),
                        p=p, cliffs_delta=cliffs_delta(x, base)))
        praw.append(p)
    res = pd.DataFrame(out)
    mask = res["p"].notna()
    res.loc[mask, "p_holm"] = holm(res.loc[mask, "p"].to_numpy())
    return res

def kruskal_with_posthoc(df, group_col, metric):
    groups = [g[metric].to_numpy() for _, g in df.groupby(group_col)]
    h, p = stats.kruskal(*groups)
    names = sorted(df[group_col].unique())
    pairs, pv = [], []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = df.loc[df[group_col] == names[i], metric]
            b = df.loc[df[group_col] == names[j], metric]
            pairs.append((names[i], names[j]))
            pv.append(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)
    adj = holm(pv)
    post = pd.DataFrame([(a, b, p0, p1) for (a, b), p0, p1 in zip(pairs, pv, adj)], columns=["g1", "g2", "p", "p_holm"])
    return dict(H=h, p=p), post

def factorial_anova(df, metric, f1="kem", f2="auth", log=True):
    """Two-factor ANOVA on log(metric); returns table with partial eta-squared per term."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    d = df.copy()
    d["y"] = np.log(d[metric]) if log else d[metric]
    model = smf.ols(f"y ~ C({f1}) * C({f2})", data=d).fit()
    tab = sm.stats.anova_lm(model, typ=2)
    ss_res = tab.loc["Residual", "sum_sq"]
    tab["partial_eta2"] = tab["sum_sq"] / (tab["sum_sq"] + ss_res)
    tab.loc["Residual", "partial_eta2"] = np.nan
    return tab

def permutation_anova_effect(df, metric, f1="kem", f2="auth", B=2000, seed=1):
    """Permutation p-values for the main effects (permuting the OTHER factor's residual structure is
    not trivial; here we permute the factor labels within the levels of the other factor)."""
    rng = np.random.default_rng(seed)
    d = df.copy()
    d["y"] = np.log(d[metric])
    def eta(dd, f, other):
        grand = dd["y"].mean()
        ss_f = sum(len(g) * (g["y"].mean() - grand) ** 2 for _, g in dd.groupby(f))
        ss_t = ((dd["y"] - grand) ** 2).sum()
        return ss_f / ss_t
    res = {}
    for f, o in ((f1, f2), (f2, f1)):
        obs = eta(d, f, o)
        cnt = 0
        for _ in range(B):
            dd = d.copy()
            dd[f] = dd.groupby(o)[f].transform(lambda s: rng.permutation(s.values))
            if eta(dd, f, o) >= obs:
                cnt += 1
        res[f] = dict(eta2=obs, p_perm=(cnt + 1) / (B + 1))
    return res