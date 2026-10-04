# Reproducible Tidepool Simulator

This repository contains a provisioning script for recreating the pinned simulator environment used with the Swift Loop algorithm bridge.

## Quick Start

```bash
./scripts/provision.sh
source workspace/activate-simulator.sh
cd workspace/data-science-simulator
```

The script clones these repositories as siblings under `workspace/` and checks out detached HEADs at the exact commits below:

| Repository | Commit |
| --- | --- |
| `https://github.com/tidepool-org/data-science-simulator.git` | `2f486457c36a96331571bf355324d19cc99a900f` |
| `https://github.com/tidepool-org/LoopAlgorithmToPython.git` | `99ee8097dfb5e26cdc5a2593a74390570a0ae77f` |
| `https://github.com/kenantang/LoopAlgorithm.git` | `a64903188ecbb9df1be198dfe010cdd40eb86727` |

It then points `LoopAlgorithmToPython` at the local pinned `LoopAlgorithm` checkout, builds the Swift dynamic library, and creates/updates the `tidepool-data-science-simulator-swift` conda environment from the simulator repo's `conda-environment-swift.yml`.

## Local Provisioning Assets

Local simulator patches, conda package overrides, and preset validation inputs live under `provisioning_assets/`. The provisioner copies those assets into the workspace after checking out the pinned upstream repositories.

The preset validation project is installed to:

```text
workspace/data-science-simulator/tidepool_data_science_simulator/projects/presets/
```

By default, the preset validation script runs all three noise conditions (`nonoise`, `samplenoise`, `fullnoise`) in a loop. A subset can be requested with `PRESET_NOISE_CONDITIONS`, for example:

```bash
cd workspace/data-science-simulator/tidepool_data_science_simulator/projects/presets
PRESET_NOISE_CONDITIONS=nonoise conda run -n tidepool-data-science-simulator-swift python t1dexi_preset_validation.py
```

The no-noise reference output zip is intentionally not tracked in Git because it is large. Download `t1dexi_preset_validation_reference.zip` from the project shared artifact location and place it here:

```text
provisioning_assets/preset_validation/reference/t1dexi_preset_validation_reference.zip
```

If the file was downloaded elsewhere:

```bash
mkdir -p provisioning_assets/preset_validation/reference
mv /path/to/t1dexi_preset_validation_reference.zip provisioning_assets/preset_validation/reference/
sha256sum provisioning_assets/preset_validation/reference/t1dexi_preset_validation_reference.zip
```

Expected reference zip details:

```text
size:   1002923555 bytes
sha256: 74ba072d92dc9988942e6d7b4feb422ece9531031de6375d292260bce80a79cb
```

To compare generated no-noise outputs against the local reference zip:

```bash
./scripts/compare_preset_reference.py --results-dir workspace/data-science-simulator/tidepool_data_science_simulator/projects/presets/t1dexi_preset_validation
```

## Linux Notes

If `swift` is not already installed, the script installs Swift `5.10.1` locally under `workspace/.toolchains/` on Ubuntu 20.04 or 22.04 x86_64. If the Swift build reports missing OS libraries, rerun with:

```bash
INSTALL_SYSTEM_DEPS=1 ./scripts/provision.sh
```

That mode uses `sudo apt-get` to install the Swift build/runtime dependencies.

On Linux, SwiftPM produces `libLoopAlgorithmToPython.so`; the script also creates `loop_to_python_api/libLoopAlgorithmToPython.dylib` as a compatibility symlink because the Python bridge currently loads that filename.

## Useful Options

```bash
./scripts/provision.sh --workspace /path/to/workspace
./scripts/provision.sh --recreate-conda
./scripts/provision.sh --run-tests
./scripts/provision.sh --skip-swift-build
./scripts/provision.sh --skip-conda
```

The script uses `conda` by default and passes `--solver libmamba` to `conda env create/update`. If your conda install does not yet include the official libmamba solver, install it into base first:

```bash
conda install -n base conda-libmamba-solver
```

You can override the solver with `CONDA_SOLVER=classic`, or force another compatible frontend with `CONDA_FRONTEND=micromamba`.

After a successful run, `workspace/provisioned-commits.txt` records the pinned source checkouts.
