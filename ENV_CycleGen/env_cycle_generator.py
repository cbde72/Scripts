#!/usr/bin/env python3
"""ENV Cycle Generator V04: temperature, humidity, Operating Mode and voltage profiles.
Python >=3.10, standard library only.
Run without arguments for Tkinter, --example output.csv for the full headless
export, --cycle1 cycle1.csv for the first-cycle Excel XY breakpoint table, or
--breakpoints points.csv for the exact phase-derived breakpoint export.
"""
from __future__ import annotations
import argparse
import bisect
import csv
import heapq
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

TIME_UNITS = {'Seconds': (1.0, 's'), 'Minutes': (60.0, 'min'), 'Hours': (3600.0, 'h')}


def convert_axis_input(text, from_unit, to_unit):
    """Convert a displayed axis field, preserving blank automatic settings."""
    raw = text.strip().replace(',', '.')
    if not raw:
        return ''
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('X Step and X End must be positive and finite, or blank for automatic.')
    converted = value*(TIME_UNITS[from_unit][0]/TIME_UNITS[to_unit][0])
    if not math.isfinite(converted) or converted <= 0:
        raise ValueError('Converted axis value is outside the supported numeric range.')
    return format(converted, '.15g')


def convert_axis_start_input(text, from_unit, to_unit):
    raw = text.strip().replace(',', '.')
    value = 0.0 if not raw else float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError('X Start must be finite and greater than or equal to zero.')
    return format(value * TIME_UNITS[from_unit][0] / TIME_UNITS[to_unit][0], '.15g')


@dataclass
class Parameters:
    test_id: str = 'ENV_026'
    temperature_c: float = 80.0
    humidity_rh: float | None = 60.0
    active_hours: float = 47.0
    standby_hours: float = 1.0
    active_mode: str = '3.2'
    standby_mode: str = '3.1'
    sample_seconds: float = 60.0
    cycles: int = 1
    # Optional engineering additions; not specified ramps in ENV_026.
    ramps: bool = False
    start_temperature_c: float = 23.0
    ramp_c_per_min: float = 1.0
    ramp_mode: str = '3.1'
    minimum_temperature_c: float = -40.0
    maximum_temperature_c: float = 80.0
    room_temperature_c: float = 23.0
    temperature_change_rate: float = 4.0
    cold_dwell_minutes: float = 15.0
    cold_active_minutes: float = 5.0
    hot_dwell_minutes: float = 15.0
    hot_standby_minutes: float = 0.0
    number_of_cycles: int = 870
    tracker_step_seconds: float = 60.0
    cooling_to_min_minutes: float = 60.0
    cycling_cold_dwell_minutes: float = 90.0
    warming_to_room_minutes: float = 60.0
    warming_to_max_minutes: float = 90.0
    cycling_hot_dwell_minutes: float = 110.0
    cooling_to_room_minutes: float = 70.0
    cold_check_start_minutes: float = 120.0
    cold_check_duration_minutes: float = 1.0
    gradient_step_c: float = 5.0
    gradient_standby_minutes: float = 25.0
    gradient_umax_minutes: float = 1.0
    gradient_pause_minutes: float = 3.0
    gradient_umin_minutes: float = 1.0
    x_axis_step_seconds: float | None = None
    x_axis_end_seconds: float | None = None
    x_axis_start_seconds: float = 0.0
    x_axis_unit: str = 'Seconds'
    total_hours: float = 504.0
    inactive_hours: float = 47.0
    functional_hours: float = 1.0
    frost_cycles: int = 5
    rising_humidity_rh: float = 93.0
    cooling_humidity_rh: float = 80.0
    hot_humidity_rh: float = 93.0
    climate_check_minutes: float = 1.0
    climate_rise_minutes: float = 90.0
    climate_hot_minutes: float = 240.0
    climate_fall_minutes: float = 90.0
    climate_room_minutes: float = 60.0
    climate_tail_minutes: float = 540.0
    frost_prehold_minutes: float = 150.0
    frost_cooling_minutes: float = 30.0
    frost_hold_minutes: float = 180.0
    frost_warming_minutes: float = 90.0
    frost_posthold_minutes: float = 90.0
    nominal_voltage_v: float = 48.0
    minimum_voltage_v: float = 36.0
    maximum_voltage_v: float = 52.0
    ua_voltage_v: float = 48.0
    ub_voltage_v: float = 48.0
    off_voltage_v: float = 0.0
    precondition_minutes: float = 30.0
    activation_minutes: float = 10.0
    load_open_seconds: float = 10.0
    load_hold_seconds: float = 10.0
    load_pause_seconds: float = 5.0
    load_close_seconds: float = 10.0
    load_start_delay_seconds: float = 1.0
    load_max_percent: float = 100.0
    load_axis_min_percent: float = 0.0
    load_axis_max_percent: float = 100.0
    load_axis_step_percent: float = 10.0
    voltage_axis_min_v: float = 0.0
    voltage_axis_max_v: float = 60.0
    voltage_axis_step_v: float = 5.0
    temperature_axis_min_c: float = -50.0
    temperature_axis_max_c: float = 100.0
    temperature_axis_step_c: float = 10.0
    humidity_axis_min_rh: float = 50.0
    humidity_axis_max_rh: float = 100.0
    humidity_axis_step_rh: float = 5.0

    def validate(self):
        if self.x_axis_unit not in TIME_UNITS:
            raise ValueError('Time Unit must be Seconds, Minutes or Hours.')
        if self.test_id not in {'ENV_026', 'ENV_013', 'ENV_014', 'ENV_015', 'ENV_012', 'ENV_002', 'ENV_003', 'ENV_004'}:
            raise ValueError('Unknown Test ID.')
        for name, value in asdict(self).items():
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError(f'{name}: Value must be finite.')
        for v in (self.x_axis_step_seconds, self.x_axis_end_seconds):
            if v is not None and v <= 0:
                raise ValueError('X Step and X End must be positive, or blank for automatic.')
        if self.x_axis_start_seconds < 0:
            raise ValueError('X Start must be greater than or equal to zero.')
        if self.test_id == 'ENV_026' and (self.active_hours <= 0 or self.standby_hours <= 0):
            raise ValueError('Both operating durations must be greater than zero.')
        if self.sample_seconds <= 0:
            raise ValueError('Time step must be greater than zero.')
        if min(self.load_start_delay_seconds, self.load_open_seconds, self.load_hold_seconds,
               self.load_close_seconds, self.load_pause_seconds) < 0:
            raise ValueError('Actuator times must be greater than or equal to zero.')
        if self.load_open_seconds + self.load_hold_seconds + self.load_close_seconds + self.load_pause_seconds <= 0:
            raise ValueError('Actuator cycle duration must be greater than zero.')
        if self.tracker_step_seconds < 0:
            raise ValueError('Tracker Step must be zero (continuous) or greater than zero.')
        if isinstance(self.cycles, bool) or not isinstance(self.cycles, int) or not 1 <= self.cycles <= 10000:
            raise ValueError('Repetitions must be an integer from 1 to 10000.')
        if self.humidity_rh is not None and not 0 <= self.humidity_rh <= 100:
            raise ValueError('Relative Humidity must be between 0 and 100 % RH.')
        if any(not -100 <= t <= 250 for t in (self.temperature_c, self.start_temperature_c)):
            raise ValueError('Temperature is outside the generator range of −100 to +250 °C.')
        if self.ramp_c_per_min <= 0:
            raise ValueError('Temperature Change Rate must be greater than zero.')
        allowed = {'1.1', '1.2', '2.1', '2.2', '2.3', '2.4', '3.1', '3.2', '3.3', '3.4'}
        if any(m not in allowed for m in (self.active_mode, self.standby_mode, self.ramp_mode)):
            raise ValueError('Unknown Operating Mode.')
        if self.test_id in {'ENV_013', 'ENV_014', 'ENV_015', 'ENV_002', 'ENV_003', 'ENV_004'}:
            if (isinstance(self.number_of_cycles, bool) or not isinstance(self.number_of_cycles, int)
                    or not 1 <= self.number_of_cycles <= 10000):
                raise ValueError('Number of Cycles must be an integer from 1 to 10000.')
            low, room, high = self.minimum_temperature_c, self.room_temperature_c, self.maximum_temperature_c
            if self.test_id == 'ENV_003':
                low = room
            if not -100 <= low <= room <= high <= 250 or low >= high:
                raise ValueError('Require −100 ≤ Tminop ≤ Troom ≤ Tmaxop ≤ 250 °C and Tminop < Tmaxop.')
            if self.temperature_change_rate <= 0:
                raise ValueError('Temperature Change Rate must be greater than zero.')
        if self.test_id == 'ENV_004':
            if not 0 < self.minimum_voltage_v <= self.nominal_voltage_v <= self.maximum_voltage_v:
                raise ValueError('Require 0 < Umin ≤ UN ≤ Umax.')
            if self.ua_voltage_v <= 0 or self.ub_voltage_v <= 0:
                raise ValueError('UA and UB must be positive.')
            if self.precondition_minutes <= 0 or self.activation_minutes <= 0:
                raise ValueError('Preconditioning and Activation durations must be positive.')
        if self.test_id == 'ENV_013':
            if self.cold_dwell_minutes <= 0 or self.hot_dwell_minutes <= 0:
                raise ValueError('Both Dwell Times must be greater than zero.')
            if not 0 <= self.cold_active_minutes <= self.cold_dwell_minutes:
                raise ValueError('Cold dwell time in normal operation must be between zero and Cold Dwell Time.')
            if not 0 <= self.hot_standby_minutes <= self.hot_dwell_minutes:
                raise ValueError('Hot dwell time in stand-by must be between zero and Hot Dwell Time.')
        if self.test_id == 'ENV_014':
            durations = [self.cooling_to_min_minutes, self.cycling_cold_dwell_minutes,
                         self.warming_to_room_minutes, self.warming_to_max_minutes,
                         self.cycling_hot_dwell_minutes, self.cooling_to_room_minutes]
            if any(v <= 0 for v in durations):
                raise ValueError('All Temperature Cycling segment durations must be greater than zero.')
            start, duration = self.cold_check_start_minutes, self.cold_check_duration_minutes
            if duration < 0 or (duration > 0 and not (self.cooling_to_min_minutes <= start
                    and start + duration <= self.cooling_to_min_minutes+self.cycling_cold_dwell_minutes)):
                raise ValueError('Cold Function Check must fit within the Cold Dwell; duration 0 disables it.')
        if self.test_id == 'ENV_015':
            if self.gradient_step_c <= 0:
                raise ValueError('Temperature Increment must be greater than zero.')
            if any(v <= 0 for v in [self.gradient_standby_minutes, self.gradient_umax_minutes,
                                    self.gradient_pause_minutes, self.gradient_umin_minutes]):
                raise ValueError('All Gradient Dwell phase durations must be greater than zero.')
            moves = math.ceil((self.room_temperature_c-self.minimum_temperature_c)/self.gradient_step_c)
            moves += math.ceil((self.maximum_temperature_c-self.minimum_temperature_c)/self.gradient_step_c)
            moves += math.ceil((self.maximum_temperature_c-self.room_temperature_c)/self.gradient_step_c)
            if moves*self.number_of_cycles > 80000:
                raise ValueError('Too many gradient points. Increase Temperature Increment or reduce Number of Cycles.')
        if self.test_id == 'ENV_012':
            if min(self.total_hours, self.inactive_hours, self.functional_hours) <= 0:
                raise ValueError('Total Duration and both Operating Durations must be positive.')
            if self.functional_hours > self.total_hours:
                raise ValueError('Final functional period cannot exceed Total Duration.')
        if self.test_id in {'ENV_002', 'ENV_003'}:
            if any(not 0 <= v <= 100 for v in (self.rising_humidity_rh, self.cooling_humidity_rh, self.hot_humidity_rh)):
                raise ValueError('Relative Humidity must be between 0 and 100 % RH.')
            if min(self.climate_rise_minutes, self.climate_hot_minutes, self.climate_fall_minutes,
                   self.climate_room_minutes, self.climate_check_minutes) <= 0:
                raise ValueError('All climate segment and Function Check durations must be positive.')
            if self.climate_check_minutes > self.climate_hot_minutes:
                raise ValueError('Function Checks must fit inside the Hot Dwell.')
            if self.test_id == 'ENV_002':
                if isinstance(self.frost_cycles, bool) or not isinstance(self.frost_cycles, int) or not 0 <= self.frost_cycles <= self.number_of_cycles:
                    raise ValueError('Frost Cycles must be an integer between 0 and Number of Cycles.')
                if min(self.climate_tail_minutes, self.frost_prehold_minutes, self.frost_cooling_minutes,
                       self.frost_hold_minutes, self.frost_warming_minutes, self.frost_posthold_minutes) <= 0:
                    raise ValueError('All frost and final room-hold durations must be positive.')


@dataclass
class Phase:
    cycle: int
    name: str
    duration_s: float
    temperature_start_c: float
    temperature_end_c: float
    humidity_rh: float | None
    mode: str
    voltage_v: float | None = None
    undefined_humidity_label: str = ""
    humidity_at_threshold: float | None = None


@dataclass
class Sample:
    time_s: float
    cycle: int
    phase: str
    temperature_c: float
    humidity_rh: float | None
    operation_mode: str
    voltage_v: float | None = None
    undefined_humidity_label: str = ""
    load_percent: float = 0.0


def env026(p: Parameters) -> list[Phase]:
    """Chapter 20: timing starts at stabilized Tmaxop, 47h 3.2 + 1h 3.1."""
    p.validate()
    phases = []
    for cycle in range(1, p.cycles + 1):
        ramp_s = abs(p.temperature_c - p.start_temperature_c) / p.ramp_c_per_min * 60
        if p.ramps and ramp_s > 0:
            phases.append(Phase(cycle, 'Initial Temperature Ramp (optional)', ramp_s,
                                p.start_temperature_c, p.temperature_c, p.humidity_rh, p.ramp_mode))
        phases.append(Phase(cycle, 'Normal Operation', p.active_hours * 3600,
                            p.temperature_c, p.temperature_c, p.humidity_rh, p.active_mode))
        phases.append(Phase(cycle, 'Stand-by', p.standby_hours * 3600,
                            p.temperature_c, p.temperature_c, p.humidity_rh, p.standby_mode))
        if p.ramps and ramp_s > 0:
            phases.append(Phase(cycle, 'Recovery Temperature Ramp (optional)', ramp_s,
                                p.temperature_c, p.start_temperature_c, p.humidity_rh, p.ramp_mode))
    return phases


def env013(p: Parameters) -> list[Phase]:
    """Current Chapter 21: 15-min total dwells; final 5 min cold active.

    The cold-dwell wording remains ambiguous; total dwell follows the parameter table.
    """
    p.validate()
    low, room, high = p.minimum_temperature_c, p.room_temperature_c, p.maximum_temperature_c
    phases = []
    for cycle in range(1, p.number_of_cycles + 1):
        def add(name, minutes, start, end, mode):
            if minutes > 0:
                phases.append(Phase(cycle, name, minutes * 60, start, end, p.humidity_rh, mode))
        rate = p.temperature_change_rate
        add('Cooling to Tminop', (room-low)/rate, room, low, p.standby_mode)
        add('Cold Dwell - Stand-by', p.cold_dwell_minutes-p.cold_active_minutes, low, low, p.standby_mode)
        add('Cold Dwell - Normal Operation', p.cold_active_minutes, low, low, p.active_mode)
        add('Heating to Tmaxop', (high-low)/rate, low, high, p.active_mode)
        add('Hot Dwell - Normal Operation', p.hot_dwell_minutes-p.hot_standby_minutes, high, high, p.active_mode)
        add('Hot Dwell - Stand-by', p.hot_standby_minutes, high, high, p.standby_mode)
        add('Cooling to Troom', (high-room)/rate, high, room, p.standby_mode)
    return phases


def default_parameters(test_id='ENV_026'):
    p = Parameters(test_id=test_id)
    if test_id == 'ENV_004':
        return replace(p, temperature_change_rate=1.0, number_of_cycles=1)
    if test_id == 'ENV_014':
        return replace(p, room_temperature_c=20.0, number_of_cycles=30)
    if test_id == 'ENV_015':
        return replace(p, room_temperature_c=25.0, temperature_change_rate=1.0, number_of_cycles=1)
    if test_id == 'ENV_012':
        return replace(p, temperature_c=65.0, humidity_rh=93.0, standby_mode='2.1')
    if test_id == 'ENV_002':
        return replace(p, minimum_temperature_c=-10.0, room_temperature_c=25.0,
                       maximum_temperature_c=65.0, number_of_cycles=10, standby_mode='3.1')
    if test_id == 'ENV_003':
        return replace(p, minimum_temperature_c=23.0, room_temperature_c=23.0,
                       maximum_temperature_c=80.0, number_of_cycles=5, standby_mode='3.1',
                       rising_humidity_rh=97.5, climate_rise_minutes=120.0,
                       climate_hot_minutes=45.0, climate_fall_minutes=90.0, climate_room_minutes=45.0)
    return p


def env014(p: Parameters) -> list[Phase]:
    """Chapter 8, 480-min reference profile; short cold check timing is assumed."""
    p.validate()
    low, room, high = p.minimum_temperature_c, p.room_temperature_c, p.maximum_temperature_c
    durations = [p.cooling_to_min_minutes, p.cycling_cold_dwell_minutes, p.warming_to_room_minutes,
                 p.warming_to_max_minutes, p.cycling_hot_dwell_minutes, p.cooling_to_room_minutes]
    temperatures = [room, low, low, room, high, high, room]
    names = ['Cooling to Tminop', 'Cold Dwell', 'Warming to Troom',
             'Warming to Tmaxop', 'Hot Dwell', 'Cooling to Troom']
    knots = [0.0]
    for duration in durations:
        knots.append(knots[-1]+duration)
    phases = []
    for cycle in range(1, p.number_of_cycles+1):
        for i, duration in enumerate(durations):
            cuts = [knots[i], knots[i+1]]
            if i == 1 and p.cold_check_duration_minutes > 0:
                cuts += [p.cold_check_start_minutes, p.cold_check_start_minutes+p.cold_check_duration_minutes]
            cuts = sorted(set(cuts))
            for a, b in zip(cuts, cuts[1:]):
                cold_check = (i == 1 and p.cold_check_duration_minutes > 0
                              and p.cold_check_start_minutes <= a < p.cold_check_start_minutes+p.cold_check_duration_minutes)
                active = i in (3, 4) or cold_check
                ta = temperatures[i]+(temperatures[i+1]-temperatures[i])*(a-knots[i])/duration
                tb = temperatures[i]+(temperatures[i+1]-temperatures[i])*(b-knots[i])/duration
                name = 'Cold Function Check' if cold_check else names[i]
                phases.append(Phase(cycle, name, (b-a)*60, ta, tb, p.humidity_rh,
                                    p.active_mode if active else p.standby_mode))
    return phases


def gradient_targets(p: Parameters):
    """Include each turn once; clip the last step to hit non-grid extrema."""
    points = [p.room_temperature_c]
    for end in [p.minimum_temperature_c, p.maximum_temperature_c, p.room_temperature_c]:
        start = points[-1]
        count = math.ceil(abs(end-start)/p.gradient_step_c)
        direction = 1 if end >= start else -1
        for i in range(1, count+1):
            points.append(end if i == count else start+direction*i*p.gradient_step_c)
    return points


def env015(p: Parameters) -> list[Phase]:
    """Chapter 7: 5-K steps, 1 K/min, 25+1+3+1-min dwell sequence."""
    p.validate()
    points = gradient_targets(p)
    phases = []
    for cycle in range(1, p.number_of_cycles+1):
        for i, temperature in enumerate(points):
            if i:
                previous = points[i-1]
                phases.append(Phase(cycle, 'Temperature Gradient Ramp',
                    abs(temperature-previous)/p.temperature_change_rate*60,
                    previous, temperature, p.humidity_rh, p.standby_mode))
            sequence = [('Gradient Dwell - Stand-by', p.gradient_standby_minutes, p.standby_mode),
                        ('Function Check - Umax', p.gradient_umax_minutes, p.active_mode),
                        ('Gradient Dwell - Stand-by Pause', p.gradient_pause_minutes, p.standby_mode),
                        ('Function Check - Umin', p.gradient_umin_minutes, p.active_mode)]
            for name, minutes, mode in sequence:
                phases.append(Phase(cycle, name, minutes*60, temperature, temperature, p.humidity_rh, mode))
    return phases


def env012(p: Parameters) -> list[Phase]:
    """Current Chapter 15: 504h total; final hour active."""
    p.validate()
    total, inactive, active = p.total_hours*3600, p.inactive_hours*3600, p.functional_hours*3600
    final_start = total-active
    t, cycle, phases = 0.0, 1, []
    while t < final_start:
        for name, duration, mode in [('Inactive', inactive, p.standby_mode),
                                     ('Normal Operation', active, p.active_mode)]:
            end = min(final_start, t+duration)
            if end > t:
                phases.append(Phase(cycle, name, end-t, p.temperature_c, p.temperature_c, p.humidity_rh, mode))
                t = end
        cycle += 1
        if len(phases) > 100000:
            raise ValueError('Too many Operating Mode periods. Increase the Operating Durations.')
    phases.append(Phase(phases[-1].cycle if phases else 1, 'Final Normal Operation', active, p.temperature_c,
                        p.temperature_c, p.humidity_rh, p.active_mode))
    return phases


def climate_cycle(p: Parameters, cycle: int, frost: bool):
    phases = []
    def add(name, minutes, start, end, humidity, mode=None):
        if minutes > 0:
            phases.append(Phase(cycle, name, minutes*60, start, end, humidity, mode or p.standby_mode))
    room, hot, cold = p.room_temperature_c, p.maximum_temperature_c, p.minimum_temperature_c
    rh, cool_rh, check = p.rising_humidity_rh, p.cooling_humidity_rh, p.climate_check_minutes
    def high_dwell(label):
        rh = p.hot_humidity_rh if p.test_id == 'ENV_002' else p.rising_humidity_rh
        add(label+' - Function Check', check, hot, hot, rh, p.active_mode)
        add(label+' - Inactive', p.climate_hot_minutes-check, hot, hot, rh)
    if p.test_id == 'ENV_003':
        add('Room Temperature Hold', p.climate_room_minutes, room, room, p.humidity_rh)
        add('Temperature Rise - Condensation', p.climate_rise_minutes, room, hot, rh)
        high_dwell('Hot Dwell')
        add('Temperature Fall - Drying', p.climate_fall_minutes, hot, room, cool_rh)
    else:
        for label in ('B', 'F'):
            add('Temperature Rise to Interval '+label, p.climate_rise_minutes, room, hot, rh)
            high_dwell('Interval '+label)
            add('Temperature Fall after Interval '+label, p.climate_fall_minutes, hot, room, cool_rh)
            if label == 'B':
                add('Intermediate Room Hold', p.climate_room_minutes, room, room, p.humidity_rh)
        if frost:
            add('Room Hold before Frost', p.frost_prehold_minutes, room, room, None)
            add('Cooling to Frost Temperature', p.frost_cooling_minutes, room, cold, None)
            add('Frost Dwell', p.frost_hold_minutes, cold, cold, None)
            add('Warming after Frost', p.frost_warming_minutes, cold, room, None)
            add('Room Hold after Frost', p.frost_posthold_minutes, room, room, None)
        else:
            add('Final Room Hold - No Frost', p.climate_tail_minutes, room, room, p.humidity_rh)
    return phases


def env002(p: Parameters) -> list[Phase]:
    p.validate()
    # ENV_002 humidity is determined solely by temperature direction and Troom.
    # Split every crossing at the exact threshold so plot, tracker and CSV agree.
    phases = []
    for cycle in range(1, p.number_of_cycles+1):
        for ph in climate_cycle(p, cycle, frost=cycle <= p.frost_cycles):
            a, b = ph.temperature_start_c, ph.temperature_end_c
            cuts = [0.0, 1.0]
            if min(a, b) < p.room_temperature_c < max(a, b):
                cuts.insert(1, (p.room_temperature_c-a)/(b-a))
            for u, v in zip(cuts, cuts[1:]):
                ta, tb = a+u*(b-a), a+v*(b-a)
                midpoint = (ta+tb)/2
                below_troom = midpoint < p.room_temperature_c
                falling = tb < ta
                rh = None if below_troom else (p.cooling_humidity_rh if falling else p.rising_humidity_rh)
                phases.append(replace(ph, duration_s=ph.duration_s*(v-u),
                    temperature_start_c=ta, temperature_end_c=tb,
                    humidity_rh=rh,
                    undefined_humidity_label='n.def.' if rh is None else '',
                    humidity_at_threshold=None))
    return phases


def env003(p: Parameters) -> list[Phase]:
    p.validate()
    return [phase for cycle in range(1, p.number_of_cycles+1)
            for phase in climate_cycle(p, cycle, frost=False)]


def env004(p: Parameters) -> list[Phase]:
    """Five checks from Chapter 6; ramp rate and UN are explicit recipe assumptions."""
    p.validate()
    inactive_voltage = (p.ua_voltage_v if p.standby_mode.startswith('3.') else
                        p.ub_voltage_v if p.standby_mode.startswith('2.') else p.off_voltage_v)
    phases = []
    for cycle in range(1, p.cycles+1):
        def add(name, minutes, ta, tb, mode, voltage):
            if minutes > 0:
                phases.append(Phase(cycle,name,minutes*60,ta,tb,p.humidity_rh,mode,voltage))
        previous = p.room_temperature_c
        for label, temperature, checks in [
                ('Troom',p.room_temperature_c,[('UN',p.nominal_voltage_v)]),
                ('Tmin',p.minimum_temperature_c,[('Umax',p.maximum_voltage_v),('Umin',p.minimum_voltage_v)]),
                ('Tmax',p.maximum_temperature_c,[('Umax',p.maximum_voltage_v),('Umin',p.minimum_voltage_v)])]:
            add('Temperature Transition to '+label,abs(temperature-previous)/p.temperature_change_rate,
                previous,temperature,p.standby_mode,inactive_voltage)
            add('Preconditioning at '+label,p.precondition_minutes,temperature,temperature,
                p.standby_mode,inactive_voltage)
            for voltage_label, voltage in checks:
                add('Function Check '+label+' / '+voltage_label,p.activation_minutes,
                    temperature,temperature,p.active_mode,voltage)
            previous = temperature
        if p.ramps or cycle < p.cycles:
            add('Recovery to Troom',abs(previous-p.room_temperature_c)/p.temperature_change_rate,
                previous,p.room_temperature_c,p.standby_mode,inactive_voltage)
    return phases


GENERATORS = {'ENV_004': env004, 'ENV_026': env026, 'ENV_013': env013, 'ENV_014': env014, 'ENV_015': env015,
              'ENV_012': env012, 'ENV_002': env002, 'ENV_003': env003}
TEST_NAMES = {'ENV_026': 'High Temperature Durability Test',
              'ENV_013': 'Temperature Cycle Durability Test',
              'ENV_014': 'Temperature Cycling Test', 'ENV_015': 'Temperature Gradient Test',
              'ENV_012': 'Steady-state Damp Heat Test', 'ENV_002': 'Damp Heat Cycle 2 – Frost Test',
              'ENV_003': 'Damp Heat Cycle 3 – Condensation Test'}
TEST_NAMES['ENV_004'] = 'Five-Point Function/Performance Test'


def description_path(test_id):
    if test_id not in TEST_NAMES:
        raise ValueError('Unknown Test ID.')
    path = Path(__file__).resolve().parent / 'descriptions' / (test_id+'.html')
    if not path.is_file():
        raise FileNotFoundError(f'Description not found: {path}. Extract the complete application ZIP.')
    return path


def open_description(test_id):
    import webbrowser
    path = description_path(test_id)
    if not webbrowser.open_new_tab(path.as_uri()):
        raise OSError(f'Could not open the default browser. Open this file manually: {path}')



SOURCE_DOCUMENT = '2.ENV_Test_Plan_Cp_r00v05(2).docx'
DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name('env_config_V04.json')
COMMON_KEYS = 'humidity_rh active_mode standby_mode'.split()
CSV_KEYS = ['sample_seconds']
ACTUATOR_KEYS = 'load_start_delay_seconds load_open_seconds load_hold_seconds load_pause_seconds load_close_seconds load_max_percent'.split()
ACTUATOR_VISIBLE_KEYS = 'load_start_delay_seconds load_open_seconds load_hold_seconds load_close_seconds load_pause_seconds'.split()
VOLTAGE_KEYS = 'minimum_voltage_v nominal_voltage_v ua_voltage_v ub_voltage_v maximum_voltage_v off_voltage_v'.split()
CHART_KEYS = ('tracker_step_seconds x_axis_unit x_axis_start_seconds x_axis_step_seconds x_axis_end_seconds '
              'temperature_axis_min_c temperature_axis_max_c temperature_axis_step_c '
              'humidity_axis_min_rh humidity_axis_max_rh humidity_axis_step_rh '
              'load_axis_min_percent load_axis_max_percent load_axis_step_percent '
              'voltage_axis_min_v voltage_axis_max_v voltage_axis_step_v').split()
GLOBAL_SECTION_KEYS = {'csv': CSV_KEYS, 'actuator': ACTUATOR_KEYS,
                       'chart': CHART_KEYS, 'voltage': VOLTAGE_KEYS}
GLOBAL_KEYS = set(key for keys in GLOBAL_SECTION_KEYS.values() for key in keys)
GLOBAL_VISIBLE_KEYS = {'sample_seconds', 'tracker_step_seconds', 'x_axis_unit',
                       'x_axis_start_seconds', 'x_axis_step_seconds', 'x_axis_end_seconds'}
TEST_KEYS = {
 'ENV_004': 'room_temperature_c minimum_temperature_c maximum_temperature_c precondition_minutes activation_minutes temperature_change_rate cycles ramps',
 'ENV_026': 'temperature_c active_hours standby_hours cycles ramps start_temperature_c ramp_c_per_min ramp_mode',
 'ENV_013': 'minimum_temperature_c maximum_temperature_c room_temperature_c temperature_change_rate cold_dwell_minutes cold_active_minutes hot_dwell_minutes hot_standby_minutes number_of_cycles',
 'ENV_014': 'minimum_temperature_c maximum_temperature_c room_temperature_c cooling_to_min_minutes cycling_cold_dwell_minutes warming_to_room_minutes warming_to_max_minutes cycling_hot_dwell_minutes cooling_to_room_minutes cold_check_start_minutes cold_check_duration_minutes number_of_cycles',
 'ENV_015': 'minimum_temperature_c maximum_temperature_c room_temperature_c gradient_step_c temperature_change_rate gradient_standby_minutes gradient_umax_minutes gradient_pause_minutes gradient_umin_minutes number_of_cycles',
 'ENV_012': 'temperature_c total_hours inactive_hours functional_hours',
 'ENV_002': 'minimum_temperature_c maximum_temperature_c room_temperature_c number_of_cycles frost_cycles rising_humidity_rh hot_humidity_rh cooling_humidity_rh climate_check_minutes climate_rise_minutes climate_hot_minutes climate_fall_minutes climate_room_minutes climate_tail_minutes frost_prehold_minutes frost_cooling_minutes frost_hold_minutes frost_warming_minutes frost_posthold_minutes',
 'ENV_003': 'maximum_temperature_c room_temperature_c number_of_cycles rising_humidity_rh cooling_humidity_rh climate_check_minutes climate_rise_minutes climate_hot_minutes climate_fall_minutes climate_room_minutes',
}
# These are initial visibility choices, not hard-coded GUI constraints.
HIDDEN_KEYS = set('ramps start_temperature_c ramp_c_per_min ramp_mode hot_standby_minutes cooling_to_min_minutes cycling_cold_dwell_minutes warming_to_room_minutes warming_to_max_minutes cycling_hot_dwell_minutes cooling_to_room_minutes cold_check_start_minutes climate_rise_minutes climate_hot_minutes climate_fall_minutes climate_room_minutes climate_tail_minutes frost_prehold_minutes frost_cooling_minutes frost_hold_minutes frost_warming_minutes frost_posthold_minutes ub_voltage_v temperature_axis_min_c temperature_axis_max_c temperature_axis_step_c humidity_axis_min_rh humidity_axis_max_rh humidity_axis_step_rh load_close_seconds load_max_percent load_axis_min_percent load_axis_max_percent load_axis_step_percent'.split())
SPECIAL_CONTROLS = {'tracker_step_seconds','x_axis_unit','x_axis_start_seconds','x_axis_step_seconds','x_axis_end_seconds'}
PARAMETER_LABELS = {
 'humidity_rh':'Default Relative Humidity [% RH]', 'sample_seconds':'CSV Time Step [s]',
 'active_mode':'Operating Mode - Function / Normal Operation', 'standby_mode':'Operating Mode - Inactive / Preconditioning',
 'ua_voltage_v':'Driving Voltage UA [V]', 'ub_voltage_v':'Parking Voltage UB [V]',
 'nominal_voltage_v':'Nominal Voltage UN [V]', 'minimum_voltage_v':'Minimum Voltage Umin [V]',
 'maximum_voltage_v':'Maximum Voltage Umax [V]', 'temperature_c':'Test Temperature [°C]',
 'minimum_temperature_c':'Minimum Temperature [°C]', 'maximum_temperature_c':'Maximum Temperature [°C]',
 'room_temperature_c':'Room / Initial Temperature [°C]', 'cycles':'Repetitions', 'number_of_cycles':'Number of Cycles',
 'temperature_change_rate':'Temperature Change Rate [°C/min]', 'precondition_minutes':'Preconditioning per Temperature [min]',
 'activation_minutes':'Activation per Test Point [min]', 'ramps':'Include Optional Final Recovery / Ramps',
 'active_hours':'Normal Operation Duration [h]', 'standby_hours':'Stand-by Duration [h]',
 'cold_dwell_minutes':'Total Cold Dwell Time [min]', 'cold_active_minutes':'Final Cold Dwell in Normal Operation [min]',
 'hot_dwell_minutes':'Total Hot Dwell Time [min]', 'hot_standby_minutes':'Final Hot Dwell in Stand-by [min]',
 'gradient_step_c':'Temperature Increment [K]', 'gradient_standby_minutes':'Dwell in Stand-by [min]',
 'gradient_umax_minutes':'Normal Operation at Umax [min]', 'gradient_pause_minutes':'Stand-by Pause [min]',
 'gradient_umin_minutes':'Normal Operation at Umin [min]', 'total_hours':'Total Duration [h]',
 'inactive_hours':'Inactive Period [h]', 'functional_hours':'Functional / Final Period [h]',
 'hot_humidity_rh':'Hot Dwell RH [%]', 'rising_humidity_rh':'Temperature Rise RH [%]', 'cooling_humidity_rh':'Temperature Fall RH [%]',
 'climate_check_minutes':'Function Check Duration [min]', 'frost_cycles':'Initial Frost Cycles',
 'cold_check_duration_minutes':'Cold Function Check Duration [min]',
 'load_open_seconds':'Actuator Opening Time [s]', 'load_hold_seconds':'Actuator Hold Time [s]',
 'load_close_seconds':'Actuator Closing Time [s]', 'load_pause_seconds':'Actuator Pause Time [s]',
 'load_start_delay_seconds':'Actuator Start Delay [s]',
}

def parameter_label(key):
    return PARAMETER_LABELS.get(key, key.replace('_',' ').title())


def default_configuration():
    defaults = asdict(Parameters())
    global_config = {}
    for section, keys in GLOBAL_SECTION_KEYS.items():
        global_config[section] = {
            'visible': {key: defaults[key] for key in keys if key in GLOBAL_VISIBLE_KEYS},
            'unvisible': {key: defaults[key] for key in keys if key not in GLOBAL_VISIBLE_KEYS}}
    config = {'schema_version':4, 'source_document':SOURCE_DOCUMENT,
              'global': global_config, 'tests':{}}
    for tid in GENERATORS:
        values = asdict(default_parameters(tid))
        keys = list(dict.fromkeys(TEST_KEYS[tid].split()+COMMON_KEYS))
        config['tests'][tid] = {'name':TEST_NAMES[tid],
            'visible':{key:values[key] for key in keys if key not in HIDDEN_KEYS},
            'unvisible':{key:values[key] for key in keys if key in HIDDEN_KEYS}}
    return config


def migrate_schema3(config):
    """Convert conflict-free schema 3 data to schema 4."""
    import copy
    if config.get('schema_version') != 3:
        return config
    conflicts = {tid: entry.get('chart_overrides', {}) for tid, entry in config.get('tests', {}).items()
                 if entry.get('chart_overrides')}
    if conflicts:
        details = '; '.join(f'{tid}: {", ".join(sorted(values))}' for tid, values in conflicts.items())
        raise ValueError('Schema-3 migration conflict in chart_overrides. Resolve explicitly before migration: '+details)
    migrated = copy.deepcopy(config)
    defaults = default_configuration()['global']
    migrated['schema_version'] = 4
    for section in ('actuator', 'chart'):
        default_values = {**defaults[section]['visible'], **defaults[section]['unvisible']}
        for key, value in default_values.items():
            migrated['global'][section].setdefault(key, value)
    migrated['global']['voltage'] = {**defaults['voltage']['visible'], **defaults['voltage']['unvisible']}
    for entry in migrated.get('tests', {}).values():
        entry.pop('chart_overrides', None)
    return migrated


def normalize_schema4(config):
    """Upgrade flat V04 globals while preserving established visibility exactly."""
    import copy
    normalized = copy.deepcopy(config)
    source_global = normalized.get('global', {})
    global_config = copy.deepcopy(source_global)
    defaults = asdict(Parameters())
    flat_globals = {}
    for section, keys in GLOBAL_SECTION_KEYS.items():
        source = source_global.get(section, {})
        established_visibility = (isinstance(source, dict)
                                  and isinstance(source.get('visible'), dict)
                                  and isinstance(source.get('unvisible'), dict))
        if established_visibility:
            values = {**source['unvisible'], **source['visible']}
        else:
            values = dict(source) if isinstance(source, dict) else {}
            for key in keys:
                values.setdefault(key, defaults[key])
            # GLOBAL_VISIBLE_KEYS defines only the initial/migrated layout. It
            # must never reclassify an existing schema-4 configuration.
            global_config[section] = {
                'visible': {key: values[key] for key in keys if key in GLOBAL_VISIBLE_KEYS},
                'unvisible': {key: values[key] for key in keys if key not in GLOBAL_VISIBLE_KEYS}}
        flat_globals.update(values)
    normalized['global'] = global_config
    for entry in normalized.get('tests', {}).values():
        overrides = dict(entry.get('overrides', {}))
        for section in ('visible', 'unvisible'):
            for key in list(entry.get(section, {})):
                if key in GLOBAL_KEYS:
                    value = entry[section].pop(key)
                    if value != flat_globals[key]:
                        overrides[key] = value
        if overrides:
            entry['overrides'] = overrides
        else:
            entry.pop('overrides', None)
    return normalized


def flattened_global(config):
    return {key: value for section in config['global'].values()
            for values in (section['unvisible'], section['visible']) for key, value in values.items()}


def visible_global_keys(config):
    return [key for section in config['global'].values() for key in section['visible']]


def parameters_from_configuration(config, test_id):
    if config.get('schema_version') != 4 or not isinstance(config.get('tests'),dict):
        raise ValueError('Expected a schema_version 4 overall configuration with global and tests sections.')
    global_config = config.get('global')
    if not isinstance(global_config, dict) or set(global_config) != set(GLOBAL_SECTION_KEYS):
        raise ValueError('Schema 4 requires global.csv, global.actuator, global.chart and global.voltage objects.')
    for section, expected_keys in GLOBAL_SECTION_KEYS.items():
        section_data = global_config.get(section)
        if not isinstance(section_data, dict) or not isinstance(section_data.get('visible'), dict) or not isinstance(section_data.get('unvisible'), dict):
            raise ValueError(f'global.{section} requires visible and unvisible objects.')
        overlap = set(section_data['visible']) & set(section_data['unvisible'])
        if overlap:
            raise ValueError(f'global.{section}: parameters occur in both visibility sections: {sorted(overlap)}')
        actual = set(section_data['visible']) | set(section_data['unvisible'])
        expected = set(expected_keys)
        if actual != expected:
            raise ValueError(f'global.{section} keys differ; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}')
    if test_id not in config['tests']:
        raise ValueError('Configuration is missing '+test_id)
    entry = config['tests'][test_id]
    if not isinstance(entry,dict) or not isinstance(entry.get('visible'),dict) or not isinstance(entry.get('unvisible'),dict):
        raise ValueError(test_id+': visible and unvisible must be JSON objects.')
    overlap = set(entry['visible']) & set(entry['unvisible'])
    if overlap:
        raise ValueError(test_id+': parameter appears in both sections: '+', '.join(sorted(overlap)))
    misplaced = (set(entry['visible']) | set(entry['unvisible'])) & GLOBAL_KEYS
    if misplaced:
        raise ValueError(test_id+': global parameters are not allowed in test sections: '+', '.join(sorted(misplaced)))
    if 'chart_overrides' in entry:
        raise ValueError(test_id+': chart_overrides are not allowed in schema 4.')
    overrides = entry.get('overrides', {})
    if not isinstance(overrides, dict) or any(key not in GLOBAL_KEYS for key in overrides):
        raise ValueError(test_id+': overrides may contain global parameters only.')
    values = asdict(default_parameters(test_id))
    combined = {**flattened_global(config), **overrides, **entry['unvisible'], **entry['visible']}
    for key, value in combined.items():
        if key not in values or key == 'test_id':
            raise ValueError(test_id+': unknown or removed parameter '+key)
        default = values[key]
        if value is None and key in {'humidity_rh','x_axis_step_seconds','x_axis_end_seconds'}:
            values[key] = None
            continue
        if isinstance(default,bool):
            valid = isinstance(value,bool)
        elif isinstance(default,int):
            valid = isinstance(value,int) and not isinstance(value,bool)
        elif isinstance(default,str):
            valid = isinstance(value,str)
        else:
            valid = isinstance(value,(float,int)) and not isinstance(value,bool)
        if not valid:
            raise ValueError(test_id+': invalid type for '+key)
        values[key] = value
    p = Parameters(**values)
    p.validate()
    return p


def load_configuration(path=DEFAULT_CONFIG_PATH):
    path = Path(path)
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    rewrite = False
    if config.get('schema_version') == 3:
        backup = path.with_name(path.stem+'.schema3.backup'+path.suffix)
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        config = migrate_schema3(config)
        rewrite = True
    if config.get('schema_version') == 4:
        normalized = normalize_schema4(config)
        rewrite = rewrite or normalized != config
        config = normalized
    if rewrite:
        temporary = path.with_name(path.name+'.schema4.tmp')
        temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        temporary.replace(path)
    for tid in GENERATORS:
        parameters_from_configuration(config,tid)
    return config


def save_current_test(path, parameters, entry_template=None, override_keys=None):
    """Read current disk contents; replace only the selected test's values.

    Other test sections, visibility membership, and unknown metadata are retained.
    """
    import copy, os, tempfile
    path = Path(path)
    config = load_configuration(path) if path.exists() else default_configuration()
    tid = parameters.test_id
    parameters.validate()
    entry = copy.deepcopy(entry_template if entry_template is not None else config['tests'][tid])
    values = asdict(parameters)
    for section in ('visible','unvisible'):
        for key in entry[section]:
            entry[section][key] = values[key]
    overrides = dict(entry.get('overrides', {}))
    override_keys = set() if override_keys is None else set(override_keys)
    for key in visible_global_keys(config):
        if key not in override_keys:
            overrides.pop(key, None)
        else:
            overrides[key] = values[key]
    if overrides:
        entry['overrides'] = overrides
    else:
        entry.pop('overrides', None)
    config['tests'][tid] = entry
    for key in GENERATORS:
        parameters_from_configuration(config,key)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(config,stream,indent=2,ensure_ascii=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
    return config


def save_global_settings(path, parameters):
    """Save only GUI-visible global values; tests and visibility stay untouched."""
    import os, tempfile
    path = Path(path)
    config = load_configuration(path) if path.exists() else default_configuration()
    values = asdict(parameters)
    for section in config['global'].values():
        for key in section['visible']:
            section['visible'][key] = values[key]
    for tid in GENERATORS:
        parameters_from_configuration(config, tid)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(config, stream, indent=2, ensure_ascii=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
    return config


def maximize_window(root):
    """Native maximization on Windows; window-manager or work-area fallback elsewhere."""
    try:
        root.state('zoomed')
        return
    except Exception:
        pass
    try:
        root.attributes('-zoomed',True)
        return
    except Exception:
        pass
    root.geometry(f'{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0')


def build_load_schedule(phases, starts):
    """Precompute the mode intervals needed by load_percent_at()."""
    active_starts = [None] * len(phases)
    off_starts = [None] * len(phases)
    active_start = None
    off_start = None
    for i, phase in enumerate(phases):
        previous = phases[i - 1].mode if i else None
        if phase.mode == '3.2' and previous != '3.2':
            active_start = starts[i]
            off_start = None
        elif phase.mode != '3.2' and previous == '3.2':
            off_start = starts[i]
        active_starts[i] = active_start
        off_starts[i] = off_start
    return active_starts, off_starts


def active_load_percent(elapsed_s, p):
    """Actuator position inside one uninterrupted Mode-3.2 interval."""
    if elapsed_s < p.load_start_delay_seconds:
        return 0.0
    duration = (p.load_open_seconds + p.load_hold_seconds
                + p.load_close_seconds + p.load_pause_seconds)
    phase_time = (elapsed_s-p.load_start_delay_seconds) % duration
    if p.load_open_seconds > 0 and phase_time < p.load_open_seconds:
        return p.load_max_percent * phase_time / p.load_open_seconds
    phase_time -= p.load_open_seconds
    if phase_time < p.load_hold_seconds:
        return p.load_max_percent
    phase_time -= p.load_hold_seconds
    if p.load_close_seconds > 0 and phase_time < p.load_close_seconds:
        return p.load_max_percent * (1.0-phase_time/p.load_close_seconds)
    return 0.0


def load_before_active_exit(active_start, active_end, p):
    """Position immediately before a right-continuous Mode-3.2 exit."""
    elapsed = max(0.0, active_end-active_start)
    if elapsed == 0:
        return 0.0
    return active_load_percent(math.nextafter(elapsed, -math.inf), p)


def actuator_event_times(phases, starts, duration_s, p):
    """Exact mode and actuator support points, including zero-duration jumps."""
    events = set(starts)
    events.add(duration_s)

    def add(time_s, discontinuity=False, lower=0.0):
        if lower <= time_s <= duration_s:
            events.add(time_s)
            if discontinuity and time_s > lower:
                events.add(math.nextafter(time_s, -math.inf))
            if len(events) > 15000000:
                raise ValueError('Too many actuator events (maximum 150000000). Increase actuator cycle times.')

    cycle_duration = (p.load_open_seconds + p.load_hold_seconds
                      + p.load_close_seconds + p.load_pause_seconds)
    i = 0
    while i < len(phases):
        if phases[i].mode != '3.2' or (i and phases[i-1].mode == '3.2'):
            i += 1
            continue
        active_start = starts[i]
        j = i + 1
        while j < len(phases) and phases[j].mode == '3.2':
            j += 1
        active_end = starts[j] if j < len(starts) else duration_s
        repeated_start = active_start + p.load_start_delay_seconds
        add(active_start)
        if repeated_start <= active_end:
            opening_jump = (p.load_open_seconds == 0 and p.load_max_percent != 0
                            and p.load_hold_seconds+p.load_close_seconds > 0)
            closing_jump = (p.load_close_seconds == 0 and p.load_max_percent != 0
                            and p.load_open_seconds+p.load_hold_seconds > 0)
            add(repeated_start, opening_jump, active_start)

            def add_while_active(time_s, discontinuity=False):
                if time_s <= active_end:
                    add(time_s, discontinuity, active_start)

            base = repeated_start
            while base <= active_end:
                opening_end = base + p.load_open_seconds
                hold_end = opening_end + p.load_hold_seconds
                closing_end = hold_end + p.load_close_seconds
                cycle_end = base + cycle_duration
                add_while_active(base, opening_jump)
                add_while_active(opening_end)
                add_while_active(hold_end, closing_jump)
                add_while_active(closing_end)
                add_while_active(cycle_end)
                base = cycle_end
        exit_load = load_before_active_exit(active_start, active_end, p)
        add(active_end, p.load_close_seconds == 0 and exit_load != 0, active_start)
        if (active_end < duration_s and p.load_close_seconds > 0
                and p.load_max_percent != 0 and exit_load != 0):
            close_duration = p.load_close_seconds*abs(exit_load/p.load_max_percent)
            add(min(duration_s, active_end+close_duration))
        i = j
    return sorted(events)


class Timeline:
    """Exact cursor values independent of CSV sampling; new mode at boundaries."""

    def __init__(self, phases: list[Phase], parameters: Parameters | None = None):
        if not phases:
            raise ValueError('The profile contains no phases.')
        self.phases = phases
        self.parameters = parameters
        self.starts = []
        self.duration_s = 0.0
        for phase in phases:
            if phase.duration_s <= 0:
                raise ValueError('Phase duration must be positive.')
            self.starts.append(self.duration_s)
            self.duration_s += phase.duration_s
        self.load_schedule = build_load_schedule(self.phases, self.starts)
        self.actuator_events = (actuator_event_times(self.phases, self.starts, self.duration_s, parameters)
                                if parameters else list(self.starts)+[self.duration_s])

    def at(self, time_s: float) -> Sample:
        if not math.isfinite(time_s):
            raise ValueError('Tracker time must be finite.')
        t = min(self.duration_s, max(0.0, time_s))
        idx = min(bisect.bisect_right(self.starts, t) - 1, len(self.phases) - 1)
        ph = self.phases[idx]
        fraction = (t - self.starts[idx]) / ph.duration_s
        temperature = ph.temperature_start_c + fraction * (ph.temperature_end_c - ph.temperature_start_c)
        at_threshold = (ph.humidity_at_threshold is not None
                        and temperature == max(ph.temperature_start_c, ph.temperature_end_c))
        rh = ph.humidity_at_threshold if at_threshold else (None if ph.undefined_humidity_label and temperature < max(ph.temperature_start_c, ph.temperature_end_c) else ph.humidity_rh)
        load = load_percent_at(self.phases, self.starts, t, self.parameters, self.load_schedule) if self.parameters else 0.0
        return Sample(t, ph.cycle, ph.name, temperature, rh, ph.mode, ph.voltage_v,
                      ph.undefined_humidity_label if rh is None else '', load)


def snap_tracker_time(time_s, step_s, start_s, end_s):
    """Nearest profile-zero grid point within the visible range, plus endpoints.

    Halfway ties go to the later time. Zero step disables snapping.
    Endpoints remain selectable even when they do not lie on the grid.
    """
    if not all(math.isfinite(v) for v in (time_s, step_s, start_s, end_s)):
        raise ValueError('Tracker values must be finite.')
    if step_s < 0 or end_s < start_s:
        raise ValueError('Invalid Tracker Step or time range.')
    t = min(end_s, max(start_s, time_s))
    if step_s == 0:
        return t
    index = math.floor(t / step_s)
    candidates = [start_s, end_s]
    candidates.extend(v for v in (index*step_s, (index+1)*step_s) if start_s <= v <= end_s)
    return min(candidates, key=lambda v: (abs(v-t), -v))


def axis_ticks(end_s, step_s=None):
    if not math.isfinite(end_s) or end_s <= 0:
        raise ValueError('X End must be positive and finite.')
    step = step_s if step_s is not None else end_s/5
    if not math.isfinite(step) or step <= 0:
        raise ValueError('X Step must be positive and finite.')
    count = end_s/step
    if not math.isfinite(count):
        raise ValueError('X Step is too small.')
    stride = max(1, math.ceil(count/40))
    ticks = [i*step*stride for i in range(math.floor(count/stride)+1)]
    return ticks, stride


@dataclass
class MeasurementMarkers:
    start_s: float | None = None
    end_s: float | None = None

    def set_start(self, time_s):
        self.start_s, self.end_s = time_s, None

    def set_end(self, time_s):
        if self.start_s is None:
            return False
        self.end_s = time_s
        return True

    def clear(self):
        self.start_s = self.end_s = None

    @property
    def distance_minutes(self):
        if self.start_s is None or self.end_s is None:
            return None
        return abs(self.end_s-self.start_s)/60


MAX_REGULAR_SAMPLES = 22500000
MAX_TOTAL_SAMPLES = 25000000


def generate_phases(p: Parameters, test_id=None) -> tuple[list[Phase], Timeline]:
    """Phases and timeline only (no Sample objects). Cheap enough for GUI updates."""
    if test_id is not None:
        # Preserve support for the original explicit generate(p, test_id) API.
        p = replace(p, test_id=test_id)
    test_id = p.test_id
    p.validate()
    phases = GENERATORS[test_id](p)
    normalized = []
    for phase in phases:
        voltage = phase.voltage_v
        if voltage is None:
            if test_id == 'ENV_015' and 'Umax' in phase.name:
                voltage = p.maximum_voltage_v
            elif test_id == 'ENV_015' and 'Umin' in phase.name:
                voltage = p.minimum_voltage_v
            elif phase.mode.startswith('3.'):
                voltage = p.ua_voltage_v
            elif phase.mode.startswith('2.'):
                voltage = p.ub_voltage_v
            else:
                voltage = p.off_voltage_v
        normalized.append(replace(phase, voltage_v=voltage))
    phases = normalized
    return phases, Timeline(phases, p)


def regular_sample_count(timeline: Timeline, p: Parameters) -> int:
    n = math.ceil(timeline.duration_s / p.sample_seconds)
    if n > MAX_REGULAR_SAMPLES:
        raise ValueError('Too many data points (maximum 22500000). Increase the time step.')
    return n


def count_sample_points(timeline: Timeline, p: Parameters) -> int:
    """Number of distinct sample times, without creating the times or Sample objects.

    Equals len({i*sample_seconds for i in range(n)} | set(actuator_events)):
    n regular points plus every event time that is not itself a regular point.
    """
    n = regular_sample_count(timeline, p)
    step = p.sample_seconds
    extra = 0
    for event in timeline.actuator_events:
        i = round(event / step)
        if not (0 <= i < n and i * step == event):
            extra += 1
    total = n + extra
    if total > MAX_TOTAL_SAMPLES:
        raise ValueError('Too many data points (maximum 25000000). Increase CSV Time Step or actuator cycle times.')
    return total


def iter_sample_times(timeline: Timeline, p: Parameters):
    """Sorted, de-duplicated sample times (regular grid + exact events), streamed."""
    n = regular_sample_count(timeline, p)
    step = p.sample_seconds
    previous = None
    for t in heapq.merge((i * step for i in range(n)), timeline.actuator_events):
        if t != previous:
            yield t
            previous = t


def iter_samples(timeline: Timeline, p: Parameters):
    """Stream Sample objects (CSV export, CLI). Regular samples plus exact
    mode/actuator events; nextafter support points keep both sides of an
    instantaneous zero-second transition."""
    count_sample_points(timeline, p)  # same limit checks as before, before any work
    for t in iter_sample_times(timeline, p):
        yield timeline.at(t)


def generate(p: Parameters, test_id=None) -> tuple[list[Phase], list[Sample]]:
    """Compatibility wrapper: phases plus the complete list of samples."""
    phases, timeline = generate_phases(p, test_id)
    samples = list(iter_samples(timeline, timeline.parameters))
    return phases, samples


def load_percent_at(phases, starts, time_s, p, schedule=None):
    """Return the trapezoidal load using a precomputed mode-change schedule."""
    idx = min(bisect.bisect_right(starts, time_s) - 1, len(phases) - 1)
    mode = phases[idx].mode
    close_s = p.load_close_seconds
    schedule = schedule or build_load_schedule(phases, starts)
    active_start = schedule[0][idx]
    if active_start is None:
        return 0.0

    if mode == '3.2':
        return active_load_percent(max(0.0, time_s-active_start), p)

    switched_off = schedule[1][idx]
    if switched_off is None:
        return 0.0
    value_at_switch = load_before_active_exit(active_start, switched_off, p)
    if close_s == 0:
        return 0.0
    closing_speed = abs(p.load_max_percent)/close_s
    return max(0.0, value_at_switch-closing_speed*(time_s-switched_off))


def actuator_motion_counts(samples, load_max_percent):
    """Count rising and falling actuator movements over the complete profile.

    Accepts a list or any iterable of samples (e.g. iter_samples) and reads it once.
    """
    tolerance = max(1.0, abs(load_max_percent))*1e-12
    openings = closings = direction = 0
    previous = None
    for sample in samples:
        current = sample.load_percent
        if previous is None:
            previous = current
            continue
        difference = current-previous
        new_direction = 1 if difference > tolerance else (-1 if difference < -tolerance else 0)
        if new_direction and new_direction != direction:
            if new_direction > 0:
                openings += 1
            else:
                closings += 1
            direction = new_direction
        previous = current
    return openings, closings


PERIODIC_WARMUP_CYCLES = 2


def periodic_skip_plan(timeline, p):
    """Find runs of identical actuator cycles inside Mode-3.2 intervals.

    Returns {index_before_probe_cycle: (index_after_probe_cycle, jump_to_index, skipped_cycles)}
    with indexes into timeline.actuator_events. Cycles after the warm-up cycles and
    before the last warm-up cycles are only skipped after the counting loop has verified
    that two consecutive cycles change the state identically (see below).
    """
    cycle = (p.load_open_seconds + p.load_hold_seconds
             + p.load_close_seconds + p.load_pause_seconds)
    if cycle <= 0 or not math.isfinite(cycle):
        return {}
    phases, starts, events = timeline.phases, timeline.starts, timeline.actuator_events
    duration = timeline.duration_s
    plan = {}
    k = PERIODIC_WARMUP_CYCLES
    i = 0
    while i < len(phases):
        if phases[i].mode != '3.2' or (i and phases[i-1].mode == '3.2'):
            i += 1
            continue
        j = i + 1
        while j < len(phases) and phases[j].mode == '3.2':
            j += 1
        active_end = starts[j] if j < len(starts) else duration
        base = starts[i] + p.load_start_delay_seconds
        bases = []
        while base <= active_end:     # same accumulation as actuator_event_times()
            bases.append(base)
            base = base + cycle
            if len(bases) > 20000000:
                return {}
        count = len(bases)
        if count >= 2*k + 4:
            # probe = cycle k+1; skipped cycles = k+2 ... count-k-1
            positions = [bisect.bisect_left(events, bases[n]) for n in (k+1, k+2, count-k)]
            if all(pos < len(events) and events[pos] == bases[n]
                   for pos, n in zip(positions, (k+1, k+2, count-k))):
                skipped = count - 2*k - 2
                plan[positions[0]] = (positions[1], positions[2], skipped)
        i = j
    return plan


def actuator_motion_counts_from_timeline(timeline, p, skip_periodic=True):
    """Same result as actuator_motion_counts(samples, ...), evaluated only at the exact
    event times (the load is piecewise linear between events, so the sequence of
    rising/falling directions is identical).

    With skip_periodic, long runs of identical actuator cycles are counted by
    multiplication: two consecutive probe cycles are evaluated exactly; only if they
    leave the counting state unchanged (same direction and load level, same number of
    openings/closings) are the cycles in between skipped. Otherwise nothing is skipped.
    """
    tolerance = max(1.0, abs(p.load_max_percent))*1e-12
    phases, starts, schedule = timeline.phases, timeline.starts, timeline.load_schedule
    events, duration = timeline.actuator_events, timeline.duration_s
    plan = periodic_skip_plan(timeline, p) if skip_periodic else {}
    probe_end = {value[0]: (key, value) for key, value in plan.items()}
    openings = closings = direction = 0
    previous = None
    snapshots = {}
    n = len(events)
    i = 0
    while i < n:
        if i in plan:
            snapshots[i] = (openings, closings, direction, previous)
        if i in probe_end:
            start_index, (_, jump_to, skipped) = probe_end[i]
            before = snapshots.pop(start_index, None)
            if before is not None:
                d_open, d_close = openings-before[0], closings-before[1]
                same_state = (direction == before[2] and previous is not None and before[3] is not None
                              and abs(previous-before[3]) <= tolerance)
                if same_state:
                    openings += skipped*d_open
                    closings += skipped*d_close
                    i = jump_to
                    continue
        t = events[i]
        current = load_percent_at(phases, starts, min(duration, max(0.0, t)), p, schedule)
        if previous is not None:
            difference = current-previous
            new_direction = 1 if difference > tolerance else (-1 if difference < -tolerance else 0)
            if new_direction and new_direction != direction:
                if new_direction > 0:
                    openings += 1
                else:
                    closings += 1
                direction = new_direction
        previous = current
        i += 1
    return openings, closings


def event_counting_is_exact(p):
    """True where evaluating the load at the exact event times reproduces the
    sample-based count: non-negative maximum and actuator times that are multiples
    of 1/64 s (exactly representable, so cycle boundaries carry no rounding noise).
    Outside this domain the count of the sample-based method itself depends on
    floating-point noise and on the CSV time step, so it is kept as the reference."""
    times = (p.load_start_delay_seconds, p.load_open_seconds, p.load_hold_seconds,
             p.load_close_seconds, p.load_pause_seconds)
    return p.load_max_percent >= 0 and all(t*64 == round(t*64) for t in times)


def actuator_counts(timeline, p):
    """(openings, closings) for the GUI. Fast event-based count where it is exact,
    otherwise the original sample-based count, streamed without storing samples."""
    if event_counting_is_exact(p):
        return actuator_motion_counts_from_timeline(timeline, p)
    return actuator_motion_counts(iter_samples(timeline, p), p.load_max_percent)


def export_csv(path, samples):
    """Right-continuous modes: at an event time, the NEW mode applies.
    Temperature: linear interpolation; humidity/mode: hold previous value.
    Final row is the endpoint, not an additional time interval.
    ENV_002 undefined humidity is n.def.; other unspecified humidity is empty.
    """
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream, delimiter=';')
        voltage_enabled = True
        writer.writerow(['time_s', 'time_min', 'time_h', 'temperature_C',
                         'humidity_percent_RH', 'operation_mode', 'cycle', 'phase', 'actuator_position_percent']+(['voltage_V'] if voltage_enabled else []))
        for s in samples:
            writer.writerow([format(s.time_s, '.17g'),
                             f'{s.time_s / 60:.9f}', f'{s.time_s / 3600:.9f}',
                             f'{s.temperature_c:.6f}',
                             ('n.def' if s.undefined_humidity_label else '') if s.humidity_rh is None else f'{s.humidity_rh:.6f}',
                             s.operation_mode, s.cycle, s.phase, f'{s.load_percent:.6f}']+(
                             ['' if s.voltage_v is None else f'{s.voltage_v:.6f}'] if voltage_enabled else []))


def export_cycle1_csv(path, timeline, parameters, step_epsilon=1e-6):
    """Export the first cycle as an Excel-ready XY breakpoint table.

    The file contains only polyline vertices, written as adjacent x/y column
    pairs for temperature, humidity, operation mode, voltage and actuator
    position. Duplicate x values encode vertical step edges, so an Excel XY
    scatter/line chart reproduces the generator curve without metadata columns.

    `step_epsilon` is retained for API compatibility and is no longer needed.
    """
    return _export_cycle1_xy_table(path, timeline, parameters)


def _same_number(a, b):
    if a is None or b is None:
        return a is b
    try:
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return a == b


def _same_value(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return _same_number(a, b)


def _same_time(a, b):
    return _same_number(a, b)


def _humidity_note(value, label):
    if value is not None:
        return ''
    return label or 'undefined'


def _phase_equivalent(a, b):
    return (
        a.name == b.name
        and _same_number(a.duration_s, b.duration_s)
        and _same_number(a.temperature_start_c, b.temperature_start_c)
        and _same_number(a.temperature_end_c, b.temperature_end_c)
        and _same_number(a.humidity_rh, b.humidity_rh)
        and a.mode == b.mode
        and _same_number(a.voltage_v, b.voltage_v)
        and a.undefined_humidity_label == b.undefined_humidity_label
        and _same_number(a.humidity_at_threshold, b.humidity_at_threshold)
    )


def _select_cycle_indices(phases, timeline, cycle):
    """(indices, first absolute time, cycle override, repeat information)."""
    available = sorted({phase.cycle for phase in phases})
    if cycle is None:
        return list(range(len(phases))), 0.0, None, None
    if cycle == 'first_plus_repeat':
        if 1 not in available:
            raise ValueError(f'Cycle 1 not found. Available cycles: {available}.')
        by_cycle = {}
        for phase in phases:
            by_cycle.setdefault(phase.cycle, []).append(phase)
        base = by_cycle[1]
        for number in available:
            sequence = by_cycle[number]
            if (len(sequence) != len(base)
                    or any(not _phase_equivalent(a, b) for a, b in zip(base, sequence))):
                raise ValueError(
                    'first_plus_repeat requires identical phase sequences for all cycles; '
                    f'cycle {number} differs from cycle 1.')
        indices = [i for i, phase in enumerate(phases) if phase.cycle == 1]
        duration_s = sum(phase.duration_s for phase in base)
        repeat = {
            'cycles_total': len(available),
            'remaining': max(0, len(available) - 1),
            'cycle_duration_s': duration_s,
        }
        return indices, timeline.starts[indices[0]], 1, repeat
    if isinstance(cycle, bool) or not isinstance(cycle, int):
        raise ValueError("cycle must be None, an integer, or 'first_plus_repeat'.")
    indices = [i for i, phase in enumerate(phases) if phase.cycle == cycle]
    if not indices:
        raise ValueError(f'Cycle {cycle} not found. Available cycles: {available}.')
    return indices, timeline.starts[indices[0]], cycle, None


def _temperature_breakpoints_for_indices(phases, timeline, indices, offset, cycle_override):
    raw = []
    for index in indices:
        phase = phases[index]
        start_s = timeline.starts[index]
        end_s = start_s + phase.duration_s
        raw.append((start_s, phase.temperature_start_c, phase.cycle))
        raw.append((end_s, phase.temperature_end_c, phase.cycle))

    cleaned = []
    for time_s, value, number in raw:
        if (cleaned and _same_time(time_s, cleaned[-1][0])
                and _same_value(value, cleaned[-1][1])):
            cleaned[-1] = (time_s, value, number)
        else:
            cleaned.append((time_s, value, number))

    kept = []
    for i, (time_s, value, number) in enumerate(cleaned):
        keep = i == 0 or i == len(cleaned) - 1
        if not keep:
            before, after = cleaned[i - 1], cleaned[i + 1]
            if _same_time(time_s, before[0]) or _same_time(time_s, after[0]):
                keep = True
            else:
                slope_before = (value - before[1]) / (time_s - before[0])
                slope_after = (after[1] - value) / (after[0] - time_s)
                keep = abs(slope_before - slope_after) > 1e-12
        if keep:
            kept.append((time_s, value, number))

    points = []
    for i, (time_s, value, number) in enumerate(kept):
        kind, slope = '', None
        if i + 1 < len(kept):
            next_s, next_value, _ = kept[i + 1]
            if _same_time(time_s, next_s):
                kind = 'jump'
            elif _same_value(value, next_value):
                kind, slope = 'hold', 0.0
            else:
                kind = 'ramp'
                slope = (next_value - value) / (next_s - time_s) * 60.0
        points.append({
            'time_s': time_s - offset,
            'value': value,
            'cycle': cycle_override if cycle_override is not None else number,
            'kind': kind,
            'slope_per_min': slope,
        })
    return points


def temperature_breakpoints(phases, timeline, p=None, *, cycle=None, relative=True):
    """Exact piecewise-linear temperature points for the selected phases.

    Points are returned in seconds (relative to the selected cycle start when
    requested). A discontinuity is represented by two points at the same time.
    """
    indices, cycle_start_s, cycle_override, _ = _select_cycle_indices(phases, timeline, cycle)
    offset = cycle_start_s if relative and cycle is not None else 0.0
    return _temperature_breakpoints_for_indices(phases, timeline, indices, offset,
                                                cycle_override)


def _simple_step_breakpoints(phases, timeline, indices, offset, cycle_override,
                             key_function, value_function, note_function):
    entries = []
    previous_key = object()
    for index in indices:
        phase = phases[index]
        key = key_function(phase)
        if entries and _same_value(key, previous_key):
            continue
        entries.append({
            'time_s': timeline.starts[index] - offset,
            'value': value_function(phase),
            'cycle': cycle_override if cycle_override is not None else phase.cycle,
            'kind': 'step',
            'note': note_function(phase),
        })
        previous_key = key
    return entries


def _humidity_step_breakpoints(phases, timeline, indices, offset, cycle_override):
    candidates = []

    def add(time_s, value, note, number):
        candidates.append({'time_s': time_s, 'value': value, 'note': note, 'cycle': number})

    for index in indices:
        phase = phases[index]
        start_s = timeline.starts[index]
        end_s = start_s + phase.duration_s
        middle = (start_s + end_s) / 2.0
        base = timeline.at(middle)
        base_value = base.humidity_rh
        base_note = _humidity_note(base_value, base.undefined_humidity_label)

        start = timeline.at(start_s)
        start_value = start.humidity_rh
        start_note = _humidity_note(start_value, start.undefined_humidity_label)
        maximum = max(phase.temperature_start_c, phase.temperature_end_c)
        constant = _same_value(phase.temperature_start_c, phase.temperature_end_c)
        if phase.humidity_at_threshold is not None and constant:
            base_note = 'at_threshold'
            start_note = 'at_threshold'
        threshold_at_start = (
            phase.humidity_at_threshold is not None
            and not constant
            and _same_value(phase.temperature_start_c, maximum)
        )
        if threshold_at_start:
            start_value = phase.humidity_at_threshold
            start_note = 'at_threshold'

        if not (_same_value(start_value, base_value) and start_note == base_note):
            add(start_s, start_value, start_note, phase.cycle)
            add(start_s, base_value, base_note, phase.cycle)
        else:
            add(start_s, base_value, base_note, phase.cycle)

        threshold_at_end = (
            phase.humidity_at_threshold is not None
            and not constant
            and _same_value(phase.temperature_end_c, maximum)
        )
        if threshold_at_end:
            add(end_s, phase.humidity_at_threshold, 'at_threshold', phase.cycle)
        elif (phase.humidity_at_threshold is None and phase.undefined_humidity_label
              and not constant and _same_value(phase.temperature_end_c, maximum)):
            end_value = phase.humidity_rh
            end_note = _humidity_note(end_value, phase.undefined_humidity_label)
            if not (_same_value(end_value, base_value) and end_note == base_note):
                add(end_s, end_value, end_note, phase.cycle)

    candidates.sort(key=lambda item: item['time_s'])
    merged = []
    for item in candidates:
        if (merged and _same_value(item['value'], merged[-1]['value'])
                and item['note'] == merged[-1]['note']):
            continue
        merged.append(item)
    return [{
        'time_s': item['time_s'] - offset,
        'value': item['value'],
        'cycle': cycle_override if cycle_override is not None else item['cycle'],
        'kind': 'step',
        'note': item['note'],
    } for item in merged]


def _normalize_step_curve(curve):
    curve_key = str(curve).strip().lower()
    if curve_key in {'humidity', 'humidity_rh', 'feuchte', 'feuchtigkeit', 'rh'}:
        return 'humidity'
    if curve_key in {'operation', 'operation_mode', 'operating_mode', 'mode',
                     'betriebsmodus'}:
        return 'operation'
    if curve_key in {'voltage', 'voltage_v', 'spannung', 'u'}:
        return 'voltage'
    raise ValueError(f'Unknown step curve: {curve!r}.')


def _step_breakpoints_for_indices(phases, timeline, curve_key, indices, offset,
                                  cycle_override):
    if curve_key == 'humidity':
        return _humidity_step_breakpoints(phases, timeline, indices, offset, cycle_override)
    if curve_key == 'operation':
        return _simple_step_breakpoints(
            phases, timeline, indices, offset, cycle_override,
            key_function=lambda phase: phase.mode,
            value_function=lambda phase: 1 if phase.mode == '3.2' else 0,
            note_function=lambda phase: f'modus={phase.mode}',
        )
    return _simple_step_breakpoints(
        phases, timeline, indices, offset, cycle_override,
        key_function=lambda phase: phase.voltage_v,
        value_function=lambda phase: phase.voltage_v,
        note_function=lambda phase: '',
    )


def step_breakpoints(phases, timeline, curve, p=None, *, cycle=None, relative=True):
    """Step points for humidity, operation mode or voltage.

    Values apply from their time until the next point. Operation mode is
    exported as derived 0/1 with the raw mode in the note.
    """
    curve_key = _normalize_step_curve(curve)
    indices, cycle_start_s, cycle_override, _ = _select_cycle_indices(phases, timeline, cycle)
    offset = cycle_start_s if relative and cycle is not None else 0.0
    return _step_breakpoints_for_indices(phases, timeline, curve_key, indices,
                                         offset, cycle_override)


def _actuator_blocks_for_indices(phases, timeline, p, indices, offset,
                                 cycle_override):
    cycle_duration_s = (p.load_open_seconds + p.load_hold_seconds
                        + p.load_close_seconds + p.load_pause_seconds)
    blocks = []
    position = 0
    while position < len(indices):
        index = indices[position]
        if phases[index].mode != '3.2':
            position += 1
            continue
        end_position = position + 1
        while (end_position < len(indices)
               and phases[indices[end_position]].mode == '3.2'):
            end_position += 1
        start_s = timeline.starts[index]
        if end_position < len(indices):
            end_s = timeline.starts[indices[end_position]]
        else:
            last_index = indices[-1]
            end_s = timeline.starts[last_index] + phases[last_index].duration_s
        repeated_start_s = start_s + p.load_start_delay_seconds
        complete_cycles = 0
        if cycle_duration_s > 0 and end_s >= repeated_start_s:
            complete_cycles = int((end_s - repeated_start_s) // cycle_duration_s)
        blocks.append({
            'time_s': start_s - offset,
            'end_s': end_s - offset,
            'start_abs': start_s,
            'end_abs': end_s,
            'cycle': cycle_override if cycle_override is not None else phases[index].cycle,
            'start_delay_s': p.load_start_delay_seconds,
            'open_s': p.load_open_seconds,
            'hold_s': p.load_hold_seconds,
            'close_s': p.load_close_seconds,
            'pause_s': p.load_pause_seconds,
            'max_percent': p.load_max_percent,
            'cycle_duration_s': cycle_duration_s,
            'complete_cycles': complete_cycles,
        })
        position = end_position
    return blocks


def actuator_blocks(phases, timeline, p, *, cycle=None, relative=True):
    """Summaries of contiguous Mode-3.2 blocks, without individual events."""
    indices, cycle_start_s, cycle_override, _ = _select_cycle_indices(phases, timeline, cycle)
    offset = cycle_start_s if relative and cycle is not None else 0.0
    return _actuator_blocks_for_indices(phases, timeline, p, indices, offset,
                                        cycle_override)


def _breakpoint_number(value):
    if value is None or value == '':
        return ''
    if isinstance(value, str):
        return value
    text = f'{float(value):.6f}'.rstrip('0').rstrip('.')
    return '0' if text in {'-0', ''} else text


def _round_half_up(value):
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _round_breakpoint_times(points, whole_seconds):
    if not whole_seconds:
        return False
    changed = False
    previous = None
    for point in points:
        original = point['time_s']
        rounded = _round_half_up(original)
        if previous is not None and rounded <= previous:
            rounded = previous + 1
        if rounded != original:
            changed = True
        point['time_s'] = float(rounded)
        previous = rounded
    return changed


def _actuator_cycle_points(phases, timeline, p, blocks, offset, cycle_override):
    block = next((item for item in blocks if item['complete_cycles'] > 0), None)
    if block is None:
        return None
    start_s = block['start_abs'] + p.load_start_delay_seconds
    maximum = p.load_max_percent
    raw = [(start_s, 0.0)]

    def add(time_s, value):
        if raw and _same_time(time_s, raw[-1][0]) and _same_value(value, raw[-1][1]):
            return
        raw.append((time_s, value))

    if p.load_open_seconds > 0:
        add(start_s + p.load_open_seconds, maximum)
    else:
        add(start_s, maximum)
    hold_end = start_s + p.load_open_seconds + p.load_hold_seconds
    add(hold_end, maximum)
    if p.load_close_seconds > 0:
        add(hold_end + p.load_close_seconds, 0.0)
    else:
        add(hold_end, 0.0)
    add(start_s + block['cycle_duration_s'], 0.0)

    points = []
    for i, (time_s, value) in enumerate(raw):
        kind, slope = '', None
        if i + 1 < len(raw):
            next_s, next_value = raw[i + 1]
            if _same_time(time_s, next_s):
                kind = 'jump'
            elif _same_value(value, next_value):
                kind, slope = 'hold', 0.0
            else:
                kind = 'ramp'
                slope = (next_value - value) / (next_s - time_s) * 60.0
        points.append({
            'time_s': time_s - offset,
            'value': value,
            'cycle': cycle_override if cycle_override is not None else block['cycle'],
            'kind': kind,
            'slope_per_min': slope,
            'note': 'erster vollstaendiger Zyklus' if i == 0 else '',
        })
    return points


def _xy_number(value):
    """Compact numeric text for CSV; blank means an undefined point."""
    if value is None or value == '':
        return ''
    if isinstance(value, str):
        return value
    text = f'{float(value):.15g}'
    return '0' if text == '-0' else text


def _dedupe_xy(points):
    cleaned = []
    for x, y in points:
        if (cleaned and _same_time(x, cleaned[-1][0])
                and _same_value(y, cleaned[-1][1])):
            continue
        cleaned.append((x, y))
    return cleaned


def _step_xy_polyline(points, end_s):
    """Turn change points into an ordered polyline with vertical step edges."""
    if not points:
        return []
    series = [(points[0]['time_s'], points[0]['value'])]
    previous_time = points[0]['time_s']
    previous_value = points[0]['value']
    for point in points[1:]:
        time_s, value = point['time_s'], point['value']
        if _same_time(time_s, previous_time):
            series.append((time_s, value))
        else:
            series.append((time_s, previous_value))
            series.append((time_s, value))
        previous_time, previous_value = time_s, value
    if end_s > previous_time:
        series.append((end_s, previous_value))
    return _dedupe_xy(series)


def _simplify_xy_polyline(points):
    """Drop points that lie on a straight segment; keep duplicate-x jumps."""
    points = _dedupe_xy(points)
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for index in range(1, len(points) - 1):
        left_x, left_y = kept[-1]
        mid_x, mid_y = points[index]
        right_x, right_y = points[index + 1]
        if (left_y is None or mid_y is None or right_y is None
                or _same_time(left_x, mid_x) or _same_time(mid_x, right_x)):
            kept.append(points[index])
            continue
        slope_left = (mid_y - left_y) / (mid_x - left_x)
        slope_right = (right_y - mid_y) / (right_x - mid_x)
        if abs(slope_left - slope_right) > 1e-12:
            kept.append(points[index])
    kept.append(points[-1])
    return kept


def _actuator_cycle_xy(phases, timeline, parameters, cycle_indices,
                       cycle_start_s, cycle_end_s):
    """Exact first-cycle actuator polyline, including vertical jumps."""
    duration_s = cycle_end_s - cycle_start_s
    if parameters is None:
        return [(0.0, 0.0), (duration_s, 0.0)]

    times = {timeline.starts[index] for index in cycle_indices}
    times.add(cycle_start_s)
    times.add(cycle_end_s)
    times.update(time_s for time_s in timeline.actuator_events
                 if cycle_start_s < time_s < cycle_end_s)

    ordered = sorted(time_s for time_s in times
                     if cycle_start_s <= time_s <= cycle_end_s)
    filtered = []
    for time_s in ordered:
        # actuator_event_times() adds nextafter(t, -inf) before a jump. In an
        # XY table the jump itself carries both values at the same x.
        if math.nextafter(time_s, math.inf) in times:
            continue
        filtered.append(time_s)

    points = []
    for time_s in filtered:
        if _same_time(time_s, cycle_start_s):
            value = load_percent_at(phases, timeline.starts, time_s,
                                    parameters, timeline.load_schedule)
            points.append((0.0, value))
        elif _same_time(time_s, cycle_end_s):
            value = load_percent_at(phases, timeline.starts,
                                    math.nextafter(time_s, -math.inf),
                                    parameters, timeline.load_schedule)
            points.append((duration_s, value))
        else:
            before = load_percent_at(phases, timeline.starts,
                                     math.nextafter(time_s, -math.inf),
                                     parameters, timeline.load_schedule)
            value = load_percent_at(phases, timeline.starts, time_s,
                                    parameters, timeline.load_schedule)
            if not _same_number(before, value):
                points.append((time_s - cycle_start_s, before))
            points.append((time_s - cycle_start_s, value))
    return _simplify_xy_polyline(points)


def _export_cycle1_xy_table(path, timeline, parameters):
    if timeline.parameters is None:
        timeline = Timeline(timeline.phases, parameters)
    phases = timeline.phases
    cycle1_indices = [i for i, phase in enumerate(phases) if phase.cycle == 1]
    if not cycle1_indices:
        raise ValueError('The profile contains no cycle 1 phases.')
    last_index = cycle1_indices[-1]
    cycle_start_s = timeline.starts[cycle1_indices[0]]
    cycle_end_s = timeline.starts[last_index] + phases[last_index].duration_s
    cycles_total = max(phase.cycle for phase in phases)
    cycle_duration_s = cycle_end_s - cycle_start_s
    mode_categories = sorted({phase.mode for phase in phases})

    curves = []
    temperature = temperature_breakpoints(phases, timeline, parameters, cycle=1)
    curves.append(('Temperatur',
                   [(point['time_s'], point['value']) for point in temperature]))

    humidity = step_breakpoints(phases, timeline, 'humidity', parameters, cycle=1)
    curves.append(('Feuchte', _step_xy_polyline(humidity, cycle_duration_s)))

    operation = _simple_step_breakpoints(
        phases, timeline, cycle1_indices, cycle_start_s, 1,
        key_function=lambda phase: phase.mode,
        value_function=lambda phase: mode_categories.index(phase.mode),
        note_function=lambda phase: f'modus={phase.mode}',
    )
    curves.append(('Operation', _step_xy_polyline(operation, cycle_duration_s)))

    voltage = step_breakpoints(phases, timeline, 'voltage', parameters, cycle=1)
    curves.append(('Spannung', _step_xy_polyline(voltage, cycle_duration_s)))

    actuator = _actuator_cycle_xy(phases, timeline, parameters, cycle1_indices,
                                  cycle_start_s, cycle_end_s)
    curves.append(('Aktuator', actuator))

    headers = []
    for name, _ in curves:
        headers.extend([f'{name}_x', f'{name}_y'])
    row_count = max(len(points) for _, points in curves)
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(headers)
        for row_index in range(row_count):
            row = []
            for _, points in curves:
                if row_index < len(points):
                    x, y = points[row_index]
                    row.extend([_xy_number(x), _xy_number(y)])
                else:
                    row.extend(['', ''])
            writer.writerow(row)
    return {'rows': row_count, 'cycles_total': cycles_total,
            'cycle_duration_s': cycle_duration_s}


def export_breakpoints(path, phases, timeline, p, *, cycle=None, time_unit='s',
                       relative=True, whole_seconds=False, fmt='csv',
                       include_actuator_points=False):
    """Export exact phase-derived breakpoints as CSV or JSON.

    Temperature points are the exact linear polygon; step curves change only
    when their value changes. Mode-3.2 actuator runs are summarized as blocks,
    because individual actuator events would be far too numerous.
    """
    unit_key = str(time_unit).strip().lower()
    unit_aliases = {'s': 's', 'sec': 's', 'seconds': 's',
                    'min': 'min', 'minutes': 'min', 'm': 'min',
                    'h': 'h', 'hours': 'h', 'hour': 'h'}
    if unit_key not in unit_aliases:
        raise ValueError("time_unit must be 's', 'min' or 'h'.")
    unit = unit_aliases[unit_key]
    factor = {'s': 1.0, 'min': 60.0, 'h': 3600.0}[unit]
    format_key = str(fmt).strip().lower()
    if format_key not in {'csv', 'json'}:
        raise ValueError("fmt must be 'csv' or 'json'.")
    if timeline.parameters is None:
        timeline = Timeline(phases, p)

    indices, cycle_start_s, cycle_override, repeat = _select_cycle_indices(
        phases, timeline, cycle)
    point_offset = cycle_start_s if relative and cycle is not None else 0.0
    notes = []
    curves = {}
    curves['Temperatur'] = _temperature_breakpoints_for_indices(
        phases, timeline, indices, point_offset, cycle_override)
    for name, curve_key in (('Feuchte', 'humidity'), ('Operation', 'operation'),
                            ('Spannung', 'voltage')):
        curves[name] = _step_breakpoints_for_indices(
            phases, timeline, curve_key, indices, point_offset, cycle_override)
    blocks = _actuator_blocks_for_indices(
        phases, timeline, p, indices, point_offset, cycle_override)
    curves['Aktuator_Block'] = blocks

    if any(point['value'] is None for point in curves['Feuchte']):
        notes.append('Undefined humidity is exported explicitly (empty value with note).')

    if include_actuator_points:
        points = _actuator_cycle_points(phases, timeline, p, blocks,
                                        point_offset, cycle_override)
        if points is None:
            notes.append('No complete actuator cycle found; no actuator points exported.')
        else:
            curves['Aktuator'] = points

    rounded = False
    for name, points in curves.items():
        if name == 'Aktuator_Block':
            if whole_seconds:
                previous = None
                for point in points:
                    original_start = point['time_s']
                    original_end = point['end_s']
                    start = _round_half_up(original_start)
                    if previous is not None and start <= previous:
                        start = previous + 1
                    end = _round_half_up(original_end)
                    if end < start:
                        end = start
                    if start != original_start or end != original_end:
                        rounded = True
                    point['time_s'] = float(start)
                    point['end_s'] = float(end)
                    previous = start
            for point in points:
                point['time_s'] /= factor
                point['end_s'] /= factor
        else:
            if _round_breakpoint_times(points, whole_seconds):
                rounded = True
            for point in points:
                point['time_s'] /= factor

    if rounded:
        notes.append('Times rounded to whole seconds; collisions were shifted by +1 s.')
    if repeat is not None and repeat['remaining'] == 0:
        notes.append('Only one cycle exists; no repetition row was written.')

    unit_label = {'s': 's', 'min': 'min', 'h': 'h'}[unit]
    rows = []

    def append_rows(curve, points, value_unit, kind_key='kind'):
        for index, point in enumerate(points):
            note_parts = []
            if point.get('note'):
                note_parts.append(point['note'])
            if curve == 'Aktuator_Block':
                note_parts.append(
                    'start={};ende={};verzoegerung={};open={};hold={};close={};pause={};'
                    'max={};zyklusdauer={};vollstaendige_zyklen={}'.format(
                        _breakpoint_number(point['time_s']),
                        _breakpoint_number(point['end_s']),
                        _breakpoint_number(point['start_delay_s']),
                        _breakpoint_number(point['open_s']),
                        _breakpoint_number(point['hold_s']),
                        _breakpoint_number(point['close_s']),
                        _breakpoint_number(point['pause_s']),
                        _breakpoint_number(point['max_percent']),
                        _breakpoint_number(point['cycle_duration_s']),
                        point['complete_cycles'],
                    ))
            kind = point.get(kind_key, '')
            slope = point.get('slope_per_min')
            value = point.get('value')
            rows.append({
                'csv': [
                    curve, str(index), str(point['cycle']),
                    _breakpoint_number(point['time_s']), _breakpoint_number(value),
                    value_unit, kind,
                    _breakpoint_number(slope) if slope is not None else '',
                    ';'.join(note_parts),
                ],
                'json': {
                    'kurve': curve, 'punkt': index, 'zyklus': point['cycle'],
                    't_s': point['time_s'], 'wert': value, 'einheit': value_unit,
                    'bis_naechster': kind, 'steigung_pro_min': slope,
                    'hinweis': ';'.join(note_parts),
                },
            })

    append_rows('Temperatur', curves['Temperatur'], '°C')
    append_rows('Feuchte', curves['Feuchte'], '%RH')
    append_rows('Operation', curves['Operation'], '0/1')
    append_rows('Spannung', curves['Spannung'], 'V')
    append_rows('Aktuator_Block', curves['Aktuator_Block'], '')
    if 'Aktuator' in curves:
        append_rows('Aktuator', curves['Aktuator'], '%')

    repeat_row = None
    if repeat is not None and repeat['remaining'] > 0:
        repeat_row = [
            'Wiederholung', '', '', '', '', '', '', '',
            'Wiederholung: {} Zyklen à {} {}'.format(
                repeat['remaining'],
                _breakpoint_number(repeat['cycle_duration_s'] / factor),
                unit_label),
        ]

    counts = {name: len(points) for name, points in curves.items()}
    if format_key == 'csv':
        with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream, delimiter=';')
            writer.writerow(['kurve', 'punkt', 'zyklus', 't_s', 'wert', 'einheit',
                             'bis_naechster', 'steigung_pro_min', 'hinweis'])
            for row in rows:
                writer.writerow(row['csv'])
            if repeat_row is not None:
                writer.writerow(repeat_row)
    else:
        payload = {
            'cycle': cycle,
            'time_unit': unit,
            'relative': relative,
            'whole_seconds': whole_seconds,
            'counts': counts,
            'notes': notes,
            'curves': {},
        }
        for row in rows:
            payload['curves'].setdefault(row['json']['kurve'], []).append(row['json'])
        if repeat_row is not None:
            payload['repeat'] = {
                'remaining': repeat['remaining'],
                'cycles_total': repeat['cycles_total'],
                'cycle_duration_s': repeat['cycle_duration_s'],
                'text': repeat_row[-1],
            }
        with Path(path).open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')

    return {
        'counts': counts,
        'notes': notes,
        'warnings': notes,
        'cycle': cycle,
        'time_unit': unit,
        'relative': relative,
        'whole_seconds': whole_seconds,
        'repeat': repeat,
        'rows': len(rows),
    }


def launch_gui(config_path=DEFAULT_CONFIG_PATH):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('ENV Cycle Generator V04 · Temperature and Humidity Profiles')
    root.geometry('1300x980')
    root.minsize(900, 650)
    root.after_idle(lambda: maximize_window(root))
    try:
        configuration = load_configuration(config_path) if Path(config_path).exists() else default_configuration()
    except (ValueError, TypeError, OSError) as exc:
        messagebox.showerror('Configuration Error', str(exc))
        root.destroy()
        return
    outer = ttk.Frame(root, padding=14)
    outer.pack(fill='both', expand=True)
    title = tk.StringVar()
    ttk.Label(outer, textvariable=title, font=('Arial', 16, 'bold')).pack(anchor='w')
    selector_row = ttk.Frame(outer)
    selector_row.pack(fill='x', pady=8)
    ttk.Label(selector_row, text='Test ID').pack(side='left', padx=(0, 8))
    selection_variable = tk.StringVar(value='ENV_026 — '+TEST_NAMES['ENV_026'])
    class Selection:
        def get(self): return selection_variable.get().split(' — ',1)[0]
        def set(self, test_id): selection_variable.set(test_id+' — '+TEST_NAMES[test_id])
    selected = Selection()
    selector = ttk.Combobox(selector_row, textvariable=selection_variable,
                           values=[tid+' — '+TEST_NAMES[tid] for tid in TEST_NAMES], state='readonly', width=56)
    selector.pack(side='left')
    def show_description():
        try:
            open_description(selected.get())
        except (ValueError, OSError) as exc:
            messagebox.showerror('Show Description', str(exc))
    ttk.Button(selector_row, text='Show Description', command=show_description).pack(side='left', padx=10)
    body = ttk.Frame(outer)
    body.pack(fill='both', expand=True)
    form_host = ttk.LabelFrame(body, text='Test Parameters')
    form_host.pack(side='left', fill='y', padx=(0, 12))
    form_canvas = tk.Canvas(form_host, width=420, highlightthickness=0)
    form_scroll = ttk.Scrollbar(form_host, orient='vertical', command=form_canvas.yview)
    form_canvas.configure(yscrollcommand=form_scroll.set)
    form_scroll.pack(side='right', fill='y')
    form_canvas.pack(side='left', fill='both', expand=True)
    form = ttk.Frame(form_canvas, padding=10)
    form_window = form_canvas.create_window((0,0), window=form, anchor='nw')
    form.bind('<Configure>', lambda event: form_canvas.configure(scrollregion=form_canvas.bbox('all')))
    form_canvas.bind('<Configure>', lambda event: form_canvas.itemconfigure(form_window,width=event.width))
    view = ttk.Frame(body)
    view.pack(side='left', fill='both', expand=True)
    controls = ttk.Frame(view)
    controls.pack(fill='x', pady=(0, 6))
    ttk.Label(controls, text='Chart View').pack(side='left')
    chart_view = tk.StringVar(value='Complete Profile')
    chart_choice = ttk.Combobox(controls, textvariable=chart_view, state='readonly',
                               values=['Complete Profile', 'Single Cycle'], width=18)
    chart_choice.pack(side='left', padx=8)
    ttk.Label(controls, text='Cycle').pack(side='left')
    preview_cycle = tk.StringVar(value='1')
    preview_spin = ttk.Spinbox(controls, from_=1, to=10000, textvariable=preview_cycle, width=7)
    preview_spin.pack(side='left', padx=8)
    unit_label = ttk.Label(controls, text='Time Unit')
    unit_label.pack(side='left', padx=(8, 0))
    x_unit = tk.StringVar(value='Seconds')
    unit_choice = ttk.Combobox(controls, textvariable=x_unit, values=list(TIME_UNITS), state='readonly', width=10)
    unit_choice.pack(side='left', padx=6)
    axis_controls = ttk.Frame(controls)
    axis_controls.pack(side='left', padx=(14, 0))
    x_start_label = tk.StringVar(value='X Start [s]')
    x_start_widget_label = ttk.Label(axis_controls, textvariable=x_start_label)
    x_start_widget_label.pack(side='left')
    x_start = tk.StringVar(value='0')
    x_start_entry = ttk.Entry(axis_controls, textvariable=x_start, width=9)
    x_start_entry.pack(side='left', padx=6)
    x_end_label = tk.StringVar(value='X End [s]')
    x_end_widget_label = ttk.Label(axis_controls, textvariable=x_end_label)
    x_end_widget_label.pack(side='left')
    x_end = tk.StringVar(value='')
    x_end_entry = ttk.Entry(axis_controls, textvariable=x_end, width=11)
    x_end_entry.pack(side='left', padx=6)
    x_step_label = tk.StringVar(value='X Step [s]')
    x_step_widget_label = ttk.Label(axis_controls, textvariable=x_step_label)
    x_step_widget_label.pack(side='left')
    x_step = tk.StringVar(value='')
    x_step_entry = ttk.Entry(axis_controls, textvariable=x_step, width=9)
    x_step_entry.pack(side='left', padx=6)
    axis_apply_button = ttk.Button(axis_controls, text='Apply Axis', command=lambda: plot())
    axis_apply_button.pack(side='left')
    axis_feedback = tk.StringVar(value='Blank = automatic. Chart time always starts at 0 s.')
    ttk.Label(view, textvariable=axis_feedback).pack(anchor='w', pady=(0, 4))
    tracker_controls = ttk.Frame(controls)
    tracker_controls.pack(side='left', padx=(14, 0))
    tracker_label = ttk.Label(tracker_controls, text='Tracker Step [s]')
    tracker_label.pack(side='left')
    tracker_step = tk.StringVar(value='60')
    tracker_entry = ttk.Entry(tracker_controls, textvariable=tracker_step, width=10)
    tracker_entry.pack(side='left', padx=8)
    tracker_apply = ttk.Button(tracker_controls, text='Apply', command=lambda: apply_tracker_step())
    tracker_apply.pack(side='left')
    ttk.Button(tracker_controls, text='Clear Markers', command=lambda: clear_markers()).pack(side='left', padx=8)
    step_feedback = tk.StringVar(value='0 = continuous; Enter or Apply to confirm.')
    ttk.Label(view, textvariable=step_feedback).pack(anchor='w', pady=(0, 4))
    canvas = tk.Canvas(view, background='white', highlightthickness=1, highlightbackground='#d2d7dd')
    canvas.pack(fill='both', expand=True)
    tracker_hint = 'Move the mouse over a chart to view all values.'
    tracker_text = tk.StringVar(value=tracker_hint)
    tracker_display = tk.Frame(view, background='white')
    tracker_display.pack(fill='x', pady=(8, 0))
    tracker_labels = []
    for color in ('#111111', '#c24436', '#2672ad', '#389064', '#d28a18'):
        label = tk.Label(tracker_display, text='', fg=color, bg='white', font=('Arial', 10, 'bold' if color == '#111111' else 'normal'))
        label.pack(side='left', padx=(0, 18))
        tracker_labels.append(label)
    actuator_count_text = tk.StringVar(value='Actuator Auf: 0  |  Zu: 0')
    tk.Label(view, textvariable=actuator_count_text, foreground='#c00000',
             font=('Arial', 20, 'bold')).pack(anchor='e', pady=(2, 4))
    marker_hint = 'Ctrl+Click: set M1. Click: set / move M2.\nTime difference is displayed in minutes.'
    marker_text = tk.StringVar(value=marker_hint)
    ttk.Label(view, textvariable=marker_text, font=('Arial', 10), justify='left').pack(anchor='w', pady=(5, 0))
    status = tk.StringVar()
    ttk.Label(view, textvariable=status, wraplength=650).pack(anchor='w', pady=8)
    source_note = tk.StringVar()
    ttk.Label(view, textvariable=source_note, wraplength=650, justify='left').pack(anchor='w')
    state = {'recipes': {tid:parameters_from_configuration(configuration,tid) for tid in GENERATORS},
             'configuration':configuration, 'config_path':Path(config_path),
             'tracker_step':60.0, 'axis_unit':'Seconds',
             'global_values': flattened_global(configuration),
             'override_selections': {tid: set(configuration['tests'][tid].get('overrides', {}))
                                     for tid in GENERATORS}}
    markers = MeasurementMarkers()
    values = {}
    override_vars = {}
    def read_axis():
        def parse(var):
            text = var.get().strip().replace(',', '.')
            return None if not text else float(text)*TIME_UNITS[x_unit.get()][0]
        start_text = x_start.get().strip().replace(',', '.')
        start = 0.0 if not start_text else float(start_text)*TIME_UNITS[x_unit.get()][0]
        step, end = parse(x_step), parse(x_end)
        if not math.isfinite(start) or start < 0:
            raise ValueError('X Start must be finite and greater than or equal to zero.')
        if any(v is not None and (not math.isfinite(v) or v <= 0) for v in (step, end)):
            raise ValueError('X Step and X End must be positive and finite, or blank for automatic.')
        return start, step, end

    def update_unit_labels():
        symbol = TIME_UNITS[x_unit.get()][1]
        x_start_label.set(f'X Start [{symbol}]')
        x_step_label.set(f'X Step [{symbol}]')
        x_end_label.set(f'X End [{symbol}]')

    def change_axis_unit(event=None):
        old_unit, new_unit = state['axis_unit'], x_unit.get()
        try:
            new_start = convert_axis_start_input(x_start.get(), old_unit, new_unit)
            new_step = convert_axis_input(x_step.get(), old_unit, new_unit)
            new_end = convert_axis_input(x_end.get(), old_unit, new_unit)
        except (ValueError, OverflowError):
            x_unit.set(old_unit)
            axis_feedback.set('Correct X Start / X Step / X End before changing Time Unit. Previous unit remains active.')
            return
        x_start.set(new_start)
        x_step.set(new_step)
        x_end.set(new_end)
        state['axis_unit'] = new_unit
        update_unit_labels()
        plot()

    def read_parameters():
        args = asdict(state['recipes'][selected.get()])
        for key,var in values.items():
            if isinstance(args[key],bool):
                args[key] = bool(var.get())
                continue
            raw = var.get().strip().replace(',', '.')
            if isinstance(args[key],str):
                args[key] = raw
            elif raw == '' and key == 'humidity_rh':
                args[key] = None
            elif isinstance(args[key],int):
                args[key] = int(raw)
            else:
                args[key] = float(raw)
        args['tracker_step_seconds'] = float(tracker_step.get().strip().replace(',', '.'))
        axis_start,axis_step,axis_end = read_axis()
        args['x_axis_start_seconds'] = axis_start
        args['x_axis_step_seconds'] = axis_step
        args['x_axis_end_seconds'] = axis_end
        args['x_axis_unit'] = x_unit.get()
        visible_globals = set(visible_global_keys(state['configuration']))
        overrides = state['configuration']['tests'][selected.get()].get('overrides', {})
        for key in GLOBAL_KEYS - visible_globals:
            args[key] = overrides.get(key, state['global_values'][key])
        p = Parameters(**args)
        p.validate()
        return p

    def hide_tracker(event=None):
        pending = state.pop('tracker_motion_after_id', None)
        if pending is not None:
            root.after_cancel(pending)
        state.pop('tracker_motion_fraction', None)
        canvas.delete('tracker')
        state.pop('cursor_fraction', None)
        tracker_text.set(tracker_hint)
        canvas.configure(cursor='')

    def draw_tracker(fraction):
        canvas.delete('tracker')
        if 'geometry' not in state:
            return
        left, right, top, bottom, mappings, start, end = state['geometry']
        fraction = min(1.0, max(0.0, fraction))
        state['cursor_fraction'] = fraction
        t = start+snap_tracker_time(fraction*(end-start), state['tracker_step'], 0, state['data_end']-start)
        s = state['timeline'].at(t)
        xx = left + (t-start)/(end-start)*(right-left)
        canvas.create_line(xx, top, xx, bottom, fill='#424b57', dash=(4, 3), width=1, tags='tracker')
        tracker_values = (s.temperature_c, s.humidity_rh, s.operation_mode, s.voltage_v,
                          s.load_percent)
        for val, mapping in zip(tracker_values, mappings):
            if val is None or mapping is None:
                continue
            lo, hi, ytop, ybot, categories, color = mapping
            number = categories.index(val) if categories else val
            yy = ybot - (number-lo)/(hi-lo)*(ybot-ytop)
            canvas.create_oval(xx-4, yy-4, xx+4, yy+4, fill=color, outline='white', tags='tracker')
        humidity = (s.undefined_humidity_label or 'unspecified') if s.humidity_rh is None else f'{s.humidity_rh:.2f} % RH'
        voltage = '' if s.voltage_v is None else f'  |  Voltage: {s.voltage_v:.2f} V'
        tracker_labels[0].configure(text=f'Time: {s.time_s/TIME_UNITS[x_unit.get()][0]:.2f} {TIME_UNITS[x_unit.get()][1]}')
        tracker_labels[1].configure(text=f'Temperature: {s.temperature_c:.2f} °C')
        tracker_labels[2].configure(text=f'Relative Humidity: {humidity}')
        tracker_labels[3].configure(text=f'Mode: {s.operation_mode}{voltage}')
        tracker_labels[4].configure(text=f'Actuator Pos.: {s.load_percent:.2f} %')

    def apply_tracker_step(event=None):
        pending = state.pop('tracker_step_after_id', None)
        if pending is not None:
            root.after_cancel(pending)
        try:
            step = float(tracker_step.get().strip().replace(',', '.'))
            if not math.isfinite(step) or step < 0:
                raise ValueError
        except (ValueError, OverflowError):
            step_feedback.set('Enter a finite Tracker Step ≥ 0 s; 0 = continuous. Previous setting remains active.')
            return False
        state['tracker_step'] = step
        step_feedback.set(f'Active Tracker Step: {step:g} s. 0 = continuous. Endpoints remain selectable.')
        if 'cursor_fraction' in state:
            draw_tracker(state['cursor_fraction'])
        return True

    def apply_tracker_step_later(event=None, delay=120):
        pending = state.pop('tracker_step_after_id', None)
        if pending is not None:
            root.after_cancel(pending)

        def apply_pending_step():
            state.pop('tracker_step_after_id', None)
            apply_tracker_step()

        state['tracker_step_after_id'] = root.after(delay, apply_pending_step)

    def draw_markers():
        canvas.delete('markers')
        if markers.start_s is None:
            marker_text.set(marker_hint)
        elif markers.end_s is None:
            marker_text.set(f'M1: {markers.start_s/60:.4f} min\nClick to set M2; Ctrl+Click to replace M1.')
        else:
            marker_text.set(f'M1: {markers.start_s/60:.4f} min  |  M2: {markers.end_s/60:.4f} min\n'
                            f'Δt = {markers.distance_minutes:.4f} min (absolute time difference)')
        if 'geometry' not in state:
            return
        left, right, top, bottom, _, start, end = state['geometry']
        visible = []
        for name, t, color in [('M1', markers.start_s, '#d26c0b'), ('M2', markers.end_s, '#7a45b5')]:
            if t is None or not start <= t <= end:
                continue
            xx = left+(t-start)/(end-start)*(right-left)
            canvas.create_line(xx, top, xx, bottom, fill=color, width=2, tags='markers')
            anchor = 'e' if xx > right-35 else 'w'
            canvas.create_text(xx-5 if anchor == 'e' else xx+5, top-10,
                               text=name, anchor=anchor, fill=color, tags='markers')
            visible.append(xx)
        if len(visible) == 2 and visible[0] != visible[1]:
            canvas.create_line(visible[0], bottom+20, visible[1], bottom+20,
                               arrow='both', fill='#59636f', tags='markers')

    def clear_markers():
        markers.clear()
        draw_markers()

    def place_marker(event):
        if 'geometry' not in state:
            return
        left, right, top, bottom, _, start, end = state['geometry']
        if not left <= event.x <= right or not top <= event.y <= bottom:
            return
        if not apply_tracker_step():
            return
        raw = start+(event.x-left)/(right-left)*(end-start)
        if raw > state['data_end']:
            return
        t = start+snap_tracker_time(raw-start, state['tracker_step'], 0, state['data_end']-start)
        if event.state & 0x0004:  # Tk Control modifier (Windows / Linux).
            markers.set_start(t)
        elif not markers.set_end(t):
            marker_text.set('Set M1 first with Ctrl+Click.\nThen click to set M2 and measure the time difference.')
            return
        draw_markers()

    def track_mouse(event):
        if 'geometry' not in state:
            return
        left, right, top, bottom, *_ = state['geometry']
        if not left <= event.x <= right or not top <= event.y <= bottom:
            hide_tracker()
            return
        canvas.configure(cursor='crosshair')
        if state['geometry'][5]+(event.x-left)/(right-left)*(state['geometry'][6]-state['geometry'][5]) > state['data_end']:
            hide_tracker()
            return
        state['tracker_motion_fraction'] = (event.x-left)/(right-left)
        if 'tracker_motion_after_id' not in state:
            def draw_pending_tracker():
                state.pop('tracker_motion_after_id', None)
                fraction = state.pop('tracker_motion_fraction', None)
                if fraction is not None:
                    draw_tracker(fraction)
            state['tracker_motion_after_id'] = root.after(16, draw_pending_tracker)

    def decimate_polyline(points, pixel_width):
        """Retain ordered extrema per pixel column for dense monotonic-x lines."""
        if len(points) <= max(4, 2*pixel_width):
            return points
        reduced = []
        bucket = []
        column = None

        def flush_bucket():
            if not bucket:
                return
            indices = {0, len(bucket)-1}
            indices.add(min(range(len(bucket)), key=lambda i: bucket[i][1]))
            indices.add(max(range(len(bucket)), key=lambda i: bucket[i][1]))
            for index in sorted(indices):
                point = bucket[index]
                if not reduced or point != reduced[-1]:
                    reduced.append(point)

        for point in points:
            point_column = int(point[0])
            if column is not None and point_column != column:
                flush_bucket()
                bucket.clear()
            column = point_column
            bucket.append(point)
        flush_bucket()
        return reduced

    def plot(event=None):
        pending = state.pop('plot_after_id', None)
        if pending is not None:
            root.after_cancel(pending)
        if 'timeline' not in state:
            return
        timeline = state['timeline']
        timeline_parameters = state['p']
        load_schedule = timeline.load_schedule
        try:
            axis_start, axis_step, axis_end = read_axis()
        except (ValueError, OverflowError) as exc:
            axis_feedback.set(str(exc))
            return
        base_start, base_end = 0.0, timeline.duration_s
        if chart_view.get() == 'Single Cycle':
            try:
                cycle = int(preview_cycle.get())
            except ValueError:
                canvas.create_text(20, 30, anchor='w', text='Enter a valid Cycle number and press Enter.')
                hide_tracker()
                return
            spans = [(t, t+ph.duration_s) for t, ph in zip(timeline.starts, timeline.phases) if ph.cycle == cycle]
            if not spans:
                canvas.create_text(20, 30, anchor='w', text='Cycle number is outside the generated profile.')
                hide_tracker()
                return
            base_start, base_end = spans[0][0], spans[-1][1]
        available_duration = base_end-base_start
        requested_end = available_duration if axis_end is None else axis_end
        if not 0 <= axis_start < requested_end <= available_duration:
            axis_feedback.set(f'Require 0 ≤ X Start < X End ≤ {available_duration/TIME_UNITS[x_unit.get()][0]:.6g} {TIME_UNITS[x_unit.get()][1]}. Previous view remains active.')
            return
        start, end = base_start+axis_start, base_start+requested_end
        data_end = end
        canvas.delete('all')
        state.pop('geometry', None)
        state['data_end'] = data_end
        try:
            tick_values, tick_stride = axis_ticks(end-start, axis_step)
        except (ValueError, OverflowError) as exc:
            axis_feedback.set(str(exc))
            return
        unit_factor, unit_symbol = TIME_UNITS[x_unit.get()]
        axis_feedback.set(f'Time [{unit_symbol}], X Start {start/unit_factor:.6g}. Blank X End = profile end.' if tick_stride == 1 else
                          f'Time [{unit_symbol}]. Showing every {tick_stride}th X Step to keep labels readable.')
        first_phase = max(0, bisect.bisect_right(timeline.starts, start)-1)
        last_phase = bisect.bisect_left(timeline.starts, data_end)
        segments = []
        for index in range(first_phase, min(last_phase+1, len(timeline.phases))):
            origin = timeline.starts[index]
            phase_end = (timeline.starts[index+1] if index+1 < len(timeline.starts)
                         else timeline.duration_s)
            if origin < data_end and phase_end > start:
                segments.append((max(origin, start), min(phase_end, data_end),
                                 timeline.phases[index], origin))
        width, height = max(canvas.winfo_width(), 400), max(canvas.winfo_height(), 300)
        left, right, top, bottom = 75, width-25, 30, height-30
        x = lambda t: left+(right-left)*(t-start)/(end-start)
        charts = [('Temperature [°C]', '#c24436'), ('Relative Humidity [% RH]', '#2672ad'),
                  ('Operating Mode', '#389064')]
        charts.append(('Voltage [V]', '#8957b0'))
        charts.append(('Actuator Pos. [%]', '#d28a18'))
        mode_categories = sorted({ph.mode for ph in timeline.phases})
        band = (bottom-top)/len(charts)
        mappings = []
        for k, (label, color) in enumerate(charts):
            ytop, ybot = top+k*band+18, top+(k+1)*band-27
            canvas.create_text(left, ytop-13, text=label, anchor='w', fill=color)
            canvas.create_line(left, ytop, left, ybot, right, ybot, fill='#9aa3ad')
            if k == 1 and all(ph.humidity_rh is None and not ph.undefined_humidity_label for _, _, ph, _ in segments):
                mappings.append(None)
                canvas.create_text((left+right)/2, (ytop+ybot)/2, text='uncontrolled / unspecified', fill='#707780')
                continue
            categories = mode_categories if k == 2 else None
            def value(ph, t, ph_start):
                if k == 2:
                    return categories.index(ph.mode)
                if k == 1:
                    return ph.humidity_rh
                if label == 'Actuator Pos. [%]':
                    return load_percent_at(timeline.phases, timeline.starts, t, timeline_parameters, load_schedule)
                if k == 3:
                    return ph.voltage_v
                f = (t-ph_start)/ph.duration_s
                return ph.temperature_start_c+f*(ph.temperature_end_c-ph.temperature_start_c)
            if k == 0:
                lo, hi, tick_step = timeline_parameters.temperature_axis_min_c, timeline_parameters.temperature_axis_max_c, timeline_parameters.temperature_axis_step_c
            elif k == 1:
                lo, hi, tick_step = timeline_parameters.humidity_axis_min_rh, timeline_parameters.humidity_axis_max_rh, timeline_parameters.humidity_axis_step_rh
            elif label == 'Actuator Pos. [%]':
                lo, hi, tick_step = timeline_parameters.load_axis_min_percent, timeline_parameters.load_axis_max_percent, timeline_parameters.load_axis_step_percent
            elif label == 'Voltage [V]':
                lo, hi, tick_step = timeline_parameters.voltage_axis_min_v, timeline_parameters.voltage_axis_max_v, timeline_parameters.voltage_axis_step_v
            else:
                nums = list(range(len(categories)))
                lo, hi = (min(nums), max(nums)) if nums else (0, 100)
                pad = 0.5 if categories else max((hi-lo)*0.08, 2)
                lo, hi, tick_step = lo-pad, hi+pad, None
            mappings.append((lo, hi, ytop, ybot, categories, color))
            y = lambda v: ybot-(v-lo)/(hi-lo)*(ybot-ytop)
            ticks = list(enumerate(categories)) if categories else [(v, f'{v:g}') for v in ([lo + i*tick_step for i in range(round((hi-lo)/tick_step)+1)] if tick_step else [lo, hi])]
            for val, text in ticks:
                canvas.create_text(left-7, y(val), text=text, anchor='e')
            undefined_spans = []
            polylines = []
            polyline = []

            def finish_polyline():
                nonlocal polyline
                if len(polyline) >= 2:
                    polylines.append(polyline)
                polyline = []

            for a, b, ph, origin in segments:
                points = [a, b]
                if label == 'Actuator Pos. [%]':
                    first = bisect.bisect_left(timeline.actuator_events, a)
                    last = bisect.bisect_right(timeline.actuator_events, b)
                    points = sorted(set(points + timeline.actuator_events[first:last]))
                for point_a, point_b in zip(points, points[1:]):
                    va, vb = value(ph, point_a, origin), value(ph, point_b, origin)
                    if va is None or vb is None:
                        if k == 1 and ph.undefined_humidity_label:
                            if undefined_spans and abs(undefined_spans[-1][1]-point_a) < 1e-6:
                                undefined_spans[-1] = (undefined_spans[-1][0], point_b)
                            else:
                                undefined_spans.append((point_a, point_b))
                        finish_polyline()
                        continue
                    # The preceding endpoint remains in the same polyline;
                    # a changed va at the same x therefore draws the jump.
                    polyline.append((x(point_a), y(va)))
                    polyline.append((x(point_b), y(vb)))
            finish_polyline()
            dense = sum(map(len, polylines)) > 2*max(1, int(right-left))
            for line_points in polylines:
                if dense:
                    line_points = decimate_polyline(line_points, max(1, int(right-left)))
                if len(line_points) >= 2:
                    coords = [coordinate for point in line_points for coordinate in point]
                    canvas.create_line(*coords, fill=color, width=2)
            # Undefined guide is graphical only; it does not encode an RH value.
            for a, b in undefined_spans:
                guide_y = (ytop+ybot)/2
                canvas.create_line(x(a), guide_y, x(b), guide_y,
                                   fill='#c4c4c4', width=2, dash=(8, 3, 2, 3))
                canvas.create_text((x(a)+x(b))/2, guide_y, text='n.def.',
                                   fill='#929292', anchor='s')
        for j, local_t in enumerate(tick_values):
            xx = x(start+local_t)
            canvas.create_line(xx, top, xx, bottom, fill='#d5d9de', width=1)
            canvas.create_line(xx, bottom, xx, bottom+4, fill='#7d8792')
            if j % max(1, math.ceil(len(tick_values)/10)) == 0:
                canvas.create_text(xx, bottom+12, text=f'{(start+local_t)/unit_factor:.6g} {unit_symbol}')
        state['geometry'] = (left, right, top, bottom, mappings, start, end)
        draw_markers()
        if 'cursor_fraction' in state:
            draw_tracker(state['cursor_fraction'])

    def plot_later(event=None, delay=120):
        pending = state.pop('plot_after_id', None)
        if pending is not None:
            root.after_cancel(pending)

        def plot_pending():
            state.pop('plot_after_id', None)
            plot()

        state['plot_after_id'] = root.after(delay, plot_pending)

    def update(silent=False):
        pending_update = state.pop('update_after_id', None)
        if pending_update is not None:
            root.after_cancel(pending_update)
        if selected.get() not in GENERATORS:
            messagebox.showinfo('Test Unavailable', 'No cycle generator is registered for this Test ID.')
            return False
        try:
            p = read_parameters()
            phases, timeline = generate_phases(p)
            point_count = count_sample_points(timeline, p)
        except (ValueError, TypeError, OverflowError) as exc:
            if not silent:
                messagebox.showerror('Check Test Parameters', str(exc))
            return False
        if phases != state.get('phases'):
            markers.clear()
        state.update(p=p, phases=phases, timeline=timeline,
                     tracker_step=p.tracker_step_seconds)
        openings, closings = actuator_counts(timeline, p)
        actuator_count_text.set(f'Actuator Auf: {openings}  |  Zu: {closings}')
        step_feedback.set(f'Active Tracker Step: {p.tracker_step_seconds:g} s. 0 = continuous. Endpoints remain selectable.')
        state['recipes'][p.test_id] = p
        count = p.cycles if p.test_id in {'ENV_026', 'ENV_004'} else (max(ph.cycle for ph in phases) if p.test_id == 'ENV_012' else p.number_of_cycles)
        message = f'Total Duration: {timeline.duration_s/3600:.3f} h · {point_count} Data Points · {count} Cycle(s)'
        if p.test_id not in {'ENV_026', 'ENV_012'}:
            per_cycle = timeline.duration_s/count/60
            duration_label = 'Average Cycle Duration' if p.test_id == 'ENV_004' and p.cycles > 1 and not p.ramps else 'Cycle Duration'
            message += f'\n{duration_label}: {per_cycle:.3f} min · {timeline.duration_s/86400:.3f} days total'
            if p.test_id == 'ENV_013' and not 3 <= p.temperature_change_rate <= 4:
                message += '\nNote: plan specifies 4 °C/min, reducible to a minimum of 3 °C/min.'
        if p.test_id not in {'ENV_012', 'ENV_002', 'ENV_003', 'ENV_004'} and p.humidity_rh is not None and not 45 <= p.humidity_rh <= 75:
            message += '\nNote: Relative Humidity is outside the specified range of 45–75 % RH.'
        reference = default_parameters(p.test_id)
        specific = TEST_KEYS[p.test_id].split()
        if any(getattr(p, key) != getattr(reference, key) for key in specific):
            message += f'\nTest Parameters differ from the {p.test_id} reference recipe.'
        status.set(message)
        preview_spin.configure(to=count)
        plot()
        return True

    # Keys that do not change an Entry's text must not trigger a recalculation.
    non_editing_keys = {'Tab', 'ISO_Left_Tab', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R',
                        'Alt_L', 'Alt_R', 'Caps_Lock', 'Left', 'Right', 'Up', 'Down', 'Home',
                        'End', 'Prior', 'Next', 'Escape', 'Return', 'KP_Enter'}

    def update_later(event=None, delay=500):
        """Debounce form edits: recalculate once after typing has paused."""
        if event is not None and getattr(event, 'keysym', '') in non_editing_keys:
            return
        pending = state.pop('update_after_id', None)
        if pending is not None:
            root.after_cancel(pending)

        def update_pending():
            state.pop('update_after_id', None)
            update(silent=True)

        state['update_after_id'] = root.after(delay, update_pending)

    def update_now(event=None):
        """Return key: recalculate immediately (cancels a pending debounced run)."""
        update(silent=True)

    def flush_pending_update(event=None):
        """Focus leaves a field: run a still-pending debounced update right away."""
        if state.get('update_after_id') is not None:
            update(silent=True)

    def build_form(p):
        pending_update = state.pop('update_after_id', None)
        if pending_update is not None:
            root.after_cancel(pending_update)
        for widget in form.winfo_children(): widget.destroy()
        values.clear()
        override_vars.clear()
        tracker_step.set(str(p.tracker_step_seconds))
        state['tracker_step'] = p.tracker_step_seconds
        x_unit.set(p.x_axis_unit)
        state['axis_unit'] = p.x_axis_unit
        unit_factor = TIME_UNITS[p.x_axis_unit][0]
        x_start.set(format(p.x_axis_start_seconds/unit_factor,'.15g'))
        x_step.set('' if p.x_axis_step_seconds is None else format(p.x_axis_step_seconds/unit_factor,'.15g'))
        x_end.set('' if p.x_axis_end_seconds is None else format(p.x_axis_end_seconds/unit_factor,'.15g'))
        update_unit_labels()
        visible = state['configuration']['tests'][p.test_id]['visible']
        global_visible = set(visible_global_keys(state['configuration']))
        for widget in (unit_label,unit_choice,x_start_widget_label,x_start_entry,x_step_widget_label,x_step_entry,
                       x_end_widget_label,x_end_entry,axis_apply_button,tracker_label,tracker_entry,tracker_apply):
            widget.pack_forget()
        if 'x_axis_unit' in global_visible:
            unit_label.pack(side='left',padx=6);unit_choice.pack(side='left',padx=6)
        if 'x_axis_start_seconds' in global_visible:
            x_start_widget_label.pack(side='left');x_start_entry.pack(side='left',padx=6)
        if 'x_axis_end_seconds' in global_visible:
            x_end_widget_label.pack(side='left');x_end_entry.pack(side='left',padx=6)
        if 'x_axis_step_seconds' in global_visible:
            x_step_widget_label.pack(side='left');x_step_entry.pack(side='left',padx=6)
        if {'x_axis_start_seconds','x_axis_step_seconds','x_axis_end_seconds'} & global_visible:
            axis_apply_button.pack(side='left')
        if 'tracker_step_seconds' in global_visible:
            tracker_label.pack(side='left');tracker_entry.pack(side='left',padx=6);tracker_apply.pack(side='left')
        row = 0
        for key in list(visible) + visible_global_keys(state['configuration']):
            if key in SPECIAL_CONTROLS: continue
            value = getattr(p,key)
            ttk.Label(form,text=parameter_label(key),wraplength=250).grid(row=row,column=0,sticky='w',padx=(0,8),pady=5)
            var = tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value='' if value is None else str(value))
            values[key] = var
            if isinstance(value,bool):
                widget = ttk.Checkbutton(form,variable=var,command=update_later)
            elif key.endswith('mode'):
                widget = ttk.Combobox(form,textvariable=var,state='readonly',width=12,
                    values=['1.1','1.2','2.1','2.2','2.3','2.4','3.1','3.2','3.3','3.4'])
            else:
                widget = ttk.Entry(form,textvariable=var,width=14)
            widget.grid(row=row,column=1,pady=5,sticky='ew')
            if isinstance(widget, ttk.Combobox):
                widget.bind('<<ComboboxSelected>>', update_later)
            elif isinstance(widget, ttk.Entry):
                widget.bind('<KeyRelease>', update_later)
                widget.bind('<Return>', update_now)
                widget.bind('<FocusOut>', flush_pending_update)
            row += 1
        global_visible_order = visible_global_keys(state['configuration'])
        if global_visible_order:
            ttk.Separator(form, orient='horizontal').grid(row=row, column=0, columnspan=3, sticky='ew', pady=(10, 6))
            row += 1
            ttk.Label(form, text='Explicit Test Overrides').grid(row=row, column=0, columnspan=3, sticky='w')
            row += 1
            selected_overrides = state['override_selections'].setdefault(p.test_id, set())
            for key in global_visible_order:
                flag = tk.BooleanVar(value=key in selected_overrides)
                override_vars[key] = flag
                ttk.Checkbutton(form, text=parameter_label(key), variable=flag).grid(
                    row=row, column=0, columnspan=3, sticky='w', pady=2)
                row += 1
        form_canvas.yview_moveto(0)
        notes = {
          'ENV_004':'Chapter 6 / Section 2.1: 48-V component: UN 48 V, UA 48 V, Umin 36 V, Umax 52 V. Mode 3.1 uses UA. Ramps and UN are configurable; transition rate remains an explicit assumption.',
          'ENV_026':'Chapter 20: 48 h at 80 °C: 47 h Mode 3.2 + 1 h Mode 3.1. Default environmental RH 60%.',
          'ENV_013':'Current Chapter 21 table: 870 cycles, 15-min total dwells, 3 DUTs. Last 5 min cold in Mode 3.2. Cold wording is ambiguous; the total dwell follows the table.',
          'ENV_014':'Chapter 8: 30 × 480 min. Brief cold-check timing is adjustable because the text does not quantify it.',
          'ENV_015':'Chapter 7: the initial temperature dwell is ALWAYS included. 25+1+3+1 min at each gradient point.',
          'ENV_012':'Current Chapter 15: 504 h, 65 °C / 93% RH. 47 h Mode 2.1 + 1 h Mode 3.2, final hour active.',
          'ENV_002':'Current Chapter 13: 10 × 24 h, first 5 with frost, Modes 3.1/3.2. Segment durations are a nominal interpretation of the uploaded figures, not independently certified IEC setpoints.',
          'ENV_003':'Current Chapter 14: one check per cycle, Mode 3.1 → 3.2 at Tmax. Default check duration 1 min is an editable assumption. 5 × 5 h.',
        }
        source_note.set(notes[p.test_id])
        title.set(p.test_id+' · '+TEST_NAMES[p.test_id])

    def switch_test(event=None):
        # Preserve edits to the previous recipe when they are valid.
        previous = state.get('form_test')
        if previous in GENERATORS:
            state['override_selections'][previous] = {key for key,var in override_vars.items() if var.get()}
            new_id = selected.get()
            selected.set(previous)
            try:
                state['recipes'][previous] = read_parameters()
            except (ValueError, TypeError, OverflowError):
                pass
            selected.set(new_id)
        state['form_test'] = selected.get()
        build_form(state['recipes'][selected.get()])
        clear_markers()
        hide_tracker()
        preview_cycle.set('1')
        chart_view.set('Complete Profile' if selected.get() in {'ENV_026', 'ENV_012'} else 'Single Cycle')
        update()

    def export():
        if not update():
            return
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile=f'{selected.get()}_Time_Profile.csv',
                                          filetypes=[('CSV', '*.csv')])
        if path:
            try:
                export_csv(path, iter_samples(state['timeline'], state['p']))
                messagebox.showinfo('Export', f'CSV saved:\n{path}')
            except OSError as exc:
                messagebox.showerror('Export Failed', str(exc))

    def export_cycle1():
        if not update():
            return
        path = filedialog.asksaveasfilename(defaultextension='.csv',
                                          initialfile=f'{selected.get()}_Cycle1.csv',
                                          filetypes=[('CSV', '*.csv')])
        if path:
            try:
                export_cycle1_csv(path, state['timeline'], state['p'])
                messagebox.showinfo('Export', f'Cycle 1 XY table saved:\n{path}')
            except OSError as exc:
                messagebox.showerror('Export Failed', str(exc))

    def export_breakpoints_dialog():
        phases = state.get('phases')
        timeline = state.get('timeline')
        p = state.get('p')
        if phases is None or timeline is None or p is None:
            messagebox.showinfo('Export Breakpoints',
                                'Generate the profile before exporting breakpoints.')
            return
        cycles = sorted({phase.cycle for phase in phases})
        dialog = tk.Toplevel(root)
        dialog.title('Export Breakpoints')
        dialog.transient(root)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill='both', expand=True)

        cycle_var = tk.StringVar(value='all')
        unit_var = tk.StringVar(value='s')
        format_var = tk.StringVar(value='csv')
        whole_var = tk.BooleanVar(value=False)
        ttk.Label(body, text='Cycle').grid(row=0, column=0, sticky='w', pady=4)
        ttk.Combobox(body, textvariable=cycle_var, state='readonly', width=20,
                     values=['all'] + [str(number) for number in cycles]
                     + ['first + repeat']).grid(row=0, column=1, sticky='ew', pady=4)
        ttk.Label(body, text='Time unit').grid(row=1, column=0, sticky='w', pady=4)
        ttk.Combobox(body, textvariable=unit_var, state='readonly', width=20,
                     values=['s', 'min', 'h']).grid(row=1, column=1, sticky='ew', pady=4)
        ttk.Label(body, text='Format').grid(row=2, column=0, sticky='w', pady=4)
        ttk.Combobox(body, textvariable=format_var, state='readonly', width=20,
                     values=['csv', 'json']).grid(row=2, column=1, sticky='ew', pady=4)
        ttk.Checkbutton(body, text='Round times to whole seconds',
                        variable=whole_var).grid(row=3, column=0, columnspan=2,
                                                 sticky='w', pady=4)
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky='e', pady=(10, 0))

        def run_export():
            selected_cycle = cycle_var.get()
            if selected_cycle == 'all':
                cycle = None
            elif selected_cycle == 'first + repeat':
                cycle = 'first_plus_repeat'
            else:
                cycle = int(selected_cycle)
            output_format = format_var.get()
            path = filedialog.asksaveasfilename(
                parent=dialog, defaultextension=f'.{output_format}',
                initialfile=f'{selected.get()}_Breakpoints.{output_format}',
                filetypes=[('CSV', '*.csv'), ('JSON', '*.json')]
                if output_format == 'csv' else [('JSON', '*.json'), ('CSV', '*.csv')])
            if not path:
                return
            if Path(path).exists() and not messagebox.askyesno(
                    'Overwrite', f'{path} already exists. Replace it?', parent=dialog):
                return
            try:
                info = export_breakpoints(path, phases, timeline, p, cycle=cycle,
                                          time_unit=unit_var.get(),
                                          whole_seconds=whole_var.get(),
                                          fmt=output_format)
            except (ValueError, OSError, TypeError) as exc:
                messagebox.showerror('Export Breakpoints Failed', str(exc),
                                     parent=dialog)
                return
            message = f'Breakpoints saved:\n{path}\n\n{info["counts"]}'
            if info['notes']:
                message += '\n' + '\n'.join(info['notes'])
            messagebox.showinfo('Export Breakpoints', message, parent=dialog)
            dialog.destroy()

        ttk.Button(buttons, text='Export', command=run_export).pack(side='right', padx=(6, 0))
        ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right')
        dialog.grab_set()
        dialog.wait_window()

    def save_config():
        if not update(): return
        try:
            selected_overrides = {key for key,var in override_vars.items() if var.get()}
            state['configuration'] = save_current_test(state['config_path'],state['p'],
                                                       override_keys=selected_overrides)
            state['override_selections'][selected.get()] = selected_overrides
            state['recipes'] = {tid:parameters_from_configuration(state['configuration'],tid)
                                for tid in GENERATORS}
            build_form(state['recipes'][selected.get()])
            update()
            messagebox.showinfo('Save Current Test', selected.get()+' saved to '+str(state['config_path'])+'\nOther test sections were not changed.')
        except (ValueError,TypeError,OSError) as exc:
            messagebox.showerror('Save Failed',str(exc))

    def save_global():
        if not update(): return
        try:
            config = save_global_settings(state['config_path'], state['p'])
            recipes = {tid:parameters_from_configuration(config,tid) for tid in GENERATORS}
            state.update(configuration=config, recipes=recipes,
                         global_values=flattened_global(config))
            build_form(recipes[selected.get()])
            update()
            messagebox.showinfo('Save Global', 'Global settings saved to '+str(state['config_path']))
        except (ValueError,TypeError,OSError) as exc:
            messagebox.showerror('Save Global Failed',str(exc))

    def load_config():
        path = filedialog.askopenfilename(initialfile=state['config_path'].name,filetypes=[('Overall Configuration','*.json')])
        if not path: return
        try:
            config = load_configuration(path)
            recipes = {tid:parameters_from_configuration(config,tid) for tid in GENERATORS}
            state.update(configuration=config,recipes=recipes,config_path=Path(path),
                         global_values=flattened_global(config),
                         override_selections={tid:set(config['tests'][tid].get('overrides', {}))
                                              for tid in GENERATORS})
            state.pop('form_test',None)
            switch_test()
        except (ValueError,TypeError,OSError) as exc:
            messagebox.showerror('Load Configuration Failed',str(exc))

    buttons = ttk.Frame(outer)
    buttons.pack(fill='x', pady=(10, 0))
    for label, command in [('Generate Profile', update), ('Save CSV', export),
                           ('Save Cycle 1 (Excel)', export_cycle1),
                           ('Export Breakpoints …', export_breakpoints_dialog),
                           ('Save Global', save_global), ('Save Current Test', save_config),
                           ('Load Configuration', load_config)]:
        ttk.Button(buttons, text=label, command=command).pack(side='left', padx=(0, 8))
    selector.bind('<<ComboboxSelected>>', switch_test)
    chart_choice.bind('<<ComboboxSelected>>', plot)
    unit_choice.bind('<<ComboboxSelected>>', change_axis_unit)
    preview_spin.configure(command=plot)
    preview_spin.bind('<Return>', plot)
    preview_spin.bind('<FocusOut>', plot)
    canvas.bind('<Configure>', plot_later)
    canvas.bind('<Motion>', track_mouse)
    canvas.bind('<Leave>', hide_tracker)
    canvas.bind('<Button-1>', place_marker)
    tracker_entry.bind('<Return>', apply_tracker_step)
    tracker_entry.bind('<FocusOut>', apply_tracker_step)
    tracker_entry.bind('<KeyRelease>', apply_tracker_step_later)
    x_step_entry.bind('<Return>', plot)
    x_end_entry.bind('<Return>', plot)
    x_start_entry.bind('<Return>', plot)
    x_start_entry.bind('<KeyRelease>', plot_later)
    x_step_entry.bind('<KeyRelease>', plot_later)
    x_end_entry.bind('<KeyRelease>', plot_later)
    root.after(100, switch_test)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', metavar='CSV', help='Export the default profile without opening the GUI')
    parser.add_argument('--cycle1', metavar='CSV', help='Export the first cycle as an Excel XY x/y breakpoint table')
    parser.add_argument('--breakpoints', metavar='PFAD', help='Export exact phase-derived breakpoints as CSV or JSON')
    parser.add_argument('--cycle', default=None,
                        help="Cycle number for --breakpoints, or 'first_plus_repeat'")
    parser.add_argument('--time-unit', choices=['s', 'min', 'h'], default='s',
                        help='Time unit for --breakpoints (default: s)')
    parser.add_argument('--whole-seconds', action='store_true',
                        help='Round --breakpoints times to whole seconds')
    parser.add_argument('--format', choices=['csv', 'json'], default=None,
                        help='Breakpoint output format (default: infer from suffix, otherwise csv)')
    parser.add_argument('--test', choices=list(GENERATORS), default=None, help='Test ID (overrides JSON Test ID)')
    parser.add_argument('--config', type=Path, help='Overall JSON configuration for GUI or CLI')
    args = parser.parse_args()
    config_path = args.config or DEFAULT_CONFIG_PATH
    cycle = args.cycle
    if cycle is not None and str(cycle).lower() not in {'all', 'first_plus_repeat'}:
        try:
            cycle = int(cycle)
        except (TypeError, ValueError):
            parser.error('--cycle must be an integer, all, or first_plus_repeat')
    elif str(cycle).lower() == 'all':
        cycle = None
    if args.example or args.cycle1 or args.breakpoints:
        config = load_configuration(config_path) if config_path.exists() else default_configuration()
        p = parameters_from_configuration(config,args.test or 'ENV_026')
        phases, timeline = generate_phases(p)
        if args.example:
            point_count = count_sample_points(timeline, p)
            export_csv(args.example, iter_samples(timeline, p))
            print(f'{args.example}: {point_count} Points, {timeline.duration_s/3600:g} Hours')
        if args.cycle1:
            info = export_cycle1_csv(args.cycle1, timeline, p)
            print(f"{args.cycle1}: Cycle 1, {info['rows']} Points, "
                  f"{info['cycles_total']} Cycles, {info['cycle_duration_s']/3600:g} Hours")
        if args.breakpoints:
            output_format = args.format
            if output_format is None:
                output_format = 'json' if Path(args.breakpoints).suffix.lower() == '.json' else 'csv'
            info = export_breakpoints(args.breakpoints, phases, timeline, p,
                                      cycle=cycle, time_unit=args.time_unit,
                                      whole_seconds=args.whole_seconds,
                                      fmt=output_format)
            print(f"{args.breakpoints}: {info['rows']} Breakpoint rows, "
                  f"{info['counts']}, {output_format}")
    else:
        launch_gui(config_path)


if __name__ == '__main__':
    main()
