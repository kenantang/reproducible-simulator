# Provisioning Assets

This directory contains the local files that are layered on top of the pinned upstream repositories during provisioning. [OVERRIDES.md](OVERRIDES.md) describes how each override and provisioning edit differs from upstream.

## Layout

```text
library_overrides/
  data-science-simulator/
    tidepool_data_science_simulator/
      makedata/make_patient.py
      models/patient.py
      models/swift_controller.py
  tidepool-data-science-models/
    tidepool_data_science_models/
      models/simple_metabolism_model.py
      models/treatment_models.py
patches/
  LoopAlgorithm-linux-swift5-language-mode.patch
  LoopAlgorithmToPython-loop-quantity-port.patch
preset_validation/
  project/
    t1dexi_preset_validation.py
    param_values.py
    tidepool_helmsley_preset_virtual_patients.csv
  reference/
    README.md
    t1dexi_preset_validation_reference.zip  # downloaded separately, not tracked
preset_intervention_comparison/
  project/
    preset_intervention_comparison.py
```

`scripts/provision.sh` applies `patches/` to the pinned Swift checkouts, copies `library_overrides/` into the provisioned simulator checkout and conda environment, then copies the three `preset_validation/project/` files listed above into:

```text
workspace/data-science-simulator/tidepool_data_science_simulator/projects/presets/
```

and `preset_intervention_comparison.py` into:

```text
workspace/data-science-simulator/tidepool_data_science_simulator/projects/preset_intervention_comparison/
```

Only the listed files are copied. Other files added to these project directories are not installed until `provision.sh` copies them.

`models/swift_controller.py` reads two optional controller settings from `controller_config.controller_settings`:

- `insulin_type`: the LoopAlgorithm insulin type for dose sizing and for every dose in the history (default `novolog`, which runs on the `rapidActingAdult` model). The preset intervention comparison sets `rapidActingAdult`, `rapidActingChild`, or `fiasp`.
- `emulation`: passed to LoopAlgorithm's `AlgorithmEmulationOptions`. With `loop-1.0`, the controller also switches to temp-basal-only dosing, as Tidepool Loop 1.0 did.

The preset intervention comparison sets both at controller construction, so the t=0 recommendation also uses them. See the top-level README for the comparison's arms and output layout.

`models/swift_controller.py` also supports an optional `pump_config.target_override` of `(start, end, lower, upper)`. While a decision time falls in `[start, end)`, the controller sends Loop that range as the only target segment, so the whole forecast is corrected to the override target instead of each forecast point's scheduled target. The preset script sets it for the raised activity target.

The preset script runs all three noise conditions (`nonoise`, `samplenoise`, `fullnoise`) by default. Set `PRESET_NOISE_CONDITIONS` to a comma-separated subset (for example `PRESET_NOISE_CONDITIONS=nonoise`) to run only some of them.

## Reference Zip

The reference output archive is intentionally ignored by Git:

```text
preset_validation/reference/t1dexi_preset_validation_reference.zip
```

Download the zip from the project shared artifact location and place it at that exact path before running `scripts/compare_preset_reference.py`.

Expected reference zip details:

```text
size:   1002923555 bytes
sha256: 74ba072d92dc9988942e6d7b4feb422ece9531031de6375d292260bce80a79cb
```
