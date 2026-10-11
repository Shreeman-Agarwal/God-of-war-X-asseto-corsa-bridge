from __future__ import annotations

import argparse
import ctypes
import json
import math
import mmap
import socket
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_POSITION_ABS = 100_000.0
MAX_LINE_BYTES = 4096


class SPageFilePhysics(ctypes.Structure):
    """Assetto Corsa 1 shared-memory physics page, #pragma pack(4) layout."""

    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int),
        ("gas", ctypes.c_float),
        ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float),
        ("gear", ctypes.c_int),
        ("rpms", ctypes.c_int),
        ("steerAngle", ctypes.c_float),
        ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3),
        ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4),
        ("wheelLoad", ctypes.c_float * 4),
        ("wheelsPressure", ctypes.c_float * 4),
        ("wheelAngularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4),
        ("tyreDirtyLevel", ctypes.c_float * 4),
        ("tyreCoreTemperature", ctypes.c_float * 4),
        ("camberRAD", ctypes.c_float * 4),
        ("suspensionTravel", ctypes.c_float * 4),
        ("drs", ctypes.c_float),
        ("tc", ctypes.c_float),
        ("heading", ctypes.c_float),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("cgHeight", ctypes.c_float),
        ("carDamage", ctypes.c_float * 5),
        ("numberOfTyresOut", ctypes.c_int),
        ("pitLimiterOn", ctypes.c_int),
        ("abs", ctypes.c_float),
        ("kersCharge", ctypes.c_float),
        ("kersInput", ctypes.c_float),
        ("autoShifterOn", ctypes.c_int),
        ("rideHeight", ctypes.c_float * 2),
        ("turboBoost", ctypes.c_float),
        ("ballast", ctypes.c_float),
        ("airDensity", ctypes.c_float),
        ("airTemp", ctypes.c_float),
        ("roadTemp", ctypes.c_float),
        ("localAngularVel", ctypes.c_float * 3),
        ("finalFF", ctypes.c_float),
        ("performanceMeter", ctypes.c_float),
        ("engineBrake", ctypes.c_int),
        ("ersRecoveryLevel", ctypes.c_int),
        ("ersPowerLevel", ctypes.c_int),
        ("ersHeatCharging", ctypes.c_int),
        ("ersIsCharging", ctypes.c_int),
        ("kersCurrentKJ", ctypes.c_float),
        ("drsAvailable", ctypes.c_int),
        ("waterTemp", ctypes.c_float),
        ("brakeTemp", ctypes.c_float * 4),
        ("clutch", ctypes.c_float),
        ("tyreTempI", ctypes.c_float * 4),
        ("tyreTempM", ctypes.c_float * 4),
        ("tyreTempO", ctypes.c_float * 4),
        ("isAIControlled", ctypes.c_int),
        ("tyreContactPoint", (ctypes.c_float * 3) * 4),
        ("tyreContactNormal", (ctypes.c_float * 3) * 4),
        ("tyreContactHeading", (ctypes.c_float * 3) * 4),
        ("brakeBias", ctypes.c_float),
        ("localVelocity", ctypes.c_float * 3),
    ]


class SPageFileGraphic(ctypes.Structure):
    """Assetto Corsa 1 shared-memory graphics page, #pragma pack(4) layout."""

    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int),
        ("status", ctypes.c_int),
        ("session", ctypes.c_int),
        ("currentTime", ctypes.c_wchar * 15),
        ("lastTime", ctypes.c_wchar * 15),
        ("bestTime", ctypes.c_wchar * 15),
        ("split", ctypes.c_wchar * 15),
        ("completedLaps", ctypes.c_int),
        ("position", ctypes.c_int),
        ("iCurrentTime", ctypes.c_int),
        ("iLastTime", ctypes.c_int),
        ("iBestTime", ctypes.c_int),
        ("sessionTimeLeft", ctypes.c_float),
        ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int),
        ("currentSectorIndex", ctypes.c_int),
        ("lastSectorTime", ctypes.c_int),
        ("numberOfLaps", ctypes.c_int),
        ("tyreCompound", ctypes.c_wchar * 33),
        ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float),
        ("carCoordinates", ctypes.c_float * 3),
        ("penaltyTime", ctypes.c_float),
        ("flag", ctypes.c_int),
        ("idealLineOn", ctypes.c_int),
        ("isInPitLane", ctypes.c_int),
        ("surfaceGrip", ctypes.c_float),
        ("mandatoryPitDone", ctypes.c_int),
        ("windSpeed", ctypes.c_float),
        ("windDirection", ctypes.c_float),
    ]


@dataclass(frozen=True)
class TelemetrySample:
    physics_packet: int
    ac_status: int
    speed_kmh: float
    rpm: int
    gear_raw: int
    throttle: float
    brake: float
    steering: float
    heading: float
    position: tuple[float, float, float]


def _finite_bounded(value: Any, name: str, minimum: float, maximum: float) -> float:
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{name} is not finite or outside [{minimum}, {maximum}]")
    return result


def sample_to_payload(sample: TelemetrySample, now: float, last_packet_at: float | None) -> dict[str, Any]:
    for field_name, value in (("ac_status", sample.ac_status), ("rpm", sample.rpm), ("gear_raw", sample.gear_raw), ("physics_packet", sample.physics_packet)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} must be an integer")
    if sample.ac_status not in (0, 1, 2, 3):
        raise ValueError("ac_status must be one of AC_OFF, AC_REPLAY, AC_LIVE, or AC_PAUSE")
    if not -1 <= sample.gear_raw <= 20:
        raise ValueError("gear_raw is outside the supported range")
    if not 0 <= sample.physics_packet <= 2_147_483_647:
        raise ValueError("physics_packet is outside the supported range")
    if len(sample.position) != 3:
        raise ValueError("ac_position must contain exactly three coordinates")
    speed = _finite_bounded(sample.speed_kmh, "speed_kmh", 0, 1000)
    throttle = _finite_bounded(sample.throttle, "throttle", 0, 1)
    brake = _finite_bounded(sample.brake, "brake", 0, 1)
    steering = _finite_bounded(sample.steering, "steering", -100, 100)
    heading = _finite_bounded(sample.heading, "heading", -1000, 1000)
    position = [_finite_bounded(value, "ac_position", -MAX_POSITION_ABS, MAX_POSITION_ABS) for value in sample.position]
    rpm = int(sample.rpm)
    if not 0 <= rpm <= 30_000:
        raise ValueError("rpm is outside the supported range")
    age = max(0.0, now - last_packet_at) if last_packet_at is not None else float("inf")
    fresh = age <= 1.5
    live = sample.ac_status == 2 and fresh
    sender_status = "receiving" if live else "waiting_for_ac"
    if sample.ac_status == 2 and not fresh:
        sender_status = "stale_ac_memory"
    return {
        "protocol_version": PROTOCOL_VERSION,
        "sender_status": sender_status,
        "connected": live,
        "ac_status": sample.ac_status,
        "speed_kmh": speed,
        "rpm": rpm,
        # AC's shared-memory convention is 0=reverse, 1=neutral, 2=first.
        # Subtract one for the conventional Minecraft HUD value (-1=reverse, 0=neutral).
        "gear_raw": sample.gear_raw,
        "throttle": throttle,
        "brake": brake,
        "steering": steering,
        "heading": heading,
        "ac_position": position,
        "physics_packet": sample.physics_packet,
        "telemetry_age_ms": int(age * 1000) if math.isfinite(age) else -1,
    }


def telemetry_from_pages(physics: SPageFilePhysics, graphic: SPageFileGraphic) -> TelemetrySample:
    return TelemetrySample(
        physics_packet=int(physics.packetId),
        ac_status=int(graphic.status),
        speed_kmh=float(physics.speedKmh),
        rpm=int(physics.rpms),
        gear_raw=int(physics.gear) - 1,
        throttle=float(physics.gas),
        brake=float(physics.brake),
        steering=float(physics.steerAngle),
        heading=float(physics.heading),
        position=tuple(float(value) for value in graphic.carCoordinates),
    )


class SharedMemoryReader:
    def __init__(self, physics_map: str, graphics_map: str):
        self.physics_map = physics_map
        self.graphics_map = graphics_map
        self._physics: mmap.mmap | None = None
        self._graphics: mmap.mmap | None = None
        self._retry_open_at = 0.0

    def open(self) -> None:
        if sys.platform != "win32":
            raise OSError("Assetto Corsa shared-memory pages are Windows-only")
        self.close()
        self._physics = mmap.mmap(-1, ctypes.sizeof(SPageFilePhysics), tagname=self.physics_map, access=mmap.ACCESS_READ)
        try:
            self._graphics = mmap.mmap(-1, ctypes.sizeof(SPageFileGraphic), tagname=self.graphics_map, access=mmap.ACCESS_READ)
        except Exception:
            self.close()
            raise

    def read(self) -> tuple[SPageFilePhysics, SPageFileGraphic]:
        if self._physics is None or self._graphics is None:
            now = time.monotonic()
            if now < self._retry_open_at:
                raise OSError("Waiting to retry AC shared-memory mapping")
            try:
                self.open()
            except OSError:
                self._retry_open_at = now + 1.0
                raise
        physics_bytes = self._physics[:ctypes.sizeof(SPageFilePhysics)]
        graphics_bytes = self._graphics[:ctypes.sizeof(SPageFileGraphic)]
        if len(physics_bytes) != ctypes.sizeof(SPageFilePhysics) or len(graphics_bytes) != ctypes.sizeof(SPageFileGraphic):
            raise OSError("Shared memory page is shorter than the documented AC 1 structure")
        if self._physics[:4] != physics_bytes[:4] or self._graphics[:4] != graphics_bytes[:4]:
            raise OSError("Shared-memory page changed while its snapshot was being copied")
        return (
            SPageFilePhysics.from_buffer_copy(physics_bytes),
            SPageFileGraphic.from_buffer_copy(graphics_bytes),
        )

    def close(self) -> None:
        for page in (self._physics, self._graphics):
            if page is not None:
                page.close()
        self._physics = None
        self._graphics = None


def encode_message(payload: dict[str, Any]) -> bytes:
    frame = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    if len(frame) > MAX_LINE_BYTES:
        raise ValueError("Encoded telemetry frame exceeds the line-size limit")
    return frame


def serve_client(client: socket.socket, reader: SharedMemoryReader, rate_hz: float) -> None:
    interval = 1.0 / rate_hz
    last_packet: int | None = None
    last_packet_at: float | None = None
    last_connect_warning = 0.0
    while True:
        started = time.monotonic()
        if last_packet is not None and last_packet_at is not None and started - last_packet_at > 3.0:
            reader.close()
            last_packet = None
            last_packet_at = None
        try:
            physics, graphic = reader.read()
            if physics.packetId != last_packet:
                last_packet = int(physics.packetId)
                last_packet_at = started
            sample = telemetry_from_pages(physics, graphic)
            payload = sample_to_payload(sample, started, last_packet_at)
        except (OSError, ValueError, OverflowError) as error:
            now = time.monotonic()
            if now - last_connect_warning >= 5.0:
                print(f"[sender] Waiting for valid AC shared-memory data: {error}", file=sys.stderr)
                last_connect_warning = now
            payload = {
                "protocol_version": PROTOCOL_VERSION,
                "sender_status": "waiting_for_ac",
                "connected": False,
                "ac_status": 0,
                "speed_kmh": 0,
                "rpm": 0,
                "gear_raw": 0,
                "throttle": 0,
                "brake": 0,
                "steering": 0,
                "heading": 0,
                "ac_position": [0, 0, 0],
                "physics_packet": 0,
                "telemetry_age_ms": -1,
            }
        client.sendall(encode_message(payload))
        time.sleep(max(0.0, interval - (time.monotonic() - started)))


def acquire_single_instance() -> tuple[Any, int]:
    if sys.platform != "win32":
        raise OSError("The Assetto Corsa sender requires Windows shared memory")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, 1, r"Local\GodWarBridge.AssettoCorsaSender")
    error = ctypes.get_last_error()
    if not handle:
        raise OSError(error, "Unable to create the sender single-instance mutex")
    if error == 183:
        kernel32.CloseHandle(handle)
        raise RuntimeError("Another GodWarBridge telemetry sender is already running")
    return kernel32, handle


def run_server(args: argparse.Namespace) -> None:
    kernel32, mutex_handle = acquire_single_instance()
    reader = SharedMemoryReader(args.physics_map, args.graphics_map)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.host, args.port))
            server.listen(1)
            print(f"[sender] Waiting for AC shared memory; listening on {args.host}:{args.port}")
            while True:
                client, address = server.accept()
                with client:
                    client.settimeout(2.0)
                    print(f"[sender] Minecraft connected from {address[0]}:{address[1]}")
                    try:
                        serve_client(client, reader, args.rate)
                    except (BrokenPipeError, ConnectionResetError, OSError) as error:
                        print(f"[sender] Minecraft connection closed ({error}); waiting for reconnect")
    finally:
        reader.close()
        kernel32.ReleaseMutex(mutex_handle)
        kernel32.CloseHandle(mutex_handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream local Assetto Corsa shared-memory telemetry to GodWarBridge.")
    parser.add_argument("--host", default="127.0.0.1", help="TCP bind address (localhost by default)")
    parser.add_argument("--port", type=int, default=47654)
    parser.add_argument("--rate", type=float, default=20.0, help="Telemetry frames per second (1..60)")
    parser.add_argument("--physics-map", default=r"Local\acpmf_physics")
    parser.add_argument("--graphics-map", default=r"Local\acpmf_graphics")
    args = parser.parse_args()
    if not 1.0 <= args.rate <= 60.0:
        parser.error("--rate must be between 1 and 60 Hz")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("The sender binds to localhost only; remote telemetry networking is not supported")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return args


if __name__ == "__main__":
    try:
        run_server(parse_args())
    except KeyboardInterrupt:
        print("\n[sender] Stopped")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[sender] Startup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
