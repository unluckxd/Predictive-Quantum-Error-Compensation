#!/usr/bin/env python3
"""One-qubit PQEC experiment: forecast slow coherent rotation drift."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from statistics import mean, pstdev
from time import perf_counter
from typing import Iterable

from pqec_baselines import (
    BASELINE_METHODS,
    ErrorPredictor,
    create_baseline_predictor,
)
from pqec_controller import PredictiveCompensator

try:
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Pauli, Statevector

    HAS_QISKIT = True
except ImportError:
    QuantumCircuit = None
    Pauli = None
    Statevector = None
    HAS_QISKIT = False


SCENARIOS = ("slow_drift", "white_noise", "probe_mismatch")
SCENARIO_SEED_OFFSETS = {
    "slow_drift": 0,
    "white_noise": 100_003,
    "probe_mismatch": 200_003,
}
SCENARIO_LABELS = {
    "slow_drift": "Shared slow drift",
    "white_noise": "Independent white noise",
    "probe_mismatch": "Probe mismatch",
}
METHODS = (
    "no_compensation",
    "static_calibration",
    "reactive_last_probe",
    "predictive_linear",
    "predictive_guarded",
    "randomized_compiling",
    "oracle_upper_bound",
)
PREDICTIVE_METHODS = (
    "predictive_linear",
    "predictive_guarded",
    *BASELINE_METHODS,
)
ROBUSTNESS_METHODS = (*METHODS, *BASELINE_METHODS)
METHOD_LABELS = {
    "no_compensation": "No compensation",
    "static_calibration": "Static calibration",
    "reactive_last_probe": "Reactive (last probe)",
    "predictive_linear": "Predictive (linear)",
    "predictive_guarded": "Predictive (trend guarded)",
    "randomized_compiling": "Randomized compiling",
    "oracle_upper_bound": "Oracle (upper bound)",
    "moving_average": "Moving average",
    "exponential_moving_average": "Exponential moving average",
    "two_point_linear": "Two-point linear",
    "kalman_constant_velocity": "Constant-velocity Kalman",
    "ideal_reference": "Ideal reference",
}


def degrees(value: float) -> float:
    return math.radians(value)


def state_after_rx_sequence(angles: Iterable[float]) -> tuple[complex, complex]:
    """Simulate |0> followed by a sequence of Rx gates."""
    angles = tuple(float(angle) for angle in angles)
    if HAS_QISKIT:
        circuit = QuantumCircuit(1)
        for angle in angles:
            circuit.rx(angle, 0)
        state = Statevector.from_instruction(circuit).data
        return complex(state[0]), complex(state[1])

    a0, a1 = 1.0 + 0.0j, 0.0 + 0.0j
    for angle in angles:
        cosine = math.cos(angle / 2.0)
        minus_i_sine = -1j * math.sin(angle / 2.0)
        a0, a1 = cosine * a0 + minus_i_sine * a1, minus_i_sine * a0 + cosine * a1
    return a0, a1


def state_fidelity(
    reference: tuple[complex, complex], actual: tuple[complex, complex]
) -> float:
    overlap = sum(ref.conjugate() * got for ref, got in zip(reference, actual))
    return min(1.0, max(0.0, abs(overlap) ** 2))


def probe_probability_zero(error_rad: float, repetitions: int) -> float:
    """Return P(0) after repeated faulty Rx(pi/2) pulses and a Y measurement."""
    if repetitions % 4 != 1:
        raise ValueError("The signed probe sequence requires repetitions = 4k + 1.")
    if HAS_QISKIT:
        circuit = probe_circuit(error_rad, repetitions)
        circuit.sdg(0)
        circuit.h(0)
        measured_z_state = Statevector.from_instruction(circuit).data
        return float(abs(measured_z_state[0]) ** 2)
    return (1.0 - math.sin(repetitions * error_rad)) / 2.0


def probe_circuit(error_rad: float, repetitions: int) -> QuantumCircuit:
    """Build the probe pulse sequence before its final measurement-basis rotation."""
    circuit = QuantumCircuit(1)
    circuit.h(0)
    circuit.s(0)
    for _ in range(repetitions):
        circuit.rx(math.pi / 2.0 + error_rad, 0)
    return circuit


def direct_y_probability_zero(error_rad: float, repetitions: int) -> float:
    """Compute P(+1) for Y directly, independent of the basis-rotation path."""
    if HAS_QISKIT:
        state = Statevector.from_instruction(probe_circuit(error_rad, repetitions))
        expectation_y = float(state.expectation_value(Pauli("Y")).real)
    else:
        amplitude_0 = 1.0 / math.sqrt(2.0)
        amplitude_1 = 1j / math.sqrt(2.0)
        for _ in range(repetitions):
            angle = math.pi / 2.0 + error_rad
            cosine = math.cos(angle / 2.0)
            minus_i_sine = -1j * math.sin(angle / 2.0)
            amplitude_0, amplitude_1 = (
                cosine * amplitude_0 + minus_i_sine * amplitude_1,
                minus_i_sine * amplitude_0 + cosine * amplitude_1,
            )
        expectation_y = 2.0 * (amplitude_0.conjugate() * amplitude_1).imag
    return (1.0 + expectation_y) / 2.0


def verify_probe_basis(repetitions: int) -> float:
    """Check the circuit's Y readout against direct Y expectation and the formula."""
    worst_difference = 0.0
    for error_deg in (-2.0, -0.2, 0.0, 0.2, 2.0):
        error_rad = degrees(error_deg)
        basis_rotated = probe_probability_zero(error_rad, repetitions)
        direct_y = direct_y_probability_zero(error_rad, repetitions)
        analytic = (1.0 - math.sin(repetitions * error_rad)) / 2.0
        worst_difference = max(
            worst_difference,
            abs(basis_rotated - direct_y),
            abs(basis_rotated - analytic),
        )
    if worst_difference > 1e-10:
        raise RuntimeError(
            f"Probe Y-basis verification failed: max probability error "
            f"{worst_difference:.3g}"
        )
    return worst_difference


def measure_probe_error(
    error_rad: float,
    shots: int,
    repetitions: int,
    rng: object,
    readout_error: float,
    readout_calibration: float,
) -> float:
    """Estimate signed over-rotation from finite-shot probe measurements."""
    probability_zero = probe_probability_zero(error_rad, repetitions)
    observed_probability_zero = (
        readout_error + (1.0 - 2.0 * readout_error) * probability_zero
    )
    binomial = getattr(rng, "binomial", None)
    if callable(binomial):
        zero_count = int(binomial(shots, observed_probability_zero))
    else:
        random_sample = getattr(rng, "random")
        zero_count = sum(
            random_sample() < observed_probability_zero for _ in range(shots)
        )
    measured_probability_zero = zero_count / shots
    if readout_calibration < 0.5:
        measured_probability_zero = (
            measured_probability_zero - readout_calibration
        ) / (1.0 - 2.0 * readout_calibration)
    measured_probability_zero = min(1.0, max(0.0, measured_probability_zero))
    measured_signal = 2.0 * measured_probability_zero - 1.0
    measured_signal = min(1.0, max(-1.0, measured_signal))
    return -math.asin(measured_signal) / repetitions


def make_trajectory(
    scenario: str,
    cycles: int,
    seed: int,
    base_error_deg: float,
    drift_rate_deg: float,
    drift_jitter_deg: float,
    white_noise_sigma_deg: float,
    probe_mismatch_offset_deg: float,
    probe_mismatch_drift_rate_deg: float,
    probe_local_noise_sigma_deg: float,
    probe_readout_error: float,
    probe_readout_calibration_error: float,
    probe_mismatch_readout_error: float,
    probe_mismatch_scale: float = 1.0,
    probe_readout_mismatch_scale: float = 1.0,
) -> tuple[float, list[float], float, list[float], float, float]:
    """Generate separate logical and probe errors for one modeled condition."""
    logical_rng = random.Random(seed)
    probe_rng = random.Random(seed + 5_000_117)
    base = degrees(base_error_deg)

    if scenario == "slow_drift":
        drift_per_cycle = degrees(drift_rate_deg)
        jitter = degrees(drift_jitter_deg)

        def error_at(cycle: int) -> float:
            return base + drift_per_cycle * cycle + logical_rng.gauss(0.0, jitter)

        logical_startup = error_at(-1)
        logical_errors = [error_at(cycle) for cycle in range(cycles)]
        probe_startup = logical_startup
        probe_errors = logical_errors.copy()
        actual_readout_error = probe_readout_error
        readout_calibration = probe_readout_calibration_error

    elif scenario == "white_noise":
        white_sigma = degrees(white_noise_sigma_deg)

        def independent_error(rng: random.Random) -> float:
            return base + rng.gauss(0.0, white_sigma)

        logical_startup = independent_error(logical_rng)
        logical_errors = [independent_error(logical_rng) for _ in range(cycles)]
        probe_startup = independent_error(probe_rng)
        probe_errors = [independent_error(probe_rng) for _ in range(cycles)]
        actual_readout_error = probe_readout_error
        readout_calibration = probe_readout_calibration_error

    elif scenario == "probe_mismatch":
        if not math.isfinite(probe_mismatch_scale) or not 0.0 <= probe_mismatch_scale <= 1.0:
            raise ValueError("probe_mismatch_scale must be in [0, 1].")
        if (
            not math.isfinite(probe_readout_mismatch_scale)
            or not 0.0 <= probe_readout_mismatch_scale <= 1.0
        ):
            raise ValueError("probe_readout_mismatch_scale must be in [0, 1].")
        logical_drift = degrees(drift_rate_deg)
        logical_jitter = degrees(drift_jitter_deg)
        probe_drift = degrees(probe_mismatch_drift_rate_deg)
        probe_offset = degrees(probe_mismatch_offset_deg)
        probe_jitter = degrees(probe_local_noise_sigma_deg)

        def logical_error_at(cycle: int) -> float:
            return (
                base
                + logical_drift * cycle
                + logical_rng.gauss(0.0, logical_jitter)
            )

        def probe_error_at(cycle: int) -> float:
            return (
                base
                + probe_offset
                + probe_drift * cycle
                + probe_rng.gauss(0.0, probe_jitter)
            )

        logical_startup = logical_error_at(-1)
        logical_errors = [logical_error_at(cycle) for cycle in range(cycles)]
        independent_probe_startup = probe_error_at(-1)
        independent_probe_errors = [
            probe_error_at(cycle) for cycle in range(cycles)
        ]
        if probe_mismatch_scale == 1.0:
            # Keep the archived v0.2 mismatch trajectory bit-for-bit unchanged.
            probe_startup = independent_probe_startup
            probe_errors = independent_probe_errors
        elif probe_mismatch_scale == 0.0:
            probe_startup = logical_startup
            probe_errors = logical_errors.copy()
        else:
            probe_startup = logical_startup + probe_mismatch_scale * (
                independent_probe_startup - logical_startup
            )
            probe_errors = [
                target_error
                + probe_mismatch_scale * (probe_error - target_error)
                for target_error, probe_error in zip(
                    logical_errors, independent_probe_errors
                )
            ]
        actual_readout_error = probe_readout_error + probe_readout_mismatch_scale * (
            probe_mismatch_readout_error - probe_readout_error
        )
        readout_calibration = probe_readout_calibration_error

    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    return (
        logical_startup,
        logical_errors,
        probe_startup,
        probe_errors,
        actual_readout_error,
        readout_calibration,
    )


def make_probe_record(
    startup_error: float,
    probe_errors: list[float],
    shots: int,
    repetitions: int,
    probe_interval: int,
    seed: int,
    readout_error: float,
    readout_calibration: float,
    rng: object | None = None,
) -> tuple[float, list[tuple[int, float]]]:
    """Measure only an auxiliary probe qubit, never the target qubit."""
    if rng is None:
        rng = random.Random(seed)
    startup_reading = measure_probe_error(
        startup_error,
        shots,
        repetitions,
        rng,
        readout_error,
        readout_calibration,
    )
    post_gate_readings: list[tuple[int, float]] = []
    for cycle in range(probe_interval - 1, len(probe_errors), probe_interval):
        reading = measure_probe_error(
            probe_errors[cycle],
            shots,
            repetitions,
            rng,
            readout_error,
            readout_calibration,
        )
        post_gate_readings.append((cycle, reading))
    return startup_reading, post_gate_readings


def correction_for(
    method: str,
    cycle: int,
    startup_reading: float,
    post_gate_readings: list[tuple[int, float]],
    predictor_window: int,
    predictor: ErrorPredictor | None = None,
) -> tuple[float, float | None]:
    """Return the applied correction and, for PQEC, the forecast value."""
    if method == "no_compensation" or method == "randomized_compiling":
        return 0.0, None
    available = [(-1, startup_reading)] + [
        (time, value) for time, value in post_gate_readings if time < cycle
    ]

    if method == "static_calibration":
        return startup_reading, None
    if method == "reactive_last_probe":
        return available[-1][1], None
    if method in PREDICTIVE_METHODS:
        if predictor is None:
            predictor = PredictiveCompensator(
                predictor_window,
                trend_threshold=2.0 if method == "predictive_guarded" else 0.0,
                min_trend_observations=4,
                anchor_to_latest=method == "predictive_guarded",
            )
            for time, value in available:
                predictor.observe(time, value)
        prediction = predictor.predict_error(cycle)
        return prediction, prediction
    raise ValueError(f"Unknown method: {method}")


def metrics_for_residuals(
    residuals: list[float], target_angle: float, ideal_state: tuple[complex, complex]
) -> dict[str, float]:
    actual_state = state_after_rx_sequence(
        target_angle + residual for residual in residuals
    )
    cumulative_error = 0.0
    prefix_fidelities: list[float] = []
    cumulative_errors: list[float] = []
    gate_fidelities: list[float] = []
    for error in residuals:
        cumulative_error += error
        cumulative_errors.append(cumulative_error)
        # Exact for this experiment: all ideal and error rotations share the X axis.
        prefix_fidelities.append(math.cos(cumulative_error / 2.0) ** 2)
        gate_fidelities.append((2.0 + math.cos(error)) / 3.0)

    return {
        "mean_prefix_state_fidelity": mean(prefix_fidelities),
        "final_state_fidelity": state_fidelity(ideal_state, actual_state),
        "mean_gate_fidelity": mean(gate_fidelities),
        "rms_gate_error_deg": math.degrees(
            math.sqrt(mean(error * error for error in residuals))
        ),
        "rms_cumulative_error_deg": math.degrees(
            math.sqrt(mean(error * error for error in cumulative_errors))
        ),
        "final_accumulated_error_deg": math.degrees(cumulative_error),
    }


def combine_repeat_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    combined: dict[str, float] = {}
    for key in rows[0]:
        values = [row[key] for row in rows]
        if key in ("rms_gate_error_deg", "rms_cumulative_error_deg"):
            combined[key] = math.sqrt(mean(value * value for value in values))
        else:
            combined[key] = mean(values)
    return combined


def evaluate_trial(
    scenario: str,
    seed_block: int,
    trial: int,
    config: argparse.Namespace,
    ideal_state: tuple[complex, complex],
    methods: tuple[str, ...] | None = None,
    measurement_rng_backend: str = "python",
) -> list[dict[str, object]]:
    seed = (
        config.seed
        + seed_block * 1_000_003
        + trial * 1009
        + SCENARIO_SEED_OFFSETS[scenario]
    )
    (
        startup_error,
        gate_errors,
        probe_startup_error,
        probe_errors,
        actual_readout_error,
        readout_calibration,
    ) = make_trajectory(
        scenario,
        config.cycles,
        seed,
        config.base_error_deg,
        config.drift_rate_deg,
        config.drift_jitter_deg,
        config.white_noise_sigma_deg,
        config.probe_mismatch_offset_deg,
        config.probe_mismatch_drift_rate_deg,
        config.probe_local_noise_sigma_deg,
        config.probe_readout_error,
        config.probe_readout_calibration_error,
        config.probe_mismatch_readout_error,
        getattr(config, "probe_mismatch_scale", 1.0),
        getattr(config, "probe_readout_mismatch_scale", 1.0),
    )
    probe_measurement_seed = seed + 700_001
    if measurement_rng_backend == "python":
        probe_rng: object | None = None
    elif measurement_rng_backend == "numpy":
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "NumPy sampling requires numpy; install requirements-robustness.txt."
            ) from exc
        probe_rng = np.random.default_rng(probe_measurement_seed)
    else:
        raise ValueError(f"Unknown measurement RNG backend: {measurement_rng_backend}")
    startup_reading, post_gate_readings = make_probe_record(
        probe_startup_error,
        probe_errors,
        config.shots,
        config.probe_repetitions,
        config.probe_interval,
        probe_measurement_seed,
        actual_readout_error,
        readout_calibration,
        rng=probe_rng,
    )

    max_abs_probe_error = max(
        abs(probe_startup_error), *(abs(value) for value in probe_errors)
    )
    if max_abs_probe_error * config.probe_repetitions >= math.pi / 2.0:
        raise ValueError(
            "The Ramsey probe is outside its unambiguous range. Reduce "
            "--probe-repetitions or the modeled error."
        )

    rows: list[dict[str, object]] = []
    selected_methods = METHODS if methods is None else methods
    for method in selected_methods:
        repeated_metrics: list[dict[str, float]] = []
        prediction_errors: list[float] = []
        repeat_count = config.rc_compilations if method == "randomized_compiling" else 1
        controller_elapsed = 0.0

        for repeat in range(repeat_count):
            residuals: list[float] = []
            rc_rng = random.Random(seed + 900_001 + repeat * 97)
            if method == "predictive_linear":
                predictor = PredictiveCompensator(config.predictor_window)
            elif method == "predictive_guarded":
                predictor = PredictiveCompensator(
                    config.predictor_window,
                    trend_threshold=config.trend_threshold,
                    min_trend_observations=config.min_trend_observations,
                    anchor_to_latest=True,
                )
            elif method in BASELINE_METHODS:
                calibration_error = config.probe_readout_calibration_error
                shot_variance = 1.0 / (
                    config.probe_repetitions**2
                    * config.shots
                    * (1.0 - 2.0 * calibration_error) ** 2
                )
                local_noise_scale = (
                    getattr(config, "probe_mismatch_scale", 1.0)
                    if scenario == "probe_mismatch"
                    else 0.0
                )
                local_noise_variance = degrees(
                    config.probe_local_noise_sigma_deg * local_noise_scale
                ) ** 2
                predictor = create_baseline_predictor(
                    method,
                    window=config.predictor_window,
                    ema_alpha_per_cycle=getattr(
                        config, "ema_alpha_per_cycle", 0.25
                    ),
                    kalman_measurement_variance_rad2=(
                        shot_variance + local_noise_variance
                    ),
                    kalman_acceleration_sigma_rad_per_cycle2=degrees(
                        getattr(
                            config,
                            "kalman_acceleration_sigma_deg_per_cycle2",
                            0.002,
                        )
                    ),
                    kalman_initial_velocity_sigma_rad_per_cycle=degrees(
                        getattr(
                            config,
                            "kalman_initial_velocity_sigma_deg_per_cycle",
                            0.05,
                        )
                    ),
                )
            else:
                predictor = None
            next_probe_reading = 0
            if predictor is not None:
                predictor.observe(-1, startup_reading)
            controller_started = perf_counter()
            for cycle, actual_error in enumerate(gate_errors):
                if predictor is not None:
                    while (
                        next_probe_reading < len(post_gate_readings)
                        and post_gate_readings[next_probe_reading][0] < cycle
                    ):
                        probe_cycle, probe_value = post_gate_readings[
                            next_probe_reading
                        ]
                        predictor.observe(probe_cycle, probe_value)
                        next_probe_reading += 1
                if method == "oracle_upper_bound":
                    correction = actual_error
                    predicted_value = None
                else:
                    correction, predicted_value = correction_for(
                        method,
                        cycle,
                        startup_reading,
                        post_gate_readings,
                        config.predictor_window,
                        predictor,
                    )
                if predicted_value is not None:
                    # The hidden error is used here only to score the forecast.
                    prediction_errors.append(abs(actual_error - predicted_value))
                residual = actual_error - correction
                if method == "randomized_compiling":
                    # Pauli-frame twirling flips the sign of an X-axis coherent error.
                    residual *= 1.0 if rc_rng.random() < 0.5 else -1.0
                residuals.append(residual)

            controller_elapsed += perf_counter() - controller_started
            repeated_metrics.append(
                metrics_for_residuals(residuals, degrees(90.0), ideal_state)
            )

        controller_time_ms = controller_elapsed * 1000.0
        result = combine_repeat_metrics(repeated_metrics)
        result["scenario"] = scenario
        result["seed_block"] = seed_block
        result["trial"] = trial
        result["seed"] = seed
        result["method"] = method
        result["statevector_backend"] = (
            "Qiskit Statevector" if HAS_QISKIT else "analytic fallback"
        )
        result["cycles"] = config.cycles
        result["shots_per_probe"] = config.shots
        result["probe_repetitions"] = config.probe_repetitions
        result["probe_interval"] = config.probe_interval
        result["measurement_rng_backend"] = measurement_rng_backend
        result["predictor_window"] = config.predictor_window
        result["ema_alpha_per_cycle"] = getattr(
            config, "ema_alpha_per_cycle", 0.25
        )
        result["kalman_acceleration_sigma_deg_per_cycle2"] = getattr(
            config, "kalman_acceleration_sigma_deg_per_cycle2", 0.002
        )
        result["kalman_initial_velocity_sigma_deg_per_cycle"] = getattr(
            config, "kalman_initial_velocity_sigma_deg_per_cycle", 0.05
        )
        result["trend_threshold"] = config.trend_threshold
        result["min_trend_observations"] = config.min_trend_observations
        result["base_error_deg"] = config.base_error_deg
        result["drift_rate_deg"] = config.drift_rate_deg
        result["drift_jitter_deg"] = config.drift_jitter_deg
        result["white_noise_sigma_deg"] = config.white_noise_sigma_deg
        result["probe_mismatch_offset_deg"] = config.probe_mismatch_offset_deg
        result["probe_mismatch_scale"] = getattr(
            config, "probe_mismatch_scale", 1.0
        )
        result["probe_readout_mismatch_scale"] = getattr(
            config, "probe_readout_mismatch_scale", 1.0
        )
        result["probe_mismatch_drift_rate_deg"] = (
            config.probe_mismatch_drift_rate_deg
        )
        result["probe_local_noise_sigma_deg"] = config.probe_local_noise_sigma_deg
        result["probe_readout_error"] = actual_readout_error
        result["readout_calibration_error"] = readout_calibration
        result["prediction_mae_deg"] = (
            math.degrees(mean(prediction_errors)) if prediction_errors else ""
        )
        probe_checkpoints_available = 1 + len(post_gate_readings)
        if method == "static_calibration":
            probe_checkpoints_used = 1
        elif method in ("reactive_last_probe", *PREDICTIVE_METHODS):
            probe_checkpoints_used = probe_checkpoints_available
        else:
            probe_checkpoints_used = 0
        result["probe_checkpoints_available_per_run"] = (
            probe_checkpoints_available
        )
        result["probe_shots_available_per_run"] = (
            probe_checkpoints_available * config.shots
        )
        result["probe_pulses_available_per_run"] = (
            probe_checkpoints_available * config.shots * config.probe_repetitions
        )
        result["probe_checkpoints_used_per_run"] = probe_checkpoints_used
        result["probe_shots_used_per_run"] = probe_checkpoints_used * config.shots
        result["probe_pulses_used_per_run"] = (
            probe_checkpoints_used * config.shots * config.probe_repetitions
        )
        result["rc_compilations"] = (
            config.rc_compilations if method == "randomized_compiling" else 0
        )
        result["controller_time_ms_per_sequence"] = controller_time_ms / repeat_count
        rows.append(result)

    ideal_metrics = metrics_for_residuals(
        [0.0] * config.cycles, degrees(90.0), ideal_state
    )
    ideal_metrics.update(
        {
            "scenario": scenario,
            "seed_block": seed_block,
            "trial": trial,
            "seed": seed,
            "method": "ideal_reference",
            "statevector_backend": (
                "Qiskit Statevector" if HAS_QISKIT else "analytic fallback"
            ),
            "cycles": config.cycles,
            "shots_per_probe": config.shots,
            "probe_repetitions": config.probe_repetitions,
            "probe_interval": config.probe_interval,
            "measurement_rng_backend": measurement_rng_backend,
            "predictor_window": config.predictor_window,
            "ema_alpha_per_cycle": getattr(
                config, "ema_alpha_per_cycle", 0.25
            ),
            "kalman_acceleration_sigma_deg_per_cycle2": getattr(
                config, "kalman_acceleration_sigma_deg_per_cycle2", 0.002
            ),
            "kalman_initial_velocity_sigma_deg_per_cycle": getattr(
                config, "kalman_initial_velocity_sigma_deg_per_cycle", 0.05
            ),
            "trend_threshold": config.trend_threshold,
            "min_trend_observations": config.min_trend_observations,
            "base_error_deg": config.base_error_deg,
            "drift_rate_deg": config.drift_rate_deg,
            "drift_jitter_deg": config.drift_jitter_deg,
            "white_noise_sigma_deg": config.white_noise_sigma_deg,
            "probe_mismatch_offset_deg": config.probe_mismatch_offset_deg,
            "probe_mismatch_scale": getattr(
                config, "probe_mismatch_scale", 1.0
            ),
            "probe_readout_mismatch_scale": getattr(
                config, "probe_readout_mismatch_scale", 1.0
            ),
            "probe_mismatch_drift_rate_deg": config.probe_mismatch_drift_rate_deg,
            "probe_local_noise_sigma_deg": config.probe_local_noise_sigma_deg,
            "probe_readout_error": "",
            "readout_calibration_error": config.probe_readout_calibration_error,
            "prediction_mae_deg": "",
            "probe_checkpoints_available_per_run": 0,
            "probe_shots_available_per_run": 0,
            "probe_pulses_available_per_run": 0,
            "probe_checkpoints_used_per_run": 0,
            "probe_shots_used_per_run": 0,
            "probe_pulses_used_per_run": 0,
            "rc_compilations": 0,
            "controller_time_ms_per_sequence": 0.0,
        }
    )
    rows.append(ideal_metrics)
    return rows


def summarize(
    run_rows: list[dict[str, object]], config: argparse.Namespace
) -> list[dict[str, object]]:
    summary_rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        for method in (*METHODS, "ideal_reference"):
            group = [
                row
                for row in run_rows
                if row["scenario"] == scenario and row["method"] == method
            ]
            prediction_mae = [
                float(row["prediction_mae_deg"])
                for row in group
                if row["prediction_mae_deg"] != ""
            ]
            final_fidelities = [float(row["final_state_fidelity"]) for row in group]
            row: dict[str, object] = {
                "scenario": scenario,
                "method": method,
                "n_pairs": len(group),
                "base_seed": config.seed,
                "seed_blocks": config.seed_blocks,
                "trials_per_seed_block": config.trials,
                "statevector_backend": group[0]["statevector_backend"],
                "cycles": group[0]["cycles"],
                "shots_per_probe": group[0]["shots_per_probe"],
                "probe_repetitions": group[0]["probe_repetitions"],
                "probe_interval": group[0]["probe_interval"],
                "ema_alpha_per_cycle": group[0]["ema_alpha_per_cycle"],
                "kalman_acceleration_sigma_deg_per_cycle2": group[0][
                    "kalman_acceleration_sigma_deg_per_cycle2"
                ],
                "kalman_initial_velocity_sigma_deg_per_cycle": group[0][
                    "kalman_initial_velocity_sigma_deg_per_cycle"
                ],
                "probe_checkpoints_available_per_run": group[0][
                    "probe_checkpoints_available_per_run"
                ],
                "predictor_window": group[0]["predictor_window"],
                "trend_threshold": group[0]["trend_threshold"],
                "min_trend_observations": group[0]["min_trend_observations"],
                "base_error_deg": group[0]["base_error_deg"],
                "drift_rate_deg": group[0]["drift_rate_deg"],
                "drift_jitter_deg": group[0]["drift_jitter_deg"],
                "white_noise_sigma_deg": group[0]["white_noise_sigma_deg"],
                "probe_mismatch_offset_deg": group[0]["probe_mismatch_offset_deg"],
                "probe_mismatch_scale": group[0]["probe_mismatch_scale"],
                "probe_readout_mismatch_scale": group[0][
                    "probe_readout_mismatch_scale"
                ],
                "probe_mismatch_drift_rate_deg": group[0][
                    "probe_mismatch_drift_rate_deg"
                ],
                "probe_local_noise_sigma_deg": group[0][
                    "probe_local_noise_sigma_deg"
                ],
                "probe_readout_error": group[0]["probe_readout_error"],
                "readout_calibration_error": group[0][
                    "readout_calibration_error"
                ],
                "mean_prefix_state_fidelity": mean(
                    float(item["mean_prefix_state_fidelity"]) for item in group
                ),
                "mean_final_state_fidelity": mean(final_fidelities),
                "sd_final_state_fidelity": pstdev(final_fidelities),
                "mean_gate_fidelity": mean(
                    float(item["mean_gate_fidelity"]) for item in group
                ),
                "rms_gate_error_deg": mean(
                    float(item["rms_gate_error_deg"]) for item in group
                ),
                "rms_cumulative_error_deg": mean(
                    float(item["rms_cumulative_error_deg"]) for item in group
                ),
                "mean_signed_final_error_deg": mean(
                    float(item["final_accumulated_error_deg"]) for item in group
                ),
                "mean_prediction_mae_deg": (
                    mean(prediction_mae) if prediction_mae else ""
                ),
                "mean_controller_time_ms_per_sequence": mean(
                    float(item["controller_time_ms_per_sequence"]) for item in group
                ),
                "probe_shots_available_per_run": group[0][
                    "probe_shots_available_per_run"
                ],
                "probe_pulses_available_per_run": group[0][
                    "probe_pulses_available_per_run"
                ],
                "probe_checkpoints_used_per_run": group[0][
                    "probe_checkpoints_used_per_run"
                ],
                "probe_shots_used_per_run": group[0][
                    "probe_shots_used_per_run"
                ],
                "probe_pulses_used_per_run": group[0][
                    "probe_pulses_used_per_run"
                ],
                "rc_compilations": group[0]["rc_compilations"],
            }
            summary_rows.append(row)
    return summary_rows


def percentile(sorted_values: list[float], probability: float) -> float:
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def paired_bootstrap_ci(
    differences: list[float], seed: int, repetitions: int
) -> tuple[float, float]:
    rng = random.Random(seed)
    sample_size = len(differences)
    bootstrap_means: list[float] = []
    for _ in range(repetitions):
        total = sum(differences[rng.randrange(sample_size)] for _ in range(sample_size))
        bootstrap_means.append(total / sample_size)
    bootstrap_means.sort()
    return percentile(bootstrap_means, 0.025), percentile(bootstrap_means, 0.975)


def paired_sign_flip_pvalue(
    differences: list[float], seed: int, repetitions: int
) -> float:
    """Two-sided paired randomization test under sign exchangeability."""
    rng = random.Random(seed)
    observed = mean(differences)
    threshold = abs(observed) - 1e-15
    extreme = 0
    for _ in range(repetitions):
        permuted = sum(
            difference if rng.random() < 0.5 else -difference
            for difference in differences
        ) / len(differences)
        if abs(permuted) >= threshold:
            extreme += 1
    return (extreme + 1) / (repetitions + 1)


def holm_adjust(rows: list[dict[str, object]], p_field: str) -> None:
    order = sorted(
        range(len(rows)), key=lambda index: float(rows[index][p_field])
    )
    running_max = 0.0
    count = len(order)
    for rank, index in enumerate(order):
        adjusted = min(
            1.0,
            (count - rank) * float(rows[index][p_field]),
        )
        running_max = max(running_max, adjusted)
        rows[index]["holm_adjusted_p"] = running_max


def paired_statistics(
    run_rows: list[dict[str, object]], config: argparse.Namespace
) -> list[dict[str, object]]:
    """Paired inference for each predictive controller versus the last probe."""
    metrics = (
        "final_state_fidelity",
        "rms_gate_error_deg",
        "rms_cumulative_error_deg",
    )
    predictive_methods = ("predictive_linear", "predictive_guarded")
    pair_rows: dict[tuple[str, int, int], dict[str, dict[str, object]]] = {}
    for row in run_rows:
        if row["method"] in (*predictive_methods, "reactive_last_probe"):
            key = (str(row["scenario"]), int(row["seed_block"]), int(row["trial"]))
            pair_rows.setdefault(key, {})[str(row["method"])] = row

    output: list[dict[str, object]] = []
    for scenario_index, scenario in enumerate(SCENARIOS):
        for metric_index, metric in enumerate(metrics):
            for method_index, predictive_method in enumerate(predictive_methods):
                per_block: dict[int, list[float]] = {
                    block: [] for block in range(config.seed_blocks)
                }
                differences: list[float] = []
                for (row_scenario, block, _trial), pair in sorted(pair_rows.items()):
                    if row_scenario != scenario:
                        continue
                    if not {
                        predictive_method,
                        "reactive_last_probe",
                    }.issubset(pair):
                        continue
                    difference = float(pair[predictive_method][metric]) - float(
                        pair["reactive_last_probe"][metric]
                    )
                    differences.append(difference)
                    per_block[block].append(difference)

                if len(differences) < 2:
                    raise ValueError(
                        f"Not enough paired runs for "
                        f"{scenario}/{predictive_method}/{metric}"
                    )
                stat_seed = (
                    config.seed
                    + scenario_index * 10_007
                    + metric_index * 97_409
                    + method_index * 1_000_003
                )
                ci_low, ci_high = paired_bootstrap_ci(
                    differences, stat_seed, config.bootstrap_repetitions
                )
                p_value = paired_sign_flip_pvalue(
                    differences,
                    stat_seed + 2_000_003,
                    config.permutation_repetitions,
                )
                row: dict[str, object] = {
                    "scenario": scenario,
                    "metric": metric,
                    "comparison": (
                        f"{predictive_method} - reactive_last_probe"
                    ),
                    "base_seed": config.seed,
                    "seed_blocks": config.seed_blocks,
                    "trials_per_seed_block": config.trials,
                    "shots_per_probe": config.shots,
                    "probe_repetitions": config.probe_repetitions,
                    "probe_interval": config.probe_interval,
                    "trend_threshold": config.trend_threshold,
                    "min_trend_observations": config.min_trend_observations,
                    "n_pairs": len(differences),
                    "mean_difference": mean(differences),
                    "bootstrap_95ci_low": ci_low,
                    "bootstrap_95ci_high": ci_high,
                    "paired_sign_flip_p": p_value,
                    "holm_adjusted_p": "",
                    "bootstrap_repetitions": config.bootstrap_repetitions,
                    "permutation_repetitions": config.permutation_repetitions,
                }
                for block in range(config.seed_blocks):
                    block_differences = per_block[block]
                    row[f"seed_block_{block}_n"] = len(block_differences)
                    row[f"seed_block_{block}_mean_difference"] = (
                        mean(block_differences) if block_differences else ""
                    )
                output.append(row)

    holm_adjust(output, "paired_sign_flip_p")
    return output


def print_summary(rows: list[dict[str, object]]) -> None:
    print(
        "scenario                method                    n   prefix F  final F   "
        "RMS gate deg  RMS accumulated deg"
    )
    for row in rows:
        print(
            f"{SCENARIO_LABELS[str(row['scenario'])]:24s}"
            f"{METHOD_LABELS[str(row['method'])]:25s}"
            f"{int(row['n_pairs']):4d}"
            f"{float(row['mean_prefix_state_fidelity']):9.4f}"
            f"{float(row['mean_final_state_fidelity']):9.4f}"
            f"{float(row['rms_gate_error_deg']):13.4f}"
            f"{float(row['rms_cumulative_error_deg']):21.3f}"
        )


def print_paired_statistics(rows: list[dict[str, object]]) -> None:
    print(
        "\nPaired inference versus last probe: bootstrap 95% CI, "
        "two-sided sign-flip permutation, Holm correction across 18 comparisons."
    )
    for row in rows:
        print(
            f"{SCENARIO_LABELS[str(row['scenario'])]:24s}"
            f"{str(row['comparison']):42s} "
            f"{str(row['metric']):28s}"
            f"n={int(row['n_pairs']):3d} "
            f"mean={float(row['mean_difference']): .7g} "
            f"CI=[{float(row['bootstrap_95ci_low']): .7g}, "
            f"{float(row['bootstrap_95ci_high']): .7g}] "
            f"p={float(row['paired_sign_flip_p']):.5g} "
            f"Holm={float(row['holm_adjusted_p']):.5g}"
        )


def parse_args() -> argparse.Namespace:
    config_scanner = argparse.ArgumentParser(add_help=False)
    config_scanner.add_argument("--config", type=Path)
    config_path = config_scanner.parse_known_args()[0].config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        help="Load simulation defaults from a JSON experiment configuration.",
    )
    parser.add_argument("--cycles", type=int, default=64)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed-blocks", type=int, default=2)
    parser.add_argument("--shots", type=int, default=4096)
    parser.add_argument("--probe-repetitions", type=int, default=13)
    parser.add_argument("--probe-interval", type=int, default=1)
    parser.add_argument("--predictor-window", type=int, default=16)
    parser.add_argument("--ema-alpha-per-cycle", type=float, default=0.25)
    parser.add_argument(
        "--kalman-acceleration-sigma-deg-per-cycle2", type=float, default=0.002
    )
    parser.add_argument(
        "--kalman-initial-velocity-sigma-deg-per-cycle", type=float, default=0.05
    )
    parser.add_argument("--trend-threshold", type=float, default=2.0)
    parser.add_argument("--min-trend-observations", type=int, default=4)
    parser.add_argument("--rc-compilations", type=int, default=1)
    parser.add_argument("--bootstrap-repetitions", type=int, default=5000)
    parser.add_argument("--permutation-repetitions", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261031)
    parser.add_argument("--base-error-deg", type=float, default=2.0)
    parser.add_argument("--drift-rate-deg", type=float, default=0.01)
    parser.add_argument("--drift-jitter-deg", type=float, default=0.005)
    parser.add_argument("--white-noise-sigma-deg", type=float, default=0.20)
    parser.add_argument("--probe-mismatch-offset-deg", type=float, default=0.20)
    parser.add_argument("--probe-mismatch-scale", type=float, default=1.0)
    parser.add_argument(
        "--probe-readout-mismatch-scale", type=float, default=1.0
    )
    parser.add_argument("--probe-mismatch-drift-rate-deg", type=float, default=0.03)
    parser.add_argument("--probe-local-noise-sigma-deg", type=float, default=0.05)
    parser.add_argument("--probe-readout-error", type=float, default=0.01)
    parser.add_argument("--probe-readout-calibration-error", type=float, default=0.01)
    parser.add_argument("--probe-mismatch-readout-error", type=float, default=0.02)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/pqec_single_qubit_summary.csv"),
    )
    parser.add_argument(
        "--runs-output",
        type=Path,
        default=Path("results/pqec_single_qubit_runs.csv"),
    )
    parser.add_argument(
        "--paired-output",
        type=Path,
        default=Path("results/pqec_single_qubit_paired_stats.csv"),
    )
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
        for path_key in ("output", "runs_output", "paired_output"):
            if path_key in defaults:
                defaults[path_key] = Path(defaults[path_key])
        parser.set_defaults(**defaults)
    args = parser.parse_args()
    if min(
        args.cycles,
        args.trials,
        args.seed_blocks,
        args.shots,
        args.probe_repetitions,
        args.probe_interval,
        args.predictor_window,
        args.min_trend_observations,
        args.rc_compilations,
        args.bootstrap_repetitions,
        args.permutation_repetitions,
    ) <= 0:
        parser.error("All counts and window sizes must be positive.")
    if args.probe_repetitions % 4 != 1:
        parser.error("--probe-repetitions must be 4k + 1 for signed Y-basis sensing.")
    if args.min_trend_observations < 3:
        parser.error("--min-trend-observations must be at least 3.")
    if args.min_trend_observations > args.predictor_window:
        parser.error("--min-trend-observations cannot exceed --predictor-window.")
    if not math.isfinite(args.trend_threshold) or args.trend_threshold < 0.0:
        parser.error("--trend-threshold must be finite and non-negative.")
    if args.drift_jitter_deg < 0.0 or args.white_noise_sigma_deg < 0.0:
        parser.error("Noise standard deviations cannot be negative.")
    if args.probe_local_noise_sigma_deg < 0.0:
        parser.error("Probe-local noise standard deviation cannot be negative.")
    if not math.isfinite(args.probe_mismatch_scale) or not 0.0 <= args.probe_mismatch_scale <= 1.0:
        parser.error("--probe-mismatch-scale must be in [0, 1].")
    if not math.isfinite(args.probe_readout_mismatch_scale) or not 0.0 <= args.probe_readout_mismatch_scale <= 1.0:
        parser.error("--probe-readout-mismatch-scale must be in [0, 1].")
    if not 0.0 < args.ema_alpha_per_cycle <= 1.0:
        parser.error("--ema-alpha-per-cycle must be in (0, 1].")
    if min(
        args.kalman_acceleration_sigma_deg_per_cycle2,
        args.kalman_initial_velocity_sigma_deg_per_cycle,
    ) < 0.0:
        parser.error("Kalman sigmas cannot be negative.")
    for error_rate in (
        args.probe_readout_error,
        args.probe_readout_calibration_error,
        args.probe_mismatch_readout_error,
    ):
        if not 0.0 <= error_rate < 0.5:
            parser.error("Readout error rates must be in [0, 0.5).")
    return args


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    config = parse_args()
    probe_difference = verify_probe_basis(config.probe_repetitions)
    ideal_state = state_after_rx_sequence([degrees(90.0)] * config.cycles)
    run_rows: list[dict[str, object]] = []
    for seed_block in range(config.seed_blocks):
        for scenario in SCENARIOS:
            for trial in range(config.trials):
                run_rows.extend(
                    evaluate_trial(
                        scenario, seed_block, trial, config, ideal_state
                    )
                )
    summary_rows = summarize(run_rows, config)
    paired_rows = paired_statistics(run_rows, config)
    print(f"Backend: {'Qiskit Statevector' if HAS_QISKIT else 'analytic statevector fallback'}")
    print(
        "Probe basis check: Y expectation matches the final Sdg-H-to-Z "
        f"measurement and analytic formula (max probability difference="
        f"{probe_difference:.2e})."
    )
    print(
        f"Paired runs per scenario: {config.trials * config.seed_blocks} "
        f"({config.trials} per seed block; {config.seed_blocks} blocks)."
    )
    probe_checkpoints = 1 + len(
        range(config.probe_interval - 1, config.cycles, config.probe_interval)
    )
    print(
        "Shared auxiliary-probe record for reactive/predictive controllers: "
        f"{probe_checkpoints * config.shots:,} shots; "
        f"{probe_checkpoints * config.shots * config.probe_repetitions:,} "
        f"probe rotations (one probe measurement every {config.probe_interval} "
        "target operations)."
    )
    print_summary(summary_rows)
    print_paired_statistics(paired_rows)

    write_csv(config.output, summary_rows)
    write_csv(config.runs_output, run_rows)
    write_csv(config.paired_output, paired_rows)
    print(f"\nSummary written to {config.output.resolve()}")
    print(f"Per-trial results written to {config.runs_output.resolve()}")
    print(f"Paired statistics written to {config.paired_output.resolve()}")


if __name__ == "__main__":
    main()
