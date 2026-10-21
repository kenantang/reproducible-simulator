# Modifications to Upstream Code

This document describes every change the provisioner makes to upstream Tidepool code. Use it to see how the provisioned simulator behaves differently from upstream, and to check whether the overrides still apply when an upstream pin changes.

The provisioner modifies upstream code in three ways:

| Mechanism | Location | Applied by |
| --- | --- | --- |
| Whole-file library overrides | [`library_overrides/`](library_overrides/) | [`replace_simulator_library_scripts`](../scripts/provision.sh#L561) and [`replace_conda_library_scripts`](../scripts/provision.sh#L579) |
| In-place source edits | [`scripts/provision.sh`](../scripts/provision.sh#L357-L559) | [`patch_presets_supporting_types`](../scripts/provision.sh#L550) and related functions |
| Swift patches | [`patches/`](patches/) | [`patch_swift_sources`](../scripts/provision.sh#L627) |

Line references point to the files in this repository as of the commit that last updated this document. Upstream references link to the exact upstream commit used for comparison.

## Upstream Baselines

| Package | Installed from | Baseline |
| --- | --- | --- |
| `data-science-simulator` | Cloned by `provision.sh` | [`2f486457`](https://github.com/tidepool-org/data-science-simulator/tree/2f486457c36a96331571bf355324d19cc99a900f) (pinned) |
| `tidepool-data-science-models` | `conda-environment-swift.yml`, `git+https://github.com/tidepool-org/data-science-models` | [`47a77bd1`](https://github.com/tidepool-org/data-science-models/tree/47a77bd1db61caa12a796bf777114f6bf6912b01) (not pinned; see below) |
| `LoopAlgorithmToPython` | Cloned by `provision.sh` | [`d555ca70`](https://github.com/tidepool-org/LoopAlgorithmToPython/tree/d555ca707dab46b42c9485a3925e263bb09e021a) (pinned) |
| `LoopAlgorithm` | Cloned by `provision.sh` | [`ab55554f`](https://github.com/tidepool-org/LoopAlgorithm/tree/ab55554f72ac191a3698392b447f72117c02cc2d) (pinned) |

> **Note:** `tidepool-data-science-models` is not pinned. The simulator's conda environment installs the default branch as it is at provisioning time, and the overrides then replace two of its files. If upstream changes those files, provisioning will overwrite the changes without warning. `47a77bd1` was the latest commit when this document was written. To find the commit in a given environment, read `direct_url.json` in the package's `.dist-info` directory under `site-packages`.

## Summary of Behavioral Changes

| Area | Change | Affects |
| --- | --- | --- |
| Physical activity | Adds a heart-rate-driven glucose model (`AielloPAModel`) and feeds a heart rate trace into the virtual patient. | Patient glucose |
| Controller insulin type | The controller insulin type can be configured per simulation. Upstream hardcodes `novolog`. | Loop dosing |
| Loop 1.0 emulation | Adds an `emulation` controller setting. `loop-1.0` also forces temp-basal-only dosing. | Loop dosing |
| Target override | While a target override is active, Loop uses the override target for its entire forecast, not just the part before the override ends. | Loop dosing |
| Preset window | Timeline: t0 → (1 h) → activity start → (activity duration) → activity end. The pump preset runs from t0 to activity end; the patient's ISF and basal change only from activity start to activity end. | Pump settings, patient physiology |
| Initial insulin on board | Steady-state IOB is computed from the patient's basal rate, not the pump's. | Initial conditions |
| Patient behavior | Randomized behavior is replaced with fixed values, and automatic meals and correction carbs are removed. | Patient actions |
| Controller defaults | Automatic bolus is enabled by default (`partial_application_factor = 0.4`). | Loop dosing |

## Library Overrides: `tidepool-data-science-models`

These files replace the corresponding files in the installed package inside the conda environment.

### `models/treatment_models.py`

[Override](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/treatment_models.py) · [Upstream](https://github.com/tidepool-org/data-science-models/blob/47a77bd1db61caa12a796bf777114f6bf6912b01/tidepool_data_science_models/models/treatment_models.py)

This override only adds code; nothing upstream is modified.

| Change | Location |
| --- | --- |
| New class `AielloPAModel`. Takes `isf`, `cir`, `w_hr`, `w_egp`, and optional `a` (default `-0.002462`), `n` (default `28`) and `tau` (default `0.9989`). | [L302](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/treatment_models.py#L302) |
| `run(num_hours, hr_amount)` computes a glucose drop proportional to heart rate above 72 bpm. It starts after a delay of `n` 10-second steps and decays by a factor of `tau`. | [L322–L373](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/treatment_models.py#L322-L373) |
| The glucose drop is scaled by `w_hr`. | [L365](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/treatment_models.py#L365) |
| Adds a one-time endogenous glucose production term at t=0, scaled by `w_egp`. | [L368–L371](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/treatment_models.py#L368-L371) |

### `models/simple_metabolism_model.py`

[Override](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/simple_metabolism_model.py) · [Upstream](https://github.com/tidepool-org/data-science-models/blob/47a77bd1db61caa12a796bf777114f6bf6912b01/tidepool_data_science_models/models/simple_metabolism_model.py)

| Change | Location | Upstream |
| --- | --- | --- |
| Constructor adds `pa_model_name="aiello"`, `w_hr=1.0`, `w_egp=0.0`, `a`, `n` and `tau`. | [L27–L33](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/simple_metabolism_model.py#L27-L33) | [L28](https://github.com/tidepool-org/data-science-models/blob/47a77bd1db61caa12a796bf777114f6bf6912b01/tidepool_data_science_models/models/simple_metabolism_model.py#L28) |
| Builds an `AielloPAModel` from those parameters. | [L89–L102](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/simple_metabolism_model.py#L89-L102) | none |
| `run()` adds a `heart_rate=0` argument. When it is positive, the activity model's glucose delta is added to the combined delta. | [L113](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/simple_metabolism_model.py#L113), [L185–L190](library_overrides/tidepool-data-science-models/tidepool_data_science_models/models/simple_metabolism_model.py#L185-L190) | none |

## Library Overrides: `data-science-simulator`

These files replace the corresponding files in the pinned simulator checkout.

### `models/swift_controller.py`

[Override](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/swift_controller.py) · [Upstream](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/swift_controller.py)

| Change | Location | Upstream |
| --- | --- | --- |
| **Insulin type.** Reads `controller_settings['insulin_type']` (default `novolog`) and sends it as `recommendationInsulinType`. | [L81–L82](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/swift_controller.py#L81-L82) | [L78](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/swift_controller.py#L78) (hardcoded `novolog`) |
| The same insulin type is set on every dose in the history, so dose sizing and IOB use the same curve. | [L200](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/swift_controller.py#L200) | [L177](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/swift_controller.py#L177) (no per-dose type) |
| **Emulation.** Reads `controller_settings['emulation']` and passes it to LoopAlgorithm, which decodes it as `AlgorithmEmulationOptions`. `loop-1.0` also forces `recommendationType = 'tempBasal'`, because Tidepool Loop 1.0 did not deliver automatic boluses. | [L94–L99](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/swift_controller.py#L94-L99) | none |
| **Target override.** If `pump_config.target_override = (start, end, lower, upper)` is set and the current time is in `[start, end)`, Loop receives a single target segment covering the forecast horizon (`FORECAST_HORIZON`, 6 h 10 min). | [L12](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/swift_controller.py#L12), [L144–L153](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/swift_controller.py#L144-L153) | [L131](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/swift_controller.py#L131) (scheduled targets only) |

LoopAlgorithm chooses each forecast point's target from the latest segment that starts at or before that point. Without the target override, forecast points after the end of the scheduled activity window would use the default target, and Loop would correct toward it during the activity.

### `models/patient.py`

[Override](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py) · [Upstream](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/patient.py)

**`VirtualPatient`**

| Change | Location | Upstream |
| --- | --- | --- |
| Stores `patient_config.hr_trace`. | [L70](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L70) | none |
| **Initial IOB** comes from the patient's basal schedule instead of the pump's scheduled basal rate. With pump settings noise, the starting IOB therefore reflects the patient's true basal rate. | [L104–L105](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L104-L105) | [L104](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/patient.py#L104) |
| `get_total_insulin_and_carb_amounts()` also returns the current heart rate. | [L291–L316](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L291-L316) | none |
| `add_event()` puts `Carb` events on the carb timelines. Upstream puts them on the bolus timelines, which appears to be a bug. | [L382–L384](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L382-L384) | [L382](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/patient.py#L382) |
| `predict()` and `run_metabolism_model()` pass the heart rate through to `SimpleMetabolismModel.run()`. | [L388–L413](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L388-L413), [L440–L462](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L440-L462) | none |
| `instantiate_metabolism_model()` passes `w_hr`, `w_egp`, `a`, `n` and `tau` from `patient_config`. Defaults are `1.0`, `0.0` and `None`; `None` means the `AielloPAModel` default is used. | [L467–L500](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L467-L500) | none |

**`VirtualPatientModel`**

| Change | Location | Upstream |
| --- | --- | --- |
| `meal_model` is empty. Upstream schedules breakfast, two snacks, lunch and dinner. | [L628](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L628) | [L625](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/patient.py#L625) |
| `get_user_inputs()` takes carbs only from `carb_event_timeline`. It no longer generates random meals or correction carbs, and it returns the current heart rate. | [L683–L701](library_overrides/data-science-simulator/tidepool_data_science_simulator/models/patient.py#L683-L701) | [L686](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/models/patient.py#L686) |

### `makedata/make_patient.py`

[Override](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py) · [Upstream](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/makedata/make_patient.py)

| Change | Location | Upstream |
| --- | --- | --- |
| **New `get_heartrate_trace()`.** Builds a 10-second `HeartRateTrace` from the activity timeline: 0 bpm outside activity, and the supplied trace (or 150 bpm if none is supplied) during activity. | [L33–L56](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L33-L56) | none |
| **`get_canonical_risk_pump_config()`** takes basal rate, CIR, ISF, target range, carb and bolus timelines, and the activity timeline as arguments. Upstream hardcodes 0.3 U/hr, 20 g/U, 150 mg/dL/U and 100–120 mg/dL. | [L81](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L81) | [L56](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/makedata/make_patient.py#L56) |
| Pump schedules are split into three segments around the preset window, which runs from t0 to activity end (t0 + 1 h + activity duration). All three segments hold the same value. | [L109–L143](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L109-L143) | none |
| The basal, CIR and ISF schedules get `override_end_time`, so a preset override ends with the preset window. | [L145–L146](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L145-L146) | none |
| **`get_canonical_risk_patient_config()`** takes the same arguments. The patient's ISF and basal schedules are split at the activity window (1 hour after t0 until the activity ends). The calling script sets the values for that window. | [L176](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L176), [L208–L227](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L208-L227) | [L173](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/makedata/make_patient.py#L173) |
| Corrects upstream's patient ISF unit (`md/dL / U` to `mg/dL/U`) and basal unit (`mg/dL` to `U/hr`). | [L220](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L220), [L226](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L226) | none |
| Attaches `pa_timeline` and `hr_trace` to the patient config. | [L242](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L242), [L249](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L249) | none |
| Timelines default to empty. Upstream defaults to a zero carb and a zero bolus at t0. | [L94–L101](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L94-L101), [L189–L198](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L189-L198) | none |
| **`get_canonical_virtual_patient_model_config()`** passes the new arguments through and replaces randomized patient behavior with fixed values (table below). | [L362–L378](library_overrides/data-science-simulator/tidepool_data_science_simulator/makedata/make_patient.py#L362-L378) | [L341](https://github.com/tidepool-org/data-science-simulator/blob/2f486457c36a96331571bf355324d19cc99a900f/tidepool_data_science_simulator/makedata/make_patient.py#L341) |

Virtual patient behavior settings:

| Setting | Upstream | Override | Effect |
| --- | --- | --- | --- |
| `recommendation_accept_prob` | uniform(0.8, 0.99) | 1.0 | Always accepts recommendations |
| `min_bolus_rec_threshold` | uniform(0.4, 0.6) | 0.0 | No minimum bolus size |
| `correct_bolus_bg_threshold` | uniform(140, 190) | 500 | No user correction boluses |
| `correct_carb_bg_threshold` | uniform(70, 90) | 0.0 | No user correction carbs |
| `carb_count_noise_percentage` | uniform(0.1, 0.25) | 0.0 | Carbs reported exactly |
| `report_carb_probability` | uniform(0.95, 1.0) | 1.0 | Always reports carbs |
| `recommendation_meal_attention_time_minutes` | `inf` | 10 | Accepts a bolus recommendation only within 10 minutes of a meal |

## In-Place Source Edits

`provision.sh` makes these edits directly to the upstream checkouts. Each one first checks whether it has already been applied, so reprovisioning is safe.

| Target file | Change | Location |
| --- | --- | --- |
| `LoopAlgorithmToPython/Package.swift` | Points the `LoopAlgorithm` dependency at the local pinned checkout (`../LoopAlgorithm`). | [L357](../scripts/provision.sh#L357) |
| `data-science-simulator/setup.py` | Corrects the `vizualization` package-name typo so the editable install works. | [L379](../scripts/provision.sh#L379) |
| `models/measures.py` | Appends the `PhysicalActivity` and `HeartRateTrace` classes. | [L417](../scripts/provision.sh#L417) |
| `models/events.py` | Appends `PhysicalActivityTimeline`. | [L448](../scripts/provision.sh#L448) |
| `makedata/scenario_parser.py` | Adds a `pa_timeline=None` field to `PatientConfig`. | [L469](../scripts/provision.sh#L469) |
| `models/simulation.py` | `set_override()` skips schedule segments that end after the schedule's `override_end_time`, so a preset override applies only within its window. | [L494](../scripts/provision.sh#L494) |
| `makedata/make_controller.py` | Changes default controller settings: `maximum_autobolus` from `0.0` to `None`, and `partial_application_factor` to `0.4` (automatic bolus enabled). | [L526](../scripts/provision.sh#L526) |

## Swift Patches

Each patch file begins with a full explanation of why it is needed.

| Patch | Purpose | Applied at |
| --- | --- | --- |
| [`LoopAlgorithmToPython-loop-quantity-port.patch`](patches/LoopAlgorithmToPython-loop-quantity-port.patch) | Ports the bridge from HealthKit types (`HKQuantity`/`HKUnit`) to `LoopQuantity`/`LoopUnit`, which the pinned `LoopAlgorithm` uses. | [L632](../scripts/provision.sh#L632) |
| [`LoopAlgorithm-linux-swift5-language-mode.patch`](patches/LoopAlgorithm-linux-swift5-language-mode.patch) | Builds `LoopAlgorithm` in Swift 5 language mode on Linux, where Swift 6 strict concurrency rejects its use of `DispatchQueue.concurrentPerform`. | [L635](../scripts/provision.sh#L635) (Linux only) |

The pinned `LoopAlgorithm` already includes `AlgorithmEmulationOptions` and the `rapidActingAdult` and `rapidActingChild` insulin types, so Loop 1.0 emulation needs no patch.
