# Provisioning Assets

This directory contains the local files that are layered on top of the pinned upstream repositories during provisioning.

## Layout

```text
library_overrides/
  data-science-simulator/
    tidepool_data_science_simulator/
      makedata/make_patient.py
      models/patient.py
  tidepool-data-science-models/
    tidepool_data_science_models/
      models/simple_metabolism_model.py
      models/treatment_models.py
preset_validation/
  project/
    t1dexi_preset_validation.py
    param_values.py
    tidepool_helmsley_preset_virtual_patients.csv
  reference/
    README.md
    t1dexi_preset_validation_reference.zip  # downloaded separately, not tracked
```

`scripts/provision.sh` copies `library_overrides/` into the provisioned simulator checkout and conda environment, then copies `preset_validation/project/` into:

```text
workspace/data-science-simulator/tidepool_data_science_simulator/projects/presets/
```

The preset script defaults to the no-noise condition. Set `PRESET_NOISE_CONDITIONS=samplenoise,fullnoise` or another comma-separated list to run other modes explicitly.

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
