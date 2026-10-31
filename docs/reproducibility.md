# Reproducibility

## Environment and commands

Use Python 3.10 or later from the repository root. The archived v0.2 data use the built-in analytic one-qubit state-vector fallback, which needs no third-party packages. Qiskit is listed in `requirements.txt` as an optional simulation backend; when installed, the code automatically selects Qiskit's `Statevector`. Scientific figures use Matplotlib, pinned in `requirements-plotting.txt`, `requirements-robustness.txt`, and `requirements-aer.txt` for their respective runs.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python pqec_single_qubit.py --config configs/full_run_v02.json
python pqec_budget_sweep.py --config configs/budget_sweep_v02.json
python -m pip install -r requirements-plotting.txt
python plot_results.py

python -m pip install -r requirements-robustness.txt
python pqec_robustness_sweep.py --config configs/robustness_v03.json
python plot_robustness.py

python -m unittest discover -s tests -v
```

The JSON parameters act as defaults; explicit command-line arguments override them. Running the full sweep regenerates the five per-budget CSV triplets, combined summary/statistics, and both seed manifests. To regenerate figures from the saved sweep CSVs only, run `python plot_results.py`.

To run the optional Qiskit backend, install it before starting the scripts with `python -m pip install -r requirements.txt`. The numerical model is the same, but the `statevector_backend` field in the CSVs will identify the selected backend.

## Frozen configurations

- [`full_run_v02.json`](../configs/full_run_v02.json): 64 target-operation cycles, 100 trials in each of two seed blocks, 4,096 shots per probe checkpoint, one checkpoint every cycle.
- [`budget_sweep_v02.json`](../configs/budget_sweep_v02.json): the same seed schedule and trajectories evaluated at five shot-count/checkpoint-interval settings.
- [`robustness_v03.json`](../configs/robustness_v03.json): 35 one-factor-at-a-time conditions, 100 trials in each of five new seed blocks (IDs 2–6), six predictors plus a reactive baseline, 5,000 paired bootstrap resamples, and 50,000 sign flips per condition.
- [`aer_noise_v01.json`](../configs/aer_noise_v01.json): four Qiskit Aer conditions, 100 paired trials in each of five new seed blocks (IDs 7–11), a reactive baseline and six predictors, 5,000 bootstrap resamples, and 20,000 sign flips per comparison.
- [`aer_noise_v02.json`](../configs/aer_noise_v02.json): eight Qiskit Aer conditions, 200 paired trials per condition in eight non-overlapping seed blocks (IDs 12–19), including a five-level 0–100% control-mismatch sweep, 5,000 bootstrap resamples, and 20,000 sign flips per comparison.

The configurations state their experiment ID, claim scope, base seed, seed offsets/strides, statistics seed formula, and model parameters. The saved v0.2 CSVs were produced with the analytic fallback. The historical v0.1 Qiskit CSV files are separate and should not be combined with the v0.2 tables. The v0.3 sweep uses the analytic state model; the separately configured Aer noise-model pilot is not a hardware result.

## Seed schedule

For scenario index $s$, seed block $b$, and trial $t$, the trajectory seed is

```text
20261031 + scenario_offset[s] + b*1000003 + t*1009
```

Scenario offsets are 0 for `slow_drift`, 100003 for `white_noise`, and 200003 for `probe_mismatch`. Derived per-run seeds are:

| Random stream | Seed |
| --- | --- |
| Target-qubit trajectory | trajectory seed |
| Probe trajectory | trajectory seed + 5,000,117 |
| Probe shot/readout sampling | trajectory seed + 700,001 |
| Randomized-compiling signs | trajectory seed + 900,001 + repeat index × 97 |

The controller comparison uses paired trajectories: methods within one scenario/block/trial share the same target-qubit trajectory and probe record. `results/experiment_seed_manifest.csv` lists the 600 unique scenario/block/trial records and their derived per-run seeds.

For scenario index $s$, metric index $m$, and predictor index $p$ (linear=0, guarded=1), the statistics seeds are

```text
bootstrap seed   = 20261031 + s*10007 + m*97409 + p*1000003
permutation seed = bootstrap seed + 2000003
```

The metric order is final state fidelity, RMS gate error, RMS cumulative error; the scenario order is slow drift, white noise, probe mismatch. `results/statistical_seed_manifest.csv` writes out every scenario/metric/predictor combination, along with the bootstrap and permutation repetition counts. The same statistics seeds are reused for the corresponding test at each measurement budget.

The v0.3 trajectory seed uses that same formula, with seed-block IDs 2–6. Its probe measurement seed is passed to `numpy.random.default_rng` and sampled with NumPy's binomial generator. `requirements-robustness.txt` pins NumPy 2.3.5; the run and seed manifests also record the NumPy version and bit generator. The probe measurement stream therefore differs from the v0.2 Python `random.Random` stream and should be reproduced with the pinned dependency.

For v0.3 condition index $c$ starting at 0, the statistics seeds are

```text
bootstrap seed   = 20261031 + 4000000019 + c*1000003
permutation seed = bootstrap seed + 2000003
```

Each condition shares its bootstrap-index and sign-pattern matrices across the 18 paired comparisons within that condition. The sign-flip p-value resolution is $1/50001 \approx 2.0 \times 10^{-5}$. Holm correction is applied once across all 35 conditions × 6 predictors × 3 metrics (630 tests); the paired bootstrap confidence intervals are unadjusted.

## Saved outputs

| Path | Contents |
| --- | --- |
| `results/pqec_single_qubit_summary.csv` | Full-budget aggregate metrics by scenario and method |
| `results/pqec_single_qubit_runs.csv` | Per-trial results for every method, including all paired trials |
| `results/pqec_single_qubit_paired_stats.csv` | Full-budget paired controller comparisons and bootstrap/sign-flip statistics |
| `results/pqec_budget_sweep_summary.csv` | Aggregate metrics and probe resource counts for all five budgets |
| `results/pqec_budget_sweep_paired_stats.csv` | Paired comparisons with global Holm-adjusted p-values across all 90 hypotheses |
| `results/budget_*_summary.csv` | Per-budget aggregate files |
| `results/budget_*_runs.csv` | Per-trial data for each budget |
| `results/budget_*_paired.csv` | Per-budget paired inference before the global sweep correction |
| `results/experiment_seed_manifest.csv` | Per-trajectory and derived measurement/controller seeds |
| `results/statistical_seed_manifest.csv` | Bootstrap and permutation seeds for the statistical comparisons |
| `results/robustness_v03/pqec_robustness_runs.csv` | All v0.3 per-trial metrics for the reactive controller and six forecasting methods |
| `results/robustness_v03/pqec_robustness_summary.csv` | Per-condition means, variation, probe-resource counts, and forecast errors |
| `results/robustness_v03/pqec_robustness_paired_stats.csv` | 630 paired tests with bootstrap intervals, raw and Holm-adjusted p-values, and seed-block effects |
| `results/robustness_v03/pqec_robustness_seed_manifest.csv` | Per-condition target/probe trajectory and probe-measurement seeds |
| `results/robustness_v03/pqec_robustness_stats_seed_manifest.csv` | Per-condition bootstrap and sign-flip seeds and resampling counts |
| `figures/*.svg` | Reproducible comparison, budget trade-off, and probe-mismatch figures |

The confidence intervals in the CSVs are 95% paired bootstrap percentile intervals. The `holm_global_all_budgets_p` column adjusts paired sign-flip p-values across 5 budgets × 18 comparisons (90 hypotheses). Seed-block means are retained in the paired-statistics CSV for a basic robustness check across the two blocks.

## Aer pilot reproducibility

The Aer pilot uses a separate environment from the analytic v0.3 run. Its tested environment is Python 3.x with Qiskit 2.6.1, Qiskit Aer 0.18.2, NumPy 2.5.4, and SciPy 1.18.1; the exact installed versions are also written to the run output. Install the pinned requirements and run:

```powershell
python -m venv .venv-aer
.\.venv-aer\Scripts\Activate.ps1
python -m pip install -r requirements-aer.txt

python pqec_aer_sweep.py --config configs/aer_noise_v01.json
python plot_aer_results.py
python pqec_aer_sweep.py --config configs/aer_noise_v02.json
python plot_aer_results.py --results-dir results/aer_noise_v02 --output-prefix aer_noise_v02
python plot_aer_mismatch.py
python -m unittest discover -s tests -v
```

Aer v0.1 uses the original five-block design; v0.2 adds eight new blocks and a graded mismatch sweep. The v0.2 run writes 12,800 per-method rows, 1,600 trajectory seed records, and 144 globally corrected tests. The trajectory seed is:

```text
base_seed + scenario_offset + seed_block_id*seed_block_stride + trial*trial_stride
```

The probe and target Aer seeds add their configured offsets to the trajectory seed. The output manifest records all three seeds per condition/block/trial. Statistics seeds use the condition, method, and metric indices according to the formula in the JSON configuration. Both Aer versions use 5,000 bootstrap resamples and 20,000 sign-flip patterns; Holm correction covers the 72 tests in v0.1 and the 144 tests in v0.2 separately. The bootstrap intervals are not multiplicity-adjusted.

The saved Aer outputs are:

| Path | Contents |
| --- | --- |
| `results/aer_noise_v01/pqec_aer_runs.csv` | 3,200 per-method trial rows, including probe counts, estimates, density-matrix metrics, and modeled timing |
| `results/aer_noise_v01/pqec_aer_summary.csv` | Condition-by-method averages and dispersions |
| `results/aer_noise_v01/pqec_aer_paired_stats.csv` | 72 paired tests, confidence intervals, raw p-values, Holm-adjusted p-values, and seed-block effects |
| `results/aer_noise_v01/pqec_aer_seed_manifest.csv` | 400 trajectory and Aer seed records |
| `results/aer_noise_v01/pqec_aer_probe_calibration.csv` | Noisy probe response curve used to decode counts |
| `results/aer_noise_v01/pqec_aer_config_snapshot.json` | Exact saved run configuration |
| `results/aer_noise_v01/pqec_aer_environment.json` | Python and library versions and total elapsed runtime |
| `results/aer_noise_v02/pqec_aer_runs.csv` | 12,800 per-method trial rows across the expanded eight-condition design |
| `results/aer_noise_v02/pqec_aer_summary.csv` | Condition-by-method means and dispersion |
| `results/aer_noise_v02/pqec_aer_paired_stats.csv` | 144 paired tests, confidence intervals, raw and Holm-adjusted p-values, and seed-block effects |
| `results/aer_noise_v02/pqec_aer_seed_manifest.csv` | 1,600 trajectory and Aer seed records from blocks 12–19 |
| `results/aer_noise_v02/pqec_aer_probe_calibration.csv` | Configured Aer probe-response calibration |
| `results/aer_noise_v02/pqec_aer_config_snapshot.json` | Exact expanded mismatch-sweep configuration |
| `results/aer_noise_v02/pqec_aer_environment.json` | Python and library versions and total elapsed runtime |

The [Aer v0.2 report](aer_noise_v02.md) is the expanded study; [Aer v0.1](aer_noise_v01.md) remains as its reproducible predecessor.

## Figures

`plot_results.py` reads `pqec_budget_sweep_summary.csv`, `pqec_budget_sweep_paired_stats.csv`, and `pqec_single_qubit_runs.csv`, then writes:

- `figures/pqec_vs_reactive_full_budget.svg` — paired guarded-PQEC effect and confidence interval for each scenario.
- `figures/probe_mismatch_failure.svg` — explicit probe-mismatch degradation with per-controller and paired summaries.
- `figures/budget_tradeoff.svg` — paired effects versus available probe shots per sequence across the five budgets.
- `figures/robustness_drift_sweep.svg` — predictor effects across the six shared-drift rates.
- `figures/probe_transfer_sweep.svg` — predictor effects across the five isolated probe-control-mismatch scales.
- `figures/measurement_budget_sweep.svg` — predictor effects across the five v0.3 shot-count/checkpoint-interval settings.
- `figures/aer_noise_v02_mismatch.svg` — guarded-PQEC paired effects across the five Aer mismatch levels.
- `figures/aer_noise_v02_final_fidelity.svg` — all six predictors' paired final-fidelity effects in the expanded Aer design.
- `figures/aer_noise_v02_cumulative_error.svg` — all six predictors' paired cumulative-angle effects in the expanded Aer design.

The per-method bars in the mismatch figure use marginal 95% bootstrap intervals with 5,000 resamples. Their fixed seeds are 9101/9102 for final fidelity and 9201/9202 for cumulative error (reactive first, guarded PQEC second). The paired difference interval and p-value shown in that figure are read directly from the saved paired-statistics CSV.

