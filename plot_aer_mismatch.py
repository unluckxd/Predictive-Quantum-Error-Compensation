#!/usr/bin/env python3
"""Plot the Aer v0.2 guarded-PQEC effect across probe-mismatch levels."""

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
DEFAULT_RESULTS_DIR = ROOT / "results" / "aer_noise_v02"
DEFAULT_OUTPUT_DIR = ROOT / "figures"
COMPARISON = "predictive_guarded - reactive_last_probe"
METRICS = (
    (
        "final_state_fidelity",
        "Final target-state fidelity difference",
        "Fidelity difference (higher is better)",
    ),
    (
        "rms_cumulative_angle_residual_deg",
        "Cumulative coherent-angle residual",
        "RMS cumulative-angle difference (degrees; lower is better)",
    ),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-prefix", default="aer_noise_v02_mismatch")
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
    mismatch_conditions = sorted(
        (
            condition
            for condition in config["conditions"]
            if condition["scenario"] == "probe_mismatch"
        ),
        key=lambda condition: float(condition["probe_mismatch_scale"]),
    )
    paired_rows = read_csv(results_dir / "pqec_aer_paired_stats.csv")

    matplotlib.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    figure, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    figure.suptitle(
        "Aer v0.2: guarded predictor sensitivity to probe mismatch",
        x=0.02,
        ha="left",
        fontsize=14,
        weight="bold",
    )
    for axis, (metric, title, y_label) in zip(axes, METRICS):
        values: list[float] = []
        lows: list[float] = []
        highs: list[float] = []
        p_values: list[float] = []
        mismatch_percent: list[float] = []
        for condition in mismatch_conditions:
            row = next(
                row
                for row in paired_rows
                if row["condition_id"] == condition["id"]
                and row["comparison"] == COMPARISON
                and row["metric"] == metric
            )
            values.append(float(row["mean_difference"]))
            lows.append(float(row["bootstrap_95ci_low"]))
            highs.append(float(row["bootstrap_95ci_high"]))
            p_values.append(float(row["holm_global_p"]))
            mismatch_percent.append(100.0 * float(condition["probe_mismatch_scale"]))

        axis.errorbar(
            mismatch_percent,
            values,
            yerr=[
                [estimate - low for estimate, low in zip(values, lows)],
                [high - estimate for estimate, high in zip(values, highs)],
            ],
            fmt="o-",
            color="#276FBF",
            markersize=6,
            capsize=4,
            linewidth=1.7,
            label="Guarded PQEC − reactive",
        )
        axis.axhline(0.0, color="#333333", linestyle="--", linewidth=1)
        axis.set_title(title, loc="left", fontsize=11, weight="bold")
        axis.set_ylabel(y_label)
        axis.set_xticks(mismatch_percent, [f"{value:.0f}%" for value in mismatch_percent])
        axis.grid(axis="y", color="#dddddd", linewidth=0.7)
        axis.set_axisbelow(True)
        for x, y, p_value in zip(mismatch_percent, values, p_values):
            vertical_offset = 8 if y <= 0 else -14
            axis.annotate(
                f"Holm p={p_value:.3g}",
                (x, y),
                xytext=(0, vertical_offset),
                textcoords="offset points",
                ha="center",
                va="bottom" if y <= 0 else "top",
                fontsize=7.5,
                color="#333333",
            )
    axes[-1].set_xlabel("Probe-to-target mismatch scale")
    figure.text(
        0.02,
        0.015,
        "Points are paired means; bars are unadjusted 95% bootstrap intervals. Holm p-values adjust the 144-test Aer v0.2 family.",
        fontsize=8,
        color="#444444",
    )
    figure.subplots_adjust(left=0.14, right=0.98, top=0.90, bottom=0.10, hspace=0.33)
    output_dir.mkdir(parents=True, exist_ok=True)
    for extension in ("svg", "png"):
        figure.savefig(
            output_dir / f"{args.output_prefix}.{extension}",
            dpi=240,
            bbox_inches="tight",
        )
        if extension == "svg":
            normalize_svg_whitespace(output_dir / f"{args.output_prefix}.{extension}")
    plt.close(figure)
    print(f"Wrote {output_dir / (args.output_prefix + '.svg')} and PNG counterpart")


if __name__ == "__main__":
    main()
