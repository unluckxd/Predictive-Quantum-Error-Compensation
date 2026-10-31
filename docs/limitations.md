# Limitations and Failure Analysis

## Evidence boundary

PQEC is a **simulation-validated prototype, not hardware-validated quantum error correction**. The simulator has one unencoded qubit and repeated X-axis rotations. It has no syndrome extraction, error-correcting code, logical encoding, code distance, or hardware run. The results establish behavior only for the stated model and seed schedule.

The model excludes decoherence, leakage, crosstalk, spatially varying pulse errors beyond the explicit probe-mismatch case, calibration drift outside the specified trajectories, measurement backaction on the logical qubit, feedback latency, and the cost of obtaining a hardware state-fidelity estimate. The statevector is used to score fidelity exactly in simulation; fidelity is not inferred from output measurement shots.

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

In this stress case, the logical qubit drifts by 0.01° per cycle, while the probe drifts by 0.03° per cycle and begins 0.20° away from the logical error. Probe-local noise has a 0.05° standard deviation; actual probe readout error is 2%, while the controller assumes 1%.

| Full-budget mean | Reactive last probe | Guarded PQEC |
| --- | ---: | ---: |
| Final state fidelity | 0.845788 | 0.836495 |
| RMS cumulative error | 21.9328° | 22.7294° |

The paired final-fidelity difference is −0.009292 (95% CI [−0.009397, −0.009190], global Holm p=0.0090). The cumulative-error difference is +0.7966° (95% CI [+0.7849°, +0.8080°], global Holm p=0.0090). This is a significant degradation under the tested mismatch model. The controller cannot infer from one probe's history that its drift differs from the logical qubit's drift.

This failure is central to the interpretation: the predictor can forecast the probe's control error, but useful logical compensation requires the probe to remain a valid proxy for the logical control path.

## Measurement budget and implementation caveats

Among reduced-budget settings, 512 shots every 4 cycles (8,704 probe shots per 64-gate sequence) retained global-Holm-supported gains under shared slow drift: final-fidelity difference +8.971e-5 (95% CI [+4.926e-5, +1.363e-4], p=0.0090) and RMS cumulative-error difference −0.0491° (95% CI [−0.0794°, −0.0186°], p=0.0357). The 128-shots-every-4-cycles signal did not survive global adjustment; the other reduced-budget settings showed no supported gain.

At the full budget, the active probe path uses 65 checkpoints × 4,096 shots = 266,240 probe shots and 3,461,120 modeled probe rotations per sequence (13 rotations per shot). These counts exclude any real-device preparation/readout latency. The simulator's Python controller timing is not a hardware feedback-latency measurement.

The randomized-compiling comparison is a simplified sign-randomization baseline. It does not implement full randomized compiling with circuit-level Pauli insertion, compensating compilation, and Pauli-frame tracking. The oracle method has access to the true upcoming logical error and is an unattainable upper bound, not a deployable controller.

## What remains untested

- Generalization to new seeds, devices, qubit pairs, pulse families, and drift spectra.
- Robustness to less frequent and less accurate probe readout on a real platform.
- Probe-to-logical transfer under spatially varying control errors and crosstalk.
- End-to-end benefit after feedback latency, calibration overhead, and output measurement cost.
- Any improvement to encoded logical error rates or fault-tolerant operation.

