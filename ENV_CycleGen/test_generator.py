import bisect
import csv
import json
import tempfile
import time
import unittest
from pathlib import Path
from env_cycle_generator import Parameters, Phase, generate, generate_phases, export_csv, export_cycle1_csv, export_breakpoints, temperature_breakpoints, step_breakpoints, Timeline, snap_tracker_time, MeasurementMarkers, default_parameters, gradient_targets, axis_ticks, convert_axis_input, count_sample_points


class GeneratorTests(unittest.TestCase):
    def test_default_and_event(self):
        p = Parameters()
        phases, s = generate(p)
        timeline = Timeline(phases, p)
        sample_times = {x.time_s for x in s}
        self.assertEqual((s[0].time_s, s[-1].time_s), (0, 48*3600))
        self.assertEqual(len(s), count_sample_points(timeline, p))
        self.assertTrue({i*60 for i in range(2881)} <= sample_times)
        self.assertTrue(set(timeline.actuator_events) <= sample_times)
        self.assertTrue(all(x.temperature_c == 80 and x.humidity_rh == 60 for x in s))
        self.assertTrue(all(x.operation_mode == '3.2' for x in s if x.time_s < 47*3600))
        self.assertTrue(all(x.operation_mode == '3.1' for x in s if x.time_s >= 47*3600))

    def test_off_grid_event(self):
        _, s = generate(Parameters(sample_seconds=721))
        self.assertEqual(next(x.operation_mode for x in s if x.time_s == 47*3600), '3.1')
        self.assertTrue(all(a.time_s < b.time_s for a, b in zip(s, s[1:])))
        self.assertEqual(s[-1].time_s, 48*3600)

    def test_ramps_and_repeats(self):
        _, s = generate(Parameters(ramps=True, cycles=2, humidity_rh=60))
        self.assertAlmostEqual(s[-1].time_s/3600, 99.8)
        self.assertEqual((s[0].temperature_c, s[-1].temperature_c), (23, 23))
        self.assertEqual({x.cycle for x in s}, {1, 2})
        self.assertTrue(all(x.humidity_rh == 60 for x in s))
        self.assertAlmostEqual(next(x.time_s for x in s if x.phase == 'Normal Operation'), 3420)

    def test_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'test.csv'
            export_csv(target, generate(Parameters())[1])
            with target.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
            by_time = {float(row['time_s']): row for row in rows}
            self.assertEqual(by_time[47*3600]['operation_mode'], '3.1')
            self.assertEqual(float(rows[0]['humidity_percent_RH']), 60)
            self.assertEqual(float(rows[-1]['time_s']), 172800)

    @staticmethod
    def _cycle1_xy(rows, curve):
        return [(float(row[f'{curve}_x']),
                 None if row[f'{curve}_y'] == '' else float(row[f'{curve}_y']))
                for row in rows if row[f'{curve}_x'] != '']

    @staticmethod
    def _xy_interpolate(points, time_s):
        times = [point[0] for point in points]
        index = bisect.bisect_right(times, time_s) - 1
        if index < 0:
            return points[0][1]
        if index >= len(points) - 1:
            return points[-1][1]
        left, right = points[index], points[index + 1]
        if left[0] == right[0]:
            return right[1]
        if left[1] is None or right[1] is None:
            return None
        fraction = (time_s - left[0]) / (right[0] - left[0])
        return left[1] + fraction * (right[1] - left[1])

    @staticmethod
    def _xy_step(points, time_s):
        times = [point[0] for point in points]
        index = bisect.bisect_right(times, time_s) - 1
        return points[max(index, 0)][1]

    def test_cycle1_excel_export_xy_pairs(self):
        p = default_parameters('ENV_013')
        p.number_of_cycles = 3
        _, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'cycle1.csv'
            info = export_cycle1_csv(target, timeline, p)
            with target.open(encoding='utf-8-sig') as stream:
                reader = csv.DictReader(stream, delimiter=';')
                rows = list(reader)
        self.assertEqual(reader.fieldnames, [
            'Temperatur_x', 'Temperatur_y', 'Feuchte_x', 'Feuchte_y',
            'Operation_x', 'Operation_y', 'Spannung_x', 'Spannung_y',
            'Aktuator_x', 'Aktuator_y', 'Legende_Operation_code',
            'Legende_Operation_modus', 'Legende_x_einheit'])
        self.assertEqual(info, {'rows': len(rows), 'cycles_total': 3,
                                'cycle_duration_s': 5400, 'time_unit': 's'})
        self.assertEqual(self._cycle1_xy(rows, 'Temperatur'),
                         [(0, 23), (945, -40), (1845, -40), (3645, 80),
                          (4545, 80), (5400, 23)])
        self.assertEqual(self._cycle1_xy(rows, 'Feuchte'), [(0, 60), (5400, 60)])
        self.assertEqual(self._cycle1_xy(rows, 'Operation'),
                         [(0, 0), (1545, 0), (1545, 1),
                          (4545, 1), (4545, 0), (5400, 0)])
        self.assertEqual(self._cycle1_xy(rows, 'Spannung'),
                         [(0, 48), (5400, 48)])
        actuator = self._cycle1_xy(rows, 'Aktuator')
        self.assertEqual(actuator[0], (0, 0))
        self.assertEqual(actuator[-1], (5400, 0))
        self.assertTrue(any(value and value > 0 for _, value in actuator))
        self.assertGreater(len(actuator), 10)

    def test_cycle1_export_reconstructs_generator_curves(self):
        for test_id in ('ENV_002', 'ENV_004', 'ENV_013', 'ENV_026'):
            with self.subTest(test_id=test_id):
                p = default_parameters(test_id)
                if test_id == 'ENV_013':
                    p.number_of_cycles = 2
                phases, timeline = generate_phases(p)
                cycle1 = [i for i, phase in enumerate(phases) if phase.cycle == 1]
                cycle_end = (timeline.starts[cycle1[-1]]
                             + phases[cycle1[-1]].duration_s)
                mode_categories = sorted({phase.mode for phase in phases})
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory)/'cycle1.csv'
                    export_cycle1_csv(target, timeline, p)
                    with target.open(encoding='utf-8-sig') as stream:
                        rows = list(csv.DictReader(stream, delimiter=';'))
                curves = {name: self._cycle1_xy(rows, name) for name in (
                    'Temperatur', 'Feuchte', 'Operation', 'Spannung', 'Aktuator')}
                for index in range(1, 200):
                    time_s = cycle_end * index / 200
                    sample = timeline.at(time_s)
                    self.assertAlmostEqual(
                        self._xy_interpolate(curves['Temperatur'], time_s),
                        sample.temperature_c, places=6)
                    humidity = self._xy_step(curves['Feuchte'], time_s)
                    if sample.humidity_rh is None:
                        self.assertIsNone(humidity)
                    else:
                        self.assertAlmostEqual(humidity, sample.humidity_rh, places=6)
                    self.assertEqual(
                        self._xy_step(curves['Operation'], time_s),
                        mode_categories.index(sample.operation_mode))
                    voltage = self._xy_step(curves['Spannung'], time_s)
                    if sample.voltage_v is None:
                        self.assertIsNone(voltage)
                    else:
                        self.assertAlmostEqual(voltage, sample.voltage_v, places=6)
                    self.assertAlmostEqual(
                        self._xy_interpolate(curves['Aktuator'], time_s),
                        sample.load_percent, places=6)

    def test_cycle1_export_undefined_humidity(self):
        p = default_parameters('ENV_002')
        p.number_of_cycles = 2
        p.frost_cycles = 1
        _, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'cycle1.csv'
            export_cycle1_csv(target, timeline, p)
            with target.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
        humidity = self._cycle1_xy(rows, 'Feuchte')
        self.assertTrue(any(value is None for _, value in humidity))
        self.assertEqual(humidity[-1][0], 24*3600)
        self.assertIn('Feuchte_x', rows[0])
        self.assertIn('Feuchte_y', rows[0])
        self.assertNotIn('humidity_note', rows[0])

    def test_cycle1_export_single_cycle(self):
        p = default_parameters('ENV_026')
        _, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'cycle1.csv'
            info = export_cycle1_csv(target, timeline, p)
            with target.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
        self.assertEqual(info['cycles_total'], 1)
        self.assertEqual(info['cycle_duration_s'], 48*3600)
        self.assertEqual(self._cycle1_xy(rows, 'Temperatur')[-1][0], 48*3600)
        self.assertTrue(any(value and value > 0
                            for _, value in self._cycle1_xy(rows, 'Aktuator')))

    def test_tracker_boundaries(self):
        phases, _ = generate(Parameters(sample_seconds=721))
        timeline = Timeline(phases)
        self.assertEqual(timeline.at(47*3600-0.001).operation_mode, '3.2')
        self.assertEqual(timeline.at(47*3600).operation_mode, '3.1')
        self.assertEqual(timeline.at(-100).time_s, 0)
        self.assertEqual(timeline.at(1e9).time_s, 48*3600)
        self.assertEqual(timeline.at(123.45).humidity_rh,60)

    def test_tracker_ramp_and_repeated_cycle(self):
        phases, _ = generate(Parameters(ramps=True, cycles=2, humidity_rh=60))
        timeline = Timeline(phases)
        self.assertAlmostEqual(timeline.at(123.45).temperature_c, 23+123.45/60)
        self.assertEqual(timeline.at(123.45).humidity_rh, 60)
        self.assertEqual(timeline.at(49.9*3600).cycle, 2)
        self.assertAlmostEqual(timeline.at(timeline.duration_s).temperature_c, 23)
        with self.assertRaises(ValueError):
            timeline.at(float('nan'))

    def test_env013_reference_profile(self):
        p = Parameters(test_id='ENV_013')
        phases, samples = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.duration_s, 870*90*60)
        self.assertEqual(len(phases), 870*6)
        self.assertEqual((samples[0].temperature_c, samples[-1].temperature_c), (23, 23))
        expected = [(0, 23, '3.1'), (945, -40, '3.1'), (1545, -40, '3.2'),
                    (1845, -40, '3.2'), (3645, 80, '3.2'), (4545, 80, '3.1')]
        for t, temperature, mode in expected:
            with self.subTest(time=t):
                self.assertEqual(timeline.at(t).temperature_c, temperature)
                self.assertEqual(timeline.at(t).operation_mode, mode)
        self.assertEqual(timeline.at(5400).cycle, 2)
        self.assertEqual(samples[-1].cycle, 870)
        self.assertEqual(samples[0].humidity_rh,60)
        self.assertTrue(all(a.time_s < b.time_s for a, b in zip(samples, samples[1:])))

    def test_env013_event_and_ramp_independent_of_time_step(self):
        phases, samples = generate(Parameters(test_id='ENV_013', number_of_cycles=1, sample_seconds=721))
        event = next(s for s in samples if s.time_s == 1545)
        self.assertEqual(event.operation_mode, '3.2')
        self.assertEqual(Timeline(phases).at(1545-0.01).operation_mode, '3.1')
        self.assertAlmostEqual(Timeline(phases).at(300).temperature_c, 3)
        self.assertAlmostEqual(Timeline(phases).at(2145).temperature_c, -20)
        self.assertEqual(samples[-1].time_s, 5400)

    def test_env013_adjustable_parameters(self):
        p = Parameters(test_id='ENV_013', number_of_cycles=2,
                       temperature_change_rate=3, humidity_rh=60)
        phases, samples = generate(p)
        self.assertEqual(samples[-1].time_s, 2*110*60)
        self.assertTrue(all(s.humidity_rh == 60 for s in samples))
        p = Parameters(test_id='ENV_013', number_of_cycles=1, hot_standby_minutes=5)
        phases, _ = generate(p)
        self.assertEqual(Timeline(phases).at(4245).operation_mode, '3.1')
        self.assertEqual(Timeline(phases).duration_s, 5400)

    def test_env013_validation_and_zero_length_parts(self):
        for changes in [{'number_of_cycles': 0}, {'number_of_cycles': 1.5},
                        {'temperature_change_rate': 0}, {'minimum_temperature_c': 100},
                        {'room_temperature_c': 90}, {'cold_active_minutes': 21},
                        {'hot_standby_minutes': -1}, {'hot_dwell_minutes': 0}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                generate(Parameters(test_id='ENV_013', **changes))
        phases, _ = generate(Parameters(test_id='ENV_013', number_of_cycles=1,
                                       room_temperature_c=-40, cold_active_minutes=0,
                                       hot_standby_minutes=15))
        self.assertTrue(all(ph.duration_s > 0 for ph in phases))
        self.assertEqual(Timeline(phases).duration_s, 5400)

    def test_tracker_time_grid(self):
        self.assertEqual(snap_tracker_time(121, 60, 0, 6000), 120)
        self.assertEqual(snap_tracker_time(149, 60, 0, 6000), 120)
        self.assertEqual(snap_tracker_time(150, 60, 0, 6000), 180)
        self.assertEqual(snap_tracker_time(121.25, 0, 0, 6000), 121.25)
        self.assertEqual(snap_tracker_time(0.375, 0.25, 0, 6000), 0.5)
        # Global grid, visible endpoints, and a range shorter than the grid.
        self.assertEqual(snap_tracker_time(6030, 60, 6000, 12000), 6060)
        self.assertEqual(snap_tracker_time(99, 60, 0, 100), 100)
        self.assertEqual(snap_tracker_time(140, 1000, 101, 151), 151)
        for step in [-1, float('nan'), float('inf')]:
            with self.subTest(step=step), self.assertRaises(ValueError):
                snap_tracker_time(100, step, 0, 1000)

    def test_measurement_markers(self):
        markers = MeasurementMarkers()
        self.assertFalse(markers.set_end(100))
        markers.set_start(180)
        markers.set_end(480)
        self.assertEqual(markers.distance_minutes, 5)
        markers.set_end(60)
        self.assertEqual(markers.distance_minutes, 2)
        markers.set_end(180)
        self.assertEqual(markers.distance_minutes, 0)
        markers.set_start(600)
        self.assertIsNone(markers.end_s)
        self.assertIsNone(markers.distance_minutes)
        markers.clear()
        self.assertIsNone(markers.start_s)

    def test_env014_reference_knots_and_modes(self):
        p = default_parameters('ENV_014')
        phases, samples = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.duration_s, 30*480*60)
        for minutes, temperature in [(0,20), (60,-40), (150,-40), (210,20),
                                     (300,80), (410,80), (480,20)]:
            self.assertEqual(timeline.at(minutes*60).temperature_c, temperature)
        for minutes, mode in [(119.9,'3.1'), (120,'3.2'), (121,'3.1'),
                              (209.9,'3.1'), (210,'3.2'), (409.9,'3.2'), (410,'3.1')]:
            self.assertEqual(timeline.at(minutes*60).operation_mode, mode)
        self.assertEqual(timeline.at(480*60).cycle, 2)
        self.assertEqual(samples[-1].cycle, 30)

    def test_env014_cold_check_and_changed_segments(self):
        p = default_parameters('ENV_014')
        p.number_of_cycles = 1
        p.cold_check_start_minutes = 70
        p.cold_check_duration_minutes = 2
        p.warming_to_room_minutes = 80
        phases, _ = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.at(70*60).operation_mode, '3.2')
        self.assertEqual(timeline.at(72*60).operation_mode, '3.1')
        self.assertEqual(timeline.at(230*60).operation_mode, '3.2')
        self.assertEqual(timeline.duration_s, 500*60)
        p.cold_check_duration_minutes = 0
        phases, _ = generate(p)
        self.assertEqual(Timeline(phases).at(70*60).operation_mode, '3.1')

    def test_env015_reference_steps_and_checks(self):
        p = default_parameters('ENV_015')
        points = gradient_targets(p)
        self.assertEqual(len(points), 49)
        self.assertEqual(points[0], 25)
        self.assertEqual(points[-1], 25)
        self.assertEqual(points.count(-40), 1)
        self.assertEqual(points.count(80), 1)
        phases, samples = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.duration_s, 1710*60)
        self.assertEqual(timeline.at(25*60).phase, 'Function Check - Umax')
        self.assertEqual(timeline.at(25*60).operation_mode, '3.2')
        self.assertEqual(timeline.at(26*60).operation_mode, '3.1')
        self.assertEqual(timeline.at(29*60).phase, 'Function Check - Umin')
        self.assertEqual(timeline.at(30*60).operation_mode, '3.1')
        self.assertEqual(timeline.at(32*60).temperature_c, 23)
        self.assertEqual(timeline.at(35*60).temperature_c, 20)
        self.assertEqual(min(s.temperature_c for s in samples), -40)
        self.assertEqual(max(s.temperature_c for s in samples), 80)

    def test_env015_initial_dwell_and_non_grid_limits(self):
        p = default_parameters('ENV_015')
        phases, _ = generate(p)
        self.assertEqual(Timeline(phases).duration_s, 1710*60)
        self.assertEqual(phases[0].name, 'Gradient Dwell - Stand-by')
        p.minimum_temperature_c = -42
        p.maximum_temperature_c = 83
        points = gradient_targets(p)
        self.assertEqual(min(points), -42)
        self.assertEqual(max(points), 83)
        self.assertTrue(all(0 < abs(b-a) <= 5 for a,b in zip(points,points[1:])))
        p.number_of_cycles = 2
        phases, samples = generate(p)
        self.assertEqual(samples[-1].cycle, 2)
        self.assertTrue(all(a.time_s < b.time_s for a,b in zip(samples,samples[1:])))

    def test_env014_env015_validation(self):
        for tid, changes in [('ENV_014',{'cold_check_start_minutes': 59}),
                             ('ENV_014',{'cold_check_duration_minutes': 100}),
                             ('ENV_014',{'cooling_to_room_minutes': 0}),
                             ('ENV_015',{'gradient_step_c': 0}),
                             ('ENV_015',{'gradient_umax_minutes': -1}),
                             ('ENV_015',{'gradient_umin_minutes': 0})]:
            p = default_parameters(tid)
            for key,value in changes.items():
                setattr(p,key,value)
            with self.subTest(test_id=tid,changes=changes), self.assertRaises(ValueError):
                generate(p)

    def test_env012_final_hour_and_alternation(self):
        p = default_parameters('ENV_012')
        phases, samples = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.duration_s, 504*3600)
        for hour, mode in [(0,'2.1'),(46.99,'2.1'),(47,'3.2'),(48,'2.1'),
                           (479,'3.2'),(480,'2.1'),(502.99,'2.1'),(503,'3.2')]:
            self.assertEqual(timeline.at(hour*3600).operation_mode, mode)
        self.assertTrue(all(s.temperature_c == 65 and s.humidity_rh == 93 for s in samples))
        self.assertEqual(phases[-1].duration_s, 3600)

    def test_env002_frost_sequence_and_humidity(self):
        p = default_parameters('ENV_002')
        phases, samples = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.duration_s, 240*3600)
        frost = [ph for ph in phases if ph.name == 'Frost Dwell']
        self.assertEqual([ph.cycle for ph in frost], [1,2,3,4,5])
        self.assertTrue(all(ph.temperature_start_c == -10 and ph.humidity_rh is None for ph in frost))
        self.assertEqual(timeline.at(90*60).operation_mode, '3.2')
        self.assertEqual(timeline.at(91*60).operation_mode, '3.1')
        self.assertEqual(timeline.at(330*60).humidity_rh, 80)
        self.assertEqual(timeline.at(0).humidity_rh, 93)
        self.assertEqual(timeline.at(5*24*3600).cycle, 6)
        self.assertEqual(min(s.temperature_c for s in samples if s.cycle >= 6),25)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'humidity.csv'
            export_csv(target,samples)
            with target.open(encoding='utf-8-sig') as stream:
                rows=list(csv.DictReader(stream,delimiter=';'))
            self.assertTrue(any(row['humidity_percent_RH']=='n.def' for row in rows))

    def test_env003_profile_and_checks(self):
        p = default_parameters('ENV_003')
        phases, samples = generate(p)
        timeline = Timeline(phases)
        self.assertEqual(timeline.duration_s,25*3600)
        self.assertEqual(timeline.at(45*60).humidity_rh,97.5)
        self.assertEqual(timeline.at(165*60).operation_mode,'3.2')
        self.assertEqual(timeline.at(166*60).operation_mode,'3.1')
        self.assertEqual(timeline.at(209*60).operation_mode,'3.1')
        self.assertEqual(timeline.at(210*60).humidity_rh,80)
        self.assertEqual(timeline.at(300*60).cycle,2)
        self.assertEqual(len([ph for ph in phases if ph.mode=='3.2']),5)
        p.room_temperature_c=20
        generate(p)

    def test_x_axis_range_and_tick_grid(self):
        ticks,stride=axis_ticks(600,60)
        self.assertEqual(ticks,list(range(0,601,60)))
        self.assertEqual(stride,1)
        ticks,stride=axis_ticks(5000000,1)
        self.assertLessEqual(len(ticks),41)
        self.assertEqual(ticks[0],0)
        self.assertEqual(axis_ticks(600)[0],[0,120,240,360,480,600])
        for end,step in [(0,60),(600,0),(600,-1),(float('nan'),60)]:
            with self.subTest(end=end,step=step),self.assertRaises(ValueError):
                axis_ticks(end,step)
        p=default_parameters('ENV_002')
        p.x_axis_end_seconds=3600
        p.x_axis_step_seconds=600
        self.assertEqual(generate(p)[1][-1].time_s,240*3600)

    def test_climate_validation(self):
        for tid,changes in [('ENV_012',{'functional_hours':701}),
                            ('ENV_002',{'frost_cycles':11}),
                            ('ENV_002',{'climate_check_minutes':241}),
                            ('ENV_003',{'rising_humidity_rh':101}),
                            ('ENV_003',{'climate_check_minutes':46}),
                            ('ENV_012',{'x_axis_end_seconds':-1})]:
            p=default_parameters(tid)
            for key,value in changes.items(): setattr(p,key,value)
            with self.subTest(test_id=tid,changes=changes),self.assertRaises(ValueError):
                generate(p)

    def test_axis_unit_conversion(self):
        self.assertEqual(convert_axis_input('3600','Seconds','Hours'),'1')
        self.assertEqual(convert_axis_input('600','Seconds','Minutes'),'10')
        self.assertEqual(convert_axis_input('1,5','Hours','Minutes'),'90')
        self.assertEqual(convert_axis_input('','Seconds','Minutes'),'')
        original=37.5
        value=convert_axis_input(str(original),'Seconds','Minutes')
        value=convert_axis_input(value,'Minutes','Hours')
        value=convert_axis_input(value,'Hours','Seconds')
        self.assertAlmostEqual(float(value),original)
        for text in ['0','-1','nan','inf','invalid']:
            with self.subTest(text=text),self.assertRaises(ValueError):
                convert_axis_input(text,'Seconds','Minutes')
        p=default_parameters('ENV_003')
        p.x_axis_unit='Hours'
        p.x_axis_end_seconds=3600
        self.assertEqual(generate(p)[1][-1].time_s,25*3600)
        p.x_axis_unit='Days'
        self.assertEqual(generate(p)[1][-1].time_s,25*3600)
        p.x_axis_unit='Weeks'
        with self.assertRaises(ValueError): generate(p)
        self.assertEqual(convert_axis_input('2','Days','Hours'),'48')
        self.assertEqual(convert_axis_input('36','Hours','Days'),'1.5')

    def test_packaged_html_descriptions_and_browser_routes(self):
        from env_cycle_generator import TEST_NAMES, description_path, open_description
        from unittest.mock import patch
        for tid in TEST_NAMES:
            with self.subTest(test_id=tid):
                path=description_path(tid)
                content=path.read_text(encoding='utf-8')
                self.assertIn('<html lang="de">',content)
                self.assertIn(tid,content)
                self.assertIn('Prüfprofil',content)
                self.assertIn('Unklarheiten / Annahmen',content)
                with patch('webbrowser.open_new_tab',return_value=True) as browser:
                    open_description(tid)
                    browser.assert_called_once_with(path.as_uri())
        with self.assertRaises(ValueError): description_path('../invalid')

    def test_env004_five_points_and_voltage_export(self):
        p=default_parameters('ENV_004')
        phases,samples=generate(p)
        checks=[ph for ph in phases if ph.name.startswith('Function Check')]
        self.assertEqual([(ph.temperature_start_c,ph.voltage_v) for ph in checks],
                         [(23,48),(-40,52),(-40,36),(80,52),(80,36)])
        self.assertTrue(all(ph.duration_s==600 and ph.mode=='3.2' for ph in checks))
        pre=[ph for ph in phases if ph.name.startswith('Preconditioning')]
        self.assertEqual(len(pre),3)
        self.assertTrue(all(ph.duration_s==1800 and ph.mode=='3.1' for ph in pre))
        timeline=Timeline(phases)
        self.assertEqual(timeline.duration_s,323*60)
        for minute,voltage in [(30,48),(133,52),(143,36),(303,52),(313,36)]:
            self.assertEqual(timeline.at(minute*60).voltage_v,voltage)
            self.assertEqual(timeline.at(minute*60).operation_mode,'3.2')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'points.csv'
            export_csv(target,samples)
            with target.open(encoding='utf-8-sig') as stream:
                rows=list(csv.DictReader(stream,delimiter=';'))
            self.assertIn('voltage_V',rows[0])
            self.assertEqual(float(rows[-1]['voltage_V']),36)

    def test_env004_off_voltage_for_mode_1x(self):
        p=default_parameters('ENV_004')
        p.standby_mode='1.1'
        p.off_voltage_v=5
        phases,_=generate(p)
        self.assertTrue(all(ph.voltage_v==5 for ph in phases if ph.mode=='1.1'))
        self.assertEqual([(ph.temperature_start_c,ph.voltage_v) for ph in phases if ph.name.startswith('Function Check')],
                         [(23,48),(-40,52),(-40,36),(80,52),(80,36)])

    def test_env004_recovery_repetition_and_validation(self):
        p=default_parameters('ENV_004')
        p.ramps=True
        phases,samples=generate(p)
        self.assertEqual(samples[-1].time_s,380*60)
        self.assertEqual(samples[-1].temperature_c,23)
        p.ramps=False
        p.cycles=2
        phases,samples=generate(p)
        self.assertEqual(samples[-1].time_s,703*60)
        self.assertTrue(all(a.temperature_end_c==b.temperature_start_c for a,b in zip(phases,phases[1:])))
        p.standby_mode='2.1'
        phases,_=generate(p)
        self.assertTrue(all(ph.mode=='2.1' for ph in phases if ph.name.startswith('Preconditioning')))
        for key,value in [('minimum_voltage_v',53),('nominal_voltage_v',0),('activation_minutes',0),('precondition_minutes',-1)]:
            q=default_parameters('ENV_004');setattr(q,key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):generate(q)

    def test_validation(self):
        for p in [Parameters(sample_seconds=0), Parameters(active_hours=-1),
                  Parameters(humidity_rh=101), Parameters(temperature_c=float('nan')),
                  Parameters(cycles=0), Parameters(sample_seconds=0.001)]:
            with self.subTest(parameters=p), self.assertRaises(ValueError):
                generate(p)





class TimeUnitAndLegendTests(unittest.TestCase):
    def _export(self, unit):
        p = default_parameters('ENV_026')
        phases, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'c1.csv'
            info = export_cycle1_csv(target, timeline, p, time_unit=unit)
            with target.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
        return info, rows

    def test_cycle1_time_units(self):
        _, base = self._export('s')
        for unit, factor in (('min', 60), ('h', 3600), ('d', 86400), ('Days', 86400)):
            info, rows = self._export(unit)
            self.assertEqual(len(rows), len(base))
            for a, b in zip(base, rows):
                for column in ('Temperatur_x', 'Aktuator_x', 'Operation_x'):
                    if a[column]:
                        self.assertAlmostEqual(float(a[column])/factor, float(b[column]), places=9)
                    else:
                        self.assertEqual(b[column], '')
            self.assertEqual(rows[0]['Legende_x_einheit'], info['time_unit'])
        with self.assertRaises(ValueError):
            self._export('weeks')

    def test_cycle1_operation_legend(self):
        _, rows = self._export('s')
        legend = [(r['Legende_Operation_code'], r['Legende_Operation_modus'])
                  for r in rows if r['Legende_Operation_code']]
        p = default_parameters('ENV_026')
        phases, _ = generate_phases(p)
        modes = sorted({ph.mode for ph in phases})
        self.assertEqual(legend, [(str(i), m) for i, m in enumerate(modes)])

    def test_breakpoints_days(self):
        p = default_parameters('ENV_026')
        phases, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            seconds = Path(directory)/'s.json'
            days = Path(directory)/'d.json'
            export_breakpoints(seconds, phases, timeline, p, time_unit='s', fmt='json')
            info = export_breakpoints(days, phases, timeline, p, time_unit='d', fmt='json')
            a = json.loads(seconds.read_text(encoding='utf-8'))
            b = json.loads(days.read_text(encoding='utf-8'))
        self.assertEqual(info['time_unit'], 'd')
        for x, y in zip(a['curves']['Temperatur'], b['curves']['Temperatur']):
            self.assertAlmostEqual(x['t_s']/86400, y['t_s'], places=9)


class BreakpointExportTests(unittest.TestCase):
    @staticmethod
    def _interpolate(points, time_s):
        times = [point['time_s'] for point in points]
        index = bisect.bisect_right(times, time_s) - 1
        if index < 0:
            return points[0]['value']
        if index >= len(points) - 1:
            return points[-1]['value']
        left, right = points[index], points[index + 1]
        if left['time_s'] == right['time_s']:
            return right['value']
        fraction = (time_s - left['time_s']) / (right['time_s'] - left['time_s'])
        return left['value'] + fraction * (right['value'] - left['value'])

    @staticmethod
    def _step_value(entries, time_s):
        times = [entry['time_s'] for entry in entries]
        index = bisect.bisect_right(times, time_s) - 1
        if index < 0:
            index = 0
        return entries[index]['value']

    def test_reference_breakpoint_counts(self):
        p = default_parameters('ENV_004')
        phases, timeline = generate_phases(p)
        points = temperature_breakpoints(phases, timeline)
        self.assertEqual(
            [(round(point['time_s'], 9), round(point['value'], 9), point['kind'])
             for point in points],
            [(0, 23, 'hold'), (2400, 23, 'ramp'), (6180, -40, 'hold'),
             (9180, -40, 'ramp'), (16380, 80, 'hold'), (19380, 80, '')])
        self.assertEqual([round(point['slope_per_min'], 9) for point in points[:5]],
                         [0, -1, 0, 1, 0])

        p = default_parameters('ENV_013')
        p.number_of_cycles = 2
        phases, timeline = generate_phases(p)
        points = temperature_breakpoints(phases, timeline)
        self.assertEqual(len(points), 10)
        self.assertEqual((points[0]['time_s'], points[0]['value']), (0, 23))
        self.assertEqual((points[5]['time_s'], points[5]['value']), (6345, -40))
        self.assertEqual((points[-1]['time_s'], points[-1]['value']), (10800, 23))

        p = default_parameters('ENV_014')
        p.number_of_cycles = 1
        phases, timeline = generate_phases(p)
        points = temperature_breakpoints(phases, timeline)
        self.assertEqual(len(points), 7)
        self.assertEqual((points[3]['time_s'], points[3]['value']), (12600, 20))
        self.assertAlmostEqual(points[2]['slope_per_min'], 1.0)
        self.assertAlmostEqual(points[3]['slope_per_min'], 2.0 / 3.0)

        p = default_parameters('ENV_015')
        phases, timeline = generate_phases(p)
        self.assertEqual(len(temperature_breakpoints(phases, timeline)), 98)

    def test_temperature_reconstruction(self):
        for test_id in ('ENV_002', 'ENV_003', 'ENV_004', 'ENV_012',
                        'ENV_013', 'ENV_014', 'ENV_015', 'ENV_026'):
            with self.subTest(test_id=test_id):
                p = default_parameters(test_id)
                if test_id == 'ENV_013':
                    p.number_of_cycles = 2
                phases, timeline = generate_phases(p)
                points = temperature_breakpoints(phases, timeline)
                maximum_error = 0.0
                for index in range(2000):
                    time_s = timeline.duration_s * (index + 0.5) / 2000
                    expected = timeline.at(time_s).temperature_c
                    actual = self._interpolate(points, time_s)
                    maximum_error = max(maximum_error, abs(expected - actual))
                self.assertLess(maximum_error, 1e-9)

    def test_step_reconstruction(self):
        for test_id in ('ENV_002', 'ENV_004', 'ENV_014', 'ENV_015'):
            with self.subTest(test_id=test_id):
                p = default_parameters(test_id)
                phases, timeline = generate_phases(p)
                curves = {
                    'humidity': step_breakpoints(phases, timeline, 'humidity'),
                    'operation': step_breakpoints(phases, timeline, 'operation'),
                    'voltage': step_breakpoints(phases, timeline, 'voltage'),
                }
                times = {0.0, timeline.duration_s}
                for entries in curves.values():
                    times.update(entry['time_s'] for entry in entries)
                ordered = sorted(times)
                times.update((a + b) / 2.0 for a, b in zip(ordered, ordered[1:]))
                for kind, entries in curves.items():
                    for time_s in sorted(times):
                        sample = timeline.at(time_s)
                        actual = self._step_value(entries, time_s)
                        if kind == 'humidity':
                            expected = sample.humidity_rh
                        elif kind == 'operation':
                            expected = 1 if sample.operation_mode == '3.2' else 0
                        else:
                            expected = sample.voltage_v
                        if expected is None:
                            self.assertIsNone(actual)
                        else:
                            self.assertAlmostEqual(actual, expected, delta=1e-9)
                for entry in curves['operation']:
                    self.assertTrue(entry['note'].startswith('modus='))

    def test_synthetic_temperature_jump(self):
        phases = [Phase(1, 'A', 10, 20, 20, 60, '3.1'),
                  Phase(1, 'B', 10, 80, 80, 60, '3.2')]
        timeline = Timeline(phases)
        points = temperature_breakpoints(phases, timeline)
        self.assertEqual([point['time_s'] for point in points], [0, 10, 10, 20])
        self.assertEqual([point['value'] for point in points], [20, 20, 80, 80])
        self.assertEqual(points[1]['kind'], 'jump')

    def test_cycle_selection_and_repeat(self):
        p = default_parameters('ENV_013')
        p.number_of_cycles = 2
        phases, timeline = generate_phases(p)
        points = temperature_breakpoints(phases, timeline, cycle=2)
        self.assertEqual((points[0]['time_s'], points[0]['value']), (0, 23))
        self.assertEqual((points[-1]['time_s'], points[-1]['value']), (5400, 23))
        self.assertEqual(len(points), 6)
        absolute = temperature_breakpoints(phases, timeline, cycle=2, relative=False)
        self.assertEqual((absolute[0]['time_s'], absolute[-1]['time_s']),
                         (5400, 10800))
        with self.assertRaisesRegex(ValueError, 'Available cycles'):
            temperature_breakpoints(phases, timeline, cycle=99)

        different = [Phase(1, 'A', 10, 20, 20, 60, '3.1'),
                     Phase(2, 'B', 20, 20, 20, 60, '3.1')]
        different_timeline = Timeline(different)
        with self.assertRaises(ValueError):
            temperature_breakpoints(different, different_timeline,
                                    cycle='first_plus_repeat')

    def test_first_plus_repeat_large_profile_runtime(self):
        p = default_parameters('ENV_013')
        phases, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'repeat.csv'
            started = time.perf_counter()
            info = export_breakpoints(target, phases, timeline, p,
                                      cycle='first_plus_repeat')
            elapsed = time.perf_counter() - started
        self.assertEqual(info['counts']['Temperatur'], 6)
        self.assertEqual(info['repeat']['cycles_total'], 870)
        self.assertEqual(info['repeat']['remaining'], 869)
        self.assertLess(elapsed, 1.0)

    def test_breakpoint_csv_and_json_roundtrip(self):
        p = default_parameters('ENV_013')
        p.number_of_cycles = 2
        phases, timeline = generate_phases(p)
        with tempfile.TemporaryDirectory() as directory:
            csv_target = Path(directory) / 'breakpoints.csv'
            info = export_breakpoints(csv_target, phases, timeline, p,
                                      include_actuator_points=True)
            self.assertEqual(csv_target.read_bytes()[:3], b'\xef\xbb\xbf')
            with csv_target.open(encoding='utf-8-sig') as stream:
                reader = csv.DictReader(stream, delimiter=';')
                rows = list(reader)
            self.assertEqual(reader.fieldnames,
                             ['kurve', 'punkt', 'zyklus', 't_s', 'wert', 'einheit',
                              'bis_naechster', 'steigung_pro_min', 'hinweis'])
            by_curve = {}
            for row in rows:
                by_curve.setdefault(row['kurve'], []).append(row)
            self.assertEqual(len(by_curve['Temperatur']), info['counts']['Temperatur'])
            self.assertEqual(len(by_curve['Temperatur']), 10)
            self.assertEqual(float(by_curve['Temperatur'][0]['t_s']), 0)
            self.assertEqual(float(by_curve['Temperatur'][-1]['t_s']), 10800)
            self.assertEqual(by_curve['Operation'][0]['wert'], '0')
            self.assertIn('modus=3.1', by_curve['Operation'][0]['hinweis'])
            self.assertIn('Aktuator', info['counts'])
            self.assertGreater(info['counts']['Aktuator'], 0)

            json_target = Path(directory) / 'breakpoints.json'
            json_info = export_breakpoints(json_target, phases, timeline, p, fmt='json')
            payload = json.loads(json_target.read_text(encoding='utf-8'))
        self.assertEqual(payload['counts']['Temperatur'], json_info['counts']['Temperatur'])
        self.assertIn('Temperatur', payload['curves'])
        self.assertEqual(len(payload['curves']['Temperatur']), 10)

    def test_undefined_humidity_and_threshold(self):
        p = default_parameters('ENV_002')
        phases, timeline = generate_phases(p)
        entries = step_breakpoints(phases, timeline, 'humidity')
        undefined = [entry for entry in entries if entry['value'] is None]
        self.assertTrue(undefined)
        self.assertTrue(any(entry['note'] == 'n.def.' for entry in undefined))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'undefined.csv'
            export_breakpoints(target, phases, timeline, p)
            with target.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
        undefined_rows = [row for row in rows
                          if row['kurve'] == 'Feuchte' and row['wert'] == '']
        self.assertTrue(undefined_rows)
        self.assertTrue(any(row['hinweis'] == 'n.def.' for row in undefined_rows))

        cooling = [Phase(1, 'Cooling', 100, 80, 20, 60, '3.1',
                         humidity_at_threshold=90)]
        cooling_timeline = Timeline(cooling)
        cooling_entries = step_breakpoints(cooling, cooling_timeline, 'humidity')
        self.assertEqual((cooling_entries[0]['time_s'],
                          cooling_entries[0]['value'],
                          cooling_entries[0]['note']), (0, 90, 'at_threshold'))
        self.assertEqual((cooling_entries[1]['time_s'],
                          cooling_entries[1]['value']), (0, 60))

        heating = [Phase(1, 'Heating', 100, 20, 80, 60, '3.1',
                         humidity_at_threshold=90)]
        heating_timeline = Timeline(heating)
        heating_entries = step_breakpoints(heating, heating_timeline, 'humidity')
        self.assertEqual((heating_entries[-1]['time_s'],
                          heating_entries[-1]['value'],
                          heating_entries[-1]['note']), (100, 90, 'at_threshold'))

    def test_whole_seconds_rounding(self):
        p = default_parameters('ENV_026')
        phases = [Phase(1, 'A', 10.4, 20, 20, 60, '3.1'),
                  Phase(1, 'B', 10.4, 20, 20, 60, '3.2')]
        timeline = Timeline(phases, p)
        original = temperature_breakpoints(phases, timeline)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'rounded.csv'
            info = export_breakpoints(target, phases, timeline, p,
                                      whole_seconds=True)
            with target.open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream, delimiter=';'))
        self.assertTrue(any('rounded' in note for note in info['notes']))
        temperature_rows = [row for row in rows if row['kurve'] == 'Temperatur']
        times = [float(row['t_s']) for row in temperature_rows]
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        for row, point in zip(temperature_rows, original):
            self.assertLessEqual(abs(float(row['t_s']) - point['time_s']), 1.0)


class OverallConfigurationTests(unittest.TestCase):
    def test_hidden_value_still_controls_generated_data(self):
        from env_cycle_generator import default_configuration,parameters_from_configuration
        config=default_configuration()
        entry=config['global']['csv']
        entry['unvisible']['sample_seconds']=entry['visible'].pop('sample_seconds')
        entry['unvisible']['sample_seconds']=721
        p=parameters_from_configuration(config,'ENV_026')
        self.assertEqual(p.sample_seconds,721)
        _,samples=generate(p)
        self.assertIn(721,{s.time_s for s in samples})
        self.assertTrue(any(s.time_s==47*3600 for s in samples))

    def test_save_only_selected_test_preserves_others_and_visibility(self):
        import copy,json
        from env_cycle_generator import default_configuration,parameters_from_configuration,save_current_test,load_configuration
        config=default_configuration()
        entry=config['tests']['ENV_026']
        entry['unvisible']['active_hours']=entry['visible'].pop('active_hours')
        config['tests']['ENV_003']['operator_note']='preserve metadata'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'all.json';path.write_text(json.dumps(config))
            p=parameters_from_configuration(config,'ENV_026');p.active_hours=40
            # Another test has been edited on disk since GUI loading.
            config['tests']['ENV_014']['visible']['number_of_cycles']=20
            path.write_text(json.dumps(config))
            before=copy.deepcopy(config)
            saved=save_current_test(path,p)
            for tid in saved['tests']:
                if tid!='ENV_026':self.assertEqual(saved['tests'][tid],before['tests'][tid])
            self.assertEqual(saved['tests']['ENV_026']['unvisible']['active_hours'],40)
            self.assertNotIn('active_hours',saved['tests']['ENV_026']['visible'])
            self.assertEqual(load_configuration(path),saved)

    def test_reject_duplicate_or_removed_keys_and_fixed_initial_dwell(self):
        from env_cycle_generator import default_configuration,parameters_from_configuration
        config=default_configuration()
        self.assertNotIn('gradient_initial_dwell',config['tests']['ENV_015']['visible'])
        self.assertNotIn('gradient_initial_dwell',config['tests']['ENV_015']['unvisible'])
        config['tests']['ENV_015']['unvisible']['gradient_initial_dwell']=False
        with self.assertRaises(ValueError):parameters_from_configuration(config,'ENV_015')
        config=default_configuration()
        config['tests']['ENV_026']['unvisible']['sample_seconds']=20
        with self.assertRaises(ValueError):parameters_from_configuration(config,'ENV_026')

    def test_ua_is_used_in_mode_31_not_un(self):
        p=default_parameters('ENV_004');p.ua_voltage_v=47
        phases,_=generate(p)
        self.assertTrue(all(ph.voltage_v==47 for ph in phases if ph.mode=='3.1'))
        self.assertEqual([(ph.temperature_start_c,ph.voltage_v) for ph in phases if ph.name.startswith('Function Check')],
                         [(23,48),(-40,52),(-40,36),(80,52),(80,36)])

    def test_maximize_native_call(self):
        from unittest.mock import MagicMock
        from env_cycle_generator import maximize_window
        window=MagicMock();maximize_window(window)
        window.state.assert_called_once_with('zoomed')


if __name__ == '__main__':
    unittest.main()
