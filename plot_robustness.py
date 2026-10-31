#!/usr/bin/env python3
"""Plot analytic robustness-sweep effects with Matplotlib."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from plotting_utils import normalize_svg_whitespace


METHODS = (
    "predictive_linear",
    "predictive_guarded",
    "moving_average",
    "exponential_moving_average",
    "two_point_linear",
    "kalman_constant_velocity",
)
METHOD_LABELS = {
    "predictive_linear": "Rolling linear",
    "predictive_guarded": "Guarded PQEC",
    "moving_average": "Moving average",
    "exponential_moving_average": "EMA",
    "two_point_linear": "Two-point linear",
    "kalman_constant_velocity": "Kalman",
}
METHOD_COLORS = {
    "predictive_linear": "#43AA8B",
    "predictive_guarded": "#F3722C",
    "moving_average": "#9B5DE5",
    "exponential_moving_average": "#00A6A6",
    "two_point_linear": "#C43D40",
    "kalman_constant_velocity": "#577590",
}
METRICS = (
    ("final_state_fidelity", "Final state fidelity difference"),
    ("rms_cumulative_error_deg", "RMS cumulative-error difference (degrees)"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def save_figure(figure: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    normalize_svg_whitespace(output)
    figure.savefig(output.with_suffix(".png"), dpi=240, bbox_inches="tight")
    plt.close(figure)


def plot_sensitivity(
    rows: list[dict[str, str]],
    conditions: list[dict[str, object]],
    *,
    axis_name: str,
    title: str,
    subtitle: str,
    output: Path,
) -> None:
    selected = [
        condition for condition in conditions if condition["axis"] == axis_name
    ]
    condition_ids = [str(condition["id"]) for condition in selected]
    if not condition_ids:
        raise ValueError(f"No configured conditions for {axis_name}.")
    if axis_name == "probe_mismatch_scale":
        x_labels = [f"{100 * float(item['value']):.0f}%" for item in selected]
        x_label = "Probe-to-target control mismatch"
    elif axis_name == "measurement_budget_shots":
        x_labels = [
            f"{item['value']}/{item.get('overrides', {}).get('probe_interval', 4)}"
            for item in selected
        ]
        x_label = "Shots per checkpoint / checkpoint interval"
    else:
        x_labels = [f"{float(item['value']):g}" for item in selected]
        x_label = "Drift rate (degrees per target cycle)"

    data = {
        (row["condition_id"], row["method"], row["metric"]): row
        for row in rows
        if row["condition_id"] in condition_ids
    }
    x_base = np.arange(len(condition_ids), dtype=float)
    jitter = np.linspace(-0.12, 0.12, len(METHODS))
    figure, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    figure.subplots_adjust(top=0.82, bottom=0.11, hspace=0.24, left=0.12, right=0.98)
    figure.suptitle(title, x=0.02, ha="left", fontsize=15, weight="bold")
    figure.text(0.02, 0.93, subtitle, fontsize=9, color="#444444")

    for axis, (metric, metric_title) in zip(axes, METRICS):
        for method_index, method in enumerate(METHODS):
            estimates: list[float] = []
            lower_errors: list[float] = []
            upper_errors: list[float] = []
            valid_x: list[float] = []
            for condition_index, condition_id in enumerate(condition_ids):
                row = data.get((condition_id, method, metric))
                if row is None:
                    continue
                estimate = float(row["mean_difference"])
                low = float(row["bootstrap_95ci_low"])
                high = float(row["bootstrap_95ci_high"])
                estimates.append(estimate)
                lower_errors.append(estimate - low)
                upper_errors.append(high - estimate)
                valid_x.append(x_base[condition_index] + jitter[method_index])
            if not valid_x:
                continue
            color = METHOD_COLORS[method]
            axis.errorbar(
                valid_x,
                estimates,
                yerr=[lower_errors, upper_errors],
                fmt="o-",
                markersize=4,
                linewidth=1.3,
                capsize=2.5,
                color=color,
                label=METHOD_LABELS[method],
            )
        axis.axhline(0.0, color="#333333", linestyle="--", linewidth=1)
        axis.grid(axis="y", color="#dddddd", linewidth=0.7)
        axis.set_axisbelow(True)
        axis.set_ylabel(metric_title)
        axis.set_title(metric_title, loc="left", fontsize=10, weight="bold")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    axes[-1].set_xticks(x_base, x_labels)
    axes[-1].set_xlabel(x_label)
    legend_handles = [
        Line2D(
            [0],
            [0],
            color=METHOD_COLORS[method],
            marker="o",
            linewidth=1.4,
            label=METHOD_LABELS[method],
        )
        for method in METHODS
    ]
    figure.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.88),
        ncol=3,
        frameon=False,
        fontsize=8,
    )
    figure.text(
        0.02,
        0.025,
        "Effects are predictor minus reactive last probe. Positive fidelity and negative cumulative error favor prediction. "
        "Intervals are unadjusted; CSV p-values use global Holm correction.",
        fontsize=8,
        color="#444444",
    )
    save_figure(figure, output)


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=project_dir / "results" / "robustness_v03",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_dir / "configs" / "robustness_v03.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_dir / "figures",
    )
    args = parser.parse_args()
    if not args.results_dir.is_absolute():
        args.results_dir = project_dir / args.results_dir
    if not args.config.is_absolute():
        args.config = project_dir / args.config
    if not args.output_dir.is_absolute():
        args.output_dir = project_dir / args.output_dir

    config = json.loads(args.config.read_text(encoding="utf-8"))
    paired = read_csv(args.results_dir / "pqec_robustness_paired_stats.csv")
    figure_specs = (
        (
            "drift_rate_deg",
            "Drift-rate sensitivity",
            "Shared-drift conditions; x-axis is target error growth per cycle.",
            "robustness_drift_sweep.svg",
        ),
        (
            "probe_mismatch_scale",
            "Probe-to-target mismatch sensitivity",
            "0% shares the target trajectory; 100% is the analytic mismatch endpoint.",
            "probe_transfer_sweep.svg",
        ),
        (
            "measurement_budget_shots",
            "Measurement-budget sensitivity",
            "X labels show shots per checkpoint / checkpoint interval in target cycles.",
            "measurement_budget_sweep.svg",
        ),
    )
    for axis_name, title, subtitle, filename in figure_specs:
        plot_sensitivity(
            paired,
            config["conditions"],
            axis_name=axis_name,
            title=title,
            subtitle=subtitle,
            output=args.output_dir / filename,
        )
    print(f"Wrote six robustness figure files to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
