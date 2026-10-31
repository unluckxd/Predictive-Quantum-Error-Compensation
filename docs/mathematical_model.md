# Mathematical Model

## Target operation and residual error

The target operation in each of $N=64$ cycles is

$$
U_i^{\rm ideal}=R_x(\theta),\qquad \theta=\pi/2.
$$

Let $\delta_i$ be the target-qubit's actual coherent angle error in cycle $i$, and let $c_i$ be the controller's compensation. The commanded angle is $\theta-c_i$; the realized operation and residual error are

$$
U_i=R_x(\theta+\delta_i-c_i),\qquad e_i=\delta_i-c_i.
$$

All modeled ideal and error rotations use the X axis and commute. The accumulated angle error after cycle $j$ is $E_j=\sum_{i=1}^{j}e_i$. For the modeled $|0\rangle$ input, the prefix state fidelity is $\cos^2(E_j/2)$, and the final state fidelity is the squared overlap of the ideal and realized statevectors. The controller does not observe either statevector.

The reported mean single-gate average fidelity for a residual X rotation is

$$
F_{\rm gate}(e_i)=\frac{2+\cos(e_i)}{3},
$$

and the reported RMS cumulative angle error is

$$
E_{\rm RMS}=\sqrt{\frac{1}{N}\sum_{j=1}^{N}E_j^2}.
$$

Final state fidelity and gate fidelity answer different questions: the former depends on the accumulated residual angle, while the latter is averaged per gate. `rms_gate_error_deg` is the RMS of the per-cycle residuals. `prediction_mae_deg` is the mean absolute forecast error against the simulator's hidden upcoming target-qubit error; it is a simulation-only diagnostic and is unavailable to the controller. Probe-shot and modeled probe-rotation counts are the resource-overhead measures in the result files.

## Auxiliary probe measurement

The probe is prepared in $|+y\rangle$, then receives $m$ identical rotations $R_x(\pi/2+\delta_p)$. For $m=4k+1$, the probability of outcome 0 after Y-basis readout is

$$
P(0\mid\delta_p)=\frac{1-\sin(m\delta_p)}{2}.
$$

With $n_s$ shots, the sampled zero fraction is used in the estimator. The simulation models symmetric readout flips with probability $r$, so

$$
P_{\rm observed}(0)=r+(1-2r)P(0\mid\delta_p).
$$

The controller applies the configured readout calibration $r_c$, clips the corrected probability into $[0,1]$, and computes

$$
\widehat{\delta}_p=-\frac{1}{m}\arcsin\left(2\,\widehat{P}_{\rm corrected}(0)-1\right).
$$

The run configuration uses $m=13$. The signed estimator is unambiguous only while the probe stays within its modeled Ramsey range; the simulator checks this precondition. It also verifies the basis-rotated measurement against a direct Y expectation and the analytic expression.

## v0.2 reference drift and noise scenarios

Angles below are in degrees; $i$ is the zero-based target-operation cycle. The reference base offset is 2 degrees.

| Scenario | Target-qubit error | Probe error | Purpose |
| --- | --- | --- | --- |
| Shared slow drift | $2+0.01i+\epsilon_i$, with $\epsilon_i\sim\mathcal{N}(0,0.005^2)$ | Same trajectory as the target qubit | Tests the favorable shared-drift assumption |
| Independent white noise | $2+\epsilon_i$, with $\epsilon_i\sim\mathcal{N}(0,0.2^2)$ | Independently generated noise from the same distribution | Tests whether prediction helps without correlated probe information |
| Probe mismatch | $2+0.01i+\epsilon_i$ | $2+0.20+0.03i+\eta_i$, with $\eta_i\sim\mathcal{N}(0,0.05^2)$ | Stress-tests offset, drift-rate, and local-noise mismatch |

Target-qubit jitter in the mismatch case uses the same 0.005-degree standard deviation as the shared-drift case. The mismatch case also uses 2% actual probe readout error while the correction assumes 1%. Other modeled cases use 1% actual and assumed readout error.

## v0.3 robustness variations

The robustness config varies one experimental factor at a time around a shared 2-degree initial error, 0.01-degree-per-cycle shared drift, 0.005-degree target jitter, 512 probe shots, and one checkpoint every 4 target cycles. It includes drift rates of 0, 0.0025, 0.005, 0.01, 0.02, and 0.04 degrees/cycle; initial-error magnitudes of 0.5–4 degrees; probe-local noise from 0–0.1 degrees; calibrated symmetric readout flips from 0–10%; independent white noise from 0–0.4 degrees; and five shot/interval combinations.

For the isolated control-transfer sweep, the logical target error is $\delta_i^T$ and an independently generated probe candidate is $\delta_i^P$. The probe trajectory is

$$
\delta_i^{\rm probe}=(1-\lambda)\delta_i^T+\lambda\delta_i^P,\qquad \lambda\in\{0,0.25,0.5,0.75,1\}.
$$

Actual and assumed probe readout error are held at the matched 1% level for this ramp. A separate joint-mismatch condition uses $\lambda=1$, 2% actual readout error, and 1% assumed calibration to retain the v0.2 failure case. The readout-mismatch scale is independent of the control-transfer scale in the simulator.

## Prediction rules

For each target operation, only probe observations from earlier cycles are available. The reactive rule uses the latest such estimate. The predictive rules fit a least-squares line to the most recent $W=16$ observations and forecast at the target cycle.

For guarded PQEC, fewer than 4 observations force the fitted slope to zero. Otherwise, with fitted slope $b$, its standard error $s_b$, and threshold $\tau=2$, the trend score is $q=|b|/s_b$. If $q\leq\tau$, the slope is set to zero; otherwise it is shrunk to

$$
b'=b\left(1-\left(\frac{\tau}{q}\right)^2\right).
$$

The next-cycle forecast is anchored to the newest observed value: $\widehat{\delta}_{i}=\widehat{\delta}_{\rm latest}+b'(i-i_{\rm latest})$. Therefore, when the trend is suppressed, guarded PQEC reduces to the reactive last-probe estimate.

The v0.3 simple baselines use fixed settings from the config:

- Moving average predicts the mean of the latest 16 readings.
- Exponential moving average uses per-cycle $\alpha=0.25$; across a gap of $\Delta t$ cycles, the applied update weight is $1-(1-\alpha)^{\Delta t}$.
- Two-point linear prediction extrapolates the slope between the latest two readings, accounting for their cycle separation.
- The constant-velocity Kalman predictor tracks angle and drift rate with a white-acceleration process model. Its finite-shot measurement variance uses the near-mid-fringe approximation

$$
R_{\rm shot}\approx\frac{1}{m^2 n_s(1-2r_c)^2},
$$

with the configured probe-local variance added in the mismatch scenario. This is a baseline approximation; it is not fitted to hardware calibration data.

## Paired inference

There are 200 paired trajectories per scenario (2 seed blocks × 100 trials). Controller comparisons use the same trajectory and probe record. The CSVs report the mean paired difference and a 95% percentile bootstrap interval based on 5,000 resamples. Two-sided paired sign-flip tests use 10,000 random permutations. The budget-sweep p-values are Holm-adjusted together across 90 hypotheses (5 budgets × 3 scenarios × 3 metrics × 2 predictive controllers). Reported bootstrap intervals are not multiplicity-adjusted.

The v0.3 robustness grid adds 500 paired trials per condition (5 new seed blocks × 100 trials), four simple forecasting baselines, 35 conditions, and 630 paired hypotheses. It uses 5,000 bootstrap resamples and 50,000 paired sign flips per condition; Holm adjustment covers the full 630-test family. Probe-shot samples use NumPy 2.3.5's recorded random generator, while target/probe trajectories retain the Python `random.Random` seed schedule. See [the v0.3 robustness report](robustness_v03.md) and the seed manifests for exact values.

## Aer v0.1/v0.2 noisy-channel model

The Aer model uses the same commanded target rotation and residual-angle definitions, but evolves density matrices through per-gate noise channels. After each target Rx gate, Aer applies a qubit-specific thermal-relaxation channel set by T1/T2 and a depolarizing channel. The target and probe have different configured T1/T2 and depolarizing probabilities. These parameters are stylized and are not taken from a particular device. Version v0.2 reuses this model while expanding seed blocks and sweeping probe-target error mismatch.

The probe's count probability is obtained from an Aer response calibration rather than the ideal closed form above. The response curve includes the probe's own per-gate channels and the asymmetric readout matrix

$$
M=\begin{bmatrix}
1-p_{1|0} & p_{1|0} \\
p_{0|1} & 1-p_{0|1}
\end{bmatrix},
$$

where $p_{1|0}=P(\mathrm{recorded}\ 1\mid\mathrm{true}\ 0)$ and $p_{0|1}=P(\mathrm{recorded}\ 0\mid\mathrm{true}\ 1)$. The configured values are 2% and 4%, respectively. A 401-point curve from −8° to +8° is generated with the same assumed noise parameters used in the shot circuits, then inverted to decode each finite-shot observation. Exact knowledge of this response is an optimistic calibration assumption.

For $m=5$ probe rotations, the modeled duration of one probe shot is

$$
t_{\mathrm{shot}}=t_{\mathrm{reset}}+(m+4)t_{\mathrm{gate}}+t_{\mathrm{readout}}=0.925\ \mu\mathrm{s}.
$$

At a checkpoint with $n_s$ shots, the target waits for

$$
\tau_{\mathrm{idle}}=n_s t_{\mathrm{shot}}+t_{\mathrm{controller}}.
$$

The target idle channel is applied before the next target operation. At 32 shots this is 31.6 μs per active checkpoint; at 8 shots it is 9.4 μs. Each run has seven active wait intervals because a final probe read after the last target operation cannot affect the output. The startup probe occurs while the target is in its initial $|0\rangle$ state and adds no simulated target idle channel.

The target output is a density matrix $\rho$ and is scored against the ideal output state $|\psi_{\mathrm{ideal}}\rangle$ as

$$
F=\langle\psi_{\mathrm{ideal}}|\rho|\psi_{\mathrm{ideal}}\rangle.
$$

This uses simulator state for offline evaluation; no target-state data enters the controller. The Aer pilot's complete configuration and results are in [the noise-model report](aer_noise_v01.md).

Positive differences favor PQEC for final state fidelity. Negative differences favor PQEC for RMS gate error and RMS cumulative error. The main README and [limitations](limitations.md) report the primary guarded-versus-reactive outcomes.

