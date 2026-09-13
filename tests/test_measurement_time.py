from datetime import datetime, timedelta, timezone
import unittest

from test_dlms_cosem import dlms, envelope_chunk, frame, octets, uint32
from custom_components.tibber_pulse_mqtt.parsers.dlms_datetime import (
    parse_frame_datetime, resolve_frame_datetime,
)


def timestamp_bytes(wall, deviation=-32768, status=0, hundredths=255):
    return (wall.year.to_bytes(2, 'big') + bytes((wall.month, wall.day, wall.isoweekday(),
            wall.hour, wall.minute, wall.second, hundredths)) +
            deviation.to_bytes(2, 'big', signed=True) + bytes((status,)))


def stamped_frame(stamp, value=1200):
    original = frame(b'\x02\x01' + uint32(value))
    return original[:17] + octets(stamp) + original[18:]


class MeasurementTimeTests(unittest.TestCase):
    def setUp(self):
        self.wall = datetime(2025, 7, 8, 12, 30, 0)
        self.received = datetime(2025, 7, 8, 10, 30, 1, tzinfo=timezone.utc)

    def test_summer_unspecified_offset_uses_configured_timezone(self):
        metadata = parse_frame_datetime(stamped_frame(timestamp_bytes(self.wall)))
        result = resolve_frame_datetime(metadata, 'Europe/Oslo', self.received)
        self.assertEqual(result['measurement_timestamp'], '2025-07-08T10:30:00+00:00')
        self.assertEqual(result['measurement_timestamp_source'], 'home_assistant_time_zone')

    def test_winter_timezone(self):
        wall = self.wall.replace(month=1)
        result = resolve_frame_datetime(parse_frame_datetime(stamped_frame(timestamp_bytes(wall))),
                                        'Europe/Oslo', self.received.replace(month=1, hour=11))
        self.assertEqual(result['measurement_timestamp'], '2025-01-08T11:30:00+00:00')

    def test_explicit_deviation_takes_precedence_and_keeps_hundredths(self):
        metadata = parse_frame_datetime(stamped_frame(timestamp_bytes(self.wall, -120, 128, 25)))
        result = resolve_frame_datetime(metadata, 'America/New_York', self.received)
        self.assertEqual(result['measurement_timestamp'], '2025-07-08T10:30:00.250000+00:00')
        self.assertEqual(result['measurement_timestamp_source'], 'dlms_deviation')

    def test_positive_deviation(self):
        metadata = parse_frame_datetime(stamped_frame(timestamp_bytes(self.wall, 300)))
        received = self.received.replace(hour=17)
        self.assertEqual(resolve_frame_datetime(metadata, 'UTC', received)['measurement_timestamp'],
                         '2025-07-08T17:30:00+00:00')

    def test_all_five_equal_values_retain_distinct_two_second_times(self):
        frames = [stamped_frame(timestamp_bytes(self.wall + timedelta(seconds=n)), 1200)
                  for n in range(0, 10, 2)]
        parsed = dlms.parse_dlms_frames_from_envelope(b'\x08\x01' + b''.join(map(envelope_chunk, frames)))
        resolved = [resolve_frame_datetime(p['_measurement_time'], 'Europe/Oslo',
                    self.received + timedelta(seconds=8)) for p in parsed]
        times = [datetime.fromisoformat(p['measurement_timestamp']) for p in resolved]
        self.assertEqual(len(parsed), 5)
        self.assertEqual([p['1-0:1.7.0'] for p in parsed], [1200] * 5)
        self.assertEqual([(b-a).total_seconds() for a,b in zip(times,times[1:])], [2] * 4)

    def test_missing_timestamp_preserves_existing_decoder_contract(self):
        result = dlms.parse_dlms(frame(b'\x02\x01' + uint32(1200)))
        self.assertEqual(result['1-0:1.7.0'], 1200)
        self.assertNotIn('_measurement_time', result)

    def test_invalid_clock_flags_do_not_block_power(self):
        for status in (1, 2, 4, 8, 255):
            with self.subTest(status=status):
                result = dlms.parse_dlms(stamped_frame(timestamp_bytes(self.wall, status=status)))
                self.assertEqual(result['1-0:1.7.0'], 1200)
                self.assertNotIn('_measurement_time', result)

    def test_invalid_calendar_precision_and_deviation(self):
        original = timestamp_bytes(self.wall)
        for index,value in ((0,255),(2,255),(2,254),(3,32),(5,24),(6,60),(7,60),(8,100)):
            data = bytearray(original); data[index] = value
            with self.subTest(index=index):
                self.assertIsNone(parse_frame_datetime(stamped_frame(bytes(data))))
        self.assertIsNone(parse_frame_datetime(stamped_frame(timestamp_bytes(self.wall, 721))))

    def test_all_truncations_of_header_are_safe(self):
        data = stamped_frame(timestamp_bytes(self.wall))
        for end in range(31):
            self.assertIsNone(parse_frame_datetime(data[:end]))

    def test_nonexistent_dst_time_rejected(self):
        wall = datetime(2025, 3, 30, 2, 30)
        metadata = parse_frame_datetime(stamped_frame(timestamp_bytes(wall)))
        self.assertIsNone(resolve_frame_datetime(metadata, 'Europe/Oslo',
            datetime(2025, 3, 30, 1, 30, 1, tzinfo=timezone.utc)))

    def test_autumn_dst_both_occurrences(self):
        wall = datetime(2025, 10, 26, 2, 30)
        metadata = parse_frame_datetime(stamped_frame(timestamp_bytes(wall)))
        for hour in (0,1):
            received = datetime(2025, 10, 26, hour, 30, 1, tzinfo=timezone.utc)
            result = resolve_frame_datetime(metadata, 'Europe/Oslo', received)
            self.assertEqual(datetime.fromisoformat(result['measurement_timestamp']),
                             received - timedelta(seconds=1))

    def test_stale_future_or_wrong_zone_are_not_guessed(self):
        metadata = parse_frame_datetime(stamped_frame(timestamp_bytes(self.wall)))
        for received,zone in ((self.received + timedelta(minutes=6),'Europe/Oslo'),
                              (self.received - timedelta(seconds=10),'Europe/Oslo'),
                              (self.received,'UTC'),(self.received,'Invalid/Zone')):
            self.assertIsNone(resolve_frame_datetime(metadata, zone, received))

    def test_bad_metadata_and_naive_receipt_are_rejected(self):
        for data in (None, {}, {'local_time':'bad'}, {'local_time':3,'deviation_minutes':None}):
            self.assertIsNone(resolve_frame_datetime(data, 'UTC', self.received))
        self.assertIsNone(resolve_frame_datetime({'local_time':self.wall.isoformat(),
                          'deviation_minutes':None}, 'UTC', self.wall))
