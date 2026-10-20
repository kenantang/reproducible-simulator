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
| `https://github.com/tidepool-org/LoopAlgorithmToPython.git` | `d555ca707dab46b42c9485a3925e263bb09e021a` |
| `https://github.com/tidepool-org/LoopAlgorithm.git` | `ab55554f72ac191a3698392b447f72117c02cc2d` |

It then points `LoopAlgorithmToPython` at the local pinned `LoopAlgorithm` checkout, applies the patches in `provisioning_assets/patches/`, builds the Swift dynamic library, and creates/updates the `tidepool-data-science-simulator-swift` conda environment from the simulator repo's `conda-environment-swift.yml`.

Upstream `LoopAlgorithmToPython` still targets the older HealthKit-based `LoopAlgorithm` API, so `LoopAlgorithmToPython-loop-quantity-port.patch` ports it to `LoopQuantity`/`LoopUnit`. Each patch file starts with a note explaining why it is needed. If a pin is bumped and a patch no longer applies, provisioning stops with an error naming the patch.

Upgrading from an older provisioned workspace: the existing `workspace/LoopAlgorithm` and `workspace/LoopAlgorithmToPython` checkouts contain the previous pins' patches, so provisioning refuses to move them. Remove those two directories and rerun the script.

## Local Provisioning Assets

Local simulator patches, conda package overrides, and the preset validation and preset intervention comparison projects live under `provisioning_assets/` (see [provisioning_assets/README.md](provisioning_assets/README.md)). The provisioner copies those assets into the workspace after checking out the pinned upstream repositories.

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

## Preset Intervention Comparison

The pinned `LoopAlgorithm` includes `AlgorithmEmulationOptions`, which reproduces deployed Tidepool Loop 1.0 behavior. The preset intervention comparison uses it to run a paired comparison of two activity interventions over the same grid as the preset validation:

| Arm | Preset | Raised target `(150, 170)` | Algorithm |
| --- | --- | --- | --- |
| `loop_2_0_preset` | yes | yes | current LoopAlgorithm |
| `loop_1_0_workout` | no | yes | `loop-1.0` emulation (temp basal only) |

Each arm runs under two controller insulin options:

| Insulin option | `loop_2_0_preset` | `loop_1_0_workout` |
| --- | --- | --- |
| `RapidActingInsulin` | `rapidActingAdult` for all VPs | `rapidActingAdult` for adults, `rapidActingChild` for pediatric VPs |
| `UltraRapidActingInsulin` | `fiasp` for all VPs | `fiasp` for all VPs |

The preset validation script does not use emulation or insulin options. Its controller uses the default insulin type (`novolog`, which LoopAlgorithm runs on the `rapidActingAdult` model).

The comparison is installed to:

```text
workspace/data-science-simulator/tidepool_data_science_simulator/projects/preset_intervention_comparison/
```

It imports the simulation builder from the sibling `projects/presets/` directory, so it only runs from the provisioned workspace. It reads the same `PRESET_*` grid and noise variables as the validation script. `PRESET_ARMS` and `PRESET_INSULIN_OPTIONS` take comma-separated subsets:

```bash
cd workspace/data-science-simulator/tidepool_data_science_simulator/projects/preset_intervention_comparison
PRESET_NOISE_CONDITIONS=nonoise PRESET_INSULIN_OPTIONS=RapidActingInsulin \
  conda run -n tidepool-data-science-simulator-swift python preset_intervention_comparison.py
```

Results are written to `<PRESET_SAVE_ROOT>/<insulin option>/<arm>_<noise condition>/<activity>_<glucose>_<iob>_<duration>_<vp>.tsv`, with `./preset_intervention_comparison` as the default save root. Pump settings noise is seeded from the grid point only, so a file name shared across arm folders marks a matched pair with identical pump basal, CIR, and ISF.

## Linux Notes

`LoopAlgorithm` requires Swift 6. If a Swift 6 toolchain is not already installed, the script installs Swift `6.0.3` locally under `workspace/.toolchains/` on Ubuntu 20.04 or 22.04 x86_64. On Linux, `LoopAlgorithm` is built in Swift 5 language mode (see `LoopAlgorithm-linux-swift5-language-mode.patch`) because its `DispatchQueue.concurrentPerform` code only passes Swift 6 strict concurrency checks against Darwin's Dispatch. If the Swift build reports missing OS libraries, rerun with:

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
./scripts/provision.sh --skip-swift-install
./scripts/provision.sh --skip-conda
./scripts/provision.sh --no-smoke-test
CONDA_ENV_NAME=my-sim-env ./scripts/provision.sh
```

Run `./scripts/provision.sh --help` for the full list of options and environment overrides.

The script uses `conda` by default and passes `--solver libmamba` to `conda env create/update`. If your conda install does not yet include the official libmamba solver, install it into base first:

```bash
conda install -n base conda-libmamba-solver
```

You can override the solver with `CONDA_SOLVER=classic`, or force another compatible frontend with `CONDA_FRONTEND=micromamba`.

After a successful run, `workspace/provisioned-commits.txt` records the pinned source checkouts.
