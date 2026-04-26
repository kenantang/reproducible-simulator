#!/usr/bin/env python3
"""Compare generated preset validation outputs with the bundled reference zip."""

from __future__ import annotations

import argparse
import copy
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = (
    REPO_ROOT
    / "workspace"
    / "data-science-simulator"
    / "tidepool_data_science_simulator"
    / "projects"
    / "presets"
    / "t1dexi_preset_validation"
)
DEFAULT_REFERENCE_ZIP = (
    REPO_ROOT
    / "provisioning_assets"
    / "preset_validation"
    / "reference"
    / "t1dexi_preset_validation_reference.zip"
)
DEFAULT_CONDITION = "controller_nonoise_withpreset_withtarget"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare preset validation TSV/JSON output with the reference zip."
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Generated results root, or the condition directory itself.",
    )
    parser.add_argument(
        "--reference-zip",
        type=Path,
        default=DEFAULT_REFERENCE_ZIP,
        help="Reference zip to compare against.",
    )
    parser.add_argument(
        "--condition",
        default=DEFAULT_CONDITION,
        help="Condition directory to compare.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-9,
        help="Maximum allowed absolute numeric TSV difference.",
    )
    parser.add_argument(
        "--strict-json",
        action="store_true",
        help="Do not ignore patient.name in JSON config comparisons.",
    )
    return parser.parse_args()


def condition_dir(results_dir: Path, condition: str) -> Path:
    if results_dir.name == condition:
        return results_dir
    return results_dir / condition


def is_macos_artifact(name: str) -> bool:
    parts = name.split("/")
    return "__MACOSX" in parts or any(part.startswith("._") for part in parts)


def reference_member_maps(
    zf: zipfile.ZipFile, condition: str
) -> tuple[dict[str, str], dict[str, str]]:
    tsv_members: dict[str, str] = {}
    json_members: dict[str, str] = {}

    for name in zf.namelist():
        if name.endswith("/") or is_macos_artifact(name):
            continue
        parts = name.split("/")
        if len(parts) < 2 or parts[-2] != condition:
            continue

        filename = parts[-1]
        if filename.endswith(".tsv"):
            tsv_members[filename] = name
        elif filename.endswith(".json"):
            json_members[filename] = name

    return tsv_members, json_members


def normalize_json(obj: object, strict_json: bool) -> object:
    if strict_json:
        return obj

    normalized = copy.deepcopy(obj)
    if isinstance(normalized, dict) and isinstance(normalized.get("patient"), dict):
        normalized["patient"].pop("name", None)
    return normalized


def compare_tsvs(
    local_tsv: dict[str, Path],
    ref_tsv: dict[str, str],
    zf: zipfile.ZipFile,
) -> dict[str, object]:
    stats: dict[str, object] = {
        "tsv_compared": 0,
        "shape_mismatches": 0,
        "column_mismatches": 0,
        "nonnumeric_mismatches": 0,
        "max_numeric_abs_diff": 0.0,
        "worst_file": None,
        "worst_col": None,
    }

    for filename in sorted(set(local_tsv) & set(ref_tsv)):
        local_df = pd.read_csv(local_tsv[filename], sep="\t")
        with zf.open(ref_tsv[filename]) as ref_file:
            ref_df = pd.read_csv(ref_file, sep="\t")

        if local_df.shape != ref_df.shape:
            stats["shape_mismatches"] += 1
            continue

        if list(local_df.columns) != list(ref_df.columns):
            stats["column_mismatches"] += 1
            continue

        stats["tsv_compared"] += 1

        for col in local_df.columns:
            local_series = local_df[col]
            ref_series = ref_df[col]

            if pd.api.types.is_numeric_dtype(local_series) and pd.api.types.is_numeric_dtype(ref_series):
                local_num = pd.to_numeric(local_series, errors="coerce")
                ref_num = pd.to_numeric(ref_series, errors="coerce")

                if not np.array_equal(local_num.isna().to_numpy(), ref_num.isna().to_numpy()):
                    stats["nonnumeric_mismatches"] += 1
                    break

                diff = (local_num - ref_num).abs()
                if diff.notna().any():
                    max_diff = float(diff.max())
                    if max_diff > float(stats["max_numeric_abs_diff"]):
                        stats["max_numeric_abs_diff"] = max_diff
                        stats["worst_file"] = filename
                        stats["worst_col"] = col
            else:
                local_values = local_series.fillna("__NA__").astype(str).to_numpy()
                ref_values = ref_series.fillna("__NA__").astype(str).to_numpy()
                if not np.array_equal(local_values, ref_values):
                    stats["nonnumeric_mismatches"] += 1
                    break

    return stats


def compare_jsons(
    local_json: dict[str, Path],
    ref_json: dict[str, str],
    zf: zipfile.ZipFile,
    strict_json: bool,
) -> dict[str, object]:
    stats: dict[str, object] = {
        "json_compared": 0,
        "json_mismatches": 0,
        "first_json_mismatch": None,
    }

    for filename in sorted(set(local_json) & set(ref_json)):
        with local_json[filename].open() as local_file:
            local_obj = normalize_json(json.load(local_file), strict_json)
        with zf.open(ref_json[filename]) as ref_file:
            ref_obj = normalize_json(
                json.load(io.TextIOWrapper(ref_file, encoding="utf-8")),
                strict_json,
            )

        stats["json_compared"] += 1
        if local_obj != ref_obj:
            stats["json_mismatches"] += 1
            if stats["first_json_mismatch"] is None:
                stats["first_json_mismatch"] = filename

    return stats


def main() -> int:
    args = parse_args()
    result_condition_dir = condition_dir(args.results_dir.resolve(), args.condition)
    reference_zip = args.reference_zip.resolve()

    if not result_condition_dir.is_dir():
        print(f"ERROR: missing results condition directory: {result_condition_dir}", file=sys.stderr)
        return 2
    if not reference_zip.is_file():
        print(f"ERROR: missing reference zip: {reference_zip}", file=sys.stderr)
        return 2

    local_tsv = {path.name: path for path in result_condition_dir.glob("*.tsv")}
    local_json = {path.name: path for path in result_condition_dir.glob("*.json")}

    with zipfile.ZipFile(reference_zip) as zf:
        ref_tsv, ref_json = reference_member_maps(zf, args.condition)

        stats: dict[str, object] = {
            "condition": args.condition,
            "local_tsv": len(local_tsv),
            "local_json": len(local_json),
            "ref_tsv": len(ref_tsv),
            "ref_json": len(ref_json),
            "missing_in_reference": len(set(local_tsv) - set(ref_tsv))
            + len(set(local_json) - set(ref_json)),
            "missing_local": len(set(ref_tsv) - set(local_tsv))
            + len(set(ref_json) - set(local_json)),
        }
        stats.update(compare_tsvs(local_tsv, ref_tsv, zf))
        stats.update(compare_jsons(local_json, ref_json, zf, args.strict_json))

    for key, value in stats.items():
        print(f"{key}: {value}")

    failed = (
        stats["missing_in_reference"]
        or stats["missing_local"]
        or stats["shape_mismatches"]
        or stats["column_mismatches"]
        or stats["nonnumeric_mismatches"]
        or stats["json_mismatches"]
        or float(stats["max_numeric_abs_diff"]) > args.tolerance
    )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
