#!/usr/bin/env python3
"""Create reproducible Matplotlib figures from the analytic experiment CSVs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator

from plotting_utils import normalize_svg_whitespace


FULL_BUDGET_ID = "4096shots_every1"
GUARDED_COMPARISON = "predictive_guarded - reactive_last_probe"
SCENARIO_ORDER = ("slow_drift", "white_noise", "probe_mismatch")
SCENARIO_LABELS = {
    "slow_drift": "Shared slow drift",
    "white_noise": "Independent white noise",
    "probe_mismatch": "Probe mismatch",
}
METRIC_LABELS = {
    "final_state_fidelity": "Final state fidelity difference",
    "rms_gate_error_deg": "RMS gate-angle error difference (degrees)",
    "rms_cumulative_error_deg": "RMS cumulative-error difference (degrees)",
}
BUDGET_LABELS = {
    "64shots_every8": "64 shots / every 8 gates",
    "128shots_every4": "128 shots / every 4 gates",
    "128shots_every1": "128 shots / every gate",
    "512shots_every4": "512 shots / every 4 gates",
    "4096shots_every1": "4,096 shots / every gate",
}
COLORS = {
    "reactive": "#277DA1",
    "pqec": "#F3722C",
    "good": "#238B73",
    "bad": "#C43D40",
    "neutral": "#667788",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def paired_row(
    rows: list[dict[str, str]],
    budget_id: str,
    scenario: str,
    metric: str,
) -> dict[str, str]:
    for row in rows:
        if (
            row["budget_id"] == budget_id
            and row["comparison"] == GUARDED_COMPARISON
            and row["scenario"] == scenario
            and row["metric"] == metric
        ):
            return row
    raise ValueError(f"Missing paired result: {budget_id}/{scenario}/{metric}")


def effect_color(row: dict[str, str], metric: str) -> str:
    estimate = float(row["mean_difference"])
    low = float(row["bootstrap_95ci_low"])
    high = float(row["bootstrap_95ci_high"])
    if low <= 0.0 <= high:
        return COLORS["neutral"]
    improves = estimate > 0.0 if metric == "final_state_fidelity" else estimate < 0.0
    return COLORS["good"] if improves else COLORS["bad"]


def save_figure(figure: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, bbox_inches="tight")
    normalize_svg_whitespace(output)
    figure.savefig(output.with_suffix(".png"), dpi=240, bbox_inches="tight")
    plt.close(figure)


def plot_full_budget_effects(
    paired: list[dict[str, str]],
    output: Path,
) -> None:
    metrics = (
        "final_state_fidelity",
        "rms_gate_error_deg",
        "rms_cumulative_error_deg",
    )
    figure, axes = plt.subplots(3, 3, figsize=(15, 9), sharex=False)
    for column, scenario in enumerate(SCENARIO_ORDER):
        for row_index, metric in enumerate(metrics):
            axis = axes[row_index, column]
            result = paired_row(paired, FULL_BUDGET_ID, scenario, metric)
            estimate = float(result["mean_difference"])
            low = float(result["bootstrap_95ci_low"])
            high = float(result["bootstrap_95ci_high"])
            color = effect_color(result, metric)
            axis.errorbar(
                estimate,
                0,
                xerr=[[estimate - low], [high - estimate]],
                fmt="o",
                markersize=6,
                capsize=4,
                linewidth=2,
                color=color,
            )
            span = max(high - low, abs(estimate), 1e-12)
            axis.set_xlim(min(0.0, low) - 0.18 * span, max(0.0, high) + 0.18 * span)
            axis.axvline(0.0, color="#333333", linestyle="--", linewidth=1)
            axis.set_yticks([])
            axis.grid(axis="x", color="#dddddd", linewidth=0.7)
            axis.set_axisbelow(True)
            axis.set_title(
                f"{SCENARIO_LABELS[scenario]}\n{METRIC_LABELS[metric]}",
                fontsize=10,
                weight="bold",
            )
            p_value = float(result["holm_global_all_budgets_p"])
            axis.text(
                0.02,
                0.92,
                f"Δ={estimate:+.3g}; global Holm p={p_value:.3g}",
                transform=axis.transAxes,
                va="top",
                fontsize=8,
            )
            axis.set_xlabel(
                "Paired difference (fidelity)" if metric == "final_state_fidelity"
                else "Paired difference (degrees)"
            )
            axis.xaxis.set_major_locator(MaxNLocator(nbins=3))
            axis.ticklabel_format(
                axis="x", style="sci", scilimits=(-2, 2), useMathText=True
            )
            axis.tick_params(axis="x", labelsize=8)
    figure.suptitle(
        "Guarded PQEC minus reactive last-probe control\n"
        "4,096 shots per checkpoint; 64 target operations; 200 paired runs per scenario",
        x=0.02,
        ha="left",
        fontsize=14,
        weight="bold",
    )
    figure.text(
        0.02,
        0.005,
        "Positive fidelity and negative error differences favor PQEC. Bars are unadjusted paired bootstrap intervals; p-values use global Holm adjustment across all budgets.",
        fontsize=8,
        color="#444444",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.91))
    save_figure(figure, output)


def bootstrap_mean_ci(
    values: list[float],
    seed: int,
    repetitions: int = 5000,
) -> tuple[float, float, float]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(array), size=(repetitions, len(array)))
    bootstrap_means = array[indices].mean(axis=1)
    low, high = np.quantile(bootstrap_means, [0.025, 0.975])
    return float(array.mean()), float(low), float(high)


def plot_probe_mismatch_failure(
    run_rows: list[dict[str, str]],
    paired_rows: list[dict[str, str]],
    output: Path,
) -> None:
    metrics = (
        ("final_state_fidelity", "Final state fidelity", "Higher is better"),
        ("rms_cumulative_error_deg", "RMS cumulative angle error (degrees)", "Lower is better"),
    )
    methods = (
        ("reactive_last_probe", "Reactive last probe", COLORS["reactive"]),
        ("predictive_guarded", "Guarded PQEC", COLORS["pqec"]),
    )
    figure, axes = plt.subplots(1, 2, figsize=(11, 5))
    for axis, (metric, title, preference) in zip(axes, metrics):
        x = np.arange(len(methods))
        estimates: list[float] = []
        lows: list[float] = []
        highs: list[float] = []
        for method_index, (method, _label, _color) in enumerate(methods):
            values = [
                float(row[metric])
                for row in run_rows
                if row["scenario"] == "probe_mismatch"
                and row["method"] == method
            ]
            estimate, low, high = bootstrap_mean_ci(
                values,
                9101 + method_index + (0 if metric == "final_state_fidelity" else 100),
            )
            estimates.append(estimate)
            lows.append(low)
            highs.append(high)
        for index, method in enumerate(methods):
            axis.errorbar(
                x[index],
                estimates[index],
                yerr=[
                    [estimates[index] - lows[index]],
                    [highs[index] - estimates[index]],
                ],
                fmt="o",
                color=method[2],
                ecolor=method[2],
                markersize=7,
                capsize=5,
                linewidth=1.4,
            )
        axis.set_xticks(x, [method[1] for method in methods], rotation=8, ha="right")
        axis.set_title(title, weight="bold")
        axis.set_ylabel("Mean across paired runs")
        lower = min(lows)
        upper = max(highs)
        pad = max((upper - lower) * 0.14, 1e-6)
        axis.set_ylim(lower - pad, upper + pad)
        axis.grid(axis="y", color="#dddddd", linewidth=0.7)
        axis.set_axisbelow(True)
        pair = paired_row(
            paired_rows,
            FULL_BUDGET_ID,
            "probe_mismatch",
            metric,
        )
        axis.text(
            0.03,
            0.97,
            f"{preference}\nPaired Δ (PQEC − reactive) = "
            f"{float(pair['mean_difference']):+.4g}\n"
            f"Global Holm p = {float(pair['holm_global_all_budgets_p']):.4f}",
            transform=axis.transAxes,
            va="top",
            fontsize=8,
            bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "alpha": 0.85},
        )
    figure.suptitle(
        "Probe-mismatch failure case: reactive controller versus guarded PQEC",
        x=0.02,
        ha="left",
        weight="bold",
        fontsize=13,
    )
    figure.text(
        0.02,
        0.01,
        "Bars show marginal means and unadjusted bootstrap intervals; the reported comparison is paired within each run.",
        fontsize=8,
        color="#444444",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.92))
    save_figure(figure, output)


def plot_budget_tradeoff(
    summary_rows: list[dict[str, str]],
    paired_rows: list[dict[str, str]],
    output: Path,
) -> None:
    shots_by_budget = {
        row["budget_id"]: int(row["probe_shots_available_per_run"])
        for row in summary_rows
        if row["scenario"] == "slow_drift"
        and row["method"] == "predictive_guarded"
    }
    effects: dict[str, dict[str, dict[str, str]]] = {
        "final_state_fidelity": {},
        "rms_cumulative_error_deg": {},
    }
    for row in paired_rows:
        if (
            row["comparison"] == GUARDED_COMPARISON
            and row["scenario"] == "slow_drift"
            and row["metric"] in effects
        ):
            effects[row["metric"]][row["budget_id"]] = row
    budget_ids = sorted(shots_by_budget, key=lambda item: shots_by_budget[item])
    tick_labels = {
        "64shots_every8": "64 shots / 8 gates\n576 total",
        "128shots_every4": "128 shots / 4 gates\n2,176 total",
        "128shots_every1": "128 shots / 1 gate\n8,320 total",
        "512shots_every4": "512 shots / 4 gates\n8,704 total",
        "4096shots_every1": "4,096 shots / 1 gate\n266,240 total",
    }
    palette = {
        "512shots_every4": COLORS["good"],
        "128shots_every4": COLORS["pqec"],
        "4096shots_every1": COLORS["reactive"],
        "128shots_every1": COLORS["neutral"],
        "64shots_every8": COLORS["neutral"],
    }
    figure, axes = plt.subplots(1, 2, figsize=(13, 5))
    budget_positions = {budget: index for index, budget in enumerate(budget_ids)}
    for axis, metric in zip(
        axes,
        ("final_state_fidelity", "rms_cumulative_error_deg"),
    ):
        for budget in budget_ids:
            result = effects[metric][budget]
            position = budget_positions[budget]
            estimate = float(result["mean_difference"])
            low = float(result["bootstrap_95ci_low"])
            high = float(result["bootstrap_95ci_high"])
            color = palette.get(budget, COLORS["reactive"])
            axis.errorbar(
                position,
                estimate,
                yerr=[[estimate - low], [high - estimate]],
                fmt="o",
                markersize=6,
                capsize=4,
                linewidth=1.6,
                color=color,
            )
            axis.annotate(
                f"Holm p={float(result['holm_global_all_budgets_p']):.3g}",
                (position, estimate),
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                fontsize=7.5,
                color=color,
            )
        axis.set_xticks(range(len(budget_ids)))
        axis.set_xticklabels([tick_labels[budget] for budget in budget_ids], fontsize=7.5)
        axis.set_xlim(-0.4, len(budget_ids) - 0.6)
        axis.axhline(0.0, color="#333333", linestyle="--", linewidth=1)
        axis.grid(axis="y", color="#dddddd", linewidth=0.7)
        axis.set_axisbelow(True)
        axis.set_xlabel("Shots per checkpoint / interval; total sequence shots below")
        axis.set_ylabel(
            METRIC_LABELS[metric]
        )
        axis.set_title(METRIC_LABELS[metric], weight="bold")
    figure.suptitle(
        "Measurement-budget trade-off under shared slow drift",
        x=0.02,
        ha="left",
        fontsize=13,
        weight="bold",
    )
    figure.text(
        0.02,
        0.01,
        "Guarded PQEC minus reactive control; intervals are unadjusted. Global Holm correction covers 90 budget/method/scenario/metric tests.",
        fontsize=8,
        color="#444444",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.92))
    save_figure(figure, output)


def parse_args() -> argparse.Namespace:
    project_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=project_dir / "results")
    parser.add_argument("--output-dir", type=Path, default=project_dir / "figures")
    args = parser.parse_args()
    if not args.results_dir.is_absolute():
        args.results_dir = project_dir / args.results_dir
    if not args.output_dir.is_absolute():
        args.output_dir = project_dir / args.output_dir
    return args


def main() -> None:
    args = parse_args()
    paired = read_csv(args.results_dir / "pqec_budget_sweep_paired_stats.csv")
    summary = read_csv(args.results_dir / "pqec_budget_sweep_summary.csv")
    runs = read_csv(args.results_dir / "pqec_single_qubit_runs.csv")
    plot_full_budget_effects(
        paired,
        args.output_dir / "pqec_vs_reactive_full_budget.svg",
    )
    plot_probe_mismatch_failure(
        runs,
        paired,
        args.output_dir / "probe_mismatch_failure.svg",
    )
    plot_budget_tradeoff(
        summary,
        paired,
        args.output_dir / "budget_tradeoff.svg",
    )
    print(f"Wrote six figure files to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
