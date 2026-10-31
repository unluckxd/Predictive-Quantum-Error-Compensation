# Qiskit Aer Noise-Model Pilot v0.1

## Scope

This pilot transfers the probe-based controller comparison from the analytic model into Qiskit Aer. It adds thermal relaxation, per-gate depolarization, asymmetric probe readout error, different target/probe noise parameters, and target idling while serial probe shots and controller processing complete.

The parameter values are stylized inputs selected for this simulation. They are not copied from a device calibration or an external dataset, and they are not a claim of hardware realism. The pilot is simulation-only; it does not establish a hardware benefit or encoded-qubit error correction.

## Device-noise model

Each circuit is simulated with Aer density-matrix evolution. Target and probe channels are configured independently:

| Qubit | T1 | T2 | Single-qubit gate duration | Depolarizing probability per gate |
| --- | ---: | ---: | ---: | ---: |
| Target | 500 μs | 300 μs | 0.025 μs | 0.0010 |
| Auxiliary probe | 400 μs | 250 μs | 0.025 μs | 0.0015 |

Thermal-relaxation channels are applied after each modeled gate. The probe readout channel is asymmetric: P(recorded 1 | true 0) = 2% and P(recorded 0 | true 1) = 4%. Probe circuits prepare $|+y\rangle$, apply five $R_x(90^\circ+\delta)$ pulses, rotate back from the Y basis, and use finite-shot measurement counts.

The controller decodes counts through a 401-point response calibration generated from the configured Aer probe model, including the assumed readout matrix. This gives the controller an exact stationary calibration of its own simulated probe path. The pilot does not add calibration-parameter uncertainty or readout-calibration mismatch; that is an optimistic assumption.

Probe acquisition is treated as serial. Each probe shot takes 0.925 μs in the configured timing model: reset, nine single-qubit gates, and readout. The target idles while each non-final checkpoint is acquired and processed, using the configured target T1/T2 channel for that interval. A 32-shot checkpoint therefore gives 31.6 μs of target wait, including 2 μs of controller latency; an 8-shot checkpoint gives 9.4 μs. The startup read is before the target sequence and does not change the initial $|0\rangle$ target state. No final checkpoint is taken when it cannot affect another target operation.

The final target density matrix is scored against the ideal 61-pulse state using $F=\langle\psi_{\mathrm{ideal}}|\rho|\psi_{\mathrm{ideal}}\rangle$. This exact state access is an offline simulator score, not a measurement available to a controller or a hardware fidelity estimate. The angular-residual metrics are separate control diagnostics and do not include T1/T2 or depolarizing-channel errors.

## Conditions and paired design

Each condition has 100 paired trials across five seed blocks (20 trials per block). The target trajectory and Aer-generated probe record are shared by the reactive controller and all forecasting methods within a trial.

| Condition | Drift / transfer model | Probe shots per checkpoint | Probe acquisition per sequence | Target idle per sequence |
| --- | --- | ---: | ---: | ---: |
| Shared drift, 32 shots | Matched target/probe slow drift | 32 | 236.8 μs | 221.2 μs |
| Shared drift, 8 shots | Matched target/probe slow drift | 8 | 59.2 μs | 65.8 μs |
| 50% probe mismatch | Probe has half the configured offset and drift-rate difference | 32 | 236.8 μs | 221.2 μs |
| Independent white noise | Target and probe errors are sampled independently | 32 | 236.8 μs | 221.2 μs |

All conditions use 61 target operations, five repeated probe rotations, and a checkpoint interval of eight target cycles. The shared slow-drift trajectory starts at 1.2° with a 0.025°/cycle trend and small random-walk innovations. The mismatch condition adds a scaled 0.2° probe offset and 0.015°/cycle probe-versus-target drift difference. The independent-noise condition uses 0.3° standard deviation around the same initial offset.

The compared methods are no compensation, reactive last-probe compensation, rolling linear prediction, guarded PQEC, moving average, exponential moving average, two-point prediction, and a constant-velocity Kalman filter. The no-compensation baseline does not run probe measurements and incurs no probe-acquisition wait. Reactive and forecasting controllers use the same measured probe record and the same target-wait schedule.

## Statistical analysis

The primary paired comparisons are each forecasting method minus the reactive controller for final state fidelity, RMS per-operation coherent-angle residual, and RMS cumulative coherent-angle residual. The report stores 3,200 per-method trial rows and 400 seed-manifest rows.

Each paired difference has a 95% percentile bootstrap interval from 5,000 resamples and a two-sided sign-flip test using 20,000 random sign patterns. Holm correction covers the complete family of 72 comparisons (4 conditions × 6 predictors × 3 metrics). Bootstrap intervals are not multiplicity-adjusted; the Monte Carlo sign-flip p-value resolution is 1/20,001.

## Guarded-PQEC results

Positive fidelity differences and negative angular-residual differences favor guarded PQEC. Every comparison below is guarded PQEC minus reactive last probe.

| Condition | Final-fidelity difference (95% paired CI) | Global Holm p | RMS cumulative-angle difference (95% paired CI) | Global Holm p |
| --- | ---: | ---: | ---: | ---: |
| Shared drift, 32 shots | −0.001308 [−0.003515, +0.000701] | 1.0000 | +0.132° [−0.130°, +0.396°] | 1.0000 |
| Shared drift, 8 shots | +0.000729 [−0.003414, +0.005677] | 1.0000 | +0.105° [−0.319°, +0.563°] | 1.0000 |
| 50% probe mismatch | −0.002188 [−0.004155, −0.000391] | 0.6709 | +0.181° [−0.069°, +0.466°] | 1.0000 |
| Independent white noise | −0.003505 [−0.007214, −0.000298] | 0.9570 | +0.057° [−0.244°, +0.401°] | 1.0000 |

No guarded-PQEC sequence-level comparison survives the global correction. The point estimates do not show a consistent direction: the 8-shot shared-drift estimate is slightly positive, while the other fidelity estimates are negative. Under 50% mismatch and independent noise, the unadjusted fidelity intervals are below zero, but the global Holm-adjusted tests do not support a definitive degradation claim.

Guarded PQEC has higher RMS per-operation coherent-angle residual than the reactive controller in all four conditions. The increases range from +0.029° to +0.053°; all four tests survive the 72-test Holm correction (global p = 0.0036). The sequence-level metrics do not improve alongside that gate-level metric.

The unguarded rolling-linear and two-point predictors often extrapolate measurement noise into large command errors. At 32 shots, their final-fidelity differences are −0.0734 and −0.0129, respectively; both survive the global correction. Exponential moving average is close to the reactive method on the reported sequence-level metrics, but it does not establish a corrected advantage in this pilot.

## Interpretation

This Aer pilot does not show that guarded PQEC improves over the reactive last-probe controller under the configured noisy model. It does show that the probe-readout calibration, finite shots, different probe/target characteristics, target waiting time, and target decoherence can be exercised together in a reproducible simulator. The main result is a useful boundary: the analytic-model gain does not automatically carry over when shot noise and serial feedback time are added.

The 8-shot setting shortens target idling but makes the probe estimate noisier. The 32-shot setting provides more probe information but imposes 221.2 μs of modeled target wait per sequence. These results are specific to the chosen pulse timing, drift, T1/T2, and shot schedule; they should not be read as general device thresholds.

The model still omits leakage, crosstalk, correlated environmental noise, pulse shaping, calibration uncertainty, and device-specific gate durations. The model's exact density-matrix scoring also avoids the measurement cost and uncertainty of estimating target fidelity on hardware.

## Reproduction and outputs

Use a separate environment for this pinned Aer run because the analytic v0.3 results use a different pinned NumPy version:

```powershell
python -m venv .venv-aer
.\.venv-aer\Scripts\Activate.ps1
python -m pip install -r requirements-aer.txt

python pqec_aer_sweep.py --config configs/aer_noise_v01.json
python plot_aer_results.py
python -m unittest discover -s tests -v
```

The run configuration freezes the model, conditions, seeds, and statistics. The output directory is `results/aer_noise_v01/`:

| File | Contents |
| --- | --- |
| `pqec_aer_runs.csv` | Per-trial, per-method density-matrix scores, shared probe records, noise parameters, and resource timing |
| `pqec_aer_summary.csv` | Condition-by-method means and dispersion |
| `pqec_aer_paired_stats.csv` | All paired differences, bootstrap intervals, raw and globally corrected p-values, and seed-block effects |
| `pqec_aer_seed_manifest.csv` | Trajectory, probe-Aer, target-Aer, and dependency-version records |
| `pqec_aer_probe_calibration.csv` | Expected noisy probe response used by the controller estimator |
| `pqec_aer_config_snapshot.json` | Exact configuration used for the run |
| `pqec_aer_environment.json` | Python and library versions and elapsed runtime |

The figures are `figures/aer_noise_final_fidelity.svg` and `figures/aer_noise_cumulative_error.svg`.

An expanded follow-up preserves these data and tests 200 paired trials across eight new seed blocks plus a 0–100% mismatch sweep. See [Aer v0.2](aer_noise_v02.md) for the later run and its results.
