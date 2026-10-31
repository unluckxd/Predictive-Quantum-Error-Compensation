#!/usr/bin/env python3
"""Qiskit Aer pilot for probe-based compensation under device-noise channels."""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from time import perf_counter
from typing import Any

import matplotlib
import numpy as np
import qiskit
import qiskit_aer
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator
from qiskit_aer.noise import (
    NoiseModel,
    ReadoutError,
    depolarizing_error,
    thermal_relaxation_error,
)

from pqec_baselines import (
    BASELINE_METHODS,
    ErrorPredictor,
    create_baseline_predictor,
)
from pqec_controller import PredictiveCompensator


PREDICTOR_METHODS = (
    "predictive_linear",
    "predictive_guarded",
    *BASELINE_METHODS,
)
METHODS = ("no_compensation", "reactive_last_probe", *PREDICTOR_METHODS)
METRICS = (
    "final_state_fidelity",
    "rms_gate_residual_deg",
    "rms_cumulative_angle_residual_deg",
)
METHOD_LABELS = {
    "no_compensation": "No compensation",
    "reactive_last_probe": "Reactive (last probe)",
    "predictive_linear": "Rolling linear",
    "predictive_guarded": "Guarded PQEC",
    "moving_average": "Moving average",
    "exponential_moving_average": "Exponential moving average",
    "two_point_linear": "Two-point linear",
    "kalman_constant_velocity": "Constant-velocity Kalman",
}
SCENARIO_SEED_OFFSETS = {
    "shared_drift": 0,
    "white_noise": 100_003,
    "probe_mismatch": 200_003,
}


def _physical_error(
    *,
    t1_us: float,
    t2_us: float,
    gate_time_us: float,
    depolarizing_probability: float,
):
    error = thermal_relaxation_error(t1_us, t2_us, gate_time_us)
    if depolarizing_probability:
        error = error.compose(depolarizing_error(depolarizing_probability, 1))
    return error


def build_noise_model(
    noise_config: dict[str, Any],
    qubit_name: str,
    *,
    target_idle_us: float = 0.0,
) -> NoiseModel:
    """Create a per-qubit thermal, depolarizing, and probe-readout model."""
    qubit = noise_config[qubit_name]
    t1_us = float(qubit["t1_us"])
    t2_us = float(qubit["t2_us"])
    gate_time_us = float(qubit["gate_duration_us"])
    depolarizing_probability = float(qubit["depolarizing_probability"])
    if not (t1_us > 0.0 and t2_us > 0.0 and t2_us <= 2.0 * t1_us):
        raise ValueError(f"Invalid T1/T2 values for {qubit_name}.")
    if gate_time_us <= 0.0 or not 0.0 <= depolarizing_probability <= 1.0:
        raise ValueError(f"Invalid gate-noise values for {qubit_name}.")

    model = NoiseModel()
    gate_error = _physical_error(
        t1_us=t1_us,
        t2_us=t2_us,
        gate_time_us=gate_time_us,
        depolarizing_probability=depolarizing_probability,
    )
    gate_names = ("rx", "h", "s", "sdg") if qubit_name == "probe" else ("rx",)
    for gate_name in gate_names:
        model.add_quantum_error(gate_error, [gate_name], [0])

    if qubit_name == "probe":
        readout = noise_config["probe_readout"]
        p_1_given_0 = float(readout["p_1_given_0"])
        p_0_given_1 = float(readout["p_0_given_1"])
        if not (
            0.0 <= p_1_given_0 <= 1.0
            and 0.0 <= p_0_given_1 <= 1.0
        ):
            raise ValueError("Probe readout probabilities must be in [0, 1].")
        model.add_readout_error(
            ReadoutError(
                [
                    [1.0 - p_1_given_0, p_1_given_0],
                    [p_0_given_1, 1.0 - p_0_given_1],
                ]
            ),
            [0],
        )
    elif target_idle_us > 0.0:
        idle_error = thermal_relaxation_error(t1_us, t2_us, target_idle_us)
        model.add_quantum_error(idle_error, ["id"], [0])
    return model


def resolve_condition_noise(
    base_noise_config: dict[str, Any],
    condition: dict[str, Any],
) -> dict[str, Any]:
    """Apply explicit per-condition overrides without mutating the base model."""
    resolved = deepcopy(base_noise_config)
    overrides = condition.get("noise_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("noise_overrides must be a mapping of noise sections.")
    for section, section_overrides in overrides.items():
        if section not in resolved or not isinstance(resolved[section], dict):
            raise ValueError(f"Unknown noise section in condition override: {section}")
        if not isinstance(section_overrides, dict):
            raise ValueError(f"Overrides for {section} must be a mapping.")
        for parameter, value in section_overrides.items():
            if parameter not in resolved[section]:
                raise ValueError(
                    f"Unknown {section} parameter in condition override: {parameter}"
                )
            resolved[section][parameter] = value
    return resolved


def build_probe_circuit(
    error_rad: float,
    repetitions: int,
    *,
    measure: bool,
) -> QuantumCircuit:
    """Prepare |+y>, apply faulty Rx pulses, and measure along Y."""
    circuit = QuantumCircuit(1, 1 if measure else 0)
    circuit.h(0)
    circuit.s(0)
    for _ in range(repetitions):
        circuit.rx(math.pi / 2.0 + error_rad, 0)
    circuit.sdg(0)
    circuit.h(0)
    if measure:
        circuit.measure(0, 0)
    else:
        circuit.save_density_matrix(label="rho")
    return circuit


class ProbeResponseCalibration:
    """Monotone noisy-circuit lookup used to decode probe probabilities."""

    def __init__(
        self,
        error_grid_deg: np.ndarray,
        observed_p0_grid: np.ndarray,
    ) -> None:
        if len(error_grid_deg) < 3 or len(error_grid_deg) != len(observed_p0_grid):
            raise ValueError("Probe calibration grid must have at least 3 points.")
        differences = np.diff(observed_p0_grid)
        if not (
            np.all(differences >= -1e-10)
            or np.all(differences <= 1e-10)
        ):
            raise ValueError("The calibrated probe response is not monotone.")
        self.error_grid_deg = np.asarray(error_grid_deg, dtype=float)
        self.observed_p0_grid = np.asarray(observed_p0_grid, dtype=float)
        order = np.argsort(self.observed_p0_grid)
        self._probability_axis = self.observed_p0_grid[order]
        self._error_axis_deg = self.error_grid_deg[order]

    def estimate_error_deg(self, observed_p0: float) -> float:
        clipped = float(np.clip(observed_p0, 0.0, 1.0))
        return float(
            np.interp(clipped, self._probability_axis, self._error_axis_deg)
        )

    def measurement_variance_rad2(self, shots: int) -> float:
        if shots < 1:
            raise ValueError("shots must be positive.")
        error_rad = np.deg2rad(self.error_grid_deg)
        derivative = np.gradient(self.observed_p0_grid, error_rad)
        zero_index = int(np.argmin(np.abs(self.error_grid_deg)))
        slope = float(derivative[zero_index])
        p0 = float(self.observed_p0_grid[zero_index])
        if abs(slope) < 1e-12:
            raise ValueError("Probe calibration has no measurable slope at zero.")
        return max(1e-12, p0 * (1.0 - p0) / (shots * slope * slope))


def calibrate_probe_response(
    simulator: AerSimulator,
    noise_config: dict[str, Any],
    parameters: dict[str, Any],
    calibration_config: dict[str, Any],
) -> ProbeResponseCalibration:
    """Measure the expected noisy probe response with Aer's density-matrix mode."""
    points = int(calibration_config["points"])
    maximum_error_deg = float(calibration_config["maximum_error_deg"])
    error_grid_deg = np.linspace(-maximum_error_deg, maximum_error_deg, points)
    circuits = [
        build_probe_circuit(math.radians(float(error)), int(parameters["probe_repetitions"]), measure=False)
        for error in error_grid_deg
    ]
    result = simulator.run(
        circuits,
        shots=1,
        seed_simulator=int(calibration_config["seed"]),
    ).result()
    readout = noise_config["probe_readout"]
    p_1_given_0 = float(readout["p_1_given_0"])
    p_0_given_1 = float(readout["p_0_given_1"])
    observed_p0_grid: list[float] = []
    for circuit_index in range(len(circuits)):
        density = np.asarray(result.data(circuit_index)["rho"], dtype=complex)
        true_p0 = float(np.clip(density[0, 0].real, 0.0, 1.0))
        observed_p0_grid.append(
            (1.0 - p_1_given_0) * true_p0
            + p_0_given_1 * (1.0 - true_p0)
        )
    return ProbeResponseCalibration(
        error_grid_deg,
        np.asarray(observed_p0_grid, dtype=float),
    )


def checkpoint_cycles(cycles: int, interval: int) -> list[int]:
    """Return the startup observation and post-gate checkpoints used for feedback."""
    if cycles < 1 or interval < 1:
        raise ValueError("cycles and probe_interval must be positive.")
    return [-1, *range(interval - 1, cycles - 1, interval)]


def make_error_trajectories(
    scenario: str,
    cycles: int,
    seed: int,
    parameters: dict[str, Any],
    mismatch_scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate target and probe coherent errors in degrees for cycles -1..N-1."""
    rng = np.random.default_rng(seed)
    cycle_axis = np.arange(-1, cycles, dtype=float)
    initial_error = float(parameters["initial_error_deg"])
    drift_rate = float(parameters["drift_rate_deg_per_cycle"])

    if scenario in ("shared_drift", "probe_mismatch"):
        innovations = rng.normal(
            0.0,
            float(parameters["drift_innovation_sigma_deg"]),
            size=cycles,
        )
        random_walk = np.concatenate(([0.0], np.cumsum(innovations)))
        target = initial_error + drift_rate * cycle_axis + random_walk
        if scenario == "probe_mismatch":
            probe = target + mismatch_scale * (
                float(parameters["probe_mismatch_offset_deg"])
                + float(parameters["probe_mismatch_extra_drift_deg_per_cycle"])
                * cycle_axis
            )
        else:
            probe = target.copy()
        return target, probe
    if scenario == "white_noise":
        sigma = float(parameters["independent_control_noise_sigma_deg"])
        target = initial_error + rng.normal(0.0, sigma, size=cycles + 1)
        probe = initial_error + rng.normal(0.0, sigma, size=cycles + 1)
        return target, probe
    raise ValueError(f"Unknown trajectory scenario: {scenario}")


def measure_probe_record(
    simulator: AerSimulator,
    probe_errors_deg: np.ndarray,
    checkpoints: list[int],
    repetitions: int,
    shots: int,
    calibration: ProbeResponseCalibration,
    aer_seed: int,
) -> list[dict[str, float | int]]:
    """Run all checkpoint probe circuits with shot noise and asymmetric readout."""
    circuits = [
        build_probe_circuit(
            math.radians(float(probe_errors_deg[cycle + 1])),
            repetitions,
            measure=True,
        )
        for cycle in checkpoints
    ]
    result = simulator.run(
        circuits,
        shots=shots,
        seed_simulator=aer_seed,
    ).result()
    record: list[dict[str, float | int]] = []
    for circuit_index, cycle in enumerate(checkpoints):
        counts = result.get_counts(circuit_index)
        zero_count = int(counts.get("0", 0))
        observed_p0 = zero_count / shots
        estimate_deg = calibration.estimate_error_deg(observed_p0)
        record.append(
            {
                "observation_cycle": cycle,
                "zero_count": zero_count,
                "shots": shots,
                "observed_p0": observed_p0,
                "estimated_probe_error_deg": estimate_deg,
            }
        )
    return record


def make_predictor(
    method: str,
    parameters: dict[str, Any],
    calibration: ProbeResponseCalibration,
    shots: int,
) -> ErrorPredictor | None:
    window = int(parameters["predictor_window"])
    if method == "predictive_linear":
        return PredictiveCompensator(window)
    if method == "predictive_guarded":
        return PredictiveCompensator(
            window,
            trend_threshold=float(parameters["trend_threshold"]),
            min_trend_observations=int(parameters["min_trend_observations"]),
            anchor_to_latest=True,
        )
    if method in BASELINE_METHODS:
        return create_baseline_predictor(
            method,
            window=window,
            ema_alpha_per_cycle=float(parameters["ema_alpha_per_cycle"]),
            kalman_measurement_variance_rad2=calibration.measurement_variance_rad2(
                shots
            ),
            kalman_acceleration_sigma_rad_per_cycle2=math.radians(
                float(parameters["kalman_acceleration_sigma_deg_per_cycle2"])
            ),
            kalman_initial_velocity_sigma_rad_per_cycle=math.radians(
                float(parameters["kalman_initial_velocity_sigma_deg_per_cycle"])
            ),
        )
    return None


def controller_corrections(
    method: str,
    cycles: int,
    probe_record: list[dict[str, float | int]],
    parameters: dict[str, Any],
    calibration: ProbeResponseCalibration,
    shots: int,
) -> tuple[list[float], list[float]]:
    """Compute causal command corrections from the shared probe record."""
    predictor = make_predictor(method, parameters, calibration, shots)
    record_index = 0
    latest_probe_deg = 0.0
    corrections: list[float] = []
    forecasts: list[float] = []
    for target_cycle in range(cycles):
        while (
            record_index < len(probe_record)
            and int(probe_record[record_index]["observation_cycle"]) < target_cycle
        ):
            observation = probe_record[record_index]
            latest_probe_deg = float(observation["estimated_probe_error_deg"])
            if predictor is not None:
                predictor.observe(
                    int(observation["observation_cycle"]),
                    math.radians(latest_probe_deg),
                )
            record_index += 1
        if method == "no_compensation":
            correction_deg = 0.0
            forecast_deg = 0.0
        elif method == "reactive_last_probe":
            correction_deg = latest_probe_deg
            forecast_deg = correction_deg
        else:
            assert predictor is not None
            forecast_deg = math.degrees(
                predictor.predict_error(target_cycle)
            )
            correction_deg = forecast_deg
        corrections.append(correction_deg)
        forecasts.append(forecast_deg)
    return corrections, forecasts


def build_target_circuit(
    target_errors_deg: np.ndarray,
    corrections_deg: list[float],
    cycles: int,
    checkpoints: list[int],
    target_idle_us: float,
) -> QuantumCircuit:
    circuit = QuantumCircuit(1)
    active_post_checkpoints = {
        cycle for cycle in checkpoints if 0 <= cycle < cycles - 1
    }
    for target_cycle in range(cycles):
        if target_idle_us > 0.0 and target_cycle - 1 in active_post_checkpoints:
            circuit.id(0)
        actual_angle_rad = math.radians(
            90.0 + float(target_errors_deg[target_cycle + 1])
            - corrections_deg[target_cycle]
        )
        circuit.rx(actual_angle_rad, 0)
    circuit.save_density_matrix(label="rho")
    return circuit


def ideal_target_state(cycles: int) -> np.ndarray:
    circuit = QuantumCircuit(1)
    for _ in range(cycles):
        circuit.rx(math.pi / 2.0, 0)
    return np.asarray(Statevector.from_instruction(circuit).data, dtype=complex)


def score_density_matrix(
    density: np.ndarray,
    ideal_state: np.ndarray,
) -> tuple[float, float]:
    fidelity = float(np.real(np.vdot(ideal_state, density @ ideal_state)))
    purity = float(np.real(np.trace(density @ density)))
    return float(np.clip(fidelity, 0.0, 1.0)), float(np.clip(purity, 0.0, 1.0))


def paired_bootstrap_ci(
    differences: np.ndarray,
    seed: int,
    repetitions: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(differences), size=(repetitions, len(differences)))
    bootstrap_means = differences[indices].mean(axis=1)
    low, high = np.quantile(bootstrap_means, [0.025, 0.975])
    return float(low), float(high)


def paired_sign_flip_pvalue(
    differences: np.ndarray,
    seed: int,
    repetitions: int,
) -> float:
    rng = np.random.default_rng(seed)
    observed = abs(float(differences.mean()))
    signs = rng.integers(
        0, 2, size=(repetitions, len(differences)), dtype=np.int8
    )
    signs = signs.astype(np.float64) * 2.0 - 1.0
    null_means = np.abs((signs * differences[None, :]).mean(axis=1))
    exceedances = int(np.count_nonzero(null_means >= observed - 1e-15))
    return (exceedances + 1.0) / (repetitions + 1.0)


def holm_adjust(rows: list[dict[str, Any]], field: str) -> None:
    ordered = sorted(range(len(rows)), key=lambda i: float(rows[i][field]))
    count = len(ordered)
    running_max = 0.0
    for rank, index in enumerate(ordered):
        adjusted = min(1.0, (count - rank) * float(rows[index][field]))
        running_max = max(running_max, adjusted)
        rows[index]["holm_global_p"] = running_max


def paired_statistics(
    run_rows: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
    seed_schedule: dict[str, Any],
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    pairs: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = {}
    for row in run_rows:
        key = (
            str(row["condition_id"]),
            int(row["seed_block"]),
            int(row["trial"]),
        )
        pairs.setdefault(key, {})[str(row["method"])] = row

    output: list[dict[str, Any]] = []
    base_seed = int(seed_schedule["base_seed"])
    bootstrap_repetitions = int(parameters["bootstrap_repetitions"])
    sign_flip_repetitions = int(parameters["sign_flip_repetitions"])
    for condition_index, condition in enumerate(conditions):
        condition_id = str(condition["id"])
        for metric_index, metric in enumerate(METRICS):
            for method_index, method in enumerate(PREDICTOR_METHODS):
                differences: list[float] = []
                by_block: dict[int, list[float]] = {}
                for (pair_condition, block, _trial), method_rows in sorted(
                    pairs.items()
                ):
                    if pair_condition != condition_id:
                        continue
                    if not {
                        method,
                        "reactive_last_probe",
                    }.issubset(method_rows):
                        continue
                    delta = float(method_rows[method][metric]) - float(
                        method_rows["reactive_last_probe"][metric]
                    )
                    differences.append(delta)
                    by_block.setdefault(block, []).append(delta)
                if len(differences) < 2:
                    raise ValueError(
                        f"Insufficient paired runs for {condition_id}/{method}/{metric}."
                    )
                values = np.asarray(differences, dtype=float)
                stat_seed = (
                    base_seed
                    + int(seed_schedule["statistics_seed_offset"])
                    + condition_index
                    * int(seed_schedule["statistics_condition_stride"])
                    + method_index
                    * int(seed_schedule["statistics_method_stride"])
                    + metric_index
                    * int(seed_schedule["statistics_metric_stride"])
                )
                ci_low, ci_high = paired_bootstrap_ci(
                    values, stat_seed, bootstrap_repetitions
                )
                p_value = paired_sign_flip_pvalue(
                    values, stat_seed + 71_117, sign_flip_repetitions
                )
                row: dict[str, Any] = {
                    "condition_id": condition_id,
                    "scenario": condition["scenario"],
                    "metric": metric,
                    "comparison": f"{method} - reactive_last_probe",
                    "n_pairs": len(values),
                    "mean_difference": float(values.mean()),
                    "bootstrap_95ci_low": ci_low,
                    "bootstrap_95ci_high": ci_high,
                    "paired_sign_flip_p": p_value,
                    "holm_global_p": "",
                    "bootstrap_repetitions": bootstrap_repetitions,
                    "sign_flip_repetitions": sign_flip_repetitions,
                }
                for block, block_values in sorted(by_block.items()):
                    row[f"seed_block_{block}_mean_difference"] = mean(block_values)
                output.append(row)
    holm_adjust(output, "paired_sign_flip_p")
    return output


def paired_sensitivity_statistics(
    run_rows: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
    seed_schedule: dict[str, Any],
    parameters: dict[str, Any],
    sensitivity_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Test changes in each predictor's paired effect against a reference condition."""
    reference_condition_id = str(sensitivity_config["reference_condition_id"])
    by_condition_pair: dict[
        tuple[str, int, int], dict[str, dict[str, Any]]
    ] = {}
    for row in run_rows:
        key = (
            str(row["condition_id"]),
            int(row["seed_block"]),
            int(row["trial"]),
        )
        by_condition_pair.setdefault(key, {})[str(row["method"])] = row

    reference_pairs = {
        (block, trial): methods
        for (condition_id, block, trial), methods in by_condition_pair.items()
        if condition_id == reference_condition_id
    }
    non_reference = [
        condition
        for condition in conditions
        if str(condition["id"]) != reference_condition_id
    ]
    output: list[dict[str, Any]] = []
    base_seed = int(seed_schedule["base_seed"])
    bootstrap_repetitions = int(parameters["bootstrap_repetitions"])
    sign_flip_repetitions = int(parameters["sign_flip_repetitions"])
    seed_offset = int(sensitivity_config["statistics_seed_offset"])
    condition_stride = int(sensitivity_config["statistics_condition_stride"])
    method_stride = int(sensitivity_config["statistics_method_stride"])
    metric_stride = int(sensitivity_config["statistics_metric_stride"])

    for condition_index, condition in enumerate(non_reference):
        condition_id = str(condition["id"])
        condition_pairs = {
            (block, trial): methods
            for (pair_condition, block, trial), methods in by_condition_pair.items()
            if pair_condition == condition_id
        }
        common_keys = sorted(set(reference_pairs) & set(condition_pairs))
        for method_index, method in enumerate(PREDICTOR_METHODS):
            for metric_index, metric in enumerate(METRICS):
                differences = np.asarray(
                    [
                        (
                            float(condition_pairs[key][method][metric])
                            - float(condition_pairs[key]["reactive_last_probe"][metric])
                        )
                        - (
                            float(reference_pairs[key][method][metric])
                            - float(reference_pairs[key]["reactive_last_probe"][metric])
                        )
                        for key in common_keys
                        if {
                            method,
                            "reactive_last_probe",
                        }.issubset(condition_pairs[key])
                        and {
                            method,
                            "reactive_last_probe",
                        }.issubset(reference_pairs[key])
                    ],
                    dtype=np.float64,
                )
                if len(differences) < 2:
                    raise ValueError(
                        f"Insufficient matched sensitivity pairs for {condition_id}/{method}/{metric}."
                    )
                bootstrap_seed = (
                    base_seed
                    + seed_offset
                    + condition_index * condition_stride
                    + method_index * method_stride
                    + metric_index * metric_stride
                )
                sign_flip_seed = bootstrap_seed + 71_117
                ci_low, ci_high = paired_bootstrap_ci(
                    differences, bootstrap_seed, bootstrap_repetitions
                )
                p_value = paired_sign_flip_pvalue(
                    differences, sign_flip_seed, sign_flip_repetitions
                )
                row: dict[str, Any] = {
                    "reference_condition_id": reference_condition_id,
                    "condition_id": condition_id,
                    "scenario": condition["scenario"],
                    "metric": metric,
                    "comparison": (
                        f"({method} - reactive) at {condition_id} minus "
                        f"({method} - reactive) at {reference_condition_id}"
                    ),
                    "method": method,
                    "n_paired_trajectories": len(differences),
                    "mean_effect_change": float(differences.mean()),
                    "bootstrap_95ci_low": ci_low,
                    "bootstrap_95ci_high": ci_high,
                    "paired_sign_flip_p": p_value,
                    "holm_global_p": "",
                    "bootstrap_seed": bootstrap_seed,
                    "sign_flip_seed": sign_flip_seed,
                    "bootstrap_repetitions": bootstrap_repetitions,
                    "sign_flip_repetitions": sign_flip_repetitions,
                }
                for block in seed_schedule["seed_block_ids"]:
                    block_values = [
                        (
                            float(condition_pairs[key][method][metric])
                            - float(condition_pairs[key]["reactive_last_probe"][metric])
                        )
                        - (
                            float(reference_pairs[key][method][metric])
                            - float(reference_pairs[key]["reactive_last_probe"][metric])
                        )
                        for key in common_keys
                        if key[0] == int(block)
                        and {
                            method,
                            "reactive_last_probe",
                        }.issubset(condition_pairs[key])
                        and {
                            method,
                            "reactive_last_probe",
                        }.issubset(reference_pairs[key])
                    ]
                    row[f"seed_block_{block}_mean_effect_change"] = mean(block_values)
                output.append(row)

    holm_adjust(output, "paired_sign_flip_p")
    return output


def summarize(
    run_rows: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in conditions:
        condition_id = str(condition["id"])
        for method in METHODS:
            rows = [
                row
                for row in run_rows
                if row["condition_id"] == condition_id and row["method"] == method
            ]
            if not rows:
                continue
            prediction_errors = [
                float(row["prediction_mae_deg"])
                for row in rows
                if row["prediction_mae_deg"] != ""
            ]
            fidelities = [float(row["final_state_fidelity"]) for row in rows]
            output.append(
                {
                    "condition_id": condition_id,
                    "label": condition["label"],
                    "scenario": condition["scenario"],
                    "method": method,
                    "n_runs": len(rows),
                    "mean_final_state_fidelity": mean(fidelities),
                    "sd_final_state_fidelity": pstdev(fidelities),
                    "mean_target_final_purity": mean(
                        float(row["target_final_purity"]) for row in rows
                    ),
                    "mean_rms_gate_residual_deg": mean(
                        float(row["rms_gate_residual_deg"]) for row in rows
                    ),
                    "mean_rms_cumulative_angle_residual_deg": mean(
                        float(row["rms_cumulative_angle_residual_deg"])
                        for row in rows
                    ),
                    "mean_prediction_mae_deg": (
                        mean(prediction_errors) if prediction_errors else ""
                    ),
                    "probe_shots_per_checkpoint": rows[0][
                        "probe_shots_per_checkpoint"
                    ],
                    "probe_checkpoints": rows[0]["probe_checkpoints"],
                    "probe_acquisition_time_us_per_sequence": rows[0][
                        "probe_acquisition_time_us_per_sequence"
                    ],
                    "target_idle_time_us_per_sequence": rows[0][
                        "target_idle_time_us_per_sequence"
                    ],
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def validate_config(config: dict[str, Any]) -> None:
    parameters = config["parameters"]
    schedule = config["seed_schedule"]
    if int(parameters["cycles"]) < 4:
        raise ValueError("The Aer pilot requires at least 4 target cycles.")
    if int(parameters["probe_repetitions"]) % 4 != 1:
        raise ValueError("probe_repetitions must be 4k + 1 for signed Y sensing.")
    if int(parameters["shots"]) < 1 or int(parameters["probe_interval"]) < 1:
        raise ValueError("shots and probe_interval must be positive.")
    if not schedule["seed_block_ids"] or int(schedule["trials_per_seed_block"]) < 1:
        raise ValueError("At least one seed block and one trial are required.")
    condition_ids = [condition["id"] for condition in config["conditions"]]
    if len(condition_ids) != len(set(condition_ids)):
        raise ValueError("Condition identifiers must be unique.")
    sensitivity_config = config.get("sensitivity_analysis")
    if sensitivity_config is not None and str(
        sensitivity_config.get("reference_condition_id", "")
    ) not in condition_ids:
        raise ValueError("Sensitivity reference_condition_id must name a condition.")
    for condition in config["conditions"]:
        if condition["scenario"] not in SCENARIO_SEED_OFFSETS:
            raise ValueError(f"Unknown scenario in condition: {condition['scenario']}")
        if condition["scenario"] not in schedule.get(
            "scenario_seed_offsets",
            SCENARIO_SEED_OFFSETS,
        ):
            raise ValueError(
                f"Missing seed offset for scenario: {condition['scenario']}"
            )
        if int(condition.get("shots", parameters["shots"])) < 1:
            raise ValueError(f"Invalid shots count in condition {condition['id']}.")
        mismatch_scale = float(condition.get("probe_mismatch_scale", 0.0))
        if not 0.0 <= mismatch_scale <= 1.0:
            raise ValueError("probe_mismatch_scale must be in [0, 1].")
        condition_noise = resolve_condition_noise(config["noise"], condition)
        for qubit_name in ("target", "probe"):
            qubit = condition_noise[qubit_name]
            t1_us = float(qubit["t1_us"])
            t2_us = float(qubit["t2_us"])
            gate_duration_us = float(qubit["gate_duration_us"])
            depolarizing_probability = float(qubit["depolarizing_probability"])
            if not (t1_us > 0.0 and 0.0 < t2_us <= 2.0 * t1_us):
                raise ValueError(
                    f"Invalid T1/T2 values in condition {condition['id']} for {qubit_name}."
                )
            if gate_duration_us <= 0.0 or not 0.0 <= depolarizing_probability <= 1.0:
                raise ValueError(
                    f"Invalid gate-noise values in condition {condition['id']} for {qubit_name}."
                )
        latency_us = float(
            condition_noise["latency"]["classical_controller_latency_us"]
        )
        if not math.isfinite(latency_us) or latency_us < 0.0:
            raise ValueError(
                f"Invalid controller latency in condition {condition['id']}."
            )


def run_experiment(config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    parameters = config["parameters"]
    schedule = config["seed_schedule"]
    noise_config = config["noise"]
    experiment_started = perf_counter()
    output_dir = Path(config["outputs"]["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)

    cycles = int(parameters["cycles"])
    interval = int(parameters["probe_interval"])
    repetitions = int(parameters["probe_repetitions"])
    checkpoints = checkpoint_cycles(cycles, interval)
    gate_count_in_probe = repetitions + 4
    ideal_state = ideal_target_state(cycles)
    run_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    scenario_offsets = schedule.get(
        "scenario_seed_offsets",
        SCENARIO_SEED_OFFSETS,
    )

    for condition in config["conditions"]:
        condition_id = str(condition["id"])
        scenario = str(condition["scenario"])
        condition_noise = resolve_condition_noise(noise_config, condition)
        probe_noise = build_noise_model(condition_noise, "probe")
        probe_simulator = AerSimulator(
            method="density_matrix",
            noise_model=probe_noise,
            max_parallel_threads=1,
        )
        calibration = calibrate_probe_response(
            probe_simulator,
            condition_noise,
            parameters,
            config["probe_response_calibration"],
        )
        calibration_rows.extend(
            {
                "condition_id": condition_id,
                "probe_T1_us": condition_noise["probe"]["t1_us"],
                "probe_T2_us": condition_noise["probe"]["t2_us"],
                "probe_error_deg": float(error),
                "expected_observed_p0": float(probability),
            }
            for error, probability in zip(
                calibration.error_grid_deg,
                calibration.observed_p0_grid,
            )
        )
        shots = int(condition.get("shots", parameters["shots"]))
        mismatch_scale = float(condition.get("probe_mismatch_scale", 0.0))
        condition_checkpoints = checkpoints
        checkpoint_count = len(condition_checkpoints)
        target_wait_count = sum(
            0 <= cycle < cycles - 1 for cycle in condition_checkpoints
        )
        gate_duration_us = float(condition_noise["probe"]["gate_duration_us"])
        latency = condition_noise["latency"]
        shot_duration_us = (
            float(latency["reset_duration_us"])
            + gate_count_in_probe * gate_duration_us
            + float(latency["readout_duration_us"])
        )
        per_checkpoint_probe_time = shots * shot_duration_us
        target_idle_us = per_checkpoint_probe_time + float(
            latency["classical_controller_latency_us"]
        )
        target_idle_total_us = target_wait_count * target_idle_us
        target_noise = build_noise_model(
            condition_noise,
            "target",
            target_idle_us=target_idle_us,
        )
        target_simulator = AerSimulator(
            method="density_matrix",
            noise_model=target_noise,
            max_parallel_threads=1,
        )

        for seed_block in schedule["seed_block_ids"]:
            for trial in range(int(schedule["trials_per_seed_block"])):
                trajectory_seed = (
                    int(schedule["base_seed"])
                    + int(scenario_offsets[scenario])
                    + int(seed_block) * int(schedule["seed_block_stride"])
                    + trial * int(schedule["trial_stride"])
                )
                probe_seed = trajectory_seed + int(schedule["probe_seed_offset"])
                target_seed = trajectory_seed + int(schedule["target_seed_offset"])
                target_errors_deg, probe_errors_deg = make_error_trajectories(
                    scenario,
                    cycles,
                    trajectory_seed,
                    parameters,
                    mismatch_scale,
                )
                probe_record = measure_probe_record(
                    probe_simulator,
                    probe_errors_deg,
                    condition_checkpoints,
                    repetitions,
                    shots,
                    calibration,
                    probe_seed,
                )
                record_json = json.dumps(
                    probe_record,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                circuits: list[QuantumCircuit] = []
                per_method: dict[str, dict[str, Any]] = {}
                for method in METHODS:
                    method_idle_us = 0.0 if method == "no_compensation" else target_idle_us
                    corrections, forecasts = controller_corrections(
                        method,
                        cycles,
                        probe_record,
                        parameters,
                        calibration,
                        shots,
                    )
                    circuit = build_target_circuit(
                        target_errors_deg,
                        corrections,
                        cycles,
                        condition_checkpoints,
                        method_idle_us,
                    )
                    circuits.append(circuit)
                    residuals = [
                        float(target_errors_deg[cycle + 1]) - correction
                        for cycle, correction in enumerate(corrections)
                    ]
                    cumulative = np.cumsum(np.asarray(residuals, dtype=float))
                    forecast_mae = (
                        mean(
                            abs(
                                float(target_errors_deg[cycle + 1])
                                - forecasts[cycle]
                            )
                            for cycle in range(cycles)
                        )
                        if method in PREDICTOR_METHODS
                        else ""
                    )
                    per_method[method] = {
                        "corrections_deg": corrections,
                        "residuals_deg": residuals,
                        "rms_gate_residual_deg": math.sqrt(
                            mean(value * value for value in residuals)
                        ),
                        "rms_cumulative_angle_residual_deg": math.sqrt(
                            mean(float(value * value) for value in cumulative)
                        ),
                        "prediction_mae_deg": forecast_mae,
                    }

                aer_result = target_simulator.run(
                    circuits,
                    shots=1,
                    seed_simulator=target_seed,
                ).result()
                for method_index, method in enumerate(METHODS):
                    density = np.asarray(
                        aer_result.data(method_index)["rho"],
                        dtype=complex,
                    )
                    fidelity, purity = score_density_matrix(density, ideal_state)
                    metrics = per_method[method]
                    run_rows.append(
                        {
                            "condition_id": condition_id,
                            "scenario": scenario,
                            "seed_block": int(seed_block),
                            "trial": trial,
                            "trajectory_seed": trajectory_seed,
                            "probe_aer_seed": probe_seed,
                            "target_aer_seed": target_seed,
                            "method": method,
                            "final_state_fidelity": fidelity,
                            "target_final_purity": purity,
                            "rms_gate_residual_deg": metrics[
                                "rms_gate_residual_deg"
                            ],
                            "rms_cumulative_angle_residual_deg": metrics[
                                "rms_cumulative_angle_residual_deg"
                            ],
                            "prediction_mae_deg": metrics["prediction_mae_deg"],
                            "probe_shots_per_checkpoint": (
                                0 if method == "no_compensation" else shots
                            ),
                            "probe_checkpoints": (
                                0 if method == "no_compensation" else checkpoint_count
                            ),
                            "probe_shots_used_per_sequence": (
                                0
                                if method == "no_compensation"
                                else shots * checkpoint_count
                            ),
                            "probe_repetitions": repetitions,
                            "probe_interval": interval,
                            "probe_observations_json": (
                                "" if method == "no_compensation" else record_json
                            ),
                            "probe_shot_duration_us": shot_duration_us,
                            "probe_acquisition_time_us_per_sequence": (
                                0.0
                                if method == "no_compensation"
                                else checkpoint_count * per_checkpoint_probe_time
                            ),
                            "target_idle_time_us_per_checkpoint": method_idle_us,
                            "target_idle_time_us_per_sequence": (
                                0.0
                                if method == "no_compensation"
                                else target_idle_total_us
                            ),
                            "target_T1_us": condition_noise["target"]["t1_us"],
                            "target_T2_us": condition_noise["target"]["t2_us"],
                            "probe_T1_us": condition_noise["probe"]["t1_us"],
                            "probe_T2_us": condition_noise["probe"]["t2_us"],
                            "classical_controller_latency_us": latency[
                                "classical_controller_latency_us"
                            ],
                            "qiskit_version": qiskit.__version__,
                            "qiskit_aer_version": qiskit_aer.__version__,
                            "numpy_version": np.__version__,
                        }
                    )
                manifest_rows.append(
                    {
                        "condition_id": condition_id,
                        "scenario": scenario,
                        "seed_block": int(seed_block),
                        "trial": trial,
                        "trajectory_seed": trajectory_seed,
                        "probe_aer_seed": probe_seed,
                        "target_aer_seed": target_seed,
                        "numpy_version": np.__version__,
                        "numpy_bit_generator": type(
                            np.random.default_rng(trajectory_seed).bit_generator
                        ).__name__,
                        "qiskit_version": qiskit.__version__,
                        "qiskit_aer_version": qiskit_aer.__version__,
                        "probe_observation_cycles": json.dumps(
                            [int(item["observation_cycle"]) for item in probe_record]
                        ),
                    }
                )
        print(
            f"Completed {condition_id}: "
            f"{len(schedule['seed_block_ids']) * int(schedule['trials_per_seed_block'])} "
            "paired trials."
        )

    write_csv(output_dir / "pqec_aer_probe_calibration.csv", calibration_rows)
    paired_rows = paired_statistics(
        run_rows,
        config["conditions"],
        schedule,
        parameters,
    )
    sensitivity_rows: list[dict[str, Any]] = []
    sensitivity_config = config.get("sensitivity_analysis")
    if sensitivity_config is not None:
        sensitivity_rows = paired_sensitivity_statistics(
            run_rows,
            config["conditions"],
            schedule,
            parameters,
            sensitivity_config,
        )
        # Keep the complete hypothesis family for this sweep under one Holm correction.
        holm_adjust(paired_rows + sensitivity_rows, "paired_sign_flip_p")
        write_csv(
            output_dir / "pqec_aer_sensitivity_paired_stats.csv",
            sensitivity_rows,
        )
    summary_rows = summarize(run_rows, config["conditions"])
    write_csv(output_dir / "pqec_aer_runs.csv", run_rows)
    write_csv(output_dir / "pqec_aer_summary.csv", summary_rows)
    write_csv(output_dir / "pqec_aer_paired_stats.csv", paired_rows)
    write_csv(output_dir / "pqec_aer_seed_manifest.csv", manifest_rows)
    (output_dir / "pqec_aer_config_snapshot.json").write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )
    environment = {
        "python": __import__("sys").version,
        "qiskit": qiskit.__version__,
        "qiskit_aer": qiskit_aer.__version__,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "aer_method": "density_matrix",
        "elapsed_wall_seconds": perf_counter() - experiment_started,
    }
    (output_dir / "pqec_aer_environment.json").write_text(
        json.dumps(environment, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "summary": summary_rows,
        "paired": paired_rows,
        "sensitivity_paired": sensitivity_rows,
        "run_count": len(run_rows),
        "elapsed_seconds": environment["elapsed_wall_seconds"],
    }


def print_results(result: dict[str, Any]) -> None:
    print(
        "\nAer noise-model results (methods are paired against reactive last probe):"
    )
    for row in result["paired"]:
        if row["metric"] not in (
            "final_state_fidelity",
            "rms_cumulative_angle_residual_deg",
        ):
            continue
        print(
            f"{row['condition_id']:30s} {row['comparison']:38s} "
            f"{row['metric']:38s} "
            f"delta={float(row['mean_difference']):+.6g} "
            f"95% CI [{float(row['bootstrap_95ci_low']):+.6g}, "
            f"{float(row['bootstrap_95ci_high']):+.6g}] "
            f"Holm p={float(row['holm_global_p']):.5g}"
        )
    print(
        f"\nSaved {result['run_count']:,} per-method trial rows in "
        f"{result['elapsed_seconds']:.1f} seconds."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PQEC Qiskit Aer noise-model pilot."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/aer_noise_v01.json"),
        help="JSON configuration file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = run_experiment(config)
    print_results(result)


if __name__ == "__main__":
    main()
