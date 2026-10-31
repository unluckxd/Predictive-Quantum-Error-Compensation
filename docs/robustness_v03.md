# PQEC Robustness Sweep v0.3

## Scope

This study extends the archived v0.2 comparison with a paired sensitivity grid and four causal forecasting baselines. It uses the same analytic, single-qubit Rx error model. The new data are a simulation robustness check; they are not a Qiskit Aer device-noise result or a hardware validation.

The design is one-factor-at-a-time. Each condition changes one named experimental factor from the shared defaults; the readout sweep keeps the estimator's calibration rate matched to the selected readout rate. It does not test interactions between drift speed, probe mismatch, readout noise, and measurement budget.

## Conditions and repetitions

`configs/robustness_v03.json` freezes 35 conditions:

- Six shared-drift rates from 0 to 0.04 degrees per target cycle.
- Five initial coherent-error amplitudes from 0.5 to 4 degrees.
- Five probe-to-target mismatch scales from 0% to 100%.
- One joint control-and-readout mismatch endpoint matching the archived v0.2 stress case.
- Four probe-local noise standard deviations from 0 to 0.1 degrees.
- Five symmetric, correctly calibrated probe readout bit-flip rates from 0% to 10%.
- Four independent white-noise standard deviations from 0 to 0.4 degrees.
- Five probe-shot/checkpoint-interval combinations, from 64 shots every 8 target cycles to 4,096 shots every cycle.

Every condition has 500 paired trials: 100 trials in each of five new seed blocks (block IDs 2 through 6). Blocks 0 and 1 from v0.2 are not reused. Within a trial, the reactive controller and all predictors see the same generated target trajectory and the same finite-shot probe record.

The graded mismatch scale changes only the probe's control-error trajectory. For these five conditions, probe readout error and calibration are held matched, so the ramp isolates probe-to-target transfer mismatch. A separate sixth condition restores the archived v0.2 readout mismatch (2% actual, 1% assumed) together with the full control mismatch. Thus the original joint stress case remains represented without confounding the graded transfer curve.

## Controllers

All forecasts use measurements strictly earlier than the target cycle. The robustness run compares each method with `reactive_last_probe`:

- `predictive_linear`: rolling linear fit over the configured 16 most recent probe observations.
- `predictive_guarded`: the existing trend-significance heuristic and latest-reading anchor.
- `moving_average`: mean of the most recent 16 readings.
- `exponential_moving_average`: exponential smoothing with a fixed 0.25 per-cycle decay, adjusted for the time between probe checkpoints.
- `two_point_linear`: extrapolation from the latest two readings.
- `kalman_constant_velocity`: a two-state angle-and-drift filter with fixed process parameters and a readout-shot variance approximation.

The simple baseline settings are frozen in the JSON file; they are not tuned separately on each condition. The Kalman filter's probe variance uses a near-mid-fringe approximation for the finite-shot Ramsey readout. This is a heuristic baseline calibration, not a device-calibrated noise model.

## Statistics and seeds

The primary paired metrics are final state fidelity, RMS gate-angle error, and RMS cumulative angle error. Every predictor-minus-reactive difference includes a 95% paired bootstrap percentile interval from 5,000 resamples and a two-sided paired sign-flip randomization p-value from 50,000 sign patterns. Holm correction covers the complete family of 630 tests (35 conditions × 6 predictors × 3 metrics). Intervals are not multiplicity-adjusted. Mean paired effects are also reported separately for each seed block.

Within a condition, resampling indices and sign patterns are shared across the controller/metric comparisons. This keeps the statistical seeds compact and does not change each test's marginal paired bootstrap or sign-flip distribution. The seed manifest records the seed for each condition's resampling sets.

Target and probe trajectories use Python's `random.Random` streams with the documented v0.2 offsets and strides. Probe shot counts use NumPy's `default_rng` binomial sampler. The sweep pins NumPy 2.3.5 in `requirements-robustness.txt` and writes the NumPy version and bit generator to its manifests and per-trial CSV. Reproduction should use the pinned version because changing random-generator implementations can change sampled shot records.

## Results

Differences below are predictor minus reactive last probe. Positive fidelity and negative error differences favor the predictor. The canonical shared-drift condition uses a 2-degree initial error, 0.01-degree-per-cycle drift, 512 shots every 4 cycles, and 500 paired trials. Guarded PQEC improved final fidelity by `+7.764e-5` (95% CI `[+5.142e-5, +1.046e-4]`, global Holm `p=0.0126`) and reduced RMS cumulative error by `−0.0374°` (95% CI `[−0.0566°, −0.0183°]`, `p=0.0262`). Both directions repeated across all five seed blocks. Its RMS gate-angle error was slightly higher by `+0.00363°` (global `p=0.0126`), so the sequence-level improvement does not mean every metric improved.

At that same setting, the direct two-point forecast had a larger final-fidelity gain (`+1.295e-4`, 95% CI `[+6.119e-5, +2.012e-4]`, global `p=0.0244`), but its RMS gate-angle error increased by `+0.144°` and its cumulative-error interval included zero. This comparison does not establish a universal winner among predictors.

The full baseline comparison at the canonical setting is:

| Predictor | Final-fidelity difference (95% CI); global p | RMS cumulative-error difference (95% CI); global p |
| --- | --- | --- |
| Rolling linear | `−6.672e-4` [`−8.708e-4`, `−4.813e-4`]; 0.0126 | `+0.693°` [`+0.555°`, `+0.828°`]; 0.0126 |
| Guarded PQEC | `+7.764e-5` [`+5.142e-5`, `+1.046e-4`]; 0.0126 | `−0.0374°` [`−0.0566°`, `−0.0183°`]; 0.0262 |
| Moving average | `−0.009517` [`−0.010086`, `−0.008981`]; 0.0126 | `+3.302°` [`+3.130°`, `+3.471°`]; 0.0126 |
| Exponential moving average | `−3.437e-4` [`−3.961e-4`, `−2.937e-4`]; 0.0126 | `+0.258°` [`+0.217°`, `+0.300°`]; 0.0126 |
| Two-point linear | `+1.295e-4` [`+6.119e-5`, `+2.012e-4`]; 0.0244 | `−0.0254°` [`−0.0863°`, `+0.0327°`]; 1.0000 |
| Constant-velocity Kalman | `+3.278e-5` [`−4.238e-5`, `+1.073e-4`]; 1.0000 | `+0.0943°` [`+0.0241°`, `+0.1654°`]; 0.7062 |

This table compares different outcome metrics and should not be collapsed into a single ranking. For example, the two-point method's final-state improvement is accompanied by higher per-gate RMS error and no adjusted evidence of lower cumulative error.

The graded control-transfer mismatch produces a clear failure boundary in this configuration. Readout error is matched across these five conditions, so the ramp varies only probe-to-target control-error transfer:

| Control mismatch | Final-fidelity difference | RMS cumulative-error difference | Global Holm p for both |
| ---: | ---: | ---: | ---: |
| 0% | `+8.022e-5` | `−0.0363°` | 0.0126 / 0.1711 |
| 25% | `−0.001911` | `+0.462°` | 0.0126 |
| 50% | `−0.006086` | `+0.758°` | 0.0126 |
| 75% | `−0.012265` | `+1.066°` | 0.0126 |
| 100% | `−0.019688` | `+1.380°` | 0.0126 |

At 0% the final-fidelity gain is supported, while the cumulative-error reduction does not survive global adjustment. From 25% onward, guarded PQEC is worse on both metrics. The separate joint-mismatch condition restores the archived 2% actual versus 1% assumed readout error; its final-fidelity difference is `−0.017596` and RMS cumulative-error difference is `+1.333°` (both global Holm `p=0.0126`).

For the five measurement budgets, guarded PQEC retained global-Holm-supported gains at 512 shots every 4 cycles (8,704 probe shots per sequence) and 4,096 shots every cycle (266,240 shots). The 64-shot/every-8-cycle case significantly worsened cumulative error; the two 128-shot settings did not show a supported sequence-level gain after correction. At 512 shots every 4 cycles, fidelity improved by `+7.764e-5` (95% CI `[+5.161e-5, +1.041e-4]`) and cumulative error changed by `−0.0374°` (CI `[−0.0565°, −0.0179°]`).

The guarded predictor's final-fidelity improvement was supported across the tested 0.01–0.04 degree-per-cycle drift rates and 0.5–4 degree initial errors, but not at 0–0.005 degree-per-cycle drift. Under independent white noise from 0 to 0.4 degrees standard deviation, guarded PQEC showed no supported improvement in final fidelity or RMS cumulative error; its small increase in RMS gate-angle error was globally supported at each noise level. Some unguarded filters changed individual metrics while worsening sequence-level metrics, so these comparisons do not yield a generally superior predictor. At 10% calibrated symmetric probe readout error, the apparent guarded fidelity gain did not survive global correction. These are results within the specified model and parameter grid, not device-level thresholds.

The Monte Carlo sign-flip p-value resolution is `1/50,001 ≈ 2.0e-5`; smaller values are not resolved by this run. The CSV stores unadjusted paired intervals, raw p-values, globally adjusted p-values, and block-specific effects for all conditions and methods.

## Outputs

Run from the project root:

```powershell
python -m pip install -r requirements-robustness.txt
python pqec_robustness_sweep.py --config configs/robustness_v03.json
python plot_robustness.py
```

The output directory is `results/robustness_v03/`:

| File | Contents |
| --- | --- |
| `pqec_robustness_runs.csv` | Every paired trial and controller, with condition parameters and seeds. |
| `pqec_robustness_summary.csv` | Condition-by-controller means, dispersion, resources, and forecast MAE. |
| `pqec_robustness_paired_stats.csv` | Paired effect estimates, confidence intervals, raw p-values, global Holm-adjusted p-values, and per-block effects. |
| `pqec_robustness_seed_manifest.csv` | Target, probe, and probe-measurement seeds for each condition and trial. |
| `pqec_robustness_stats_seed_manifest.csv` | Bootstrap and sign-flip seeds and repetition counts for each condition. |

Figures are written to `figures/robustness_drift_sweep.svg`, `figures/probe_transfer_sweep.svg`, and `figures/measurement_budget_sweep.svg`.

## Limits and next model

The v0.3 analytic sweep includes binomial probe shot noise, a symmetric readout bit-flip channel, target/probe trajectory differences, and measurement-budget variation. It still has no T1/T2 relaxation, leakage, crosstalk, asymmetric readout, pulse-duration effects, or feedback delay. Its exact state-fidelity score remains analytic.

A separate stylized Qiskit Aer study models heterogeneous target/probe T1/T2, per-gate depolarization, asymmetric probe readout, and target idle evolution during serial measurement and controller latency. Its expanded v0.2 run adds 200 paired trials per condition across eight new seed blocks and five mismatch levels. It does not replace the analytic v0.3 data, and it finds no guarded-PQEC sequence-level advantage over reactive control after the global correction. The expanded design and outputs are documented in [the Aer v0.2 report](aer_noise_v02.md); the initial Aer run remains available in [the v0.1 report](aer_noise_v01.md). Neither simulation track establishes hardware performance.
