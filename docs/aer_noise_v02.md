# Qiskit Aer Noise-Model Study v0.2

## Scope

This expanded Aer study increases the paired sample size and tests a graded probe-to-target control mismatch. It uses the same stylized one-qubit density-matrix noise model as [Aer v0.1](aer_noise_v01.md), with heterogeneous target/probe T1 and T2, per-gate depolarization, asymmetric probe readout, finite-shot measurement, and target idle evolution during serial probe acquisition and classical feedback.

The noise parameters are project-selected simulation inputs. They are not copied from a device calibration or an external dataset. The study is simulator-only and does not establish hardware benefit, encoded-qubit error correction, or a general device threshold.

## Expanded design

Each of eight conditions has 200 paired trajectories: 25 trials in each of eight seed blocks, IDs 12–19. These blocks do not overlap the five v0.1 blocks (IDs 7–11). Every controller within a trajectory receives the same target-error trajectory and the same probe-measurement record.

| Condition | Probe shots per checkpoint | Control mismatch scale |
| --- | ---: | ---: |
| Shared slow drift | 32 | 0% |
| Shared slow drift | 8 | 0% |
| Probe mismatch | 32 | 0% |
| Probe mismatch | 32 | 25% |
| Probe mismatch | 32 | 50% |
| Probe mismatch | 32 | 75% |
| Probe mismatch | 32 | 100% |
| Independent white noise | 32 | 0% |

The 0–100% scale multiplies the probe-only coherent offset and additional drift-rate term. At 0%, target and probe share the same modeled coherent control trajectory. Their T1/T2, gate depolarization, readout, and measurement records still differ according to the configured probe/target channels; “0% mismatch” therefore means no added coherent control mismatch, not identical devices.

The experiment compares no compensation, reactive last-probe control, rolling linear prediction, guarded PQEC, moving average, exponential moving average, two-point prediction, and a constant-velocity Kalman filter. The controller sees only finite-shot probe counts and uses the exact stationary calibration of the configured probe channel. Calibration uncertainty is not included.

Eight conditions × six predictors × three metrics yield 144 paired tests. Each comparison uses 5,000 paired bootstrap resamples for an unadjusted 95% percentile interval and 20,000 sign flips for its paired test. Holm correction is applied once across all 144 tests. The Monte Carlo p-value resolution is 1/20,001. The run saves 12,800 per-method rows and 1,600 trajectory/seed records.

## Guarded-PQEC results

Every effect is guarded PQEC minus reactive last-probe control. Positive fidelity and negative angle-error differences favor PQEC. Confidence intervals are paired and unadjusted; p-values use global Holm correction.

| Condition | Final-fidelity difference (95% CI) | Holm p | RMS cumulative-angle difference (95% CI) | Holm p |
| --- | ---: | ---: | ---: | ---: |
| Shared drift, 32 shots | −0.002031 [−0.004199, −0.000155] | 1.0000 | +0.062° [−0.142°, +0.291°] | 1.0000 |
| Shared drift, 8 shots | −0.002093 [−0.006592, +0.002034] | 1.0000 | +0.223° [−0.087°, +0.556°] | 1.0000 |
| 0% control mismatch | −0.003017 [−0.005577, −0.000660] | 0.4603 | +0.241° [−0.025°, +0.524°] | 1.0000 |
| 25% control mismatch | −0.004144 [−0.006989, −0.001761] | 0.0552 | +0.302° [+0.031°, +0.625°] | 1.0000 |
| 50% control mismatch | −0.005097 [−0.008166, −0.002442] | 0.0085 | +0.412° [+0.103°, +0.752°] | 0.3672 |
| 75% control mismatch | −0.005570 [−0.008560, −0.002931] | 0.0072 | +0.435° [+0.133°, +0.791°] | 0.2497 |
| 100% control mismatch | −0.006615 [−0.009666, −0.003871] | 0.0072 | +0.494° [+0.181°, +0.847°] | 0.0943 |
| Independent white noise | −0.000058 [−0.001672, +0.001512] | 1.0000 | −0.112° [−0.308°, +0.079°] | 1.0000 |

Guarded PQEC has no supported sequence-level advantage over reactive control in any condition. After the 144-test correction, final-state fidelity is lower at 50%, 75%, and 100% mismatch; the 25% result is close to, but does not cross, the adjusted significance threshold. The cumulative-angle differences all have adjusted p-values above 0.05.

The third metric, RMS per-operation coherent-angle residual, is higher for guarded PQEC in all eight conditions. Each of these tests has global Holm p = 0.0072. This agrees with the sequence-level results: under this Aer model, the predictor is not improving control accuracy over the reactive measurement baseline.

The baselines are not interchangeable. Exponential moving average has a positive final-fidelity difference at 50%, 75%, and 100% mismatch after the global correction, but its cumulative-angle differences do not show a corrected gain. No method dominates across all conditions and endpoints. The CSV contains all baseline effects, intervals, p-values, and seed-block means.

![Guarded PQEC effects across the five Aer probe-mismatch levels](../figures/aer_noise_v02_mismatch.svg)

See [the full final-fidelity comparisons](../figures/aer_noise_v02_final_fidelity.svg) and [the cumulative-angle comparisons](../figures/aer_noise_v02_cumulative_error.svg) for all six forecasting baselines across all eight conditions.

## Interpretation and limits

Increasing the number of seed blocks and adding intermediate mismatch levels did not reveal a regime in this noise model where guarded PQEC outperformed the reactive baseline. Instead, the graded mismatch sweep shows a growing negative fidelity estimate, with globally supported degradation beginning at the tested 50% level. The 25% result is not significant after correction, so this study does not identify a precise mismatch threshold.

This is evidence about the chosen simulation, not a claim that the same threshold applies to hardware. The model has no leakage, crosstalk, correlated environmental noise, pulse shaping, device-derived parameters, calibration uncertainty, or measured end-to-end controller latency. The exact final density matrix is used only for offline scoring; a controller does not access the target state.

## Reproduction

Use the pinned Aer environment and run:

```powershell
python -m venv .venv-aer
.\.venv-aer\Scripts\Activate.ps1
python -m pip install -r requirements-aer.txt

python pqec_aer_sweep.py --config configs/aer_noise_v02.json
python plot_aer_results.py --results-dir results/aer_noise_v02 --output-prefix aer_noise_v02
python plot_aer_mismatch.py
python -m unittest discover -s tests -v
```

The complete saved run is under `results/aer_noise_v02/`:

| File | Contents |
| --- | --- |
| `pqec_aer_runs.csv` | Per-method trial scores, probe records, model parameters, and resource timing |
| `pqec_aer_summary.csv` | Condition-by-method means and dispersion |
| `pqec_aer_paired_stats.csv` | All 144 paired tests, intervals, raw and Holm-adjusted p-values, and seed-block effects |
| `pqec_aer_seed_manifest.csv` | All 1,600 trajectory, probe-Aer, and target-Aer seed records |
| `pqec_aer_probe_calibration.csv` | Configured Aer probe-response calibration |
| `pqec_aer_config_snapshot.json` | Exact configuration used for the run |
| `pqec_aer_environment.json` | Python, Qiskit, Aer, NumPy, Matplotlib versions, and runtime | 
