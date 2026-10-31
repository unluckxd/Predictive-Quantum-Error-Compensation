# PQEC v0.3 Frozen Simulation Bundle

## Version scope

PQEC v0.3 freezes the analytic robustness study and two follow-up Qiskit Aer sensitivity sweeps as a reproducible simulation bundle. The analytic and Aer studies use separate models, dependency sets, configurations, and output directories. It is not a hardware release, logical-qubit implementation, or fault-tolerant quantum error-correction system.

The Aer follow-up changes no controller algorithms. It consists of two one-factor-at-a-time experiments:

| Study | Conditions | Paired trajectories | Per-method rows | Test families |
| --- | ---: | ---: | ---: | --- |
| Target/probe T1 and T2 | 17 | 3,400 | 27,200 | 306 condition effects + 288 paired effect changes |
| Feedback latency | 4 | 800 | 6,400 | 72 condition effects + 54 paired effect changes |

Both use seed blocks 20–27 with 25 trajectories per block, shared operation-indexed error trajectories across parameter levels, 32 probe shots every eight target cycles, 5,000 paired bootstrap resamples, and 20,000 sign flips. The combined Holm families contain 594 tests for T1/T2 and 126 for latency. Paired bootstrap intervals are unadjusted.

## Frozen artifacts

- [T1/T2 configuration](../configs/aer_t1t2_sweep_v03.json) and [saved results](../results/pqec_v03/aer_t1t2/).
- [Feedback-latency configuration](../configs/aer_feedback_latency_sweep_v03.json) and [saved results](../results/pqec_v03/aer_latency/).
- [Sensitivity report](aer_sensitivity_v03.md), [T1/T2 figure](../figures/aer_v03_t1t2_sensitivity.svg), and [latency figure](../figures/aer_v03_latency_sensitivity.svg).
- [Reproduction instructions](reproducibility.md).
- [Machine-readable version manifest](../results/pqec_v03/version_manifest.json) and [SHA-256 manifest](../results/pqec_v03/SHA256SUMS.txt), covering the frozen configs, reports, scripts, plots, and generated result files. The checksum file does not hash itself.

Each results directory contains the per-method run CSV, condition summaries, paired statistics, paired effect-change statistics, seed manifest, condition-specific calibration curve, exact configuration snapshot, and environment record. The version uses the Aer dependency set recorded in `requirements-aer.txt` and the environment JSON files.

After reproducing the studies and figures, run `python freeze_pqec_v03.py` to audit the saved row counts and regenerate the machine-readable inventory and SHA-256 file. This packaging step does not rerun the simulations.

## Frozen interpretation

Under the tested stylized Aer model, guarded PQEC has no corrected final-fidelity advantage over reactive last-probe control across the T1/T2 or latency conditions. Its per-gate angle residual is higher in every condition. The latency sweep's rise in active-controller final fidelity as idle time increases is a sequence-specific relaxation effect in this simulator; the control-error trajectory itself does not drift during the extra wall-clock wait. The result is not evidence that longer latency benefits a device.

The analytic robustness study still shows conditional gains in some common-drift, high-measurement-budget settings, while the Aer sensitivity studies do not reproduce a guarded-PQEC sequence-level gain. The frozen bundle therefore supports a model-dependent simulation prototype, not a validated quantum error-correction technology.
