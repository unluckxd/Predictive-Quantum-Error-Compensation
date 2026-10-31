#!/usr/bin/env python3
"""Create reproducible, dependency-free SVG figures from the archived CSVs."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path
from statistics import mean
from xml.sax.saxutils import escape


COLORS = {
    "ink": "#17212B",
    "muted": "#5D6B78",
    "grid": "#D9E0E7",
    "panel": "#F6F8FA",
    "reactive": "#277DA1",
    "pqec": "#F3722C",
    "good": "#238B73",
    "bad": "#C43D40",
    "neutral": "#667788",
    "highlight": "#E9F5F1",
}

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
    "rms_gate_error_deg": "RMS gate-angle error difference (deg)",
    "rms_cumulative_error_deg": "RMS cumulative error difference (deg)",
}
BUDGET_LABELS = {
    "64shots_every8": "64 shots / every 8 gates",
    "128shots_every4": "128 shots / every 4 gates",
    "128shots_every1": "128 shots / every gate",
    "512shots_every4": "512 shots / every 4 gates",
    "4096shots_every1": "4096 shots / every gate",
}


class Svg:
    def __init__(self, width: int, height: int, title: str, description: str):
        self.width = width
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            'role="img">',
            f"<title>{escape(title)}</title>",
            f"<desc>{escape(description)}</desc>",
            f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        ]

    @staticmethod
    def _n(value: float) -> str:
        return f"{value:.2f}"

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        fill: str,
        stroke: str = "none",
        radius: float = 0.0,
    ) -> None:
        self.parts.append(
            f'<rect x="{self._n(x)}" y="{self._n(y)}" '
            f'width="{self._n(width)}" height="{self._n(height)}" '
            f'rx="{self._n(radius)}" fill="{fill}" stroke="{stroke}"/>'
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
        width: float = 1.0,
        dash: str | None = None,
    ) -> None:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{self._n(x1)}" y1="{self._n(y1)}" '
            f'x2="{self._n(x2)}" y2="{self._n(y2)}" '
            f'stroke="{color}" stroke-width="{self._n(width)}"'
            f'{dash_attr}/>'
        )

    def circle(
        self,
        cx: float,
        cy: float,
        radius: float,
        fill: str,
        stroke: str = "#FFFFFF",
        stroke_width: float = 2.0,
    ) -> None:
        self.parts.append(
            f'<circle cx="{self._n(cx)}" cy="{self._n(cy)}" '
            f'r="{self._n(radius)}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{self._n(stroke_width)}"/>'
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: int = 16,
        color: str = COLORS["ink"],
        anchor: str = "start",
        weight: str = "normal",
    ) -> None:
        escaped = escape(str(value))
        self.parts.append(
            f'<text x="{self._n(x)}" y="{self._n(y)}" '
            f'font-family="Arial, Helvetica, sans-serif" font-size="{size}px" '
            f'font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}">{escaped}</text>'
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.parts.append("</svg>")
        path.write_text("\n".join(self.parts), encoding="utf-8")


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


def effect_axis_range(row: dict[str, str]) -> tuple[float, float]:
    low = min(0.0, float(row["bootstrap_95ci_low"]))
    high = max(0.0, float(row["bootstrap_95ci_high"]))
    span = max(high - low, abs(float(row["mean_difference"])), 1e-12)
    return low - 0.14 * span, high + 0.14 * span


def format_effect(value: float, metric: str) -> str:
    if metric == "final_state_fidelity":
        return f"{value:+.2e}"
    return f"{value:+.3f} deg"


def plot_full_budget_effects(
    paired: list[dict[str, str]], output: Path
) -> None:
    width, height = 1500, 960
    svg = Svg(
        width,
        height,
        "Guarded PQEC versus reactive control: full measurement budget",
        "Paired mean differences and 95 percent bootstrap confidence intervals "
        "for final state fidelity, RMS gate-angle error, and RMS cumulative error "
        "in three simulation scenarios.",
    )
    svg.text(42, 48, "Guarded PQEC vs reactive last-probe control", 28, weight="bold")
    svg.text(
        42,
        78,
        "Full budget: 4096 shots per checkpoint, 64 Rx gates, 200 paired runs per scenario",
        16,
        COLORS["muted"],
    )
    panel_xs = (35, 535, 1035)
    panel_width = 465
    panel_top = 112
    panel_height = 785
    metrics = (
        "final_state_fidelity",
        "rms_gate_error_deg",
        "rms_cumulative_error_deg",
    )

    for scenario_index, scenario in enumerate(SCENARIO_ORDER):
        panel_x = panel_xs[scenario_index]
        svg.rect(panel_x, panel_top, panel_width, panel_height, COLORS["panel"], "#E3E8ED", 12)
        svg.text(
            panel_x + 22,
            panel_top + 38,
            SCENARIO_LABELS[scenario],
            20,
            weight="bold",
        )
        for metric_index, metric in enumerate(metrics):
            row = paired_row(paired, FULL_BUDGET_ID, scenario, metric)
            y_base = panel_top + 70 + metric_index * 223
            x_left = panel_x + 38
            x_right = panel_x + panel_width - 28
            y_mark = y_base + 55
            axis_low, axis_high = effect_axis_range(row)

            def scale(value: float) -> float:
                return x_left + (value - axis_low) / (axis_high - axis_low) * (x_right - x_left)

            svg.text(panel_x + 22, y_base + 20, METRIC_LABELS[metric], 15, weight="bold")
            svg.line(x_left, y_mark, x_right, y_mark, COLORS["grid"], 2)
            x_zero = scale(0.0)
            svg.line(x_zero, y_mark - 33, x_zero, y_mark + 33, COLORS["ink"], 1.5, "5 4")
            low = float(row["bootstrap_95ci_low"])
            high = float(row["bootstrap_95ci_high"])
            estimate = float(row["mean_difference"])
            color = effect_color(row, metric)
            svg.line(scale(low), y_mark, scale(high), y_mark, color, 4)
            svg.line(scale(low), y_mark - 8, scale(low), y_mark + 8, color, 2)
            svg.line(scale(high), y_mark - 8, scale(high), y_mark + 8, color, 2)
            svg.circle(scale(estimate), y_mark, 8, color)
            svg.text(x_left, y_mark + 28, f"{axis_low:.1e}" if metric == "final_state_fidelity" else f"{axis_low:.3f}", 11, COLORS["muted"])
            svg.text(x_zero, y_mark + 28, "0", 11, COLORS["ink"], "middle", "bold")
            svg.text(x_right, y_mark + 28, f"{axis_high:.1e}" if metric == "final_state_fidelity" else f"{axis_high:.3f}", 11, COLORS["muted"], "end")
            svg.text(
                panel_x + 22,
                y_base + 112,
                f"Delta = {format_effect(estimate, metric)}",
                14,
                color,
                weight="bold",
            )
            svg.text(
                panel_x + 22,
                y_base + 136,
                f"95% paired CI: [{format_effect(low, metric)}, {format_effect(high, metric)}]",
                12,
                COLORS["muted"],
            )
            svg.text(
                panel_x + 22,
                y_base + 159,
                f"Global Holm p (90 tests): {float(row['holm_global_all_budgets_p']):.4f}",
                12,
                COLORS["muted"],
            )

    svg.line(50, 925, 92, 925, COLORS["ink"], 1.5, "5 4")
    svg.text(102, 931, "No difference", 13, COLORS["muted"])
    svg.line(255, 925, 297, 925, COLORS["good"], 4)
    svg.circle(276, 925, 6, COLORS["good"])
    svg.text(307, 931, "Favors PQEC", 13, COLORS["muted"])
    svg.line(445, 925, 487, 925, COLORS["bad"], 4)
    svg.circle(466, 925, 6, COLORS["bad"])
    svg.text(497, 931, "Favors reactive", 13, COLORS["muted"])
    svg.text(
        760,
        931,
        "Each scenario has its own scale; positive fidelity and negative error differences favor PQEC.",
        12,
        COLORS["muted"],
    )
    svg.save(output)


def percentile(sorted_values: list[float], probability: float) -> float:
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def bootstrap_mean_ci(
    values: list[float], seed: int, repetitions: int = 5000
) -> tuple[float, float, float]:
    rng = random.Random(seed)
    count = len(values)
    means = [
        mean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(repetitions)
    ]
    means.sort()
    return mean(values), percentile(means, 0.025), percentile(means, 0.975)


def draw_bar_panel(
    svg: Svg,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    metric: str,
    run_rows: list[dict[str, str]],
    paired: dict[str, str],
    seed_base: int,
) -> None:
    svg.rect(x, y, width, height, COLORS["panel"], "#E3E8ED", 12)
    svg.text(x + 22, y + 36, title, 19, weight="bold")
    methods = (
        ("reactive_last_probe", "Reactive", COLORS["reactive"]),
        ("predictive_guarded", "Guarded PQEC", COLORS["bad"]),
    )
    metric_values: dict[str, list[float]] = {}
    intervals: dict[str, tuple[float, float, float]] = {}
    for index, (method, _label, _color) in enumerate(methods):
        values = [
            float(row[metric])
            for row in run_rows
            if row["scenario"] == "probe_mismatch" and row["method"] == method
        ]
        if not values:
            raise ValueError(f"No probe-mismatch rows for {method}/{metric}")
        metric_values[method] = values
        intervals[method] = bootstrap_mean_ci(values, seed_base + index)

    if metric == "final_state_fidelity":
        axis_low, axis_high = 0.82, 0.86
        tick_values = (0.82, 0.83, 0.84, 0.85, 0.86)
        formatter = lambda value: f"{value:.2f}"
        paired_delta_label = "Paired delta (PQEC - reactive)"
        difference = float(paired["mean_difference"])
        ci_low = float(paired["bootstrap_95ci_low"])
        ci_high = float(paired["bootstrap_95ci_high"])
        stat_label = (
            f"{difference:+.5f} [{ci_low:+.5f}, {ci_high:+.5f}]"
        )
    else:
        axis_low, axis_high = 20.0, 24.0
        tick_values = (20.0, 21.0, 22.0, 23.0, 24.0)
        formatter = lambda value: f"{value:.0f}"
        paired_delta_label = "Paired delta (PQEC - reactive), degrees"
        difference = float(paired["mean_difference"])
        ci_low = float(paired["bootstrap_95ci_low"])
        ci_high = float(paired["bootstrap_95ci_high"])
        stat_label = f"{difference:+.3f} [{ci_low:+.3f}, {ci_high:+.3f}]"

    plot_left = x + 72
    plot_right = x + width - 28
    plot_top = y + 77
    plot_bottom = y + height - 145

    def scale_y(value: float) -> float:
        return plot_bottom - (value - axis_low) / (axis_high - axis_low) * (plot_bottom - plot_top)

    for tick in tick_values:
        tick_y = scale_y(tick)
        svg.line(plot_left, tick_y, plot_right, tick_y, COLORS["grid"], 1)
        svg.text(plot_left - 10, tick_y + 4, formatter(tick), 11, COLORS["muted"], "end")

    center_positions = (plot_left + 110, plot_left + 300)
    bar_width = 66
    for (method, label, color), center in zip(methods, center_positions):
        estimate, low, high = intervals[method]
        top_y = scale_y(estimate)
        svg.rect(center - bar_width / 2, top_y, bar_width, plot_bottom - top_y, color, "none", 4)
        low_y = scale_y(low)
        high_y = scale_y(high)
        svg.line(center, high_y, center, low_y, COLORS["ink"], 2)
        svg.line(center - 12, low_y, center + 12, low_y, COLORS["ink"], 2)
        svg.line(center - 12, high_y, center + 12, high_y, COLORS["ink"], 2)
        value_label = f"{estimate:.4f}" if metric == "final_state_fidelity" else f"{estimate:.2f} deg"
        svg.text(center, top_y - 12, value_label, 13, color, "middle", "bold")
        svg.text(center, plot_bottom + 25, label, 13, COLORS["ink"], "middle")

    svg.text(x + 22, y + height - 83, paired_delta_label, 12, COLORS["muted"])
    svg.text(x + 22, y + height - 59, stat_label, 13, COLORS["bad"], weight="bold")
    svg.text(
        x + 22,
        y + height - 34,
        f"Global Holm p (90 tests): {float(paired['holm_global_all_budgets_p']):.4f}",
        12,
        COLORS["muted"],
    )


def plot_probe_mismatch_failure(
    summary_rows: list[dict[str, str]],
    run_rows: list[dict[str, str]],
    paired_rows: list[dict[str, str]],
    output: Path,
) -> None:
    width, height = 1320, 760
    svg = Svg(
        width,
        height,
        "Probe mismatch failure scenario",
        "Under a probe drift of 0.03 degrees per cycle and logical drift of 0.01 degrees per cycle, guarded PQEC has lower final fidelity and higher accumulated error than the reactive controller.",
    )
    svg.rect(0, 0, width, 115, "#FFF1F1")
    svg.text(42, 48, "Failure mode: probe mismatch", 28, COLORS["bad"], weight="bold")
    svg.text(
        42,
        80,
        "Probe drift = 0.03 deg/cycle; target-qubit drift = 0.01 deg/cycle; probe offset = 0.20 deg",
        16,
        COLORS["ink"],
    )
    final_pair = paired_row(
        paired_rows, FULL_BUDGET_ID, "probe_mismatch", "final_state_fidelity"
    )
    cumulative_pair = paired_row(
        paired_rows, FULL_BUDGET_ID, "probe_mismatch", "rms_cumulative_error_deg"
    )
    draw_bar_panel(
        svg,
        35,
        138,
        610,
        570,
        "Final state fidelity (higher is better)",
        "final_state_fidelity",
        run_rows,
        final_pair,
        9101,
    )
    draw_bar_panel(
        svg,
        675,
        138,
        610,
        570,
        "RMS cumulative error (lower is better)",
        "rms_cumulative_error_deg",
        run_rows,
        cumulative_pair,
        9201,
    )
    svg.text(
        42,
        740,
        "Bars: per-method mean with marginal 95% bootstrap CI. The reported test uses paired within-run differences.",
        13,
        COLORS["muted"],
    )
    svg.save(output)


def plot_budget_tradeoff(
    summary_rows: list[dict[str, str]],
    paired_rows: list[dict[str, str]],
    output: Path,
) -> None:
    width, height = 1400, 760
    svg = Svg(
        width,
        height,
        "PQEC versus reactive control across measurement budgets",
        "Paired guarded-PQEC minus reactive-controller effects under shared slow drift, across five probe budgets. Error bars show unadjusted 95 percent bootstrap intervals; labels report global Holm-adjusted p values across 90 hypotheses.",
    )
    svg.text(42, 48, "Measurement-budget trade-off under shared slow drift", 27, weight="bold")
    svg.text(
        42,
        78,
        "Guarded PQEC minus reactive last-probe control; paired runs, n = 200 per budget",
        16,
        COLORS["muted"],
    )
    shots_by_budget: dict[str, int] = {}
    for row in summary_rows:
        if (
            row["scenario"] == "slow_drift"
            and row["method"] == "predictive_guarded"
        ):
            shots_by_budget[row["budget_id"]] = int(row["probe_shots_available_per_run"])

    effects: dict[str, dict[str, dict[str, str]]] = {}
    for metric in ("final_state_fidelity", "rms_cumulative_error_deg"):
        effects[metric] = {}
        for row in paired_rows:
            if (
                row["comparison"] == GUARDED_COMPARISON
                and row["scenario"] == "slow_drift"
                and row["metric"] == metric
            ):
                effects[metric][row["budget_id"]] = row

    budget_ids = sorted(shots_by_budget, key=lambda item: shots_by_budget[item])
    palette = {
        "512shots_every4": COLORS["good"],
        "128shots_every4": COLORS["pqec"],
        "4096shots_every1": COLORS["reactive"],
        "128shots_every1": COLORS["neutral"],
        "64shots_every8": COLORS["neutral"],
    }
    label_offsets = {
        "128shots_every1": (-24, -33),
        "512shots_every4": (32, -54),
        "128shots_every4": (0, -31),
        "64shots_every8": (0, -31),
        "4096shots_every1": (0, -31),
    }

    for panel_index, metric in enumerate(("final_state_fidelity", "rms_cumulative_error_deg")):
        panel_x = 35 + panel_index * 680
        panel_y = 112
        panel_width = 650
        panel_height = 570
        svg.rect(panel_x, panel_y, panel_width, panel_height, COLORS["panel"], "#E3E8ED", 12)
        svg.text(
            panel_x + 22,
            panel_y + 36,
            METRIC_LABELS[metric],
            18,
            weight="bold",
        )
        plot_left = panel_x + 66
        plot_right = panel_x + panel_width - 30
        plot_top = panel_y + 92
        plot_bottom = panel_y + panel_height - 110
        logs = [math.log10(shots_by_budget[budget]) for budget in budget_ids]
        x_min = min(logs) - 0.20
        x_max = max(logs) + 0.20

        def scale_x(value: float) -> float:
            return plot_left + (math.log10(value) - x_min) / (x_max - x_min) * (plot_right - plot_left)

        all_lows = [float(effects[metric][budget]["bootstrap_95ci_low"]) for budget in budget_ids]
        all_highs = [float(effects[metric][budget]["bootstrap_95ci_high"]) for budget in budget_ids]
        y_min = min(0.0, min(all_lows))
        y_max = max(0.0, max(all_highs))
        span = max(y_max - y_min, 1e-12)
        y_min -= 0.12 * span
        y_max += 0.12 * span

        def scale_y(value: float) -> float:
            return plot_bottom - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top)

        for tick_index in range(5):
            tick_value = y_min + (y_max - y_min) * tick_index / 4
            tick_y = scale_y(tick_value)
            svg.line(plot_left, tick_y, plot_right, tick_y, COLORS["grid"], 1)
            label = f"{tick_value:.1e}" if metric == "final_state_fidelity" else f"{tick_value:.3f}"
            svg.text(plot_left - 9, tick_y + 4, label, 10, COLORS["muted"], "end")
        zero_y = scale_y(0.0)
        svg.line(plot_left, zero_y, plot_right, zero_y, COLORS["ink"], 1.5, "5 4")

        for budget in budget_ids:
            row = effects[metric][budget]
            x = scale_x(shots_by_budget[budget])
            estimate = float(row["mean_difference"])
            low = float(row["bootstrap_95ci_low"])
            high = float(row["bootstrap_95ci_high"])
            color = palette.get(budget, COLORS["reactive"])
            svg.line(x, scale_y(low), x, scale_y(high), color, 3)
            svg.line(x - 7, scale_y(low), x + 7, scale_y(low), color, 2)
            svg.line(x - 7, scale_y(high), x + 7, scale_y(high), color, 2)
            svg.circle(x, scale_y(estimate), 7, color)
            dx, dy = label_offsets[budget]
            svg.text(x + dx, scale_y(estimate) + dy, BUDGET_LABELS[budget], 10, color, "middle", "bold")
            svg.text(
                x + dx,
                scale_y(estimate) + dy + 14,
                f"global p={float(row['holm_global_all_budgets_p']):.3f}",
                9,
                COLORS["muted"],
                "middle",
            )

        for power in range(3, 6):
            value = 10**power
            if 10**x_min <= value <= 10**x_max:
                x = scale_x(value)
                svg.line(x, plot_top, x, plot_bottom, COLORS["grid"], 1, "2 5")
                svg.text(x, plot_bottom + 22, f"{value:,}", 11, COLORS["muted"], "middle")
        svg.text((plot_left + plot_right) / 2, plot_bottom + 44, "Available probe shots per sequence (log scale)", 12, COLORS["muted"], "middle")
        svg.text(panel_x + 22, panel_y + panel_height - 23, "Positive fidelity / negative error favors PQEC; CIs are unadjusted.", 10, COLORS["muted"])

    svg.text(
        42,
        725,
        "Global Holm adjustment covers 90 hypotheses (5 budgets x 18 method/scenario/metric comparisons).",
        13,
        COLORS["muted"],
    )
    svg.save(output)


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
    plot_full_budget_effects(paired, args.output_dir / "pqec_vs_reactive_full_budget.svg")
    plot_probe_mismatch_failure(
        summary,
        runs,
        paired,
        args.output_dir / "probe_mismatch_failure.svg",
    )
    plot_budget_tradeoff(
        summary,
        paired,
        args.output_dir / "budget_tradeoff.svg",
    )
    print(f"Wrote three figures to {args.output_dir}")


if __name__ == "__main__":
    main()
