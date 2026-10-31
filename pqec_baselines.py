"""Simple causal filters for benchmarking probe-based angle compensation."""

from __future__ import annotations

import math
from statistics import mean
from typing import Protocol


BASELINE_METHODS = (
    "moving_average",
    "exponential_moving_average",
    "two_point_linear",
    "kalman_constant_velocity",
)


class ErrorPredictor(Protocol):
    """Structural type shared by the stateful one-step predictors."""

    def observe(self, cycle: int, measured_error_rad: float) -> None:
        ...

    def predict_error(self, target_cycle: int) -> float:
        ...


class MovingAveragePredictor:
    """Predict the next error with the mean of the latest probe readings."""

    def __init__(self, window: int = 16) -> None:
        if window < 1:
            raise ValueError("window must be positive")
        self.window = window
        self._observations: list[tuple[int, float]] = []

    def observe(self, cycle: int, measured_error_rad: float) -> None:
        if not math.isfinite(measured_error_rad):
            raise ValueError("measured_error_rad must be finite")
        if self._observations and cycle <= self._observations[-1][0]:
            raise ValueError("Probe observations must have strictly increasing cycles")
        self._observations.append((cycle, measured_error_rad))
        if len(self._observations) > self.window:
            del self._observations[:-self.window]

    def predict_error(self, target_cycle: int) -> float:
        _require_future(self._observations, target_cycle)
        return mean(value for _, value in self._observations)


class ExponentialMovingAveragePredictor:
    """Smooth probe readings with a per-cycle exponential decay."""

    def __init__(self, alpha_per_cycle: float = 0.25) -> None:
        if not math.isfinite(alpha_per_cycle) or not 0.0 < alpha_per_cycle <= 1.0:
            raise ValueError("alpha_per_cycle must be in (0, 1]")
        self.alpha_per_cycle = alpha_per_cycle
        self._cycle: int | None = None
        self._estimate: float | None = None

    def observe(self, cycle: int, measured_error_rad: float) -> None:
        if not math.isfinite(measured_error_rad):
            raise ValueError("measured_error_rad must be finite")
        if self._cycle is not None and cycle <= self._cycle:
            raise ValueError("Probe observations must have strictly increasing cycles")
        if self._cycle is None:
            self._estimate = measured_error_rad
        else:
            elapsed = cycle - self._cycle
            alpha = 1.0 - (1.0 - self.alpha_per_cycle) ** elapsed
            assert self._estimate is not None
            self._estimate += alpha * (measured_error_rad - self._estimate)
        self._cycle = cycle

    def predict_error(self, target_cycle: int) -> float:
        if self._cycle is None or self._estimate is None:
            raise ValueError("At least one prior probe measurement is required")
        if target_cycle <= self._cycle:
            raise ValueError("Prediction target must follow the latest observation")
        return self._estimate


class TwoPointPredictor:
    """Extrapolate the slope between the latest two probe measurements."""

    def __init__(self) -> None:
        self._observations: list[tuple[int, float]] = []

    def observe(self, cycle: int, measured_error_rad: float) -> None:
        if not math.isfinite(measured_error_rad):
            raise ValueError("measured_error_rad must be finite")
        if self._observations and cycle <= self._observations[-1][0]:
            raise ValueError("Probe observations must have strictly increasing cycles")
        self._observations.append((cycle, measured_error_rad))
        if len(self._observations) > 2:
            del self._observations[:-2]

    def predict_error(self, target_cycle: int) -> float:
        _require_future(self._observations, target_cycle)
        latest_cycle, latest_value = self._observations[-1]
        if len(self._observations) == 1:
            return latest_value
        prior_cycle, prior_value = self._observations[-2]
        slope = (latest_value - prior_value) / (latest_cycle - prior_cycle)
        return latest_value + slope * (target_cycle - latest_cycle)


class ConstantVelocityKalmanPredictor:
    """Two-state angle-and-drift Kalman filter with white acceleration noise."""

    def __init__(
        self,
        *,
        measurement_variance_rad2: float,
        acceleration_sigma_rad_per_cycle2: float,
        initial_velocity_sigma_rad_per_cycle: float,
    ) -> None:
        values = (
            measurement_variance_rad2,
            acceleration_sigma_rad_per_cycle2,
            initial_velocity_sigma_rad_per_cycle,
        )
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("Kalman variances and standard deviations must be finite and non-negative")
        if measurement_variance_rad2 == 0.0:
            raise ValueError("measurement_variance_rad2 must be positive")
        self.measurement_variance = measurement_variance_rad2
        self.acceleration_variance = acceleration_sigma_rad_per_cycle2**2
        self.initial_velocity_variance = initial_velocity_sigma_rad_per_cycle**2
        self._cycle: int | None = None
        self._angle: float | None = None
        self._velocity = 0.0
        self._p_angle = 0.0
        self._p_cross = 0.0
        self._p_velocity = self.initial_velocity_variance

    def _propagate(self, elapsed: int) -> tuple[float, float, float, float, float]:
        assert self._angle is not None
        dt = float(elapsed)
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        q = self.acceleration_variance
        angle = self._angle + dt * self._velocity
        velocity = self._velocity
        p_angle = (
            self._p_angle
            + 2.0 * dt * self._p_cross
            + dt2 * self._p_velocity
            + q * dt4 / 4.0
        )
        p_cross = self._p_cross + dt * self._p_velocity + q * dt3 / 2.0
        p_velocity = self._p_velocity + q * dt2
        return angle, velocity, p_angle, p_cross, p_velocity

    def observe(self, cycle: int, measured_error_rad: float) -> None:
        if not math.isfinite(measured_error_rad):
            raise ValueError("measured_error_rad must be finite")
        if self._cycle is None:
            self._cycle = cycle
            self._angle = measured_error_rad
            self._p_angle = self.measurement_variance
            self._p_cross = 0.0
            self._p_velocity = self.initial_velocity_variance
            return
        if cycle <= self._cycle:
            raise ValueError("Probe observations must have strictly increasing cycles")

        angle, velocity, p_angle, p_cross, p_velocity = self._propagate(
            cycle - self._cycle
        )
        innovation_variance = p_angle + self.measurement_variance
        gain_angle = p_angle / innovation_variance
        gain_velocity = p_cross / innovation_variance
        innovation = measured_error_rad - angle
        self._angle = angle + gain_angle * innovation
        self._velocity = velocity + gain_velocity * innovation
        self._p_angle = max(0.0, (1.0 - gain_angle) * p_angle)
        self._p_cross = (1.0 - gain_angle) * p_cross
        self._p_velocity = max(0.0, p_velocity - gain_velocity * p_cross)
        self._cycle = cycle

    def predict_error(self, target_cycle: int) -> float:
        if self._cycle is None or self._angle is None:
            raise ValueError("At least one prior probe measurement is required")
        if target_cycle <= self._cycle:
            raise ValueError("Prediction target must follow the latest observation")
        angle, _velocity, _p_angle, _p_cross, _p_velocity = self._propagate(
            target_cycle - self._cycle
        )
        return angle


def create_baseline_predictor(
    method: str,
    *,
    window: int,
    ema_alpha_per_cycle: float,
    kalman_measurement_variance_rad2: float,
    kalman_acceleration_sigma_rad_per_cycle2: float,
    kalman_initial_velocity_sigma_rad_per_cycle: float,
) -> ErrorPredictor:
    """Create a baseline using fixed, pre-registered hyperparameters."""
    if method == "moving_average":
        return MovingAveragePredictor(window=window)
    if method == "exponential_moving_average":
        return ExponentialMovingAveragePredictor(
            alpha_per_cycle=ema_alpha_per_cycle
        )
    if method == "two_point_linear":
        return TwoPointPredictor()
    if method == "kalman_constant_velocity":
        return ConstantVelocityKalmanPredictor(
            measurement_variance_rad2=kalman_measurement_variance_rad2,
            acceleration_sigma_rad_per_cycle2=(
                kalman_acceleration_sigma_rad_per_cycle2
            ),
            initial_velocity_sigma_rad_per_cycle=(
                kalman_initial_velocity_sigma_rad_per_cycle
            ),
        )
    raise ValueError(f"Unknown baseline predictor: {method}")


def _require_future(
    observations: list[tuple[int, float]], target_cycle: int
) -> None:
    if not observations:
        raise ValueError("At least one prior probe measurement is required")
    if target_cycle <= observations[-1][0]:
        raise ValueError("Prediction target must follow the latest observation")
