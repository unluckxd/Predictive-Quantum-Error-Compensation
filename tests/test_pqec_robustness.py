import importlib.util
import math
import unittest
from argparse import Namespace

from pqec_single_qubit import (
    degrees,
    evaluate_trial,
    make_trajectory,
    state_after_rx_sequence,
)


class ProbeMismatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.arguments = (
            "probe_mismatch",
            12,
            321,
            2.0,
            0.01,
            0.005,
            0.2,
            0.2,
            0.03,
            0.05,
            0.01,
            0.01,
            0.02,
        )

    def test_zero_mismatch_scale_reuses_target_error_and_readout(self) -> None:
        result = make_trajectory(
            *self.arguments,
            probe_mismatch_scale=0.0,
            probe_readout_mismatch_scale=0.0,
        )
        target_start, target_errors, probe_start, probe_errors, readout, _ = result
        self.assertEqual(probe_start, target_start)
        self.assertEqual(probe_errors, target_errors)
        self.assertEqual(readout, 0.01)

    def test_full_mismatch_endpoint_keeps_the_existing_stress_parameters(self) -> None:
        result = make_trajectory(*self.arguments, probe_mismatch_scale=1.0)
        target_start, target_errors, probe_start, probe_errors, readout, _ = result
        self.assertEqual(readout, 0.02)
        self.assertNotEqual(probe_start, target_start)
        self.assertNotEqual(probe_errors, target_errors)

    def test_half_mismatch_is_linear_interpolation_of_the_same_seed(self) -> None:
        matched = make_trajectory(
            *self.arguments,
            probe_mismatch_scale=0.0,
            probe_readout_mismatch_scale=0.0,
        )
        midpoint = make_trajectory(
            *self.arguments,
            probe_mismatch_scale=0.5,
            probe_readout_mismatch_scale=0.0,
        )
        mismatched = make_trajectory(
            *self.arguments,
            probe_mismatch_scale=1.0,
            probe_readout_mismatch_scale=0.0,
        )
        self.assertAlmostEqual(
            midpoint[2], (matched[2] + mismatched[2]) / 2.0, places=14
        )
        for target, halfway, independent in zip(
            matched[1], midpoint[3], mismatched[3]
        ):
            self.assertAlmostEqual(
                halfway, target + 0.5 * (independent - target), places=14
            )
        self.assertAlmostEqual(midpoint[4], 0.01, places=14)

    def test_readout_mismatch_is_an_independent_parameter(self) -> None:
        for control_scale in (0.0, 0.5, 1.0):
            result = make_trajectory(
                *self.arguments,
                probe_mismatch_scale=control_scale,
                probe_readout_mismatch_scale=1.0,
            )
            self.assertEqual(result[4], 0.02)


@unittest.skipUnless(
    importlib.util.find_spec("numpy"), "NumPy is required for this robustness path"
)
class ExtendedPredictorSimulationTests(unittest.TestCase):
    def test_new_baselines_use_only_past_probe_records(self) -> None:
        config = Namespace(
            seed=20261031,
            cycles=8,
            shots=64,
            probe_repetitions=13,
            probe_interval=2,
            predictor_window=4,
            trend_threshold=2.0,
            min_trend_observations=3,
            rc_compilations=1,
            base_error_deg=1.0,
            drift_rate_deg=0.02,
            drift_jitter_deg=0.0,
            white_noise_sigma_deg=0.1,
            probe_mismatch_offset_deg=0.2,
            probe_mismatch_scale=0.5,
            probe_mismatch_drift_rate_deg=0.03,
            probe_local_noise_sigma_deg=0.02,
            probe_readout_error=0.01,
            probe_readout_calibration_error=0.01,
            probe_mismatch_readout_error=0.02,
            ema_alpha_per_cycle=0.25,
            kalman_acceleration_sigma_deg_per_cycle2=0.002,
            kalman_initial_velocity_sigma_deg_per_cycle=0.05,
        )
        methods = (
            "reactive_last_probe",
            "moving_average",
            "exponential_moving_average",
            "two_point_linear",
            "kalman_constant_velocity",
        )
        ideal = state_after_rx_sequence([math.pi / 2.0] * config.cycles)
        rows = evaluate_trial(
            "slow_drift",
            2,
            3,
            config,
            ideal,
            methods=methods,
            measurement_rng_backend="numpy",
        )
        by_method = {str(row["method"]): row for row in rows}
        self.assertEqual(set(by_method), {*methods, "ideal_reference"})
        self.assertEqual(
            by_method["moving_average"]["probe_shots_available_per_run"],
            by_method["reactive_last_probe"]["probe_shots_available_per_run"],
        )
        for method in methods:
            self.assertTrue(
                math.isfinite(float(by_method[method]["final_state_fidelity"]))
            )
            self.assertEqual(
                by_method[method]["measurement_rng_backend"], "numpy"
            )


if __name__ == "__main__":
    unittest.main()
