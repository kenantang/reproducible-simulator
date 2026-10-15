"""
Paired comparison of two activity interventions over the t1dexi preset validation grid:

    loop_2_0_preset   activity preset and raised target during the activity window, current LoopAlgorithm
    loop_1_0_workout  no preset, raised target during the activity window, LoopAlgorithm in loop-1.0 emulation

Each arm runs under two controller insulin options:

    RapidActingInsulin       loop-1.0: rapidActingAdult for adult VPs, rapidActingChild for pediatric VPs
                             current:  rapidActingAdult for all VPs
    UltraRapidActingInsulin  fiasp for all VPs

Results go to <save root>/<insulin option>/<arm>_<noise condition>/<sim name>.tsv.

Pump settings noise is seeded from the grid point only (not the arm or insulin option), so every arm
of a grid point sees identical pump basal/CIR/ISF. Matched pairs share a file name across the arm folders.
"""
import functools
import gc
import math
import os
import sys
import time
from datetime import timedelta

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_DIR = os.path.join(SCRIPT_DIR, '..', 'presets')
sys.path.insert(0, PRESETS_DIR)

from t1dexi_preset_validation import (
    NO_PRESET,
    NOISE_CONDITIONS,
    PEDIATRIC_AGE_CUTOFF,
    build_metabolic_sensitivity_sim,
    env_int,
    env_list,
    get_noise_rng,
    run_simulation_batch,
)
from param_values import metabolism_model_params

from tidepool_data_science_simulator.makedata.make_patient import DATETIME_DEFAULT
from tidepool_data_science_simulator.models.swift_controller import SwiftLoopController
from tidepool_data_science_simulator.models.events import CarbTimeline, BolusTimeline, PhysicalActivityTimeline
from tidepool_data_science_simulator.models.measures import Bolus, PhysicalActivity

# Same values as preset_by_activity in t1dexi_preset_validation.py
PRESET_BY_ACTIVITY = {
    'walking': 0.23,
    'biking': 0.22,
    'jogging': 0.21,
    'strength training': 0.39,
}

RAISED_TARGET = (150, 170)


class ArmSwiftLoopController(SwiftLoopController):
    """
    SwiftLoopController with an arm's emulation and insulin type. Both are set at construction because
    Simulation.__init__ already asks the controller for its t=0 recommendation; setting them on a
    built sim would leave that first decision on the default (automatic bolus, novolog) settings.
    """

    def __init__(self, time, controller_config, emulation=None, insulin_type=None, **kwargs):
        super().__init__(time, controller_config, **kwargs)
        settings = self.controller_config.controller_settings
        if emulation:
            settings['emulation'] = emulation
        settings['insulin_type'] = insulin_type


INSULIN_OPTIONS = ['RapidActingInsulin', 'UltraRapidActingInsulin']

ARMS = {
    'loop_2_0_preset': {
        'use_preset': True,
        'use_target': True,
        'target': RAISED_TARGET,
        'emulation': None,
        'insulin_types': {
            'RapidActingInsulin': {'adult': 'rapidActingAdult', 'pediatric': 'rapidActingAdult'},
            'UltraRapidActingInsulin': {'adult': 'fiasp', 'pediatric': 'fiasp'},
        },
    },
    'loop_1_0_workout': {
        'use_preset': False,
        'use_target': True,
        'target': RAISED_TARGET,
        'emulation': 'loop-1.0',
        # Tidepool Loop 1.0 offered only the rapid-acting adult and child models
        'insulin_types': {
            'RapidActingInsulin': {'adult': 'rapidActingAdult', 'pediatric': 'rapidActingChild'},
            'UltraRapidActingInsulin': {'adult': 'fiasp', 'pediatric': 'fiasp'},
        },
    },
}


if __name__ == "__main__":
    save_root_base = os.environ.get('PRESET_SAVE_ROOT', './preset_intervention_comparison')
    if not os.path.isdir(save_root_base):
        os.makedirs(save_root_base)

    # Grid search parameters (same defaults and env overrides as t1dexi_preset_validation.py)
    starting_glucoses = env_list('PRESET_STARTING_GLUCOSES', list(range(70, 270, 20)), int)
    # Whole numbers parse as ints so names print like the default ints ("0", not "0.0").
    netIoBs = env_list('PRESET_NET_IOBS', [0, 1, 2, 3], lambda value: int(float(value)) if float(value).is_integer() else float(value))
    pa_durations = env_list('PRESET_PA_DURATIONS', [30, 60], int)
    activities = env_list('PRESET_ACTIVITIES', ['walking', 'biking', 'jogging', 'strength training'])
    arms = env_list('PRESET_ARMS', list(ARMS))
    unknown_arms = set(arms) - set(ARMS)
    if unknown_arms:
        raise ValueError(f"PRESET_ARMS has unknown values {sorted(unknown_arms)}; expected some of {list(ARMS)}")
    insulin_options = env_list('PRESET_INSULIN_OPTIONS', INSULIN_OPTIONS)
    unknown_insulin_options = set(insulin_options) - set(INSULIN_OPTIONS)
    if unknown_insulin_options:
        raise ValueError(f"PRESET_INSULIN_OPTIONS has unknown values {sorted(unknown_insulin_options)}; expected some of {INSULIN_OPTIONS}")

    num_virtual_patients = env_int('PRESET_NUM_VIRTUAL_PATIENTS', None)
    noise_conditions = env_list('PRESET_NOISE_CONDITIONS', NOISE_CONDITIONS)
    unknown_noise_conditions = set(noise_conditions) - set(NOISE_CONDITIONS)
    if unknown_noise_conditions:
        raise ValueError(f"PRESET_NOISE_CONDITIONS has unknown values {sorted(unknown_noise_conditions)}; expected some of {NOISE_CONDITIONS}")
    batch_size = env_int('PRESET_BATCH_SIZE', 144)
    num_procs = env_int('PRESET_NUM_PROCS', 48)

    # Virtual patient inputs
    vp_info_path = os.environ.get('PRESET_VP_INFO_PATH', os.path.join(PRESETS_DIR, 'tidepool_helmsley_preset_virtual_patients.csv'))
    vp_info = pd.read_csv(vp_info_path)
    if num_virtual_patients is not None:
        vp_info = vp_info.head(num_virtual_patients)
    print(f'vp info: {vp_info}')

    # Metabolism model parameters
    w_ins_vals = metabolism_model_params['w_ins_vals']
    w_hr_vals = metabolism_model_params['w_hr_vals']
    a_vals = metabolism_model_params['a_vals']
    n_vals = metabolism_model_params['n_vals']
    tau_vals = metabolism_model_params['tau_vals']
    hr_vals = metabolism_model_params['hr_vals']
    peds_hr_vals = metabolism_model_params['peds_hr_vals']

    # Default simulation start time
    t0 = DATETIME_DEFAULT
    sim_activity_starttime = t0 + timedelta(hours=1)  # start activity 1 hour after start of simulation

    for noise_condition in noise_conditions:

        add_noise = noise_condition != 'nonoise'
        sample_noise = noise_condition == 'samplenoise'

        for activity in activities:
            w_ins = w_ins_vals[activity]
            w_hr = w_hr_vals[activity]
            a = a_vals[activity]
            n = n_vals[activity]
            tau = tau_vals[activity]

            for starting_glucose in starting_glucoses:
                for netIoB in netIoBs:
                    for pa_duration in pa_durations:
                        for insulin_option in insulin_options:
                            for arm_name in arms:
                                arm = ARMS[arm_name]
                                preset = PRESET_BY_ACTIVITY[activity] if arm['use_preset'] else NO_PRESET

                                save_dir = os.path.join(save_root_base, insulin_option, f"{arm_name}_{noise_condition}")
                                if not os.path.isdir(save_dir):
                                    os.makedirs(save_dir)

                                start_time = time.time()
                                sims = {}
                                for vp_index, vp in vp_info.iterrows():

                                    is_pediatric = vp['age'] < PEDIATRIC_AGE_CUTOFF
                                    hr = peds_hr_vals[activity] if is_pediatric else hr_vals[activity]
                                    insulin_type = arm['insulin_types'][insulin_option]['pediatric' if is_pediatric else 'adult']

                                    # Same name across arm folders marks a matched pair
                                    sim_name = f"{activity}_{starting_glucose}_{netIoB}_{pa_duration}_{vp_index}"
                                    savefilename = os.path.join(save_dir, f"{sim_name}.tsv")

                                    if os.path.isfile(savefilename):
                                        print(f"FOUND FILE FOR {insulin_option}/{arm_name}/{sim_name}.. continuing")
                                        continue

                                    print(f"CREATING {insulin_option}/{arm_name}/{sim_name} ({insulin_type})")

                                    bolus_timeline = BolusTimeline([t0], [Bolus(netIoB, "U")])
                                    pa_timeline = PhysicalActivityTimeline(datetimes=[sim_activity_starttime], events=[PhysicalActivity(activity=activity, duration=pa_duration)])
                                    hrs = [hr] * (pa_duration * 60 // 10)
                                    duration_hrs = math.ceil((pa_duration + 4 * 60) / 60)
                                    sim = build_metabolic_sensitivity_sim(
                                        start_glucose_value=starting_glucose,
                                        basal_rate=vp['basal_rate'],
                                        cir=vp['cir'],
                                        isf=vp['isf'],
                                        controller=functools.partial(
                                            ArmSwiftLoopController,
                                            emulation=arm['emulation'],
                                            insulin_type=insulin_type,
                                        ),
                                        add_noise=add_noise,
                                        sample_noise=sample_noise,
                                        # Seeded by grid point only, so all arms and insulin options draw identical pump noise
                                        noise_rng=get_noise_rng(noise_condition, sim_name),
                                        use_target=arm['use_target'],
                                        carb_timeline=CarbTimeline(),
                                        pump_carb_timeline=CarbTimeline(),
                                        bolus_timeline=bolus_timeline,
                                        duration_hrs=duration_hrs,
                                        pa_timeline=pa_timeline,
                                        heart_rate_trace=hrs,
                                        w_hr=w_hr,
                                        w_ins=w_ins,
                                        exercise_preset_p=preset,
                                        a=a,
                                        n=n,
                                        tau=tau,
                                        new_target_min=arm['target'][0],
                                        new_target_max=arm['target'][1],
                                    )
                                    sims[sim_name] = sim
                                    gc.collect()

                                gc.collect()
                                print(f"RUNNING {len(sims)} {insulin_option}/{arm_name} sims")

                                sims_items = list(sims.items())
                                sim_batches = [dict(sims_items[i:i + batch_size]) for i in range(0, len(sims), batch_size)]

                                for batch_num, sim_batch in enumerate(sim_batches):
                                    print(f"BATCH {batch_num} of {len(sim_batches)}")
                                    run_simulation_batch(
                                        sim_batch,
                                        save_dir=save_dir,
                                        num_procs=num_procs,
                                        batch_num=batch_num
                                    )

                                elapsed_time = time.time() - start_time
                                print(f"COMPLETED {len(sims)} SIMS IN {elapsed_time / 3600:.2f} HOURS ({elapsed_time:.2f} SECONDS)")
