"""Focused smoke tests for the optional Qiskit Aer noise-model experiment."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import numpy as np
    from qiskit_aer import AerSimulator

    from pqec_aer_sweep import (
        PREDICTOR_METHODS,
        build_noise_model,
        calibrate_probe_response,
        checkpoint_cycles,
        make_error_trajectories,
        paired_sensitivity_statistics,
        resolve_condition_noise,
        validate_config,
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


@unittest.skipUnless(HAS_AER, "Install requirements-aer.txt to run Aer tests.")
class AerV03SensitivityConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with (ROOT / "configs" / "aer_noise_v02.json").open(
            encoding="utf-8"
        ) as handle:
            cls.base = json.load(handle)
        with (ROOT / "configs" / "aer_t1t2_sweep_v03.json").open(
            encoding="utf-8"
        ) as handle:
            cls.t1t2 = json.load(handle)
        with (ROOT / "configs" / "aer_feedback_latency_sweep_v03.json").open(
            encoding="utf-8"
        ) as handle:
            cls.latency = json.load(handle)

    def test_condition_noise_overrides_are_isolated_and_non_mutating(self) -> None:
        original_target_t1 = self.base["noise"]["target"]["t1_us"]
        condition = {
            "noise_overrides": {
                "target": {"t1_us": original_target_t1 / 2},
                "latency": {"classical_controller_latency_us": 10.0},
            }
        }
        resolved = resolve_condition_noise(self.base["noise"], condition)
        self.assertEqual(resolved["target"]["t1_us"], original_target_t1 / 2)
        self.assertEqual(
            resolved["latency"]["classical_controller_latency_us"], 10.0
        )
        self.assertEqual(self.base["noise"]["target"]["t1_us"], original_target_t1)
        self.assertEqual(
            resolved["probe"], self.base["noise"]["probe"]
        )

    def test_t1t2_sweep_changes_one_physical_parameter_at_a_time(self) -> None:
        self.assertEqual(len(self.t1t2["conditions"]), 17)
        self.assertEqual(
            set(self.t1t2["seed_schedule"]["seed_block_ids"]),
            set(range(20, 28)),
        )
        self.assertEqual(
            self.t1t2["parameters"]["shots"], self.base["parameters"]["shots"]
        )
        self.assertEqual(
            self.t1t2["parameters"]["probe_interval"],
            self.base["parameters"]["probe_interval"],
        )
        for condition in self.t1t2["conditions"]:
            self.assertEqual(condition["scenario"], "shared_drift")
            overrides = condition["noise_overrides"]
            if condition["sweep_factor"] == "reference":
                self.assertEqual(overrides, {})
                continue
            self.assertEqual(len(overrides), 1)
            section, parameters = next(iter(overrides.items()))
            self.assertIn(section, ("target", "probe"))
            self.assertEqual(len(parameters), 1)
            self.assertIn(next(iter(parameters)), ("t1_us", "t2_us"))
        validate_config(self.t1t2)

    def test_latency_sweep_changes_only_controller_latency(self) -> None:
        self.assertEqual(len(self.latency["conditions"]), 4)
        self.assertEqual(
            [
                condition["noise_overrides"]["latency"][
                    "classical_controller_latency_us"
                ]
                for condition in self.latency["conditions"]
            ],
            [0.0, 2.0, 10.0, 50.0],
        )
        self.assertEqual(
            self.latency["parameters"]["shots"], self.base["parameters"]["shots"]
        )
        self.assertEqual(
            self.latency["parameters"]["probe_interval"],
            self.base["parameters"]["probe_interval"],
        )
        for condition in self.latency["conditions"]:
            self.assertEqual(
                set(condition["noise_overrides"]), {"latency"}
            )
            self.assertEqual(
                set(condition["noise_overrides"]["latency"]),
                {"classical_controller_latency_us"},
            )
        validate_config(self.latency)

    def test_effect_change_analysis_uses_matched_trajectory_contrasts(self) -> None:
        conditions = [
            {"id": "reference", "scenario": "shared_drift"},
            {"id": "changed", "scenario": "shared_drift"},
        ]
        run_rows = []
        for block in (20, 21):
            for trial in (0, 1):
                for condition in conditions:
                    reactive_offset = 0.1 if condition["id"] == "changed" else 0.0
                    for method_index, method in enumerate(
                        ("reactive_last_probe", *PREDICTOR_METHODS)
                    ):
                        method_effect = 0.0
                        if method != "reactive_last_probe":
                            method_effect = 0.01 * (method_index + 1)
                            if condition["id"] == "changed":
                                method_effect += 0.2
                        run_rows.append(
                            {
                                "condition_id": condition["id"],
                                "seed_block": block,
                                "trial": trial,
                                "method": method,
                                "final_state_fidelity": reactive_offset + method_effect,
                                "rms_gate_residual_deg": reactive_offset + method_effect,
                                "rms_cumulative_angle_residual_deg": reactive_offset + method_effect,
                            }
                        )
        result = paired_sensitivity_statistics(
            run_rows,
            conditions,
            {
                "base_seed": 123,
                "seed_block_ids": [20, 21],
            },
            {
                "bootstrap_repetitions": 20,
                "sign_flip_repetitions": 20,
            },
            {
                "reference_condition_id": "reference",
                "statistics_seed_offset": 5000,
                "statistics_condition_stride": 100,
                "statistics_method_stride": 10,
                "statistics_metric_stride": 1,
            },
        )
        self.assertEqual(len(result), len(PREDICTOR_METHODS) * 3)
        guarded = next(
            row
            for row in result
            if row["method"] == "predictive_guarded"
            and row["metric"] == "final_state_fidelity"
        )
        self.assertEqual(guarded["n_paired_trajectories"], 4)
        self.assertAlmostEqual(guarded["mean_effect_change"], 0.2)
        self.assertAlmostEqual(guarded["bootstrap_95ci_low"], 0.2)
        self.assertAlmostEqual(guarded["bootstrap_95ci_high"], 0.2)


if __name__ == "__main__":
    unittest.main()
