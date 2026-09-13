import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('history_export', Path(__file__).resolve().parents[1]/'tools/export_measurement_history.py')
export=importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def row(stamp, value=100):
    return {'entity_id':'sensor.example_power', 'last_updated':'2025-07-08T10:30:10+00:00',
            'state':str(value), 'attributes':{'measurement_timestamp':stamp, 'unit_of_measurement':'W'}}


class HistoryExportTests(unittest.TestCase):
    def test_original_times_survive_equal_values_and_status_duplicates(self):
        a=row('2025-07-08T12:30:02+02:00'); b=row('2025-07-08T12:30:04+02:00')
        points,skipped=export.measurement_points([[b,a,a]])
        self.assertEqual(points,[('2025-07-08T10:30:02+00:00',100.0),('2025-07-08T10:30:04+00:00',100.0)])
        self.assertEqual(skipped,0)

    def test_missing_or_invalid_time_never_falls_back_to_arrival(self):
        samples=[row(None),row('bad'),row('2025-07-08T12:30:02'),row('2025-07-08T10:30:02+00:00','nan')]
        points,skipped=export.measurement_points([samples])
        self.assertEqual(points,[]); self.assertEqual(skipped,4)

    def test_conflicting_values_are_reported(self):
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            export.measurement_points([[row('2025-07-08T10:30:02+00:00'),row('2025-07-08T10:30:02+00:00',101)]])

    def test_fractional_seconds_sort_chronologically(self):
        points,_=export.measurement_points([[row('2025-07-08T10:30:02.250000+00:00'),row('2025-07-08T10:30:02+00:00')]])
        self.assertEqual(points[0][0],'2025-07-08T10:30:02+00:00')

    def test_multiple_sensors_are_rejected(self):
        with self.assertRaises(ValueError): export.measurement_points([[],[]])
