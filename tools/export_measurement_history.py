#!/usr/bin/env python3
"""Convert full-attribute HA history for one power sensor into measured-time CSV."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
import sys


def measurement_points(history):
    """Keep explicit measurement times; reject conflicts and collapse status repeats."""
    if not isinstance(history, list) or len(history) != 1 or not isinstance(history[0], list):
        raise ValueError('Expected HA history for exactly one sensor: [[states...]]')
    points = {}
    skipped = 0
    entity_ids = {row.get('entity_id') for row in history[0]
                  if isinstance(row, dict) and row.get('entity_id')}
    if len(entity_ids) > 1:
        raise ValueError('History mixes multiple entities')
    for row in history[0]:
        try:
            attrs = row.get('attributes') or {}
            timestamp = datetime.fromisoformat(attrs['measurement_timestamp'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Measurement time must include a UTC offset')
            if attrs.get('unit_of_measurement') != 'W':
                raise ValueError('Expected watts')
            value = float(row['state'])
            if not math.isfinite(value):
                raise ValueError('Nonfinite power')
            timestamp = timestamp.astimezone(timezone.utc).isoformat()
        except (KeyError, ValueError, TypeError, AttributeError):
            skipped += 1
            continue
        if timestamp in points and points[timestamp] != value:
            raise ValueError('Conflicting power values at measurement timestamp ' + timestamp)
        points[timestamp] = value
    return sorted(points.items(), key=lambda item:datetime.fromisoformat(item[0])), skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('history_json', help='Full HA REST history response with all state attributes')
    args = parser.parse_args()
    with open(args.history_json, encoding='utf-8') as handle:
        points, skipped = measurement_points(json.load(handle))
    if not points:
        raise SystemExit('No timestamped power measurements found; request full attributes and a post-upgrade interval.')
    writer = csv.writer(sys.stdout)
    writer.writerow(('measurement_timestamp_utc', 'power_W'))
    writer.writerows(points)
    print(f'Exported {len(points)} measurements; skipped {skipped} un-timestamped/invalid records.', file=sys.stderr)


if __name__ == '__main__':
    main()
