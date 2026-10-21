#!/usr/bin/env python3
"""ENV profile generator V2.1: temperature, humidity, Operating Mode and voltage profiles.
Python >=3.10, standard library only.
Run without arguments for Tkinter, or --example output.csv for headless export.
"""
from __future__ import annotations
import argparse
import bisect
import csv
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
    precondition_minutes: float = 30.0
    activation_minutes: float = 10.0
    load_open_seconds: float = 10.0
    load_hold_seconds: float = 10.0
    load_pause_seconds: float = 5.0
    load_close_seconds: float = 10.0
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
        if self.load_open_seconds <= 0 or self.load_hold_seconds < 0 or self.load_pause_seconds < 0:
            raise ValueError('Actuator opening time must be > 0; hold and pause times must be >= 0.')
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
                        p.ub_voltage_v if p.standby_mode.startswith('2.') else 0.0)
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



SOURCE_DOCUMENT = '2.ENV_Test_Plan_Cp_r00v05(1).docx'
DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name('env_config.json')
COMMON_KEYS = 'humidity_rh active_mode standby_mode sample_seconds'.split()
ACTUATOR_KEYS = 'load_open_seconds load_hold_seconds load_pause_seconds load_close_seconds load_max_percent'.split()
ACTUATOR_VISIBLE_KEYS = 'load_open_seconds load_hold_seconds load_pause_seconds'.split()
CHART_KEYS = ('tracker_step_seconds x_axis_unit x_axis_start_seconds x_axis_step_seconds x_axis_end_seconds '
              'temperature_axis_min_c temperature_axis_max_c temperature_axis_step_c '
              'humidity_axis_min_rh humidity_axis_max_rh humidity_axis_step_rh '
              'load_axis_min_percent load_axis_max_percent load_axis_step_percent '
              'voltage_axis_min_v voltage_axis_max_v voltage_axis_step_v').split()
GLOBAL_KEYS = set(ACTUATOR_KEYS + CHART_KEYS)
TEST_KEYS = {
 'ENV_004': 'room_temperature_c minimum_temperature_c maximum_temperature_c nominal_voltage_v minimum_voltage_v maximum_voltage_v ua_voltage_v ub_voltage_v precondition_minutes activation_minutes temperature_change_rate cycles ramps',
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
 'load_pause_seconds':'Actuator Pause Time [s]',
}

def parameter_label(key):
    return PARAMETER_LABELS.get(key, key.replace('_',' ').title())


def default_configuration():
    defaults = asdict(Parameters())
    config = {'schema_version':3, 'source_document':SOURCE_DOCUMENT,
              'global': {'actuator': {key: defaults[key] for key in ACTUATOR_KEYS},
                         'chart': {key: defaults[key] for key in CHART_KEYS}}, 'tests':{}}
    for tid in GENERATORS:
        values = asdict(default_parameters(tid))
        keys = list(dict.fromkeys(TEST_KEYS[tid].split()+COMMON_KEYS))
        config['tests'][tid] = {'name':TEST_NAMES[tid],
            'visible':{key:values[key] for key in keys if key not in HIDDEN_KEYS},
            'unvisible':{key:values[key] for key in keys if key in HIDDEN_KEYS},
            'chart_overrides': {}}
    return config


def migrate_schema2(config):
    """Convert schema 2 in memory, retaining every differing global value as an override."""
    import copy
    if config.get('schema_version') != 2:
        return config
    migrated = copy.deepcopy(config)
    base = default_configuration()
    migrated['schema_version'] = 3
    migrated['global'] = copy.deepcopy(base['global'])
    global_values = {**migrated['global']['actuator'], **migrated['global']['chart']}
    for tid, entry in migrated.get('tests', {}).items():
        overrides = {}
        for section in ('visible', 'unvisible'):
            values = entry.get(section, {})
            for key in list(values):
                if key in GLOBAL_KEYS:
                    value = values.pop(key)
                    if value != global_values[key]:
                        overrides[key] = value
        entry['chart_overrides'] = overrides
    return migrated


def parameters_from_configuration(config, test_id):
    if config.get('schema_version') != 3 or not isinstance(config.get('tests'),dict):
        raise ValueError('Expected a schema_version 3 overall configuration with global and tests sections.')
    global_config = config.get('global')
    if not isinstance(global_config, dict) or not isinstance(global_config.get('actuator'), dict) or not isinstance(global_config.get('chart'), dict):
        raise ValueError('Schema 3 requires global.actuator and global.chart objects.')
    if test_id not in config['tests']:
        raise ValueError('Configuration is missing '+test_id)
    entry = config['tests'][test_id]
    if not isinstance(entry,dict) or not isinstance(entry.get('visible'),dict) or not isinstance(entry.get('unvisible'),dict):
        raise ValueError(test_id+': visible and unvisible must be JSON objects.')
    overlap = set(entry['visible']) & set(entry['unvisible'])
    if overlap:
        raise ValueError(test_id+': parameter appears in both sections: '+', '.join(sorted(overlap)))
    overrides = entry.get('chart_overrides', {})
    if not isinstance(overrides, dict) or any(key not in GLOBAL_KEYS for key in overrides):
        raise ValueError(test_id+': chart_overrides contains an unsupported parameter.')
    values = asdict(default_parameters(test_id))
    combined = {**global_config['actuator'], **global_config['chart'], **overrides,
                **entry['unvisible'], **entry['visible']}
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
    if config.get('schema_version') == 2:
        backup = path.with_name(path.stem+'.schema2.backup'+path.suffix)
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        config = migrate_schema2(config)
        temporary = path.with_name(path.name+'.schema3.tmp')
        temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        temporary.replace(path)
    for tid in GENERATORS:
        parameters_from_configuration(config,tid)
    return config


def save_current_test(path, parameters, entry_template=None, global_values=None):
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
    global_values = values if global_values is None else global_values
    for section in ('actuator','chart'):
        for key in config['global'][section]:
            config['global'][section][key] = global_values[key]
    config['global']['actuator']['load_close_seconds'] = config['global']['actuator']['load_open_seconds']
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


def generate(p: Parameters, test_id=None) -> tuple[list[Phase], list[Sample]]:
    if test_id is not None:
        # Preserve support for the original explicit generate(p, test_id) API.
        from dataclasses import replace
        p = replace(p, test_id=test_id)
    test_id = p.test_id
    p.validate()
    phases = GENERATORS[test_id](p)
    starts, end = [], 0.0
    for phase in phases:
        starts.append(end)
        end += phase.duration_s
    n = math.ceil(end / p.sample_seconds)
    if n + len(starts) + 1 > 500000:
        raise ValueError('Too many data points (maximum 500000). Increase the time step.')
    # Include all boundaries, even if the sampling interval does not hit them.
    # Deduplicate near-identical floats at ns precision, keeping exact events.
    times = {round(i * p.sample_seconds, 9): i * p.sample_seconds for i in range(n)}
    times.update({round(t, 9): t for t in starts + [end]})
    samples = []
    load_schedule = build_load_schedule(phases, starts)
    for t in sorted(times.values()):
        idx = min(bisect.bisect_right(starts, t) - 1, len(phases) - 1)
        ph = phases[idx]
        fraction = min(1.0, max(0.0, (t - starts[idx]) / ph.duration_s))
        temperature = ph.temperature_start_c + fraction * (ph.temperature_end_c - ph.temperature_start_c)
        at_threshold = (ph.humidity_at_threshold is not None
                        and temperature == max(ph.temperature_start_c, ph.temperature_end_c))
        rh = ph.humidity_at_threshold if at_threshold else (None if ph.undefined_humidity_label and temperature < max(ph.temperature_start_c, ph.temperature_end_c) else ph.humidity_rh)
        samples.append(Sample(t, ph.cycle, ph.name, temperature, rh, ph.mode, ph.voltage_v,
                              ph.undefined_humidity_label if rh is None else '',
                              load_percent_at(phases, starts, t, p, load_schedule)))
    return phases, samples


def load_percent_at(phases, starts, time_s, p, schedule=None):
    """Return the trapezoidal load using a precomputed mode-change schedule."""
    idx = min(bisect.bisect_right(starts, time_s) - 1, len(phases) - 1)
    mode = phases[idx].mode
    open_s, hold_s, pause_s = p.load_open_seconds, p.load_hold_seconds, p.load_pause_seconds
    duration = 2 * open_s + hold_s + pause_s

    schedule = schedule or build_load_schedule(phases, starts)
    active_start = schedule[0][idx]
    if active_start is None:
        return 0.0

    def active_load(delta):
        phase_time = delta % duration
        if phase_time < open_s:
            return p.load_max_percent * phase_time / open_s
        phase_time -= open_s
        if phase_time < hold_s:
            return p.load_max_percent
        phase_time -= hold_s
        if phase_time < open_s:
            return p.load_max_percent * (1.0 - phase_time / open_s)
        return 0.0

    if mode == '3.2':
        return active_load(max(0.0, time_s - active_start))

    switched_off = schedule[1][idx]
    if switched_off is None:
        return 0.0
    value_at_switch = active_load(max(0.0, switched_off - active_start))
    return max(0.0, value_at_switch - p.load_max_percent * (time_s - switched_off) / open_s)


def export_csv(path, samples):
    """Right-continuous modes: at an event time, the NEW mode applies.
    Temperature: linear interpolation; humidity/mode: hold previous value.
    Final row is the endpoint, not an additional time interval.
    ENV_002 undefined humidity is n.def.; other unspecified humidity is empty.
    """
    with Path(path).open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream, delimiter=';')
        voltage_enabled = any(s.voltage_v is not None for s in samples)
        writer.writerow(['time_s', 'time_min', 'time_h', 'temperature_C',
                         'humidity_percent_RH', 'operation_mode', 'cycle', 'phase', 'load_percent']+(['voltage_V'] if voltage_enabled else []))
        for s in samples:
            writer.writerow([f'{s.time_s:.9f}'.rstrip('0').rstrip('.'),
                             f'{s.time_s / 60:.9f}', f'{s.time_s / 3600:.9f}',
                             f'{s.temperature_c:.6f}',
                             ('n.def' if s.undefined_humidity_label else '') if s.humidity_rh is None else f'{s.humidity_rh:.6f}',
                             s.operation_mode, s.cycle, s.phase, f'{s.load_percent:.6f}']+(
                             ['' if s.voltage_v is None else f'{s.voltage_v:.6f}'] if voltage_enabled else []))


def launch_gui(config_path=DEFAULT_CONFIG_PATH):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('ENV Cycle Generator V2.1 · Temperature and Humidity Profiles')
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
    load_enabled = tk.BooleanVar(value=False)
    ttk.Checkbutton(selector_row, text='Actuator Pos. [%]', variable=load_enabled, command=lambda: plot()).pack(side='left', padx=(0, 10))
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
             'global_values': {**configuration['global']['actuator'], **configuration['global']['chart']}}
    markers = MeasurementMarkers()
    values = {}
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
        args['load_close_seconds'] = args['load_open_seconds']
        args['tracker_step_seconds'] = float(tracker_step.get().strip().replace(',', '.'))
        axis_start,axis_step,axis_end = read_axis()
        args['x_axis_start_seconds'] = axis_start
        args['x_axis_step_seconds'] = axis_step
        args['x_axis_end_seconds'] = axis_end
        args['x_axis_unit'] = x_unit.get()
        editable_global = set(ACTUATOR_VISIBLE_KEYS) | SPECIAL_CONTROLS
        for key in GLOBAL_KEYS - editable_global:
            args[key] = state['global_values'][key]
        global_values = {key: args[key] for key in GLOBAL_KEYS}
        global_values['load_close_seconds'] = global_values['load_open_seconds']
        args.update(state['configuration']['tests'][selected.get()].get('chart_overrides', {}))
        p = Parameters(**args)
        p.validate()
        state['global_values'].update(global_values)
        return p

    def hide_tracker(event=None):
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
                          s.load_percent if load_enabled.get() else None)
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
        if load_enabled.get():
            tracker_labels[4].configure(text=f'Actuator Pos.: {s.load_percent:.2f} %')

    def apply_tracker_step(event=None):
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
        draw_tracker((event.x-left)/(right-left))

    def plot(event=None):
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
        segments = [(max(t, start), min(t+ph.duration_s, data_end), ph, t)
                    for t, ph in zip(timeline.starts, timeline.phases)
                    if t < data_end and t+ph.duration_s > start]
        width, height = max(canvas.winfo_width(), 400), max(canvas.winfo_height(), 300)
        left, right, top, bottom = 75, width-25, 30, height-30
        x = lambda t: left+(right-left)*(t-start)/(end-start)
        charts = [('Temperature [°C]', '#c24436'), ('Relative Humidity [% RH]', '#2672ad'),
                  ('Operating Mode', '#389064')]
        if any(ph.voltage_v is not None for ph in timeline.phases):
            charts.append(('Voltage [V]', '#8957b0'))
        if load_enabled.get():
            charts.append(('Actuator Pos. [%]', '#d28a18'))
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
            categories = sorted({ph.mode for ph in timeline.phases}) if k == 2 else None
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
            nums = [value(ph, t, origin) for a, b, ph, origin in segments for t in (a, b)
                    if value(ph, t, origin) is not None]
            if k == 2:
                nums = list(range(len(categories)))
            elif k == 1:
                nums = [ph.humidity_rh for ph in timeline.phases if ph.humidity_rh is not None]
            elif label == 'Actuator Pos. [%]':
                nums = [timeline_parameters.load_axis_min_percent, timeline_parameters.load_axis_max_percent]
            elif label == 'Voltage [V]':
                nums = [ph.voltage_v for ph in timeline.phases if ph.voltage_v is not None]
            if k == 0:
                lo, hi, tick_step = timeline_parameters.temperature_axis_min_c, timeline_parameters.temperature_axis_max_c, timeline_parameters.temperature_axis_step_c
            elif k == 1:
                lo, hi, tick_step = timeline_parameters.humidity_axis_min_rh, timeline_parameters.humidity_axis_max_rh, timeline_parameters.humidity_axis_step_rh
            elif label == 'Actuator Pos. [%]':
                lo, hi, tick_step = timeline_parameters.load_axis_min_percent, timeline_parameters.load_axis_max_percent, timeline_parameters.load_axis_step_percent
            elif label == 'Voltage [V]':
                lo, hi, tick_step = timeline_parameters.voltage_axis_min_v, timeline_parameters.voltage_axis_max_v, timeline_parameters.voltage_axis_step_v
            else:
                lo, hi = (min(nums), max(nums)) if nums else (0, 100)
                pad = 0.5 if categories else max((hi-lo)*0.08, 2)
                lo, hi, tick_step = lo-pad, hi+pad, None
            mappings.append((lo, hi, ytop, ybot, categories, color))
            y = lambda v: ybot-(v-lo)/(hi-lo)*(ybot-ytop)
            ticks = list(enumerate(categories)) if categories else [(v, f'{v:g}') for v in ([lo + i*tick_step for i in range(round((hi-lo)/tick_step)+1)] if tick_step else [lo, hi])]
            for val, text in ticks:
                canvas.create_text(left-7, y(val), text=text, anchor='e')
            previous = None
            undefined_spans = []
            for a, b, ph, origin in segments:
                points = [a, b]
                if label == 'Actuator Pos. [%]':
                    active_start = load_schedule[0][min(bisect.bisect_right(timeline.starts, origin)-1,
                                                       len(timeline.phases)-1)]
                    if active_start is not None:
                        cycle_duration = (2 * timeline_parameters.load_open_seconds
                                          + timeline_parameters.load_hold_seconds
                                          + timeline_parameters.load_pause_seconds)
                        first_cycle = math.floor((a-active_start)/cycle_duration)
                        last_cycle = math.ceil((b-active_start)/cycle_duration)
                        for cycle_index in range(first_cycle, last_cycle + 1):
                            base = active_start + cycle_index * cycle_duration
                            points.extend(base + offset for offset in (
                                0, timeline_parameters.load_open_seconds,
                                timeline_parameters.load_open_seconds + timeline_parameters.load_hold_seconds,
                                2 * timeline_parameters.load_open_seconds + timeline_parameters.load_hold_seconds,
                                cycle_duration))
                        points = sorted({max(a, min(b, point)) for point in points})
                for point_a, point_b in zip(points, points[1:]):
                    va, vb = value(ph, point_a, origin), value(ph, point_b, origin)
                    if va is None or vb is None:
                        if k == 1 and ph.undefined_humidity_label:
                            if undefined_spans and abs(undefined_spans[-1][1]-point_a) < 1e-6:
                                undefined_spans[-1] = (undefined_spans[-1][0], point_b)
                            else:
                                undefined_spans.append((point_a, point_b))
                        previous = None
                        continue
                    if previous is not None:
                        canvas.create_line(x(point_a), y(previous), x(point_a), y(va), fill=color, width=2)
                    canvas.create_line(x(point_a), y(va), x(point_b), y(vb), fill=color, width=2)
                    previous = vb
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

    def update(silent=False):
        if selected.get() not in GENERATORS:
            messagebox.showinfo('Test Unavailable', 'No cycle generator is registered for this Test ID.')
            return False
        try:
            p = read_parameters()
            phases, samples = generate(p)
        except (ValueError, TypeError, OverflowError) as exc:
            if not silent:
                messagebox.showerror('Check Test Parameters', str(exc))
            return False
        if phases != state.get('phases'):
            markers.clear()
        state.update(p=p, phases=phases, samples=samples, timeline=Timeline(phases, p),
                     tracker_step=p.tracker_step_seconds)
        step_feedback.set(f'Active Tracker Step: {p.tracker_step_seconds:g} s. 0 = continuous. Endpoints remain selectable.')
        state['recipes'][p.test_id] = p
        count = p.cycles if p.test_id in {'ENV_026', 'ENV_004'} else (max(ph.cycle for ph in phases) if p.test_id == 'ENV_012' else p.number_of_cycles)
        message = f'Total Duration: {samples[-1].time_s/3600:.3f} h · {len(samples)} Data Points · {count} Cycle(s)'
        if p.test_id not in {'ENV_026', 'ENV_012'}:
            per_cycle = samples[-1].time_s/count/60
            duration_label = 'Average Cycle Duration' if p.test_id == 'ENV_004' and p.cycles > 1 and not p.ramps else 'Cycle Duration'
            message += f'\n{duration_label}: {per_cycle:.3f} min · {samples[-1].time_s/86400:.3f} days total'
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

    def build_form(p):
        for widget in form.winfo_children(): widget.destroy()
        values.clear()
        global_values = state['global_values']
        tracker_step.set(str(global_values['tracker_step_seconds']))
        state['tracker_step'] = global_values['tracker_step_seconds']
        x_unit.set(global_values['x_axis_unit'])
        state['axis_unit'] = global_values['x_axis_unit']
        unit_factor = TIME_UNITS[global_values['x_axis_unit']][0]
        x_start.set(format(global_values['x_axis_start_seconds']/unit_factor,'.15g'))
        x_step.set('' if global_values['x_axis_step_seconds'] is None else format(global_values['x_axis_step_seconds']/unit_factor,'.15g'))
        x_end.set('' if global_values['x_axis_end_seconds'] is None else format(global_values['x_axis_end_seconds']/unit_factor,'.15g'))
        update_unit_labels()
        visible = state['configuration']['tests'][p.test_id]['visible']
        for widget in (unit_label,unit_choice,x_start_widget_label,x_start_entry,x_step_widget_label,x_step_entry,
                       x_end_widget_label,x_end_entry,axis_apply_button,tracker_label,tracker_entry,tracker_apply):
            widget.pack_forget()
        unit_label.pack(side='left',padx=6);unit_choice.pack(side='left',padx=6)
        x_start_widget_label.pack(side='left');x_start_entry.pack(side='left',padx=6)
        x_end_widget_label.pack(side='left');x_end_entry.pack(side='left',padx=6)
        x_step_widget_label.pack(side='left');x_step_entry.pack(side='left',padx=6)
        axis_apply_button.pack(side='left')
        tracker_label.pack(side='left');tracker_entry.pack(side='left',padx=6);tracker_apply.pack(side='left')
        row = 0
        for key in list(visible) + ACTUATOR_VISIBLE_KEYS:
            if key in SPECIAL_CONTROLS: continue
            value = global_values[key] if key in ACTUATOR_VISIBLE_KEYS else getattr(p,key)
            ttk.Label(form,text=parameter_label(key),wraplength=250).grid(row=row,column=0,sticky='w',padx=(0,8),pady=5)
            var = tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value='' if value is None else str(value))
            values[key] = var
            if isinstance(value,bool): widget = ttk.Checkbutton(form,variable=var)
            elif key.endswith('mode'):
                widget = ttk.Combobox(form,textvariable=var,state='readonly',width=12,
                    values=['1.1','1.2','2.1','2.2','2.3','2.4','3.1','3.2','3.3','3.4'])
            elif key == 'x_axis_unit': widget = ttk.Combobox(form,textvariable=var,state='readonly',values=list(TIME_UNITS))
            else: widget = ttk.Entry(form,textvariable=var,width=14)
            widget.grid(row=row,column=1,pady=5,sticky='ew')
            if isinstance(widget, ttk.Entry):
                widget.bind('<KeyRelease>', lambda event: update(silent=True))
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
                export_csv(path, state['samples'])
                messagebox.showinfo('Export', f'CSV saved:\n{path}')
            except OSError as exc:
                messagebox.showerror('Export Failed', str(exc))

    def save_config():
        if not update(): return
        try:
            state['configuration'] = save_current_test(state['config_path'],state['p'],
                                                       global_values=state['global_values'])
            messagebox.showinfo('Save Current Test', selected.get()+' saved to '+str(state['config_path'])+'\nOther test sections were not changed.')
        except (ValueError,TypeError,OSError) as exc:
            messagebox.showerror('Save Failed',str(exc))

    def load_config():
        path = filedialog.askopenfilename(initialfile=state['config_path'].name,filetypes=[('Overall Configuration','*.json')])
        if not path: return
        try:
            config = load_configuration(path)
            recipes = {tid:parameters_from_configuration(config,tid) for tid in GENERATORS}
            state.update(configuration=config,recipes=recipes,config_path=Path(path),
                         global_values={**config['global']['actuator'], **config['global']['chart']})
            state.pop('form_test',None)
            switch_test()
        except (ValueError,TypeError,OSError) as exc:
            messagebox.showerror('Load Configuration Failed',str(exc))

    buttons = ttk.Frame(outer)
    buttons.pack(fill='x', pady=(10, 0))
    for label, command in [('Generate Profile', update), ('Save CSV', export),
                           ('Save Current Test', save_config), ('Load Configuration', load_config)]:
        ttk.Button(buttons, text=label, command=command).pack(side='left', padx=(0, 8))
    selector.bind('<<ComboboxSelected>>', switch_test)
    chart_choice.bind('<<ComboboxSelected>>', plot)
    unit_choice.bind('<<ComboboxSelected>>', change_axis_unit)
    preview_spin.configure(command=plot)
    preview_spin.bind('<Return>', plot)
    preview_spin.bind('<FocusOut>', plot)
    canvas.bind('<Configure>', plot)
    canvas.bind('<Motion>', track_mouse)
    canvas.bind('<Leave>', hide_tracker)
    canvas.bind('<Button-1>', place_marker)
    tracker_entry.bind('<Return>', apply_tracker_step)
    tracker_entry.bind('<FocusOut>', apply_tracker_step)
    tracker_entry.bind('<KeyRelease>', lambda event: update(silent=True))
    x_step_entry.bind('<Return>', plot)
    x_end_entry.bind('<Return>', plot)
    x_start_entry.bind('<Return>', plot)
    x_start_entry.bind('<KeyRelease>', plot)
    x_step_entry.bind('<KeyRelease>', plot)
    x_end_entry.bind('<KeyRelease>', plot)
    root.after(100, switch_test)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', metavar='CSV', help='Export the default profile without opening the GUI')
    parser.add_argument('--test', choices=list(GENERATORS), default=None, help='Test ID (overrides JSON Test ID)')
    parser.add_argument('--config', type=Path, help='Overall JSON configuration for GUI or CLI')
    args = parser.parse_args()
    config_path = args.config or DEFAULT_CONFIG_PATH
    if args.example:
        config = load_configuration(config_path) if config_path.exists() else default_configuration()
        p = parameters_from_configuration(config,args.test or 'ENV_026')
        _,samples = generate(p)
        export_csv(args.example,samples)
        print(f'{args.example}: {len(samples)} Points, {samples[-1].time_s/3600:g} Hours')
    else:
        launch_gui(config_path)


if __name__ == '__main__':
    main()
