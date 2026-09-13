"""DLMS measurement times, kept separate from HA's state-arrival timestamps."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_frame_datetime(frame: bytes) -> dict | None:
    """Read the optional 12-byte DataNotification date-time without guessing fields.

    DLMS deviation is local-to-UTC minutes (UTC = local + deviation).
    0x8000 means unspecified. Hundredths 0xff means unspecified precision.
    Invalid, doubtful, different-base or invalid-status clocks are not trusted.
    """
    if not frame or frame[0] != 0x7E:
        return None
    llc = frame.find(b"\xe6\xe7\x00", 1, 30)
    if llc < 0 or frame[llc + 3:llc + 4] != b"\x0f":
        return None
    pos = llc + 8  # LLC + DataNotification tag + four-byte invoke-id
    if frame[pos:pos + 2] != b"\x09\x0c":
        return None
    data = frame[pos + 2:pos + 14]
    if len(data) != 12 or data[11] & 0x0F:
        return None
    if data[8] != 0xFF and data[8] > 99:
        return None
    try:
        wall = datetime(
            int.from_bytes(data[:2], "big"), data[2], data[3],
            data[5], data[6], data[7], 0 if data[8] == 0xFF else data[8] * 10000,
        )
    except ValueError:
        return None
    deviation = int.from_bytes(data[9:11], "big", signed=True)
    if deviation != -32768 and not -720 <= deviation <= 720:
        return None
    return {"local_time": wall.isoformat(),
            "deviation_minutes": None if deviation == -32768 else deviation}


def resolve_frame_datetime(
    timestamp: dict | None, time_zone: str, received_at: datetime,
) -> dict | None:
    """Resolve a fresh meter time to UTC, using HA's zone when offset is absent.

    Reject clocks more than five minutes old or five seconds in the future.
    For an unspecified offset, validate local times by round-tripping through
    UTC. At the autumn DST fold only the candidate near receipt time is valid.
    This deliberately cannot reconstruct delayed/offline historical uploads.
    """
    if not timestamp or received_at.tzinfo is None:
        return None
    try:
        wall = datetime.fromisoformat(timestamp["local_time"])
        if wall.tzinfo is not None:
            return None
        deviation = timestamp["deviation_minutes"]
        if deviation is not None:
            if not isinstance(deviation, int) or not -720 <= deviation <= 720:
                return None
            candidates = [(wall + timedelta(minutes=deviation)).replace(tzinfo=timezone.utc)]
            source = "dlms_deviation"
        else:
            zone = ZoneInfo(time_zone)
            candidates = []
            for fold in (0, 1):
                candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                if candidate.astimezone(zone).replace(tzinfo=None) == wall and candidate not in candidates:
                    candidates.append(candidate)
            source = "home_assistant_time_zone"
        plausible = [candidate for candidate in candidates
                     if -5 <= (received_at - candidate).total_seconds() <= 300]
        if len(plausible) != 1:
            return None
        return {"measurement_timestamp": plausible[0].isoformat(),
                "measurement_timestamp_source": source}
    except (KeyError, TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        return None
