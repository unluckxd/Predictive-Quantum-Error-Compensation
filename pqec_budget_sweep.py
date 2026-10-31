#!/usr/bin/env python3
"""Run the PQEC measurement-budget sweep and combine its paired results."""

from __future__ import annotations

import argparse
import csv
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
    parser = argparse.ArgumentParser(description=__doc__)
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
    for budget_id, file_suffix, shots, interval in BUDGETS:
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
    print(
        f"\nCombined {len(summary_rows)} summary rows and "
        f"{len(paired_rows)} paired comparisons. Global Holm correction "
        f"covers all {len(paired_rows)} budget-comparison hypotheses."
    )
    print(f"Combined files are in {output_dir}")


if __name__ == "__main__":
    main()
