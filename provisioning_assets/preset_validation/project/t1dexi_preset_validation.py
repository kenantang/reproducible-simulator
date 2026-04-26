import datetime
from datetime import timedelta
import gc
import inspect
import logging
import math
import os
import time

import numpy as np
import pandas as pd

from tidepool_data_science_simulator.models.sensor import IdealSensor
from tidepool_data_science_simulator.models.patient import VirtualPatientModel
from tidepool_data_science_simulator.models.pump import ContinuousInsulinPump
from tidepool_data_science_simulator.models.controller import DoNothingController
from tidepool_data_science_simulator.models.swift_controller import SwiftLoopController
from tidepool_data_science_simulator.makedata.make_simulation import get_canonical_simulation
from tidepool_data_science_simulator.makedata.make_patient import (
    DATETIME_DEFAULT,
    get_canonical_risk_pump_config,
    get_canonical_sensor_config,
    get_canonical_virtual_patient_model_config,
)
from param_values import metabolism_model_params

from tidepool_data_science_simulator.run import run_simulations

from tidepool_data_science_simulator.models.events import CarbTimeline, BolusTimeline, PhysicalActivityTimeline
from tidepool_data_science_simulator.models.simulation import TargetRangeSchedule24hr
from tidepool_data_science_simulator.models.measures import Bolus, PhysicalActivity, InsulinSensitivityFactor, BasalRate, TargetRange

logging.getLogger().setLevel(logging.ERROR)

RANDOM_SEED = 42
PUMP_NOISE_FRACTION = 0.25
PRESET_EPSILON = 0.00000001
DEFAULT_TARGET_MIN = 100
DEFAULT_TARGET_MAX = 120
SCHEDULE_HALF_DAY_MINUTES = 720
ACTIVITY_START_CLOCK_TIME = datetime.time(13, 0)
ACTIVITY_PREP_MINUTES = 60

np.random.seed(RANDOM_SEED)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def env_list(name, default, cast=str, separator=","):
    value = os.environ.get(name)
    if not value:
        return default
    return [cast(item.strip()) for item in value.split(separator) if item.strip()]


def env_int(name, default):
    value = os.environ.get(name)
    return default if not value else int(value)


def env_targets(name, default):
    value = os.environ.get(name)
    if not value:
        return default

    targets = []
    for item in value.split(";"):
        parts = item.replace("(", "").replace(")", "").split(",")
        if len(parts) != 2:
            raise ValueError(f"{name} entries must look like '100,120;150,170'")
        targets.append((int(parts[0].strip()), int(parts[1].strip())))
    return targets


def run_simulation_batch(sim_batch, save_dir, num_procs, batch_num):
    kwargs = {
        "save_dir": save_dir,
        "save_results": True,
        "num_procs": num_procs,
    }
    if "name" in inspect.signature(run_simulations).parameters:
        kwargs["name"] = f"{batch_num}"
    return run_simulations(sim_batch, **kwargs)


def get_noise(value, percentage=PUMP_NOISE_FRACTION, sample=True):
    if sample:
        return np.random.uniform(-percentage, percentage) * value

    noise_factor = np.random.choice([1 + percentage, 1 - percentage])
    return value * noise_factor


def build_metabolic_sensitivity_sim(
    start_glucose_value=110,
    basal_rate=0.3,
    cir=20.0,
    isf=150.0,
    controller=SwiftLoopController,
    add_noise=False,
    sample_noise=False,
    use_target=False,
    carb_timeline=None,
    pump_carb_timeline=None,
    bolus_timeline=None,
    duration_hrs=1,
    pa_timeline=None,
    heart_rate_trace=None,
    w_hr=1.0,
    w_ins=1.0,
    exercise_preset_p=1.0,
    a=0,
    n=0,
    tau=0,
    new_target_min=DEFAULT_TARGET_MIN,
    new_target_max=DEFAULT_TARGET_MAX,
):
    """
    Parameters:
    start_glucose_value: glucose value at the start of the simulation
    basal_rate, cir, isf: human metabolism model EGP, CIR, and ISF
    controller: SwiftLoopController or DoNothingController
    add_noise: noise between controller and human metabolism model parameters
    sample_noise: whether to uniformly sample noise
    use_target: whether to use raised controller target during activity
    new_target_min, new_target_max: controller target range
    carb_timeline, bolus_timeline: patient carb and bolus timeline
    pump_carb_timeline: pump carb timeline
    duration_hrs: simulation number of hours
    pa_timeline: physical activity timeline
    heart_rate_trace: patient heart rate trace
    exercise_preset_p: activity preset
    """

    assert a != 0
    assert n != 0
    assert tau != 0

    t0, patient_config = get_canonical_virtual_patient_model_config(
        start_glucose_value=start_glucose_value,
        basal_rate=basal_rate,
        cir=cir,
        isf=isf,
        carb_timeline=carb_timeline,
        bolus_timeline=bolus_timeline,
        pa_timeline=pa_timeline,
        sim_length=duration_hrs,
        heart_rate_trace=heart_rate_trace,
    )
    patient_config.recommendation_accept_prob = 1.0  # Accept the bolus
    patient_config.w_hr = w_hr
    patient_config.a = a
    patient_config.n = n
    patient_config.tau = tau

    t0, sensor_config = get_canonical_sensor_config(t0, start_value=start_glucose_value)
    sensor_config.std_dev = 1.0

    if add_noise:
        pump_basal_rate = basal_rate + get_noise(basal_rate, PUMP_NOISE_FRACTION, sample_noise)
        pump_cir = cir + get_noise(cir, PUMP_NOISE_FRACTION, sample_noise)
        pump_isf = isf + get_noise(isf, PUMP_NOISE_FRACTION, sample_noise)
    else:
        pump_basal_rate, pump_cir, pump_isf = basal_rate, cir, isf

    t0, pump_config = get_canonical_risk_pump_config(
        t0,
        basal_rate=pump_basal_rate,
        cir=pump_cir,
        isf=pump_isf,
        carb_timeline=pump_carb_timeline,
        bolus_timeline=bolus_timeline,
        pa_timeline=pa_timeline,
    )
    basal_p_factor = -1 + exercise_preset_p  # note: funky math because of how override function works
    pump_config.basal_schedule.set_override(basal_p_factor)

    isf_p_factor = -1 + 1 / max(exercise_preset_p, PRESET_EPSILON)
    pump_config.insulin_sensitivity_schedule.set_override(isf_p_factor)

    cir_p_factor = -1 + 1 / max(exercise_preset_p, PRESET_EPSILON)
    pump_config.carb_ratio_schedule.set_override(cir_p_factor)

    pa = next(iter(pa_timeline.events.values()))
    activity_duration = pa.duration

    target_end_time = add_time(ACTIVITY_START_CLOCK_TIME, timedelta(minutes=activity_duration))
    target_duration = ACTIVITY_PREP_MINUTES + activity_duration
    remaining_time = SCHEDULE_HALF_DAY_MINUTES - target_duration

    if use_target:
        target_range_schedule = TargetRangeSchedule24hr(
            t0,
            start_times=[
                datetime.time(hour=0, minute=0, second=0),
                datetime.time(hour=12, minute=0, second=0),
                target_end_time,
            ],
            values=[
                TargetRange(DEFAULT_TARGET_MIN, DEFAULT_TARGET_MAX, 'mg/dL'),
                TargetRange(new_target_min, new_target_max, 'mg/dL'),
                TargetRange(DEFAULT_TARGET_MIN, DEFAULT_TARGET_MAX, 'mg/dL'),
            ],
            duration_minutes=[SCHEDULE_HALF_DAY_MINUTES, target_duration, remaining_time]
        )
        pump_config.target_range_schedule = target_range_schedule
    else:
        target_range_schedule = TargetRangeSchedule24hr(
            t0,
            start_times=[
                datetime.time(hour=0, minute=0, second=0),
                datetime.time(hour=12, minute=0, second=0),
                target_end_time,
            ],
            values=[
                TargetRange(DEFAULT_TARGET_MIN, DEFAULT_TARGET_MAX, 'mg/dL'),
                TargetRange(DEFAULT_TARGET_MIN, DEFAULT_TARGET_MAX, 'mg/dL'),
                TargetRange(DEFAULT_TARGET_MIN, DEFAULT_TARGET_MAX, 'mg/dL'),
            ],
            duration_minutes=[SCHEDULE_HALF_DAY_MINUTES, target_duration, remaining_time]
        )
        pump_config.target_range_schedule = target_range_schedule

    isf_change_factor = -1 + w_ins
    basal_change_factor = -1 + 1 / (w_ins)
    patient_config.insulin_sensitivity_schedule.schedule_durations = {
        (datetime.time(0, 0), ACTIVITY_START_CLOCK_TIME): SCHEDULE_HALF_DAY_MINUTES + ACTIVITY_PREP_MINUTES,
        (ACTIVITY_START_CLOCK_TIME, target_end_time): target_duration - ACTIVITY_PREP_MINUTES,
        (target_end_time, datetime.time(23, 59, 59)): remaining_time + ACTIVITY_PREP_MINUTES
    }

    patient_config.insulin_sensitivity_schedule.schedule = {
        (datetime.time(0, 0), ACTIVITY_START_CLOCK_TIME): InsulinSensitivityFactor(isf, 'mg/dL/U'),
        (ACTIVITY_START_CLOCK_TIME, target_end_time): InsulinSensitivityFactor(isf * (1.0 + isf_change_factor), 'mg/dL/U'),
        (target_end_time, datetime.time(23, 59, 59)): InsulinSensitivityFactor(isf, 'mg/dL/U')
    }

    patient_config.basal_schedule.schedule_durations = {
        (datetime.time(0, 0), ACTIVITY_START_CLOCK_TIME): SCHEDULE_HALF_DAY_MINUTES + ACTIVITY_PREP_MINUTES,
        (ACTIVITY_START_CLOCK_TIME, target_end_time): target_duration - ACTIVITY_PREP_MINUTES,
        (target_end_time, datetime.time(23, 59, 59)): remaining_time + ACTIVITY_PREP_MINUTES
    }
    patient_config.basal_schedule.schedule = {
        (datetime.time(0, 0), ACTIVITY_START_CLOCK_TIME): BasalRate(basal_rate, 'mg/dL'),
        (ACTIVITY_START_CLOCK_TIME, target_end_time): BasalRate(basal_rate  * (1.0 + basal_change_factor), 'mg/dL'),
        (target_end_time, datetime.time(23, 59, 59)): BasalRate(basal_rate, 'mg/dL'),
    }

    t0, sim = get_canonical_simulation(
        patient_config=patient_config,
        patient_class=VirtualPatientModel,
        sensor_config=sensor_config,
        sensor_class=IdealSensor,
        pump_config=pump_config,
        pump_class=ContinuousInsulinPump,
        controller_class=controller,
        multiprocess=True,
        duration_hrs=duration_hrs,
    )
    return sim


def add_time(clock_time, delta):
    start = datetime.datetime(
        2000, 1, 1,
        hour=clock_time.hour,
        minute=clock_time.minute,
        second=clock_time.second,
    )
    return (start + delta).time()


if __name__ == "__main__":
    save_root_base = os.environ.get('PRESET_SAVE_ROOT', './t1dexi_preset_validation')
    if not os.path.isdir(save_root_base):
        os.makedirs(save_root_base)

    # Grid search parameters
    sim_conditions = env_list('PRESET_SIM_CONDITIONS', ['preset+target'])
    starting_glucoses = env_list('PRESET_STARTING_GLUCOSES', np.arange(70, 270, 20).tolist(), int)
    netIoBs = env_list('PRESET_NET_IOBS', [0], float)
    pa_durations = env_list('PRESET_PA_DURATIONS', [30, 60], int)
    activities = env_list('PRESET_ACTIVITIES', ['walking', 'biking', 'jogging', 'strength training'])

    presets = env_list('PRESET_VALUES', [0.23, 0.22, 0.21, 0.39], float)
    targets = env_targets('PRESET_TARGETS', [
        (100, 120),
        (150, 170)
    ])
    num_virtual_patients = env_int('PRESET_NUM_VIRTUAL_PATIENTS', 72)
    noise_conditions = env_list('PRESET_NOISE_CONDITIONS', ['nonoise'])
    batch_size = env_int('PRESET_BATCH_SIZE', 144)
    num_procs = env_int('PRESET_NUM_PROCS', 48)

    preset_by_activity = {
        'walking': 0.23,
        'biking': 0.22,
        'jogging': 0.21,
        'strength training': 0.39,
    }

    # Virtual patient inputs
    vp_info_path = os.environ.get('PRESET_VP_INFO_PATH', os.path.join(SCRIPT_DIR, 'tidepool_helmsley_preset_virtual_patients.csv'))
    vp_info = pd.read_csv(vp_info_path)
    vp_info = vp_info[vp_info['age'] >= 18] # select adult virtual patients
    vp_info = vp_info.head(num_virtual_patients)
    print(f'vp info: {vp_info}')

    # Metabolism model parameters
    w_ins_vals = metabolism_model_params['w_ins_vals']
    w_hr_vals = metabolism_model_params['w_hr_vals']
    a_vals = metabolism_model_params['a_vals']
    n_vals = metabolism_model_params['n_vals']
    tau_vals = metabolism_model_params['tau_vals']
    hr_vals = metabolism_model_params['hr_vals']

    # Default simulation start time
    t0 = DATETIME_DEFAULT
    sim_activity_starttime = t0 + timedelta(hours=1) # start activity 1 hour after start of simulation

    for sim_condition in sim_conditions:

        use_controller = False
        use_preset = False
        use_target = False

        if sim_condition == 'preset+target':
            use_controller = True
            use_target = True
            use_preset = True
        else:
            raise Exception("This grid search only considers the case when both percentage and target are activated!")

        for noise_condition in noise_conditions:
            
            add_noise = False
            sample_noise = False

            if noise_condition == 'samplenoise':
                add_noise = True
                sample_noise = True
            elif noise_condition == 'fullnoise':
                add_noise = True

            if use_controller:
                experiment_name = 'controller'
            else:
                experiment_name = 'nocontroller'
            
            if not add_noise:
                experiment_name += '_nonoise'
            elif sample_noise:
                experiment_name += '_samplednoise'
            else:
                experiment_name += '_fullnoise'
            
            if use_preset:
                experiment_name += '_withpreset'
            else:
                experiment_name += '_withoutpreset'
            
            if use_target:
                experiment_name += '_withtarget'
            else:
                experiment_name += '_withouttarget'

            print(f"Experiment name: {experiment_name}")

            save_root = os.path.join(save_root_base, experiment_name)
            if not os.path.isdir(save_root):
                os.makedirs(save_root)

            for activity in activities:
                w_ins = w_ins_vals[activity]
                w_hr = w_hr_vals[activity]
                a = a_vals[activity]
                n = n_vals[activity]
                tau = tau_vals[activity]
                hr = hr_vals[activity]

                for starting_glucose in starting_glucoses:
                    for netIoB in netIoBs:
                        for pa_duration in pa_durations:
                            for preset in presets:
                                if preset_by_activity[activity] != preset:
                                    print(f"SKIPPING {activity} with preset {preset}")
                                    continue
                                start_time = time.time()
                                sims = {}
                                for target in targets:
                                    for vp_index, vp in vp_info.iterrows():

                                        isf = vp['isf']
                                        cir = vp['cir']
                                        egp = vp['basal_rate']

                                        if not use_preset:
                                            preset = 1.0
                                        if use_controller:
                                            controller = SwiftLoopController
                                        else:
                                            controller = DoNothingController

                                        sim_name = f"{activity}_{starting_glucose}_{netIoB}_{pa_duration}_{preset}_{target}_{vp_index}"
                                        savefilename = os.path.join(save_root, f"{sim_name}.tsv")

                                        if os.path.isfile(savefilename):
                                            print(f"FOUND FILE FOR {sim_name}.. continuing")
                                            continue

                                        print(f"CREATING {sim_name}")

                                        bolus_timeline = BolusTimeline([t0], [Bolus(netIoB, "U")])
                                        carb_timeline = CarbTimeline()
                                        pump_carb_timeline = CarbTimeline()

                                        pa_timeline = PhysicalActivityTimeline(datetimes=[sim_activity_starttime], events=[PhysicalActivity(activity=activity, duration=pa_duration)])
                                        hrs = [hr]*(pa_duration*60//10)
                                        duration_hrs = math.ceil((pa_duration + 4*60) / 60)
                                        sim = build_metabolic_sensitivity_sim(
                                            start_glucose_value=starting_glucose,
                                            basal_rate=egp,
                                            cir=cir,
                                            isf=isf,
                                            controller=controller,
                                            add_noise=add_noise,
                                            sample_noise=sample_noise,
                                            use_target=use_target,
                                            carb_timeline=carb_timeline,
                                            pump_carb_timeline=pump_carb_timeline,
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
                                            new_target_min=target[0],
                                            new_target_max=target[1]
                                        )
                                        sims[sim_name] = sim
                                        gc.collect()

                                gc.collect()
                                print(f"RUNNING {len(sims)} sims")
                                save_dir = save_root
                                if not os.path.isdir(save_dir):
                                    os.makedirs(save_dir)
                                
                                sims_items = list(sims.items())
                                sim_batches = [dict(sims_items[i:i + batch_size]) for i in range(0, len(sims), batch_size)]

                                for batch_num, sim_batch in enumerate(sim_batches):
                                    print(f"BATCH {batch_num} of {len(sim_batches)}")
                                    all_results, _summary_results_df = run_simulation_batch(
                                        sim_batch,
                                        save_dir=save_dir,
                                        num_procs=num_procs,
                                        batch_num=batch_num
                                    )

                                    for sim_id, results_df in all_results.items():
                                        hr_trace = sims[sim_id].virtual_patient.patient_config.hr_trace
                                        hr_series = pd.Series(data=hr_trace.hr_values, index=hr_trace.datetimes)
                                        filtered_hrs_series = hr_series.loc[hr_series.index.isin(results_df.index)]
                                        results_df['hrs'] = filtered_hrs_series.reindex(results_df.index)

                                end_time = time.time()
                                elapsed_time = end_time - start_time
                                elapsed_hours = elapsed_time / 3600

                                print(f"COMPLETED {len(sims)} SIMS IN {elapsed_hours:.2f} HOURS ({elapsed_time:.2f} SECONDS)")
