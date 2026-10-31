#!/usr/bin/env python3
"""Run the PQEC measurement-budget sweep and combine its paired results."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


BUDGETS = (
    ("128shots_every1", "128s_interval1", 128, 1),
    ("512shots_every4", "512s_interval4", 512, 4),
    ("128shots_every4", "128s_interval4", 128, 4),
    ("64shots_every8", "64s_interval8", 64, 8),
    ("4096shots_every1", "4096s_interval1", 4096, 1),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write to {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_seed_manifest(path: Path, base_seed: int) -> list[dict[str, object]]:
    unique_rows: dict[tuple[str, int, int, int], dict[str, object]] = {}
    for row in read_csv(path):
        key = (
            row["scenario"],
            int(row["seed_block"]),
            int(row["trial"]),
            int(row["seed"]),
        )
        unique_rows[key] = {
            "base_seed": base_seed,
            "scenario": key[0],
            "seed_block": key[1],
            "trial": key[2],
            "trajectory_seed": key[3],
            "probe_trajectory_seed": key[3] + 5_000_117,
            "probe_measurement_seed": key[3] + 700_001,
            "randomized_compiling_seed": key[3] + 900_001,
        }
    return [unique_rows[key] for key in sorted(unique_rows)]


def build_statistical_seed_manifest(
    base_seed: int,
    bootstrap_repetitions: int,
    permutation_repetitions: int,
) -> list[dict[str, object]]:
    scenarios = ("slow_drift", "white_noise", "probe_mismatch")
    metrics = (
        "final_state_fidelity",
        "rms_gate_error_deg",
        "rms_cumulative_error_deg",
    )
    predictors = ("predictive_linear", "predictive_guarded")
    rows: list[dict[str, object]] = []
    for scenario_index, scenario in enumerate(scenarios):
        for metric_index, metric in enumerate(metrics):
            for predictor_index, predictor in enumerate(predictors):
                bootstrap_seed = (
                    base_seed
                    + scenario_index * 10_007
                    + metric_index * 97_409
                    + predictor_index * 1_000_003
                )
                rows.append(
                    {
                        "base_seed": base_seed,
                        "scenario": scenario,
                        "scenario_index": scenario_index,
                        "metric": metric,
                        "metric_index": metric_index,
                        "predictor": predictor,
                        "predictor_index": predictor_index,
                        "bootstrap_seed": bootstrap_seed,
                        "permutation_seed": bootstrap_seed + 2_000_003,
                        "bootstrap_repetitions": bootstrap_repetitions,
                        "permutation_repetitions": permutation_repetitions,
                    }
                )
    return rows


def holm_adjust_global(rows: list[dict[str, object]]) -> None:
    """Adjust the full family of comparisons across every budget setting."""
    order = sorted(
        range(len(rows)),
        key=lambda index: float(rows[index]["paired_sign_flip_p"]),
    )
    running_max = 0.0
    count = len(order)
    for rank, index in enumerate(order):
        adjusted = min(
            1.0,
            (count - rank) * float(rows[index]["paired_sign_flip_p"]),
        )
        running_max = max(running_max, adjusted)
        rows[index]["holm_global_all_budgets_p"] = running_max


def parse_args() -> argparse.Namespace:
    config_scanner = argparse.ArgumentParser(add_help=False)
    config_scanner.add_argument("--config", type=Path)
    config_path = config_scanner.parse_known_args()[0].config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        help="Load sweep defaults and budget settings from a JSON file.",
    )
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed-blocks", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--cycles", type=int, default=64)
    parser.add_argument("--probe-repetitions", type=int, default=13)
    parser.add_argument("--predictor-window", type=int, default=16)
    parser.add_argument("--trend-threshold", type=float, default=2.0)
    parser.add_argument("--min-trend-observations", type=int, default=4)
    parser.add_argument("--bootstrap-repetitions", type=int, default=5000)
    parser.add_argument("--permutation-repetitions", type=int, default=10000)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    config_data: dict[str, object] = {}
    if config_path is not None:
        try:
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            defaults = config_data["parameters"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            parser.error(f"Could not read configuration {config_path}: {exc}")
        allowed_parameters = {
            action.dest for action in parser._actions if action.dest != "help"
        }
        unknown_parameters = set(defaults) - allowed_parameters
        if unknown_parameters:
            parser.error(
                "Unknown configuration parameters: "
                + ", ".join(sorted(unknown_parameters))
            )
        if "output_dir" in defaults:
            defaults["output_dir"] = Path(defaults["output_dir"])
        parser.set_defaults(**defaults)
    args = parser.parse_args()
    if min(
        args.trials,
        args.seed_blocks,
        args.cycles,
        args.probe_repetitions,
        args.predictor_window,
        args.min_trend_observations,
        args.bootstrap_repetitions,
        args.permutation_repetitions,
    ) <= 0:
        parser.error("All run counts and sizes must be positive.")
    if args.min_trend_observations > args.predictor_window:
        parser.error("--min-trend-observations cannot exceed --predictor-window.")
    if args.probe_repetitions % 4 != 1:
        parser.error("--probe-repetitions must be 4k + 1.")
    configured_budgets = config_data.get("budgets")
    if configured_budgets is None:
        args.budgets = BUDGETS
    else:
        try:
            args.budgets = tuple(
                (
                    str(item["id"]),
                    str(item["file_suffix"]),
                    int(item["shots"]),
                    int(item["interval"]),
                )
                for item in configured_budgets
            )
        except (KeyError, TypeError, ValueError) as exc:
            parser.error(f"Invalid budget list in {config_path}: {exc}")
        if not args.budgets:
            parser.error("The configuration must define at least one budget.")
        for budget_id, suffix, shots, interval in args.budgets:
            if Path(suffix).name != suffix or min(shots, interval) < 1:
                parser.error(f"Invalid budget entry: {budget_id}")
    return args


def main() -> None:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = project_dir / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    simulator = project_dir / "pqec_single_qubit.py"
    default_budget_shots = (args.cycles + 1) * 4096

    summary_rows: list[dict[str, object]] = []
    paired_rows: list[dict[str, object]] = []
    seed_manifest_rows: list[dict[str, object]] = []
    for budget_id, file_suffix, shots, interval in args.budgets:
        summary_path = output_dir / f"budget_{file_suffix}_summary.csv"
        runs_path = output_dir / f"budget_{file_suffix}_runs.csv"
        paired_path = output_dir / f"budget_{file_suffix}_paired.csv"
        command = [
            sys.executable,
            str(simulator),
            "--cycles",
            str(args.cycles),
            "--trials",
            str(args.trials),
            "--seed-blocks",
            str(args.seed_blocks),
            "--seed",
            str(args.seed),
            "--shots",
            str(shots),
            "--probe-repetitions",
            str(args.probe_repetitions),
            "--probe-interval",
            str(interval),
            "--predictor-window",
            str(args.predictor_window),
            "--trend-threshold",
            str(args.trend_threshold),
            "--min-trend-observations",
            str(args.min_trend_observations),
            "--bootstrap-repetitions",
            str(args.bootstrap_repetitions),
            "--permutation-repetitions",
            str(args.permutation_repetitions),
            "--output",
            str(summary_path),
            "--runs-output",
            str(runs_path),
            "--paired-output",
            str(paired_path),
        ]
        print(
            f"\n=== {budget_id}: {shots} shots/checkpoint, "
            f"one probe every {interval} logical pulses ===",
            flush=True,
        )
        subprocess.run(command, check=True)

        if budget_id == "4096shots_every1" and interval == 1:
            seed_manifest_rows = build_seed_manifest(runs_path, args.seed)

        for row in read_csv(summary_path):
            row["budget_id"] = budget_id
            probe_shots = int(row["probe_shots_available_per_run"])
            row["fold_reduction_vs_default"] = (
                default_budget_shots / probe_shots if probe_shots else ""
            )
            summary_rows.append(row)
        for row in read_csv(paired_path):
            row["budget_id"] = budget_id
            paired_rows.append(row)

    holm_adjust_global(paired_rows)
    write_csv(output_dir / "pqec_budget_sweep_summary.csv", summary_rows)
    write_csv(output_dir / "pqec_budget_sweep_paired_stats.csv", paired_rows)
    write_csv(
        output_dir / "statistical_seed_manifest.csv",
        build_statistical_seed_manifest(
            args.seed,
            args.bootstrap_repetitions,
            args.permutation_repetitions,
        ),
    )
    if seed_manifest_rows:
        write_csv(output_dir / "experiment_seed_manifest.csv", seed_manifest_rows)
    print(
        f"\nCombined {len(summary_rows)} summary rows and "
        f"{len(paired_rows)} paired comparisons. Global Holm correction "
        f"covers all {len(paired_rows)} budget-comparison hypotheses."
    )
    print(f"Combined files are in {output_dir}")


if __name__ == "__main__":
    main()
