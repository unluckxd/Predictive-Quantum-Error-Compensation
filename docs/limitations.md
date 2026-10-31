# Limitations and Failure Analysis

## Evidence boundary

PQEC is a **simulation-validated prototype, not hardware-validated quantum error correction**. The project has an analytic one-qubit simulation and a separate Qiskit Aer noise-model pilot. Both use one unencoded target qubit and repeated X-axis rotations. There is no syndrome extraction, qubit encoding, code distance, or hardware run. Results establish behavior only for the stated models and seed schedules.

The analytic model excludes decoherence, leakage, crosstalk, asymmetric readout, pulse durations, and feedback latency. Aer v0.1/v0.2 add target/probe T1 and T2 channels, per-gate depolarization, asymmetric probe readout, and target idle relaxation during modeled acquisition and controller time. The v0.2 run adds five graded levels of coherent probe-to-target mismatch and more independent seed blocks. Its physical parameters are stylized rather than device-derived; it still excludes leakage, crosstalk, correlated environmental noise, pulse shaping, and uncertainty in probe calibration. State fidelity is scored from the simulator's internal state and is not estimated from hardware readout shots.

## Primary guarded-PQEC results at the full budget

The full-budget comparison uses 4,096 probe shots per checkpoint, a checkpoint every cycle, and 200 paired runs per scenario. The differences below are guarded PQEC minus the reactive last-probe controller. Positive fidelity and negative error differences favor PQEC.

| Scenario | Final-fidelity difference (95% paired CI) | Global Holm p | RMS cumulative-error difference (95% paired CI) | Global Holm p |
| --- | ---: | ---: | ---: | ---: |
| Shared slow drift | +1.858e-5 [1.520e-5, 2.186e-5] | 0.0090 | −0.0743° [−0.0878°, −0.0602°] | 0.0090 |
| Independent white noise | +1.384e-6 [−1.755e-6, 4.831e-6] | 1.0000 | −0.0024° [−0.0085°, +0.0035°] | 1.0000 |
| Probe mismatch | −0.009292 [−0.009397, −0.009190] | 0.0090 | +0.7966° [+0.7849°, +0.8080°] | 0.0090 |

The p-values are adjusted across all 90 budget-sweep hypotheses. The confidence intervals are ordinary paired bootstrap intervals and are not adjusted. The independent-noise result provides no evidence of a predictive gain. The common-drift result is small in absolute final fidelity despite statistical support.

The gate-level metrics do not improve: guarded PQEC has higher RMS gate-angle error in each scenario (slow drift +0.001476°, white noise +0.000706°, mismatch +0.022642°; global Holm p=0.0090 for each). Mean gate fidelity remains high but is slightly lower than the reactive controller. The guarded predictor's forecast MAE is 0.0586° under shared drift, 0.2338° under independent noise, and 0.7456° under probe mismatch. These MAE values are scored against hidden simulator errors and are not deployable measurements.

## Explicit failure: probe mismatch

In this stress case, the target qubit drifts by 0.01° per cycle, while the probe drifts by 0.03° per cycle and begins 0.20° away from the target error. Probe-local noise has a 0.05° standard deviation; actual probe readout error is 2%, while the controller assumes 1%.

| Full-budget mean | Reactive last probe | Guarded PQEC |
| --- | ---: | ---: |
| Final state fidelity | 0.845788 | 0.836495 |
| RMS cumulative error | 21.9328° | 22.7294° |

The paired final-fidelity difference is −0.009292 (95% CI [−0.009397, −0.009190], global Holm p=0.0090). The cumulative-error difference is +0.7966° (95% CI [+0.7849°, +0.8080°], global Holm p=0.0090). This is a significant degradation under the tested mismatch model. The controller cannot infer from one probe's history that its drift differs from the target qubit's drift.

This failure is central to the interpretation: the predictor can forecast the probe's control error, but useful compensation requires the probe to remain a valid proxy for the target qubit's control path.

## Measurement budget and implementation caveats

Among reduced-budget settings, 512 shots every 4 cycles (8,704 probe shots per 64-gate sequence) retained global-Holm-supported gains under shared slow drift: final-fidelity difference +8.971e-5 (95% CI [+4.926e-5, +1.363e-4], p=0.0090) and RMS cumulative-error difference −0.0491° (95% CI [−0.0794°, −0.0186°], p=0.0357). The 128-shots-every-4-cycles signal did not survive global adjustment; the other reduced-budget settings showed no supported gain.

At the full budget, the active probe path uses 65 checkpoints × 4,096 shots = 266,240 probe shots and 3,461,120 modeled probe rotations per sequence (13 rotations per shot). These counts exclude any real-device preparation/readout latency. The simulator's Python controller timing is not a hardware feedback-latency measurement.

The randomized-compiling comparison is a simplified sign-randomization baseline. It does not implement full randomized compiling with circuit-level Pauli insertion, compensating compilation, and Pauli-frame tracking. The oracle method has access to the true upcoming target-qubit error and is an unattainable upper bound, not a deployable controller.

## v0.3 robustness extension

The follow-on sweep adds 35 one-factor-at-a-time conditions, 500 paired runs per condition across five new seed blocks, four simple forecasting baselines, and 630 paired tests with a single global Holm correction. The 512-shots-every-4-cycles reference condition reproduces a guarded-PQEC final-fidelity gain of `+7.764e-5` (95% paired CI `[+5.142e-5, +1.046e-4]`, global `p=0.0126`) and a cumulative-error reduction of `−0.0374°` (CI `[−0.0566°, −0.0183°]`, `p=0.0262`). The RMS gate-angle error is slightly worse by `+0.00363°`. All five seed blocks show the same directions for the two sequence-level effects.

The graded control-transfer study holds probe readout calibrated while ramping the probe's control-error trajectory from 0% to 100% mismatch. At 25%, guarded PQEC is already worse than the reactive baseline on final fidelity (`−0.001911`) and RMS cumulative error (`+0.462°`), with both comparisons globally significant. At 100%, the differences reach `−0.019688` and `+1.380°`. The archived joint control/readout mismatch is retained separately.

This is stronger evidence about robustness within the same analytic model, not a more realistic physical simulation. The full controller comparison, intervals, baselines, block-level effects, and parameter grid are in [the robustness report](robustness_v03.md). The one-factor grid does not test interactions and cannot identify the probe's own transfer mismatch from its measurement history.

## Aer v0.1 noise-model result

The Aer pilot has four conditions, 100 paired trials per condition, and six forecast methods compared with reactive last-probe control. It models finite-shot probe measurements and target waiting time. Across 72 globally Holm-corrected tests, guarded PQEC did not show a supported final-fidelity or cumulative-angle advantage in any condition. Its RMS per-operation coherent-angle residual was higher than reactive control in all four conditions, with global adjusted p = 0.0036.

For the shared-drift, 32-shot condition, guarded PQEC changed final fidelity by −0.001308 (95% paired CI [−0.003515, +0.000701], global p = 1.0000) and RMS cumulative-angle residual by +0.132° (CI [−0.130°, +0.396°], global p = 1.0000). At 50% probe mismatch, the fidelity difference was −0.002188 (CI [−0.004155, −0.000391], global p = 0.6709). Its unadjusted interval is below zero, but the globally adjusted test is not significant.

The reactive controller had nearly the same or better sequence-level outcomes than guarded PQEC in this model. This pilot therefore limits the scope of the analytic result: predictive gains did not automatically transfer after finite-shot probe noise, asymmetric readout, per-gate channels, target/probe parameter differences, and modeled feedback waiting time were combined. Exact parameters and per-trial outputs are in [the Aer report](aer_noise_v01.md).

## Aer v0.2 expanded mismatch study

The expanded Aer run uses 200 paired trials per condition across eight new seed blocks and tests mismatch from 0% to 100%. Guarded PQEC again has no corrected sequence-level advantage in any condition. Its final-fidelity difference becomes significantly negative at the tested 50%, 75%, and 100% mismatch levels after Holm correction over all 144 tests; the 25% result does not pass that threshold. Its RMS per-operation coherent-angle residual is higher than reactive control in all eight conditions (global Holm p = 0.0072 each). The RMS cumulative-angle differences do not survive global correction. Full results and the graded mismatch plot are in [the v0.2 report](aer_noise_v02.md).

## PQEC v0.3 Aer sensitivity

The v0.3 follow-up varies target/probe T1 and T2 independently and tests four feedback-delay settings at a fixed 32-shot probe budget. It again finds no corrected final-fidelity advantage for guarded PQEC over reactive control; per-gate residual is higher in every condition. In the chosen channel and pulse sequence, longer idle relaxation increases active-controller final fidelity, which is consistent with relaxation damping some coherent error between probe checkpoints. The model keeps the coherent-error trajectory indexed by gate cycle, so it does not add drift during the extra wall-clock delay. This result is a model-specific idle-channel effect, not evidence that longer latency benefits a real device. See [the full v0.3 sensitivity report](aer_sensitivity_v03.md).

## What remains untested

- Generalization to new seeds, devices, qubit pairs, pulse families, and drift spectra.
- Robustness to less frequent and less accurate probe readout on a real platform.
- Probe-to-target transfer under spatially varying control errors and crosstalk.
- End-to-end benefit after feedback latency, calibration overhead, and output measurement cost.
- Generalization of the stylized Aer studies to device-derived T1/T2 distributions, pulse durations, readout calibration uncertainty, drift during wall-clock feedback delay, and realistic controller timing.
- Any improvement to encoded-qubit error rates or fault-tolerant operation.

