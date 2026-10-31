#!/usr/bin/env python3
"""Render Matplotlib paired-effect figures for the Qiskit Aer pilot."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plotting_utils import normalize_svg_whitespace


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = ROOT / "results" / "aer_noise_v01"
DEFAULT_OUTPUT_DIR = ROOT / "figures"
METHOD_COLORS = {
    "predictive_linear": "#8c2d04",
    "predictive_guarded": "#1f77b4",
    "moving_average": "#7b3294",
    "exponential_moving_average": "#008837",
    "two_point_linear": "#e08214",
    "kalman_constant_velocity": "#555555",
}
METHOD_LABELS = {
    "predictive_linear": "Rolling linear",
    "predictive_guarded": "Guarded PQEC",
    "moving_average": "Moving average",
    "exponential_moving_average": "Exponential moving average",
    "two_point_linear": "Two-point linear",
    "kalman_constant_velocity": "Constant-velocity Kalman",
}
METHOD_ORDER = tuple(METHOD_LABELS)


def read_statistics(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def plot_metric(
    axis: plt.Axes,
    rows: list[dict[str, str]],
    *,
    metric: str,
    title: str,
    x_label: str,
    favorable_direction: str,
    condition_labels: dict[str, str],
    condition_order: tuple[str, ...],
) -> None:
    selected = [row for row in rows if row["metric"] == metric]
    selected.sort(
        key=lambda row: (
            condition_order.index(row["condition_id"]),
            METHOD_ORDER.index(row["comparison"].split(" - ")[0]),
        )
    )
    if not selected:
        raise ValueError(f"No paired statistics found for {metric}.")

    positions = list(range(len(selected)))
    labels: list[str] = []
    lows: list[float] = []
    highs: list[float] = []
    for index, row in enumerate(selected):
        method = row["comparison"].split(" - ")[0]
        condition = row["condition_id"]
        estimate = float(row["mean_difference"])
        low = float(row["bootstrap_95ci_low"])
        high = float(row["bootstrap_95ci_high"])
        color = METHOD_COLORS[method]
        axis.errorbar(
            estimate,
            index,
            xerr=[[estimate - low], [high - estimate]],
            fmt="o",
            color=color,
            ecolor=color,
            markersize=5,
            capsize=3,
            linewidth=1.5,
            zorder=3,
        )
        labels.append(
            f"{condition_labels[condition]} / {METHOD_LABELS[method]}"
        )
        lows.append(low)
        highs.append(high)

    all_values = [0.0, *lows, *highs]
    spread = max(max(all_values) - min(all_values), 1e-8)
    x_left = min(all_values) - 0.1 * spread
    x_right = max(all_values) + 0.1 * spread
    axis.set_xlim(x_left, x_right)
    axis.axvline(0.0, color="#333333", linestyle="--", linewidth=1.0)
    axis.set_yticks(positions, labels=labels)
    axis.invert_yaxis()
    axis.set_title(title, loc="left", fontsize=13, weight="bold")
    axis.set_xlabel(x_label)
    axis.set_ylabel("")
    axis.grid(axis="x", color="#dddddd", linewidth=0.7, alpha=0.8)
    axis.set_axisbelow(True)
    axis.tick_params(axis="y", labelsize=8)
    axis.text(
        0.02,
        -0.085,
        favorable_direction,
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color="#444444",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Figure filename prefix. Defaults to aer_noise for v0.1, or the results folder name otherwise.",
    )
    args = parser.parse_args()
    results_dir = args.results_dir
    if not results_dir.is_absolute():
        results_dir = ROOT / results_dir
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    config = json.loads(
        (results_dir / "pqec_aer_config_snapshot.json").read_text(encoding="utf-8")
    )
    condition_labels = {
        str(condition["id"]): str(condition["label"])
        for condition in config["conditions"]
    }
    condition_order = tuple(condition_labels)
    rows = read_statistics(results_dir / "pqec_aer_paired_stats.csv")
    output_prefix = args.output_prefix
    if output_prefix is None:
        output_prefix = "aer_noise" if results_dir.name == "aer_noise_v01" else results_dir.name
    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    figures = (
        (
            "final_state_fidelity",
            "Final target-state fidelity",
            "Mean paired difference",
            "Positive values favor the predictor.",
            "aer_noise_final_fidelity",
        ),
        (
            "rms_cumulative_angle_residual_deg",
            "Cumulative coherent-angle residual",
            "Mean paired difference (degrees)",
            "Negative values favor the predictor.",
            "aer_noise_cumulative_error",
        ),
    )
    for metric, title, x_label, direction, filename in figures:
        figure, axis = plt.subplots(figsize=(13, 13))
        figure_height = max(13.0, 0.39 * len(condition_order) * len(METHOD_ORDER) + 2.0)
        figure.set_size_inches(13, figure_height)
        output_stem = f"{output_prefix}_{filename.removeprefix('aer_noise_')}"
        plot_metric(
            axis,
            rows,
            metric=metric,
            title=title,
            x_label=x_label,
            favorable_direction=direction,
            condition_labels=condition_labels,
            condition_order=condition_order,
        )
        figure.suptitle(
            "Aer pilot: predictor minus reactive last-probe control",
            x=0.02,
            y=0.99,
            ha="left",
            fontsize=14,
            weight="bold",
        )
        figure.text(
            0.02,
            0.015,
            "Points are paired mean differences; bars are unadjusted 95% bootstrap intervals. "
            "Global Holm-adjusted p-values are in the paired-statistics CSV.",
            fontsize=9,
            color="#444444",
        )
        figure.subplots_adjust(left=0.48, right=0.96, top=0.90, bottom=0.08)
        for extension in ("svg", "png"):
            figure.savefig(
                output_dir / f"{output_stem}.{extension}",
                dpi=240,
                bbox_inches="tight",
            )
            if extension == "svg":
                normalize_svg_whitespace(output_dir / f"{output_stem}.{extension}")
        plt.close(figure)
        print(f"Wrote {output_dir / f'{output_stem}.svg'} and {output_dir / f'{output_stem}.png'}")


if __name__ == "__main__":
    main()
