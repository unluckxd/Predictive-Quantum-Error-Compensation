"""Stateful predictive angle compensator used by the PQEC prototype."""

from __future__ import annotations

import math
from statistics import mean


class PredictiveCompensator:
    """Forecast the next coherent angle error from prior probe readings.

    All angles are in radians. The controller only sees values passed to
    observe(); it has no access to the logical qubit or to future errors.
    """

    def __init__(
        self,
        window: int = 16,
        *,
        trend_threshold: float = 0.0,
        min_trend_observations: int = 3,
        anchor_to_latest: bool = False,
    ) -> None:
        if window < 1:
            raise ValueError("window must be positive")
        if not math.isfinite(trend_threshold) or trend_threshold < 0.0:
            raise ValueError("trend_threshold must be finite and non-negative")
        if min_trend_observations < 3:
            raise ValueError("min_trend_observations must be at least 3")
        self.window = window
        self.trend_threshold = trend_threshold
        self.min_trend_observations = min_trend_observations
        self.anchor_to_latest = anchor_to_latest
        self._observations: list[tuple[int, float]] = []

    @property
    def observations(self) -> tuple[tuple[int, float], ...]:
        return tuple(self._observations)

    def reset(self) -> None:
        self._observations.clear()

    def observe(self, cycle: int, measured_error_rad: float) -> None:
        """Add a probe measurement with its cycle index."""
        if not math.isfinite(measured_error_rad):
            raise ValueError("measured_error_rad must be finite")
        if self._observations and cycle <= self._observations[-1][0]:
            raise ValueError("Probe observations must have strictly increasing cycles")
        self._observations.append((cycle, measured_error_rad))
        if len(self._observations) > self.window:
            del self._observations[:-self.window]

    def predict_error(self, target_cycle: int) -> float:
        """Forecast the error at target_cycle using only earlier observations."""
        if not self._observations:
            raise ValueError("At least one prior probe measurement is required")
        if target_cycle <= self._observations[-1][0]:
            raise ValueError("Prediction target must follow the latest observation")

        points = self._observations[-self.window :]
        if len(points) == 1:
            return points[0][1]

        x_mean = mean(cycle for cycle, _ in points)
        y_mean = mean(value for _, value in points)
        denominator = sum((cycle - x_mean) ** 2 for cycle, _ in points)
        if denominator == 0.0:
            return y_mean
        slope = sum(
            (cycle - x_mean) * (value - y_mean) for cycle, value in points
        ) / denominator
        if self.trend_threshold > 0.0:
            if len(points) < self.min_trend_observations:
                slope = 0.0
            else:
                residual_sum_squares = sum(
                    (
                        value
                        - (y_mean + slope * (cycle - x_mean))
                    )
                    ** 2
                    for cycle, value in points
                )
                residual_variance = residual_sum_squares / (len(points) - 2)
                slope_standard_error = math.sqrt(
                    residual_variance / denominator
                )
                if slope_standard_error > 0.0:
                    trend_score = abs(slope) / slope_standard_error
                    if trend_score <= self.trend_threshold:
                        slope = 0.0
                    else:
                        shrinkage = 1.0 - (
                            self.trend_threshold / trend_score
                        ) ** 2
                        slope *= shrinkage
        if self.anchor_to_latest:
            latest_cycle, latest_value = points[-1]
            return latest_value + slope * (target_cycle - latest_cycle)
        return y_mean + slope * (target_cycle - x_mean)

    def command_angle(self, target_angle_rad: float, target_cycle: int) -> float:
        """Return target angle minus the forecast error for the next pulse."""
        return target_angle_rad - self.predict_error(target_cycle)
