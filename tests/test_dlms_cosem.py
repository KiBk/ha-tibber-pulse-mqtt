from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PARSERS = ROOT / "custom_components" / "tibber_pulse_mqtt" / "parsers"


def load_parser_modules():
    package_names = (
        "custom_components",
        "custom_components.tibber_pulse_mqtt",
        "custom_components.tibber_pulse_mqtt.parsers",
    )
    for name in package_names:
        module = sys.modules.setdefault(name, types.ModuleType(name))
        module.__path__ = [str(ROOT.joinpath(*name.split('.')))]

    time_name = "custom_components.tibber_pulse_mqtt.parsers.dlms_datetime"
    time_spec = importlib.util.spec_from_file_location(time_name, PARSERS / "dlms_datetime.py")
    time_module = importlib.util.module_from_spec(time_spec)
    sys.modules[time_name] = time_module
    time_spec.loader.exec_module(time_module)

    envelope_name = "custom_components.tibber_pulse_mqtt.parsers.pulse_envelope"
    envelope_spec = importlib.util.spec_from_file_location(
        envelope_name, PARSERS / "pulse_envelope.py"
    )
    envelope = importlib.util.module_from_spec(envelope_spec)
    sys.modules[envelope_name] = envelope
    envelope_spec.loader.exec_module(envelope)

    dlms_name = "custom_components.tibber_pulse_mqtt.parsers.dlms_cosem"
    dlms_spec = importlib.util.spec_from_file_location(dlms_name, PARSERS / "dlms_cosem.py")
    dlms = importlib.util.module_from_spec(dlms_spec)
    sys.modules[dlms_name] = dlms
    dlms_spec.loader.exec_module(dlms)
    return dlms


dlms = load_parser_modules()


def octets(value: bytes) -> bytes:
    return bytes((0x09, len(value))) + value


def uint32(value: int) -> bytes:
    return b"\x06" + value.to_bytes(4, "big")


def varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def frame(container: bytes) -> bytes:
    header = bytes.fromhex("7ea000010201100000e6e7000f4000000000")
    return header + container + b"\x00\x00\x7e"


def positional_frame(members: list[bytes]) -> bytes:
    return frame(bytes((0x02, len(members))) + b"".join(members))


def envelope_chunk(hdlc_frame: bytes) -> bytes:
    nested = b"\x12\x03HAN" + b"\x1a" + varint(len(hdlc_frame)) + hdlc_frame
    return b"\x12" + varint(len(nested)) + nested


class DlmsCosemTests(unittest.TestCase):
    def test_existing_aidon_array_format_still_decodes(self):
        obis = bytes((1, 0, 1, 7, 0, 255))
        item = b"\x02\x03" + octets(obis) + uint32(1234) + b"\x02\x02\x0f\x00\x16\x1b"
        result = dlms.parse_dlms(frame(b"\x01\x01" + item))

        self.assertEqual(result["1-0:1.7.0"], 1234)
        self.assertEqual(result["_units"]["1-0:1.7.0"], "W")

    def test_existing_three_phase_kfm_list_still_decodes(self):
        members = [
            octets(b"KFM_001"),
            octets(b"6970631400000000"),
            octets(b"MA304H3E"),
            *(uint32(value) for value in range(100, 110)),
        ]
        result = dlms.parse_dlms(positional_frame(members))

        self.assertEqual(result["1-0:1.7.0"], 100)
        self.assertAlmostEqual(result["1-0:31.7.0"], 0.104)
        self.assertAlmostEqual(result["1-0:32.7.0"], 10.7)

    def test_single_phase_kfm_list_two_decodes(self):
        members = [
            octets(b"KFM_001"),
            octets(b"6970631400000000"),
            octets(b"MA105H2E"),
            uint32(2345),
            uint32(0),
            uint32(12),
            uint32(0),
            uint32(6789),
            uint32(2312),
        ]
        result = dlms.parse_dlms(positional_frame(members))

        self.assertEqual(result["1-0:1.7.0"], 2345)
        self.assertAlmostEqual(result["1-0:31.7.0"], 6.789)
        self.assertAlmostEqual(result["1-0:32.7.0"], 231.2)

    def test_single_phase_kfm_list_three_decodes_energy(self):
        members = [
            octets(b"KFM_001"),
            octets(b"6970631400000000"),
            octets(b"MA105H2E"),
            uint32(2345),
            uint32(0),
            uint32(12),
            uint32(0),
            uint32(6789),
            uint32(2312),
            octets(bytes.fromhex("07ea081e07102a00ff800000")),
            uint32(5_000_000),
            uint32(1000),
            uint32(2000),
            uint32(3000),
        ]
        result = dlms.parse_dlms(positional_frame(members))

        self.assertEqual(result["1-0:1.8.0"], 5_000_000)
        self.assertEqual(result["1-0:2.8.0"], 1000)
        self.assertEqual(result["_units"]["1-0:1.8.0"], "Wh")

    def test_repeated_envelope_decodes_every_supported_frame(self):
        short = positional_frame([uint32(1500)])
        single_phase = positional_frame(
            [
                octets(b"KFM_001"),
                octets(b"6970631400000000"),
                octets(b"MA105H2E"),
                uint32(2345),
                uint32(0),
                uint32(12),
                uint32(0),
                uint32(6789),
                uint32(2312),
            ]
        )
        payload = b"\x08\x01" + envelope_chunk(short) * 4 + envelope_chunk(single_phase)

        results = dlms.parse_dlms_frames_from_envelope(payload)

        self.assertEqual(len(results), 5)
        self.assertEqual([result["1-0:1.7.0"] for result in results], [1500] * 4 + [2345])


if __name__ == "__main__":
    unittest.main()
