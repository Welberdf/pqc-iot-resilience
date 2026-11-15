# PQC-IoT resilience: experiments and model calculator

Supplementary material of the doctoral thesis **"Evaluation of Post-Quantum Cryptographic Resilience in IoT Architectures"**
(Welber Santos de Oliveira, Programa de Pós-Graduação em Engenharia Elétrica, Universidade de Brasília; advisor: Prof. Dr. Fábio Lúcio Lopes de Mendonça).

It contains (i) the Colab notebook and measurement programs of the emulated testbed (Chapter 5), (ii) `pqmodel`, the calculator of the
component-based resilience model (Chapter 4, Appendix C), and (iii) the raw data and results of the session reported in the thesis.

## Contents

| Path | Description |
|---|---|
| `notebooks/tese_pqc_colab.ipynb` | Builds OpenSSL 3.5.4, liboqs and oqs-provider, runs experiments E1 to E7 and the statistical analysis (Google Colab). |
| `src/hs_bench.c` | TLS 1.3 handshake benchmark (client and server in one process, memory BIO pairs). |
| `src/sig_bench.c` | Firmware signature verification benchmark (EVP interface). |
| `src/pqlab.py` | Statistics (bootstrap, Mann-Whitney, Kruskal-Wallis, Holm, Cliff's delta, factorial ANOVA) and the TCP slow-start link model. |
| `pqmodel/` | Calculator of the resilience model (Python standard library only). |
| `tests/test_model.py` | 30 automated tests of the calculator. |
| `build_profiles.py` | Builds the profile files PA, PB, PC from the notebook results (budgets and urgency inputs fixed before the run). |
| `results/session_20261115_011418/` | Raw data of the session reported in the thesis (`hs_raw.csv`, `hs_modeled.csv`, `fw_metrics.csv`, `drill.csv`, `continuity.csv`, `environment.json`, ...) and the outputs of the model (`model/`). |

## Reproducing

1. Open `notebooks/tese_pqc_colab.ipynb` in Google Colab and run all cells (about nine minutes to build the stack). The processor assigned by Colab changes between sessions; the environment of each run is stored in `environment.json`.
2. The calculator, with the profile files of the thesis:

```
python -m unittest tests.test_model
python -m pqmodel results/session_20261115_011418/model/profile_PA.json --sens 10000 --seed 1
```

Expected output for profile PA: levels RL0 (A), RL1 (B), RL2 (C), RL3 (D, E), RL2 (F, whose LMS signature was not measured);
OV = 0.991 for A to E and 0.854 for F; level stability 1.000.

## Scope and limitations

Emulated testbed: the TLS 1.3 handshake is executed and measured on a real software stack (OpenSSL 3.5.4) in a cloud virtual machine
(Intel Xeon 2.20 GHz, 2 vCPU); the network is modeled, not measured. Energy, flash occupation, MQTT broker, LMS signing and
microcontroller hardware are not covered. The budgets and thresholds are provisional. Computation times are those of the Colab
processor and are not times of embedded devices. See Chapter 5 (Threats to Validity) of the thesis.

liboqs and oqs-provider are research libraries and are not recommended for production use.

## License

MIT (see `LICENSE`).

## How to cite

Oliveira, W. S. *Evaluation of Post-Quantum Cryptographic Resilience in IoT Architectures*. PhD thesis, Universidade de Brasília, 2026. Code and data: see the DOI of this release (Zenodo).
