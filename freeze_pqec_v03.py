#!/usr/bin/env python3
"""Create the deterministic PQEC v0.3 artifact inventory and SHA-256 file."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
FREEZE_DATE = "2026-10-31"
MANIFEST_PATH = Path("results/pqec_v03/version_manifest.json")
CHECKSUM_PATH = Path("results/pqec_v03/SHA256SUMS.txt")

EXPECTED_AER_COUNTS = {
    "aer_t1t2": {
        "conditions": 17,
        "run_rows": 27200,
        "seed_records": 3400,
        "primary_tests": 306,
        "effect_change_tests": 288,
    },
    "aer_latency": {
        "conditions": 4,
        "run_rows": 6400,
        "seed_records": 800,
        "primary_tests": 72,
        "effect_change_tests": 54,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    with (ROOT / path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def csv_record_count(path: Path) -> int:
    with (ROOT / path).open("r", newline="", encoding="utf-8-sig") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with (ROOT / path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_count(label: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise RuntimeError(f"{label}: expected {expected} records, found {actual}")


def aer_study(slug: str, config_path: Path, output_dir: Path) -> dict[str, Any]:
    config = load_json(config_path)
    expected = EXPECTED_AER_COUNTS[slug]
    conditions = config["conditions"]
    seed = config["seed_schedule"]
    params = config["parameters"]

    run_path = output_dir / "pqec_aer_runs.csv"
    seed_path = output_dir / "pqec_aer_seed_manifest.csv"
    primary_path = output_dir / "pqec_aer_paired_stats.csv"
    sensitivity_path = output_dir / "pqec_aer_sensitivity_paired_stats.csv"
    calibration_path = output_dir / "pqec_aer_probe_calibration.csv"

    counts = {
        "conditions": len(conditions),
        "run_rows": csv_record_count(run_path),
        "seed_records": csv_record_count(seed_path),
        "primary_tests": csv_record_count(primary_path),
        "effect_change_tests": csv_record_count(sensitivity_path),
    }
    for field, expected_value in expected.items():
        require_count(f"{slug}.{field}", counts[field], expected_value)

    trials_per_condition = len(seed["seed_block_ids"]) * seed["trials_per_seed_block"]
    total_pairs = len(conditions) * trials_per_condition
    if counts["seed_records"] != total_pairs:
        raise RuntimeError(f"{slug}: seed manifest does not contain one record per paired trajectory")
    if counts["run_rows"] % total_pairs:
        raise RuntimeError(f"{slug}: per-method rows do not divide evenly across paired trajectories")

    sweep_conditions = [
        {
            "condition_id": condition["id"],
            "factor": condition.get("sweep_factor"),
            "scale": condition.get("sweep_scale"),
            "value_us": condition.get("sweep_value_us"),
            "noise_overrides": condition.get("noise_overrides", {}),
        }
        for condition in conditions
    ]

    environment = load_json(output_dir / "pqec_aer_environment.json")
    return {
        "experiment_id": config["experiment_id"],
        "claim_scope": config["claim_scope"],
        "model": "Qiskit Aer density-matrix simulation; not hardware validation",
        "configuration": config_path.as_posix(),
        "output_directory": output_dir.as_posix(),
        "condition_ids": [condition["id"] for condition in conditions],
        "condition_count": len(conditions),
        "seed_block_ids": seed["seed_block_ids"],
        "trials_per_seed_block": seed["trials_per_seed_block"],
        "paired_trajectories_per_condition": trials_per_condition,
        "total_paired_trajectories": total_pairs,
        "per_method_rows": counts["run_rows"],
        "methods_per_trajectory": counts["run_rows"] // total_pairs,
        "probe_shots_per_checkpoint": params["shots"],
        "checkpoint_interval_target_cycles": params["probe_interval"],
        "sweep_conditions": sweep_conditions,
        "primary_paired_tests": counts["primary_tests"],
        "paired_effect_change_tests": counts["effect_change_tests"],
        "holm_family_size": counts["primary_tests"] + counts["effect_change_tests"],
        "bootstrap_resamples_per_test": params["bootstrap_repetitions"],
        "sign_flip_patterns_per_test": params["sign_flip_repetitions"],
        "probe_calibration_records": csv_record_count(calibration_path),
        "software_environment": environment,
        "outputs": {
            "per_method_runs": run_path.as_posix(),
            "summary": (output_dir / "pqec_aer_summary.csv").as_posix(),
            "paired_statistics": primary_path.as_posix(),
            "paired_effect_change_statistics": sensitivity_path.as_posix(),
            "seed_manifest": seed_path.as_posix(),
            "probe_calibration": calibration_path.as_posix(),
            "configuration_snapshot": (output_dir / "pqec_aer_config_snapshot.json").as_posix(),
            "environment_record": (output_dir / "pqec_aer_environment.json").as_posix(),
        },
    }


def analytic_study() -> dict[str, Any]:
    config_path = Path("configs/robustness_v03.json")
    output_dir = Path("results/robustness_v03")
    config = load_json(config_path)
    seed = config["seed_schedule"]
    params = config["parameters"]
    conditions = config["conditions"]
    trials_per_condition = len(seed["seed_block_ids"]) * seed["trials_per_block"]

    run_path = output_dir / "pqec_robustness_runs.csv"
    seed_path = output_dir / "pqec_robustness_seed_manifest.csv"
    stats_path = output_dir / "pqec_robustness_paired_stats.csv"
    rows = csv_record_count(run_path)
    pairs = csv_record_count(seed_path)
    if pairs != len(conditions) * trials_per_condition:
        raise RuntimeError("Analytic robustness seed manifest is incomplete")
    if csv_record_count(stats_path) != 630:
        raise RuntimeError("Analytic robustness statistics table must contain 630 tests")

    return {
        "experiment_id": config["experiment_id"],
        "claim_scope": config["claim_scope"],
        "model": "analytic single-qubit state simulation; separate from Aer runs",
        "configuration": config_path.as_posix(),
        "output_directory": output_dir.as_posix(),
        "condition_count": len(conditions),
        "seed_block_ids": seed["seed_block_ids"],
        "trials_per_seed_block": seed["trials_per_block"],
        "paired_trajectories_per_condition": trials_per_condition,
        "total_paired_trajectories": pairs,
        "per_method_rows": rows,
        "primary_paired_tests": csv_record_count(stats_path),
        "probe_shots_per_checkpoint_reference": params["shots"],
        "checkpoint_interval_reference_target_cycles": params["probe_interval"],
    }


def bundle_artifacts() -> list[Path]:
    files: set[Path] = {Path("README.md")}
    for pattern in (
        "*.py",
        "tests/**/*.py",
        "configs/**/*.json",
        "docs/**/*.md",
        "figures/*.svg",
        "figures/*.png",
        "requirements*.txt",
    ):
        files.update(path.relative_to(ROOT) for path in ROOT.glob(pattern) if path.is_file())

    for directory in (
        Path("results/robustness_v03"),
        Path("results/pqec_v03/aer_t1t2"),
        Path("results/pqec_v03/aer_latency"),
    ):
        files.update(path.relative_to(ROOT) for path in (ROOT / directory).rglob("*") if path.is_file())

    files.discard(MANIFEST_PATH)
    files.discard(CHECKSUM_PATH)
    missing = [path.as_posix() for path in sorted(files) if not (ROOT / path).is_file()]
    if missing:
        raise RuntimeError("Missing frozen artifact(s): " + ", ".join(missing))
    return sorted(files, key=lambda path: path.as_posix().lower())


def main() -> None:
    t1t2 = aer_study(
        "aer_t1t2",
        Path("configs/aer_t1t2_sweep_v03.json"),
        Path("results/pqec_v03/aer_t1t2"),
    )
    latency = aer_study(
        "aer_latency",
        Path("configs/aer_feedback_latency_sweep_v03.json"),
        Path("results/pqec_v03/aer_latency"),
    )
    analytic = analytic_study()
    artifacts = bundle_artifacts()

    manifest = {
        "schema_version": 1,
        "version": "PQEC v0.3",
        "freeze_date": FREEZE_DATE,
        "status": "frozen_simulation_bundle",
        "claim_scope": "Simulation-validated prototype; not hardware-validated QEC and not encoded-qubit error correction.",
        "studies": {
            "analytic_robustness": analytic,
            "aer_t1t2_sensitivity": t1t2,
            "aer_feedback_latency_sensitivity": latency,
        },
        "interpretation": [
            "The analytic robustness study reports conditional gains in selected common-drift settings.",
            "Neither Aer v0.3 sensitivity sweep shows a corrected final-fidelity advantage for guarded PQEC over reactive last-probe control.",
            "The guarded method has a larger RMS per-gate angle residual in every tested Aer v0.3 condition.",
            "The latency sweep holds operation-indexed coherent drift fixed during additional wall-clock wait; its relaxation response is sequence- and simulator-specific.",
        ],
        "reproduction_entry_points": [
            "python pqec_robustness_sweep.py --config configs/robustness_v03.json",
            "python pqec_aer_sweep.py --config configs/aer_t1t2_sweep_v03.json",
            "python pqec_aer_sweep.py --config configs/aer_feedback_latency_sweep_v03.json",
            "python plot_aer_sensitivity_v03.py",
        ],
        "artifact_files": [path.as_posix() for path in artifacts],
        "artifact_file_count_excluding_manifests": len(artifacts),
        "sha256_file": CHECKSUM_PATH.as_posix(),
        "checksum_rule": "SHA256SUMS.txt covers every artifact_file and this version_manifest.json; it does not hash itself.",
    }

    manifest_abs = ROOT / MANIFEST_PATH
    manifest_abs.parent.mkdir(parents=True, exist_ok=True)
    manifest_abs.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    hash_paths = sorted(artifacts + [MANIFEST_PATH], key=lambda path: path.as_posix().lower())
    checksum_text = "".join(f"{file_sha256(path)}  {path.as_posix()}\n" for path in hash_paths)
    (ROOT / CHECKSUM_PATH).write_text(checksum_text, encoding="utf-8", newline="\n")

    print(f"Wrote {MANIFEST_PATH.as_posix()} ({len(artifacts)} artifacts)")
    print(f"Wrote {CHECKSUM_PATH.as_posix()} ({len(hash_paths)} SHA-256 entries)")
    print(
        "Audited Aer records: "
        f"T1/T2={t1t2['total_paired_trajectories']} paired trajectories / "
        f"{t1t2['holm_family_size']} corrected tests; "
        f"latency={latency['total_paired_trajectories']} paired trajectories / "
        f"{latency['holm_family_size']} corrected tests"
    )


if __name__ == "__main__":
    main()
