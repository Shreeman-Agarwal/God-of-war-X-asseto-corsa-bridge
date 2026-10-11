import json
import math
import unittest

from tools.assetto_corsa_sender import (
    MAX_LINE_BYTES,
    SPageFileGraphic,
    SPageFilePhysics,
    TelemetrySample,
    encode_message,
    sample_to_payload,
    telemetry_from_pages,
)


class SenderProtocolTests(unittest.TestCase):
    def setUp(self):
        self.sample = TelemetrySample(
            physics_packet=102,
            ac_status=2,
            speed_kmh=128.5,
            rpm=6120,
            gear_raw=3,
            throttle=0.75,
            brake=0.0,
            steering=-0.12,
            heading=1.25,
            position=(14.0, 0.2, -31.5),
        )

    def test_live_payload_matches_mod_schema(self):
        payload = sample_to_payload(self.sample, now=12.0, last_packet_at=11.8)
        self.assertEqual(payload["protocol_version"], 1)
        self.assertEqual(payload["sender_status"], "receiving")
        self.assertTrue(payload["connected"])
        self.assertEqual(payload["ac_position"], [14.0, 0.2, -31.5])
        self.assertEqual(payload["gear_raw"], 3)
        self.assertEqual(payload["physics_packet"], 102)

    def test_paused_session_is_not_reported_as_live(self):
        sample = TelemetrySample(**{**self.sample.__dict__, "ac_status": 3})
        payload = sample_to_payload(sample, now=12.0, last_packet_at=11.8)
        self.assertEqual(payload["sender_status"], "waiting_for_ac")
        self.assertFalse(payload["connected"])

    def test_stale_physics_page_is_reported(self):
        payload = sample_to_payload(self.sample, now=14.0, last_packet_at=12.0)
        self.assertEqual(payload["sender_status"], "stale_ac_memory")
        self.assertFalse(payload["connected"])

    def test_frame_is_compact_utf8_ndjson(self):
        frame = encode_message(sample_to_payload(self.sample, 12.0, 11.8))
        self.assertTrue(frame.endswith(b"\n"))
        self.assertNotIn(b"\n", frame[:-1])
        self.assertEqual(json.loads(frame), sample_to_payload(self.sample, 12.0, 11.8))
        self.assertLessEqual(len(frame), MAX_LINE_BYTES)

    def test_invalid_numeric_values_are_rejected(self):
        for value in (math.nan, math.inf, -1.0):
            bad = TelemetrySample(**{**self.sample.__dict__, "speed_kmh": value})
            with self.subTest(value=value), self.assertRaises(ValueError):
                sample_to_payload(bad, 12.0, 11.8)

    def test_out_of_range_position_is_rejected(self):
        bad = TelemetrySample(**{**self.sample.__dict__, "position": (100_001, 0, 0)})
        with self.assertRaises(ValueError):
            sample_to_payload(bad, 12.0, 11.8)

    def test_invalid_position_shape_and_non_integer_gear_are_rejected(self):
        short_position = TelemetrySample(**{**self.sample.__dict__, "position": (1.0, 2.0)})
        bad_gear = TelemetrySample(**{**self.sample.__dict__, "gear_raw": 2.5})
        with self.assertRaises(ValueError):
            sample_to_payload(short_position, 12.0, 11.8)
        with self.assertRaises(ValueError):
            sample_to_payload(bad_gear, 12.0, 11.8)

    def test_page_extraction_uses_documented_fields_and_gear_offset(self):
        physics = SPageFilePhysics()
        physics.packetId = 51
        physics.speedKmh = 92.25
        physics.rpms = 4200
        physics.gear = 3
        physics.gas = 0.4
        physics.brake = 0.2
        physics.steerAngle = -0.07
        physics.heading = 0.5
        graphic = SPageFileGraphic()
        graphic.status = 2
        graphic.carCoordinates[:] = (2.0, 1.5, -8.0)
        sample = telemetry_from_pages(physics, graphic)
        self.assertEqual(sample.physics_packet, 51)
        self.assertEqual(sample.gear_raw, 2)
        self.assertEqual(sample.position, (2.0, 1.5, -8.0))
        payload = sample_to_payload(sample, now=5.0, last_packet_at=5.0)
        self.assertEqual(payload["gear_raw"], 2)
        self.assertEqual(payload["ac_status"], 2)


if __name__ == "__main__":
    unittest.main()
