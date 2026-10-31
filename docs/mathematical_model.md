# Mathematical Model

## Logical operation and residual error

The target gate in each of $N=64$ cycles is

$$
U_i^{\rm ideal}=R_x(\theta),\qquad \theta=\pi/2.
$$

Let $\delta_i$ be the actual coherent angle error in cycle $i$, and let $c_i$ be the controller's compensation. The commanded angle is $\theta-c_i$; the realized operation and residual error are

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

Final state fidelity and gate fidelity answer different questions: the former depends on the accumulated residual angle, while the latter is averaged per gate. `rms_gate_error_deg` is the RMS of the per-cycle residuals. `prediction_mae_deg` is the mean absolute forecast error against the simulator's hidden upcoming logical error; it is a simulation-only diagnostic and is unavailable to the controller. Probe-shot and modeled probe-rotation counts are the resource-overhead measures in the result files.

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

## Drift and noise scenarios

Angles below are in degrees; $i$ is the zero-based logical cycle. The base offset is 2 degrees in all conditions.

| Scenario | Logical error | Probe error | Purpose |
| --- | --- | --- | --- |
| Shared slow drift | $2+0.01i+\epsilon_i$, with $\epsilon_i\sim\mathcal{N}(0,0.005^2)$ | Same trajectory as the logical qubit | Tests the favorable shared-drift assumption |
| Independent white noise | $2+\epsilon_i$, with $\epsilon_i\sim\mathcal{N}(0,0.2^2)$ | Independently generated noise from the same distribution | Tests whether prediction helps without correlated probe information |
| Probe mismatch | $2+0.01i+\epsilon_i$ | $2+0.20+0.03i+\eta_i$, with $\eta_i\sim\mathcal{N}(0,0.05^2)$ | Stress-tests offset, drift-rate, and local-noise mismatch |

Logical jitter in the mismatch case uses the same 0.005-degree standard deviation as the shared-drift case. The mismatch case also uses 2% actual probe readout error while the correction assumes 1%. Other modeled cases use 1% actual and assumed readout error.

## Prediction rules

For each logical pulse, only probe observations from earlier cycles are available. The reactive rule uses the latest such estimate. The predictive rules fit a least-squares line to the most recent $W=16$ observations and forecast at the target cycle.

For guarded PQEC, fewer than 4 observations force the fitted slope to zero. Otherwise, with fitted slope $b$, its standard error $s_b$, and threshold $\tau=2$, the trend score is $q=|b|/s_b$. If $q\leq\tau$, the slope is set to zero; otherwise it is shrunk to

$$
b'=b\left(1-\left(\frac{\tau}{q}\right)^2\right).
$$

The next-cycle forecast is anchored to the newest observed value: $\widehat{\delta}_{i}=\widehat{\delta}_{\rm latest}+b'(i-i_{\rm latest})$. Therefore, when the trend is suppressed, guarded PQEC reduces to the reactive last-probe estimate.

## Paired inference

There are 200 paired trajectories per scenario (2 seed blocks × 100 trials). Controller comparisons use the same trajectory and probe record. The CSVs report the mean paired difference and a 95% percentile bootstrap interval based on 5,000 resamples. Two-sided paired sign-flip tests use 10,000 random permutations. The budget-sweep p-values are Holm-adjusted together across 90 hypotheses (5 budgets × 3 scenarios × 3 metrics × 2 predictive controllers). Reported bootstrap intervals are not multiplicity-adjusted.

Positive differences favor PQEC for final state fidelity. Negative differences favor PQEC for RMS gate error and RMS cumulative error. The main README and [limitations](limitations.md) report the primary guarded-versus-reactive outcomes.

