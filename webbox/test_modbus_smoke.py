"""Smoke test for the Modbus module: profile parsing, decode/encode, and a
full client round-trip against a simulated WebBox gateway.

Run from the webbox/ directory:  python test_modbus_smoke.py
"""

from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path

from app.modbus import (
    available_profiles,
    discover_units,
    load_profile,
    read_channels,
    write_channel,
)
from app.modbus.service import _merge_blocks


def _u32_words(value: int) -> list[int]:
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]


def test_profile() -> None:
    profiles = available_profiles()
    assert profiles, "no profiles found"
    names = {p["name"] for p in profiles}
    assert {"SI5048MBP", "SI6048MBP"} <= names, names
    print("profiles:", profiles)

    p = load_profile("SI6048MBP")
    assert p.devicename == "SI 6048" and p.susyid == 69
    assert len(p.channels) == 141, len(p.channels)

    p5 = load_profile("SI5048MBP")
    assert p5.devicename == "SI 5048" and p5.susyid == 69
    assert len(p5.channels) == 141, len(p5.channels)
    assert [c.address for c in p5.channels] == [c.address for c in p.channels]

    soc = p.find("BatSoc")
    assert soc.address == 30845 and not soc.write
    assert soc.decode(_u32_words(87)) == 87
    assert soc.decode(_u32_words(0xFFFF_FFFF)) is None  # U32 NaN

    vtg = p.find("BatVtg")  # FIX2
    assert vtg.decode(_u32_words(4850)) == 48.50

    cur = p.find("TotBatCur")  # S32 FIX3
    assert cur.decode(_u32_words((1 << 32) - 12345)) == -12.345
    assert cur.decode(_u32_words(0x8000_0000)) is None  # S32 NaN

    tmp = p.find("BatTmp")  # TEMP: one implied decimal place
    assert tmp.decode(_u32_words(253)) == 25.3

    tmp_max = p.find("BatTmpMax")  # writable TEMP channel
    assert tmp_max.write
    assert tmp_max.encode(45.0) == _u32_words(450)

    # the profile's `scale` attribute is a WebBox-UI display hint and must
    # NOT be applied: OnTmh (scale=3600, unit="s") stays in raw seconds
    on_tmh = p.find("OnTmh")
    assert on_tmh.scale == 3600
    assert on_tmh.decode(_u32_words(7200)) == 7200

    # path traversal / invalid profile ids must be rejected
    for bad_id in ("../SI6048MBP", "..\\secret", "a/b", "/etc/passwd", ".."):
        try:
            load_profile(bad_id)
            raise AssertionError(f"profile id {bad_id!r} must be rejected")
        except FileNotFoundError:
            pass

    man = p.find("ManStr")
    assert man.write and man.disp == "TAGLIST"
    assert set(man.mapping) == {973, 569, 381}
    assert man.encode("Stop") == _u32_words(381)
    assert man.encode("Activated") == _u32_words(569)
    assert man.encode(569) == _u32_words(569)
    for bad in (999, "Reboot"):
        try:
            man.encode(bad)
            raise AssertionError(f"encode must reject {bad!r}")
        except ValueError:
            pass

    gn = p.find("GnManStr")
    assert gn.encode("Start") == _u32_words(1467)
    assert gn.encode("Automatic") == _u32_words(1438)

    chrg = p.find("40045")  # by address: BatChrgCurMax FIX3
    assert chrg.name == "BatChrgCurMax"
    assert chrg.encode(110.0) == _u32_words(110000)

    blocks = _merge_blocks(list(p.channels))
    assert all(count <= 100 for _, count, _ in blocks), blocks
    covered: set[int] = set()
    for start, count, _ in blocks:
        covered.update(range(start, start + count))
    for ch in p.channels:
        for r in range(ch.address, ch.address + ch.words):
            assert r in covered, f"register {r} of {ch.name} not covered"
    total = sum(count for _, count, _ in blocks)
    print(f"read_blocks: {len(blocks)} blocks, {total} registers total")
    print("profile tests OK")


def test_profile_dir_override() -> None:
    """WEBBOX_MODBUS_PROFILE_DIR may hold user profiles + unitid_config.xml;
    the config file (and non-profile XML) must not appear as a profile."""
    import os
    import shutil
    import tempfile

    from app.modbus import profile as profile_mod

    src = Path(profile_mod.__file__).resolve().parent
    tmp_dir = tempfile.mkdtemp(prefix="webbox-profiles-")
    try:
        shutil.copy(src / "profiles" / "SI5048MBP.xml", os.path.join(tmp_dir, "MYPROFILE.xml"))
        shutil.copy(src / "unitid_config.xml", os.path.join(tmp_dir, "unitid_config.xml"))
        with open(os.path.join(tmp_dir, "notaprofile.xml"), "w", encoding="utf-8") as f:
            f.write("<somethingelse><entry/></somethingelse>")

        os.environ["WEBBOX_MODBUS_PROFILE_DIR"] = tmp_dir
        load_profile.cache_clear()
        profile_mod.unit_id_categories.cache_clear()
        try:
            names = {p["name"] for p in available_profiles()}
            assert "MYPROFILE" in names, names
            assert "unitid_config" not in names, names
            assert "notaprofile" not in names, names
            assert profile_mod.unit_id_categories(), "override unitid_config.xml not loaded"
        finally:
            del os.environ["WEBBOX_MODBUS_PROFILE_DIR"]
            load_profile.cache_clear()
            profile_mod.unit_id_categories.cache_clear()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print("profile dir override OK")


class FakeGateway:
    """Simulates the WebBox Modbus server: unit 1 = gateway table, unit 3 = SI 6048.

    With ``empty_table=True`` the gateway has no assignment-table registers
    at all, mimicking a real WebBox before any device has been assigned a
    unit ID (it answers *Illegal data address*, not empty slots).
    """

    def __init__(self, empty_table: bool = False) -> None:
        p = load_profile("SI6048MBP")
        self.registers: dict[tuple[int, int], int] = {}
        # unit 3: give every SI channel a value
        seed = {
            "BatSoc": 87, "BatVtg": 4850, "TotBatCur": (1 << 32) - 12345,
            "ManStr": 381, "GnManStr": 1438, "TotInvPwrAt": 1234,
            "BatTmp": 253, "Mode": 307,
        }
        seeded: set[int] = set()
        for ch in p.channels:
            if ch.address in seeded:
                continue
            seeded.add(ch.address)
            raw = seed.get(ch.name)
            if raw is None:
                raw = 0xFFFF_FFFF if ch.type == "U32" else 0x8000_0000
            self._set_u32(3, ch.address, raw)
        # unit 1: gateway table with one device (device-id 105, serial 21000777, unit 3)
        if not empty_table:
            self.registers[(1, 42109)] = 105
            self._set_u32(1, 42110, 21000777)
            self.registers[(1, 42112)] = 3

    def _set_u32(self, unit: int, addr: int, value: int) -> None:
        self.registers[(unit, addr)] = (value >> 16) & 0xFFFF
        self.registers[(unit, addr + 1)] = value & 0xFFFF

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                header = await reader.readexactly(7)
                tid, proto, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                fc = pdu[0]
                if fc == 0x03:
                    addr, count = struct.unpack(">HH", pdu[1:5])
                    known = [(unit, a) in self.registers for a in range(addr, addr + count)]
                    if not any(known):
                        resp = struct.pack(">BB", 0x83, 2)  # illegal data address
                    else:
                        values = [self.registers.get((unit, a), 0xFFFF) for a in range(addr, addr + count)]
                        resp = struct.pack(f">BB{count}H", 0x03, count * 2, *values)
                elif fc == 0x10:
                    addr, count, bc = struct.unpack(">HHB", pdu[1:6])
                    values = struct.unpack(f">{count}H", pdu[6:6 + bc])
                    for i, v in enumerate(values):
                        self.registers[(unit, addr + i)] = v
                    resp = struct.pack(">BHH", 0x10, addr, count)
                else:
                    resp = struct.pack(">BB", fc | 0x80, 1)
                writer.write(struct.pack(">HHHB", tid, proto, len(resp) + 1, unit) + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()


async def test_roundtrip() -> None:
    gw = FakeGateway()
    server = await asyncio.start_server(gw.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        # discovery — unit 3 falls in the "Inverter" range of unitid_config.xml
        devices = await discover_units("127.0.0.1", port)
        assert len(devices) == 1, devices
        dev = devices[0]
        assert dev["device_id"] == 105 and dev["serial"] == 21000777
        assert dev["unit_id"] == 3 and dev["addressable"]
        assert dev.get("category") == "Inverter", dev
        print("discover OK:", devices)

        # full profile read
        data = await read_channels("127.0.0.1", 3, "SI6048MBP", port=port)
        by_name = {c["name"]: c for c in data["channels"]}
        assert by_name["BatSoc"]["value"] == 87
        assert by_name["BatVtg"]["value"] == 48.5
        assert by_name["TotBatCur"]["value"] == -12.345
        assert by_name["ManStr"]["label"] == "Stop"
        assert by_name["GnManStr"]["label"] == "Automatic"
        assert by_name["BatTmp"]["value"] == 25.3
        assert by_name["GdRmgTm"]["value"] is None  # NaN seeded
        assert not data["errors"], data["errors"]
        print("full read OK:", len(data["channels"]), "channels")

        # the SI5048 profile reads the same registers
        data5 = await read_channels(
            "127.0.0.1", 3, "SI5048MBP", port=port, channels=["BatSoc", "BatVtg"]
        )
        by_name5 = {c["name"]: c for c in data5["channels"]}
        assert by_name5["BatSoc"]["value"] == 87
        assert by_name5["BatVtg"]["value"] == 48.5
        print("SI5048 read OK")

        # filtered read by name and by address
        data = await read_channels(
            "127.0.0.1", 3, "SI6048MBP", port=port, channels=["BatSoc", "30851"]
        )
        assert sorted(c["name"] for c in data["channels"]) == ["BatSoc", "BatVtg"]
        print("filtered read OK")

        # write by enum label, verify readback
        result = await write_channel("127.0.0.1", 3, "SI6048MBP", "ManStr", "Activated", port=port)
        assert result["status"] == "ok" and result["readback"] == 569, result
        # write numeric FIX3 value
        result = await write_channel("127.0.0.1", 3, "SI6048MBP", "BatChrgCurMax", 110, port=port)
        assert result["readback"] == 110.0, result
        # enum writes must reject values outside the mapping
        try:
            await write_channel("127.0.0.1", 3, "SI6048MBP", "ManStr", 999, port=port)
            raise AssertionError("invalid enum tag must be rejected")
        except ValueError:
            pass
        # read-only must be rejected
        try:
            await write_channel("127.0.0.1", 3, "SI6048MBP", "BatSoc", 50, port=port)
            raise AssertionError("write to read-only channel must fail")
        except ValueError as exc:
            assert "read-only" in str(exc)
        print("write OK")

    # a WebBox with no assigned devices answers "Illegal data address" for
    # the assignment table; discovery must return [] instead of raising
    gw_empty = FakeGateway(empty_table=True)
    server = await asyncio.start_server(gw_empty.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        devices = await discover_units("127.0.0.1", port)
        assert devices == [], devices
        print("empty assignment table OK")


def test_api() -> None:
    """End-to-end through the FastAPI endpoints (skipped if fastapi missing)."""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("fastapi not installed — skipping API test")
        return

    import os
    import tempfile
    import threading

    data_dir = tempfile.mkdtemp(prefix="webbox-test-")
    os.environ["WEBBOX_DATA_DIR"] = data_dir
    os.environ["WEBBOX_OPTIONS_PATH"] = os.path.join(data_dir, "options.json")
    from app.main import app  # import after env is set

    # Run the fake gateway on its own loop/thread so the TestClient's
    # event loop can connect to it.
    gw = FakeGateway()
    loop = asyncio.new_event_loop()
    started = threading.Event()
    port_holder: list[int] = []

    def run_gateway() -> None:
        asyncio.set_event_loop(loop)

        async def serve() -> None:
            server = await asyncio.start_server(gw.handle, "127.0.0.1", 0)
            port_holder.append(server.sockets[0].getsockname()[1])
            started.set()
            async with server:
                await server.serve_forever()

        try:
            loop.run_until_complete(serve())
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=run_gateway, daemon=True)
    thread.start()
    assert started.wait(5), "fake gateway did not start"
    port = port_holder[0]

    with TestClient(app) as client:
        wb = client.post("/api/webboxes", json={
            "name": "test", "host": "http://127.0.0.1:80",
            "installer_password": "sma12345",
            "modbus_port": port, "modbus_unit_id": 3,
        }).json()
        assert wb["modbus_port"] == port and wb["modbus_profile"] == "SI6048MBP", wb

        profiles = client.get("/api/modbus/profiles").json()
        assert {p["name"] for p in profiles} >= {"SI5048MBP", "SI6048MBP"}, profiles

        disc = client.post(f"/api/webboxes/{wb['id']}/modbus/discover").json()
        assert disc["host"] == "127.0.0.1" and disc["devices"][0]["unit_id"] == 3, disc

        read = client.get(f"/api/webboxes/{wb['id']}/modbus/channels?channels=BatSoc,ManStr").json()
        by_name = {c["name"]: c for c in read["channels"]}
        assert by_name["BatSoc"]["value"] == 87
        assert by_name["ManStr"]["label"] in ("Stop", "Activated")

        # writes must carry the correct installer password
        noauth = client.put(f"/api/webboxes/{wb['id']}/modbus/channels", json={
            "channel": "GnManStr", "value": "Start",
        })
        assert noauth.status_code == 403, noauth.text
        wrong = client.put(f"/api/webboxes/{wb['id']}/modbus/channels", json={
            "channel": "GnManStr", "value": "Start", "installer_password": "nope",
        })
        assert wrong.status_code == 403, wrong.text

        write = client.put(f"/api/webboxes/{wb['id']}/modbus/channels", json={
            "channel": "GnManStr", "value": "Start", "installer_password": "sma12345",
        }).json()
        assert write["status"] == "ok" and write["readback"] == 1467, write

        bad = client.put(f"/api/webboxes/{wb['id']}/modbus/channels", json={
            "channel": "BatSoc", "value": 1, "installer_password": "sma12345",
        })
        assert bad.status_code == 400 and "read-only" in bad.json()["detail"], bad.text

    loop.call_soon_threadsafe(loop.stop)
    print("API test OK")


if __name__ == "__main__":
    test_profile()
    test_profile_dir_override()
    asyncio.run(test_roundtrip())
    test_api()
    print("ALL MODBUS SMOKE TESTS PASSED")
    sys.exit(0)
