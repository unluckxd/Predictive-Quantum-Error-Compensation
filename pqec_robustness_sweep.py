#!/usr/bin/env python3
"""Run the v0.3 paired robustness grid for probe-based error prediction."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from time import perf_counter

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - exercised by the CLI message
    raise SystemExit(
        "This study requires NumPy. Install it with: "
        "python -m pip install -r requirements-robustness.txt"
    ) from exc

from pqec_baselines import BASELINE_METHODS
from pqec_single_qubit import (
    METHOD_LABELS,
    SCENARIO_SEED_OFFSETS,
    degrees,
    evaluate_trial,
    state_after_rx_sequence,
)


METHODS = (
    "reactive_last_probe",
    "predictive_linear",
    "predictive_guarded",
    *BASELINE_METHODS,
)
METRICS = (
    "final_state_fidelity",
    "rms_gate_error_deg",
    "rms_cumulative_error_deg",
)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write to {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def effective_parameters(
    defaults: dict[str, object], condition: dict[str, object]
) -> dict[str, object]:
    parameters = dict(defaults)
    parameter = condition.get("parameter")
    if parameter is not None:
        parameters[str(parameter)] = condition["value"]
    parameters.update(condition.get("overrides", {}))
    return parameters


def attach_condition_metadata(
    row: dict[str, object],
    condition: dict[str, object],
    parameters_json: str,
    numpy_version: str,
) -> None:
    row["condition_id"] = condition["id"]
    row["sweep_axis"] = condition["axis"]
    row["sweep_value"] = condition["value"]
    row["sweep_label"] = condition["label"]
    row["condition_parameters_json"] = parameters_json
    row["numpy_version"] = numpy_version
    row["python_version"] = platform.python_version()


def summarize_condition(
    condition: dict[str, object], rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for method in METHODS:
        group = [row for row in rows if row["method"] == method]
        final = [float(row["final_state_fidelity"]) for row in group]
        predictions = [
            float(row["prediction_mae_deg"])
            for row in group
            if row["prediction_mae_deg"] != ""
        ]
        representative = group[0]
        output.append(
            {
                "condition_id": condition["id"],
                "sweep_axis": condition["axis"],
                "sweep_value": condition["value"],
                "sweep_label": condition["label"],
                "scenario": representative["scenario"],
                "method": method,
                "method_label": METHOD_LABELS[method],
                "n_pairs": len(group),
                "seed_blocks": len({int(row["seed_block"]) for row in group}),
                "mean_final_state_fidelity": mean(final),
                "sd_final_state_fidelity": pstdev(final),
                "mean_gate_fidelity": mean(
                    float(row["mean_gate_fidelity"]) for row in group
                ),
                "mean_rms_gate_error_deg": mean(
                    float(row["rms_gate_error_deg"]) for row in group
                ),
                "mean_rms_cumulative_error_deg": mean(
                    float(row["rms_cumulative_error_deg"]) for row in group
                ),
                "mean_prediction_mae_deg": (
                    mean(predictions) if predictions else ""
                ),
                "probe_shots_available_per_run": representative[
                    "probe_shots_available_per_run"
                ],
                "probe_shots_used_per_run": representative[
                    "probe_shots_used_per_run"
                ],
                "probe_pulses_used_per_run": representative[
                    "probe_pulses_used_per_run"
                ],
                "mean_controller_time_ms_per_sequence": mean(
                    float(row["controller_time_ms_per_sequence"])
                    for row in group
                ),
                "condition_parameters_json": representative[
                    "condition_parameters_json"
                ],
            }
        )
    return output


def paired_statistics(
    condition: dict[str, object],
    rows: list[dict[str, object]],
    parameters: dict[str, object],
    condition_index: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    by_pair: dict[tuple[int, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        by_pair[(int(row["seed_block"]), int(row["trial"]))][
            str(row["method"])
        ] = row

    paired_keys = sorted(
        key
        for key, pair in by_pair.items()
        if {"reactive_last_probe", *METHODS[1:]}.issubset(pair)
    )
    if len(paired_keys) < 2:
        raise ValueError(f"Insufficient complete pairs in {condition['id']}")

    count = len(paired_keys)
    base_seed = int(parameters["seed"])
    bootstrap_seed = base_seed + 4_000_000_019 + condition_index * 1_000_003
    permutation_seed = bootstrap_seed + 2_000_003
    bootstrap_rng = np.random.default_rng(bootstrap_seed)
    permutation_rng = np.random.default_rng(permutation_seed)
    bootstrap_indices = bootstrap_rng.integers(
        0, count,
        size=(int(parameters["bootstrap_repetitions"]), count),
        endpoint=False,
    )
    sign_patterns = (
        permutation_rng.integers(
            0,
            2,
            size=(int(parameters["permutation_repetitions"]), count),
            dtype=np.int8,
        )
        * 2
        - 1
    )
    statistical_manifest = {
        "condition_id": condition["id"],
        "condition_index": condition_index,
        "base_seed": base_seed,
        "bootstrap_seed": bootstrap_seed,
        "permutation_seed": permutation_seed,
        "bootstrap_repetitions": parameters["bootstrap_repetitions"],
        "permutation_repetitions": parameters["permutation_repetitions"],
        "n_pairs": count,
        "numpy_version": np.__version__,
        "bit_generator": type(bootstrap_rng.bit_generator).__name__,
        "resampling_patterns_shared_within_condition": True,
    }

    output: list[dict[str, object]] = []
    for metric in METRICS:
        for method in METHODS[1:]:
            differences = np.asarray(
                [
                    float(by_pair[key][method][metric])
                    - float(by_pair[key]["reactive_last_probe"][metric])
                    for key in paired_keys
                ],
                dtype=np.float64,
            )
            bootstrap_means = differences[bootstrap_indices].mean(axis=1)
            ci_low, ci_high = np.quantile(
                bootstrap_means, (0.025, 0.975), method="linear"
            )
            observed = float(differences.mean())
            permuted_means = sign_patterns @ differences / count
            threshold = abs(observed) - 1e-15
            p_value = (
                int(np.count_nonzero(np.abs(permuted_means) >= threshold)) + 1
            ) / (len(permuted_means) + 1)
            row: dict[str, object] = {
                "condition_id": condition["id"],
                "sweep_axis": condition["axis"],
                "sweep_value": condition["value"],
                "sweep_label": condition["label"],
                "scenario": condition["scenario"],
                "metric": metric,
                "comparison": f"{method} - reactive_last_probe",
                "method": method,
                "n_pairs": count,
                "mean_difference": observed,
                "bootstrap_95ci_low": float(ci_low),
                "bootstrap_95ci_high": float(ci_high),
                "paired_sign_flip_p": p_value,
                "holm_global_p": "",
                "bootstrap_repetitions": parameters["bootstrap_repetitions"],
                "permutation_repetitions": parameters["permutation_repetitions"],
                "bootstrap_seed": bootstrap_seed,
                "permutation_seed": permutation_seed,
                "better_direction": "higher" if metric == "final_state_fidelity" else "lower",
            }
            for block in parameters["seed_block_ids"]:
                block_differences = [
                    float(by_pair[key][method][metric])
                    - float(by_pair[key]["reactive_last_probe"][metric])
                    for key in paired_keys
                    if key[0] == int(block)
                ]
                row[f"seed_block_{block}_n"] = len(block_differences)
                row[f"seed_block_{block}_mean_difference"] = mean(
                    block_differences
                )
            output.append(row)
    return output, statistical_manifest


def holm_adjust_global(rows: list[dict[str, object]]) -> None:
    order = sorted(
        range(len(rows)),
        key=lambda index: float(rows[index]["paired_sign_flip_p"]),
    )
    running_max = 0.0
    total = len(order)
    for rank, index in enumerate(order):
        adjusted = min(
            1.0,
            (total - rank) * float(rows[index]["paired_sign_flip_p"]),
        )
        running_max = max(running_max, adjusted)
        rows[index]["holm_global_p"] = running_max


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/robustness_v03.json")
    )
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_dir = Path(__file__).resolve().parent
    config_path = args.config if args.config.is_absolute() else project_dir / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = config["parameters"]
    output_dir = args.output_dir or Path(config["outputs"]["directory"])
    if not output_dir.is_absolute():
        output_dir = project_dir / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    run_path = output_dir / "pqec_robustness_runs.csv"
    summary_rows: list[dict[str, object]] = []
    paired_rows: list[dict[str, object]] = []
    seed_manifest: list[dict[str, object]] = []
    statistical_manifest: list[dict[str, object]] = []
    ideal_state = state_after_rx_sequence([degrees(90.0)] * int(defaults["cycles"]))
    started = perf_counter()

    with run_path.open("w", newline="", encoding="utf-8") as run_handle:
        run_writer: csv.DictWriter[str] | None = None
        conditions = config["conditions"]
        for condition_index, condition in enumerate(conditions):
            condition_parameters = effective_parameters(defaults, condition)
            run_config = argparse.Namespace(**condition_parameters)
            parameters_json = json.dumps(
                condition_parameters, sort_keys=True, separators=(",", ":")
            )
            condition_rows: list[dict[str, object]] = []
            for block in condition_parameters["seed_block_ids"]:
                for trial in range(int(condition_parameters["trials"])):
                    trial_rows = evaluate_trial(
                        str(condition["scenario"]),
                        int(block),
                        trial,
                        run_config,
                        ideal_state,
                        methods=METHODS,
                        measurement_rng_backend="numpy",
                    )
                    trajectory_seed = (
                        int(condition_parameters["seed"])
                        + int(block) * 1_000_003
                        + trial * 1009
                        + SCENARIO_SEED_OFFSETS[str(condition["scenario"])]
                    )
                    seed_manifest.append(
                        {
                            "condition_id": condition["id"],
                            "scenario": condition["scenario"],
                            "seed_block": int(block),
                            "trial": trial,
                            "base_seed": condition_parameters["seed"],
                            "trajectory_seed": trajectory_seed,
                            "probe_trajectory_seed": trajectory_seed + 5_000_117,
                            "probe_measurement_seed": trajectory_seed + 700_001,
                            "measurement_rng": "numpy.random.default_rng",
                            "numpy_version": np.__version__,
                            "bit_generator": "PCG64",
                        }
                    )
                    for row in trial_rows:
                        if row["method"] == "ideal_reference":
                            continue
                        attach_condition_metadata(
                            row, condition, parameters_json, np.__version__
                        )
                        condition_rows.append(row)
            if run_writer is None:
                run_fields = [
                    name
                    for name in condition_rows[0]
                    if name != "condition_parameters_json"
                ]
                run_writer = csv.DictWriter(
                    run_handle, fieldnames=run_fields
                )
                run_writer.writeheader()
            run_writer.writerows(
                {
                    key: row[key]
                    for key in run_writer.fieldnames or ()
                }
                for row in condition_rows
            )
            summary_rows.extend(summarize_condition(condition, condition_rows))
            comparisons, stats_manifest = paired_statistics(
                condition,
                condition_rows,
                condition_parameters,
                condition_index,
            )
            paired_rows.extend(comparisons)
            statistical_manifest.append(stats_manifest)
            print(
                f"[{condition_index + 1}/{len(conditions)}] "
                f"{condition['id']}: {len(condition_rows) // len(METHODS)} "
                "paired trials completed",
                flush=True,
            )

    holm_adjust_global(paired_rows)
    write_csv(output_dir / "pqec_robustness_summary.csv", summary_rows)
    write_csv(output_dir / "pqec_robustness_paired_stats.csv", paired_rows)
    write_csv(output_dir / "pqec_robustness_seed_manifest.csv", seed_manifest)
    write_csv(
        output_dir / "pqec_robustness_stats_seed_manifest.csv",
        statistical_manifest,
    )
    print(
        f"Completed {len(config['conditions'])} conditions, "
        f"{len(seed_manifest):,} paired trials, and {len(paired_rows)} "
        f"paired hypotheses in {perf_counter() - started:.1f}s."
    )
    print(f"Results: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
