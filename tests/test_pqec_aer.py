"""Focused smoke tests for the optional Qiskit Aer noise-model experiment."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import numpy as np
    from qiskit_aer import AerSimulator

    from pqec_aer_sweep import (
        build_noise_model,
        calibrate_probe_response,
        checkpoint_cycles,
        make_error_trajectories,
    )

    HAS_AER = True
except ImportError:
    HAS_AER = False


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_AER, "Install requirements-aer.txt to run Aer tests.")
class AerNoiseModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with (ROOT / "configs" / "aer_noise_v01.json").open(
            encoding="utf-8"
        ) as handle:
            cls.config = json.load(handle)

    def test_probe_checkpoint_schedule_is_causal(self) -> None:
        self.assertEqual(checkpoint_cycles(17, 4), [-1, 3, 7, 11, 15])
        self.assertEqual(checkpoint_cycles(8, 8), [-1])

    def test_shared_and_mismatched_probe_trajectories(self) -> None:
        parameters = self.config["parameters"]
        target_shared, probe_shared = make_error_trajectories(
            "shared_drift", 32, 77, parameters, 0.0
        )
        target_match, probe_match = make_error_trajectories(
            "probe_mismatch", 32, 77, parameters, 0.0
        )
        target_mismatch, probe_mismatch = make_error_trajectories(
            "probe_mismatch", 32, 77, parameters, 0.5
        )
        np.testing.assert_allclose(target_shared, probe_shared)
        np.testing.assert_allclose(target_match, probe_match)
        self.assertGreater(float(np.max(np.abs(target_mismatch - probe_mismatch))), 0.0)

    def test_noisy_probe_calibration_round_trip(self) -> None:
        noise = self.config["noise"]
        parameters = self.config["parameters"]
        simulator = AerSimulator(
            method="density_matrix",
            noise_model=build_noise_model(noise, "probe"),
            max_parallel_threads=1,
        )
        calibration_config = dict(self.config["probe_response_calibration"])
        calibration_config["points"] = 81
        calibration = calibrate_probe_response(
            simulator,
            noise,
            parameters,
            calibration_config,
        )
        error_deg = 1.25
        p0 = float(
            np.interp(
                error_deg,
                calibration.error_grid_deg,
                calibration.observed_p0_grid,
            )
        )
        self.assertAlmostEqual(
            calibration.estimate_error_deg(p0),
            error_deg,
            places=2,
        )
        self.assertGreater(calibration.measurement_variance_rad2(32), 0.0)


class AerV02ConfigurationTests(unittest.TestCase):
    def test_seed_blocks_and_mismatch_grid_are_expanded(self) -> None:
        with (ROOT / "configs" / "aer_noise_v01.json").open(
            encoding="utf-8"
        ) as handle:
            v01 = json.load(handle)
        with (ROOT / "configs" / "aer_noise_v02.json").open(
            encoding="utf-8"
        ) as handle:
            v02 = json.load(handle)

        old_blocks = set(v01["seed_schedule"]["seed_block_ids"])
        new_blocks = set(v02["seed_schedule"]["seed_block_ids"])
        self.assertEqual(new_blocks, set(range(12, 20)))
        self.assertTrue(old_blocks.isdisjoint(new_blocks))
        self.assertEqual(v02["seed_schedule"]["trials_per_seed_block"], 25)
        self.assertEqual(
            len(new_blocks) * v02["seed_schedule"]["trials_per_seed_block"],
            200,
        )
        mismatch_scales = sorted(
            condition["probe_mismatch_scale"]
            for condition in v02["conditions"]
            if condition["scenario"] == "probe_mismatch"
        )
        self.assertEqual(mismatch_scales, [0.0, 0.25, 0.5, 0.75, 1.0])


if __name__ == "__main__":
    unittest.main()
