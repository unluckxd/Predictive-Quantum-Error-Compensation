import unittest

from pqec_controller import PredictiveCompensator


class PredictiveCompensatorTests(unittest.TestCase):
    def test_linear_forecast_uses_prior_observations(self) -> None:
        controller = PredictiveCompensator(window=4)
        for cycle in range(4):
            controller.observe(cycle, 0.1 + 0.02 * cycle)

        self.assertAlmostEqual(controller.predict_error(4), 0.18, places=12)
        self.assertAlmostEqual(
            controller.command_angle(1.0, 4), 0.82, places=12
        )

    def test_guarded_forecast_falls_back_until_four_observations(self) -> None:
        controller = PredictiveCompensator(
            window=8,
            trend_threshold=2.0,
            min_trend_observations=4,
            anchor_to_latest=True,
        )
        for cycle, value in enumerate((0.1, 0.2, 0.3)):
            controller.observe(cycle, value)

        self.assertAlmostEqual(controller.predict_error(3), 0.3, places=12)

    def test_guarded_forecast_shrinks_a_weak_trend_to_latest_probe(self) -> None:
        controller = PredictiveCompensator(
            window=8,
            trend_threshold=2.0,
            min_trend_observations=4,
            anchor_to_latest=True,
        )
        for cycle, value in enumerate((0.0, 0.01, -0.01, 0.015)):
            controller.observe(cycle, value)

        self.assertAlmostEqual(controller.predict_error(4), 0.015, places=12)

    def test_guarded_forecast_keeps_a_clean_shared_drift(self) -> None:
        controller = PredictiveCompensator(
            window=8,
            trend_threshold=2.0,
            min_trend_observations=4,
            anchor_to_latest=True,
        )
        for cycle in range(4):
            controller.observe(cycle * 10, 0.1 + 0.01 * cycle * 10)

        self.assertAlmostEqual(controller.predict_error(40), 0.5, places=12)

    def test_rejects_a_prediction_at_or_before_latest_probe(self) -> None:
        controller = PredictiveCompensator()
        controller.observe(4, 0.2)

        with self.assertRaises(ValueError):
            controller.predict_error(4)

    def test_observations_must_be_finite_and_ordered(self) -> None:
        controller = PredictiveCompensator()
        controller.observe(1, 0.2)

        with self.assertRaises(ValueError):
            controller.observe(1, 0.3)
        with self.assertRaises(ValueError):
            controller.observe(2, float("nan"))


if __name__ == "__main__":
    unittest.main()
