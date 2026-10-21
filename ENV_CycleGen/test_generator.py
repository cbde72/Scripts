import csv
import tempfile
import unittest
from pathlib import Path
from env_cycle_generator import Parameters, generate, export_csv, Timeline, snap_tracker_time, MeasurementMarkers, default_parameters, gradient_targets, axis_ticks, convert_axis_input, TIME_UNITS


class GeneratorTests(unittest.TestCase):
    def test_default_and_event(self):
        _, s = generate(Parameters())
        self.assertEqual((len(s), s[-1].time_s), (2881, 48*3600))
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
            self.assertEqual(rows[2820]['operation_mode'], '3.1')
            self.assertEqual(float(rows[0]['humidity_percent_RH']), 60)
            self.assertEqual(float(rows[-1]['time_s']), 172800)

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
            self.assertTrue(any(row['humidity_percent_RH']=='' for row in rows))

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
        with self.assertRaises(ValueError): generate(p)

    def test_packaged_html_descriptions_and_browser_routes(self):
        from env_cycle_generator import TEST_NAMES, description_path, open_description
        from unittest.mock import patch
        for tid in TEST_NAMES:
            with self.subTest(test_id=tid):
                path=description_path(tid)
                content=path.read_text(encoding='utf-8')
                self.assertIn('<html lang="en">',content)
                self.assertIn(tid,content)
                self.assertIn('Acceptance Criteria',content)
                self.assertIn('Generator Interpretation',content)
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





class OverallConfigurationTests(unittest.TestCase):
    def test_hidden_value_still_controls_generated_data(self):
        from env_cycle_generator import default_configuration,parameters_from_configuration
        config=default_configuration()
        entry=config['tests']['ENV_026']
        entry['unvisible']['sample_seconds']=entry['visible'].pop('sample_seconds')
        entry['unvisible']['sample_seconds']=721
        p=parameters_from_configuration(config,'ENV_026')
        self.assertEqual(p.sample_seconds,721)
        _,samples=generate(p)
        self.assertEqual(samples[1].time_s,721)
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
