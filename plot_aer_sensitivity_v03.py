#!/usr/bin/env python3
"""Plot paired PQEC sensitivity effects for the v0.3 Aer sweeps."""

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
DEFAULT_OUTPUT_DIR = ROOT / "figures"
COMPARISON_METHOD = "predictive_guarded"
FACTORS = (
    ("target_t1", "Target T1"),
    ("target_t2", "Target T2"),
    ("probe_t1", "Probe T1"),
    ("probe_t2", "Probe T2"),
)
METRICS = (
    (
        "final_state_fidelity",
        "Change in final-fidelity advantage",
        "Change in fidelity effect",
    ),
    (
        "rms_cumulative_angle_residual_deg",
        "Change in cumulative-angle effect",
        "Change in RMS cumulative residual (degrees)",
    ),
    (
        "rms_gate_residual_deg",
        "Change in per-gate residual effect",
        "Change in RMS gate residual (degrees)",
    ),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def save_figure(figure: plt.Figure, output_stem: Path) -> None:
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    for extension in ("svg", "png"):
        output_path = output_stem.with_suffix(f".{extension}")
        figure.savefig(output_path, dpi=240, bbox_inches="tight")
        if extension == "svg":
            normalize_svg_whitespace(output_path)
    plt.close(figure)


def find_effect_change(
    rows: list[dict[str, str]], condition_id: str, metric: str
) -> dict[str, str]:
    return next(
        row
        for row in rows
        if row["condition_id"] == condition_id
        and row["method"] == COMPARISON_METHOD
        and row["metric"] == metric
    )


def plot_effect_change_axis(
    axis: plt.Axes,
    rows: dict[str, str],
    *,
    x_value: float,
    reference: bool = False,
) -> None:
    if reference:
        axis.plot(
            [x_value],
            [0.0],
            marker="s",
            markersize=5,
            color="#555555",
            linestyle="none",
            label="Reference condition",
            zorder=4,
        )
        return
    estimate = float(rows["mean_effect_change"])
    low = float(rows["bootstrap_95ci_low"])
    high = float(rows["bootstrap_95ci_high"])
    axis.errorbar(
        [x_value],
        [estimate],
        yerr=[[estimate - low], [high - estimate]],
        fmt="o",
        color="#276FBF",
        ecolor="#276FBF",
        markersize=5,
        capsize=3,
        linewidth=1.3,
        zorder=3,
    )
    if float(rows["holm_global_p"]) < 0.05:
        axis.annotate(
            "*",
            (x_value, estimate),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            weight="bold",
        )


def plot_t1t2(results_dir: Path, output_dir: Path) -> None:
    config = json.loads(
        (results_dir / "pqec_aer_config_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    rows = read_csv(results_dir / "pqec_aer_sensitivity_paired_stats.csv")
    conditions = config["conditions"]
    non_reference_by_factor = {
        factor: {
            float(condition["sweep_scale"]): str(condition["id"])
            for condition in conditions
            if condition.get("sweep_factor") == factor
        }
        for factor, _label in FACTORS
    }
    levels = (0.5, 0.75, 1.0, 1.5, 2.0)

    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    figure, axes = plt.subplots(3, 4, figsize=(14, 9), sharex=True)
    for column, (factor, factor_label) in enumerate(FACTORS):
        for row_index, (metric, title, y_label) in enumerate(METRICS):
            axis = axes[row_index, column]
            factor_ids = non_reference_by_factor[factor]
            for level in levels:
                if level == 1.0:
                    plot_effect_change_axis(
                        axis,
                        {},
                        x_value=level,
                        reference=True,
                    )
                    continue
                condition_id = factor_ids[level]
                effect = find_effect_change(rows, condition_id, metric)
                plot_effect_change_axis(
                    axis,
                    effect,
                    x_value=level,
                )
            axis.axhline(0.0, color="#333333", linestyle="--", linewidth=0.9)
            axis.set_xticks(levels, [f"{level:g}×" for level in levels])
            axis.grid(axis="y", color="#dddddd", linewidth=0.65)
            axis.set_axisbelow(True)
            if row_index == 0:
                axis.set_title(factor_label, loc="left", fontsize=10, weight="bold")
            if column == 0:
                axis.set_ylabel(y_label)
            if row_index == len(METRICS) - 1:
                axis.set_xlabel("Parameter scale")

    figure.suptitle(
        "PQEC v0.3 Aer: change in guarded-PQEC effect across T1/T2 levels",
        x=0.03,
        ha="left",
        fontsize=14,
        weight="bold",
    )
    figure.text(
        0.03,
        0.015,
        "Each point is the paired change in (guarded PQEC − reactive) versus the shared baseline; "
        "bars are unadjusted 95% bootstrap intervals. * marks global Holm p < 0.05 across all "
        "T1/T2 controller and effect-change tests. Negative residual changes favor PQEC; "
        "the reference point is zero by definition.",
        fontsize=8,
        color="#444444",
    )
    figure.subplots_adjust(
        left=0.13,
        right=0.99,
        top=0.90,
        bottom=0.11,
        hspace=0.38,
        wspace=0.28,
    )
    save_figure(figure, output_dir / "aer_v03_t1t2_sensitivity")


def plot_latency(results_dir: Path, output_dir: Path) -> None:
    config = json.loads(
        (results_dir / "pqec_aer_config_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    rows = read_csv(results_dir / "pqec_aer_sensitivity_paired_stats.csv")
    reference_id = str(config["sensitivity_analysis"]["reference_condition_id"])
    conditions = config["conditions"]
    latency_reference = next(
        float(condition["sweep_value_us"])
        for condition in conditions
        if str(condition["id"]) == reference_id
    )

    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.5))
    for axis, (metric, title, y_label) in zip(axes, METRICS):
        x_values: list[float] = []
        latency_labels: list[str] = []
        for position, condition in enumerate(conditions):
            latency_us = float(condition["sweep_value_us"])
            x_values.append(float(position))
            latency_labels.append(f"{latency_us:g}")
            if str(condition["id"]) == reference_id:
                plot_effect_change_axis(
                    axis,
                    {},
                    x_value=float(position),
                    reference=True,
                )
                continue
            effect = find_effect_change(rows, str(condition["id"]), metric)
            plot_effect_change_axis(
                axis,
                effect,
                x_value=float(position),
            )
        axis.axhline(0.0, color="#333333", linestyle="--", linewidth=0.9)
        axis.set_xticks(x_values, latency_labels)
        axis.set_title(title, loc="left", fontsize=10, weight="bold")
        axis.set_xlabel("Classical controller latency (µs)")
        axis.set_ylabel(y_label)
        axis.grid(axis="y", color="#dddddd", linewidth=0.65)
        axis.set_axisbelow(True)

    figure.suptitle(
        "PQEC v0.3 Aer: change in guarded-PQEC effect with feedback latency",
        x=0.03,
        ha="left",
        fontsize=13,
        weight="bold",
    )
    figure.text(
        0.03,
        0.015,
        f"Paired change versus {latency_reference:g} µs baseline; probe shots and acquisition time stay fixed. "
        "Bars are unadjusted 95% bootstrap intervals. * marks global Holm p < 0.05 across latency "
        "tests. Negative residual changes favor PQEC; reference point is zero by definition.",
        fontsize=8,
        color="#444444",
    )
    figure.subplots_adjust(left=0.11, right=0.99, top=0.84, bottom=0.19, wspace=0.37)
    save_figure(figure, output_dir / "aer_v03_latency_sensitivity")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--t1t2-results",
        type=Path,
        default=ROOT / "results" / "pqec_v03" / "aer_t1t2",
    )
    parser.add_argument(
        "--latency-results",
        type=Path,
        default=ROOT / "results" / "pqec_v03" / "aer_latency",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    t1t2_results = args.t1t2_results
    if not t1t2_results.is_absolute():
        t1t2_results = ROOT / t1t2_results
    latency_results = args.latency_results
    if not latency_results.is_absolute():
        latency_results = ROOT / latency_results
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    plot_t1t2(t1t2_results, output_dir)
    plot_latency(latency_results, output_dir)
    print(f"Wrote v0.3 sensitivity figures under {output_dir}")


if __name__ == "__main__":
    main()
