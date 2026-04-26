# Preset Validation Reference

The reference archive is intentionally not tracked in Git because it is large.

Download `t1dexi_preset_validation_reference.zip` from the project shared artifact location and place it in this directory:

```text
provisioning_assets/preset_validation/reference/t1dexi_preset_validation_reference.zip
```

Expected file details:

```text
size:   1002923555 bytes
sha256: 74ba072d92dc9988942e6d7b4feb422ece9531031de6375d292260bce80a79cb
```

The default comparator looks for this path automatically:

```bash
./scripts/compare_preset_reference.py --results-dir workspace/data-science-simulator/tidepool_data_science_simulator/projects/presets/t1dexi_preset_validation
```
