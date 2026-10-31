# Reproducibility

## Environment and commands

Use Python 3.10 or later from the repository root. The archived v0.2 data use the built-in analytic one-qubit state-vector fallback, which needs no third-party packages. Qiskit is listed in `requirements.txt` as an optional simulation backend; when installed, the code automatically selects Qiskit's `Statevector`. The plotting script uses only the Python standard library and writes SVG files.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python pqec_single_qubit.py --config configs/full_run_v02.json
python pqec_budget_sweep.py --config configs/budget_sweep_v02.json
python plot_results.py

python -m unittest discover -s tests -v
```

The JSON parameters act as defaults; explicit command-line arguments override them. Running the full sweep regenerates the five per-budget CSV triplets, combined summary/statistics, and both seed manifests. To regenerate figures from the saved sweep CSVs only, run `python plot_results.py`.

To run the optional Qiskit backend, install it before starting the scripts with `python -m pip install -r requirements.txt`. The numerical model is the same, but the `statevector_backend` field in the CSVs will identify the selected backend.

## Frozen configurations

- [`full_run_v02.json`](../configs/full_run_v02.json): 64 target-operation cycles, 100 trials in each of two seed blocks, 4,096 shots per probe checkpoint, one checkpoint every cycle.
- [`budget_sweep_v02.json`](../configs/budget_sweep_v02.json): the same seed schedule and trajectories evaluated at five shot-count/checkpoint-interval settings.

Both configurations state their experiment ID, claim scope, base seed, seed offsets/strides, statistics seed formula, and model parameters. The saved v0.2 CSVs were produced with the analytic fallback. The historical v0.1 Qiskit CSV files are separate and should not be combined with the v0.2 tables.

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
| `figures/*.svg` | Reproducible comparison, budget trade-off, and probe-mismatch figures |

The confidence intervals in the CSVs are 95% paired bootstrap percentile intervals. The `holm_global_all_budgets_p` column adjusts paired sign-flip p-values across 5 budgets × 18 comparisons (90 hypotheses). Seed-block means are retained in the paired-statistics CSV for a basic robustness check across the two blocks.

## Figures

`plot_results.py` reads `pqec_budget_sweep_summary.csv`, `pqec_budget_sweep_paired_stats.csv`, and `pqec_single_qubit_runs.csv`, then writes:

- `figures/pqec_vs_reactive_full_budget.svg` — paired guarded-PQEC effect and confidence interval for each scenario.
- `figures/probe_mismatch_failure.svg` — explicit probe-mismatch degradation with per-controller and paired summaries.
- `figures/budget_tradeoff.svg` — paired effects versus available probe shots per sequence across the five budgets.

The per-method bars in the mismatch figure use marginal 95% bootstrap intervals with 5,000 resamples. Their fixed seeds are 9101/9102 for final fidelity and 9201/9202 for cumulative error (reactive first, guarded PQEC second). The paired difference interval and p-value shown in that figure are read directly from the saved paired-statistics CSV.

