# Methodology audit

This audit records what the current analytic and Qiskit Aer studies establish about statistical units, parameter selection, controller fairness, sensitivity, and reproduction. It is a description of the saved experiments, not a new experiment or a claim of hardware validation.

## Status summary

| Check | Status | What the current study supports |
| --- | --- | --- |
| Statistical unit | Mostly addressed, conditional on independent seeded trajectories | Inference uses paired trajectory-level differences, not the number of per-method CSV rows. Seed blocks are recorded and their effects are reported, but they are not cluster-resampled. |
| Predictor parameter selection | Partially documented | Parameters are fixed in configuration files and the sweep code does not optimize them. The project has no preregistered protocol or separate tuning/holdout record, so complete independence from all earlier exploratory choices cannot be established. |
| Comparison fairness | Addressed for active probe controllers; reference methods differ by design | Reactive and predictive controllers share the same probe record, shot count, checkpoint schedule, and configured Aer wait. No-compensation and oracle/ideal references do not have the same information or resource use. |
| Sensitivity | Partial | The analytic grid varies drift, initial error, probe mismatch, readout/probe noise, and measurement budget. Aer varies mismatch and shot count, but not T1/T2 or controller latency independently. |
| Reproduction | Addressed | Analytic and Aer studies have separate configurations, dependency files, output directories, seed manifests, and saved configuration snapshots. |

## Statistical unit and seed blocks

The independent observation used by the paired analyses is one simulated trajectory and its associated probe record, identified by `(condition, seed_block, trial)`. All methods in that pair receive the same target-error trajectory and, for active controllers, the same finite-shot probe record. The bootstrap and paired sign-flip tests operate on one method-minus-reactive difference per trajectory. A collection of method rows for one trajectory is therefore one pair, not several independent observations.

The analytic v0.3 grid has 500 paired trajectories per condition (five seed blocks of 100); Aer v0.2 has 200 per condition (eight blocks of 25). Each trajectory receives its own derived random seed. A seed-block ID selects a non-overlapping range of per-trajectory seeds; the simulator does not inject a shared block-level random disturbance. The current inference consequently treats trajectories as independent draws from the configured simulator and records block means as a stability diagnostic. It does not resample the five or eight blocks as clusters. This assumption is reasonable for the implemented seed schedule, but it is conditional on the pseudo-random generator and model; it is not a claim that five or eight blocks alone establish population-level independence. If a block is instead interpreted as the independent experimental unit, the current confidence intervals and p-values are not block-cluster adjusted, and the number of such units is only five or eight.

## Parameter selection and possible tuning

The guarded predictor uses the saved heuristic values `predictor_window = 16`, `trend_threshold = 2.0`, and `min_trend_observations = 4`. The EMA and Kalman settings are likewise fixed in the experiment configurations. Sweep scripts load these values and evaluate the listed conditions; they do not fit or optimize predictor parameters against each final seed block. The v0.3 analytic sweep and Aer v0.2 sweep use seed-block ranges not used by their earlier saved runs.

There is no preregistration, separate tuning dataset, or dated parameter-freeze record. Earlier exploratory results and manual design choices may have influenced which heuristic values and baselines were carried forward. Accordingly, v0.3 and Aer v0.2 are fresh-seed evaluations relative to the earlier run blocks, but should not be described as formally preregistered confirmatory tests. A stronger confirmatory study should freeze the algorithm/configuration before generating its test seeds and preserve the tuning history separately.

## Comparison fairness and resource accounting

Within each condition, reactive last-probe control and the causal predictors share the same generated trajectory, probe observations, shot count, and checkpoint schedule. The reactive controller intentionally uses only the latest probe reading; predictors process the available history. This compares processing rules under a common measurement record, not controllers with identical internal state.

In Aer, every active controller is assigned the same configured probe-acquisition time and classical feedback delay, and the target idles for that modeled wait. The analytic model does not inject controller latency into the target evolution; its measured Python execution time is host software timing, not a hardware delay model. Aer uses one fixed controller-latency value per configuration and does not charge method-specific compute time.

No compensation uses no probe measurements and incurs no modeled probe wait. Ideal and oracle references have privileged information; in particular, the oracle knows the upcoming target error. These are useful reference bounds, but they are not equal-information or equal-resource controller comparisons and should not be used to claim a fair controller win.

## Sensitivity covered and still open

The analytic v0.3 one-factor-at-a-time grid varies drift speed, initial coherent error, probe-target mismatch, probe-local noise, calibrated readout error, independent white noise, and shots/checkpoint interval. It does not test interactions among those factors. Aer v0.2 adds a graded mismatch sweep and an 8-versus-32-shot comparison.

Aer uses one configured T1/T2 pair for each of the target and probe and one fixed classical-controller latency. Changing the shot count also changes modeled acquisition time, so that comparison is not an isolated latency sweep. No Aer sensitivity sweep over T1/T2, gate duration, or independently varied feedback latency is currently saved. The analytic drift-rate grid does not close those Aer-specific gaps.

## Reproducible model separation

The analytic and Aer tracks use separate JSON configurations and output directories. The Aer track has its own pinned dependency file, saved configuration snapshot, environment record, and per-run seed manifest. Reproduction instructions are in [reproducibility](reproducibility.md); the exact Aer conditions are in [the Aer v0.2 report](aer_noise_v02.md) and the analytic conditions in [the robustness v0.3 report](robustness_v03.md).

## Conclusion

The current artifacts address paired trajectory-level inference, shared probe information among active controllers, and reproducible separation of simulation tracks. They do not fully close the tuning-history question, cluster-level sensitivity, or Aer sensitivity to T1/T2 and independently varied feedback latency. The results should remain described as exploratory simulation evidence until those limitations are resolved.
