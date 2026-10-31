import unittest

from pqec_baselines import (
    ConstantVelocityKalmanPredictor,
    ExponentialMovingAveragePredictor,
    MovingAveragePredictor,
    TwoPointPredictor,
)


class BaselinePredictorTests(unittest.TestCase):
    def test_moving_average_uses_latest_window(self) -> None:
        controller = MovingAveragePredictor(window=2)
        for cycle, value in enumerate((0.1, 0.2, 0.4)):
            controller.observe(cycle, value)
        self.assertAlmostEqual(controller.predict_error(3), 0.3)

    def test_ema_adjusts_weight_for_irregular_probe_interval(self) -> None:
        controller = ExponentialMovingAveragePredictor(alpha_per_cycle=0.5)
        controller.observe(0, 0.0)
        controller.observe(2, 0.4)
        self.assertAlmostEqual(controller.predict_error(3), 0.3)

    def test_two_point_forecast_uses_observation_cycle_spacing(self) -> None:
        controller = TwoPointPredictor()
        controller.observe(0, 0.1)
        controller.observe(2, 0.2)
        self.assertAlmostEqual(controller.predict_error(3), 0.25)

    def test_kalman_forecast_is_finite_and_extrapolates_learned_drift(self) -> None:
        controller = ConstantVelocityKalmanPredictor(
            measurement_variance_rad2=1e-8,
            acceleration_sigma_rad_per_cycle2=1e-7,
            initial_velocity_sigma_rad_per_cycle=0.1,
        )
        controller.observe(0, 0.0)
        controller.observe(1, 0.1)
        controller.observe(2, 0.2)
        self.assertAlmostEqual(controller.predict_error(3), 0.3, places=5)

    def test_predictors_reject_non_future_targets(self) -> None:
        for controller in (
            MovingAveragePredictor(),
            ExponentialMovingAveragePredictor(),
            TwoPointPredictor(),
            ConstantVelocityKalmanPredictor(
                measurement_variance_rad2=1e-6,
                acceleration_sigma_rad_per_cycle2=1e-4,
                initial_velocity_sigma_rad_per_cycle=0.1,
            ),
        ):
            controller.observe(2, 0.1)
            with self.assertRaises(ValueError):
                controller.predict_error(2)


if __name__ == "__main__":
    unittest.main()
