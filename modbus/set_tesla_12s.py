"""Configure SI charge voltages for a 12s Tesla pack (2x 6s Model S modules).

The SI is configured for a 42 V nominal (21-cell lead) bank, so the
ChrgVtg* registers are per-cell values multiplied by 21 for the pack:

    register 2.31 V/cell * 21 = 48.51 V pack = 4.04 V per Tesla cell
    register 2.23 V/cell * 21 = 46.83 V pack = 3.90 V per Tesla cell

Targets (12s NCA): absorb ~4.05 V/cell, float ~3.9 V/cell, equalize
disabled (set equal to absorb — 2.5/cell would be 52.5 V = 4.375 V per
Tesla cell, dangerously over the 4.2 V max).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webbox"))

from app.modbus.service import read_channels, write_channel  # noqa: E402

HOST = "192.168.100.180"
PORT = 502
UNIT = 3
PROFILE = "SI5048MBP"

WRITES = [
    ("ChrgVtgBoost", 2.31),  # boost charge  -> 48.51 V (4.04 V/cell)
    ("ChrgVtgFul", 2.31),    # full charge   -> 48.51 V (4.04 V/cell)
    ("ChrgVtgEqu", 2.31),    # equalization  -> same as full (disabled)
    ("ChrgVtgFlo", 2.23),    # float charge  -> 46.83 V (3.90 V/cell)
]


async def main() -> None:
    before = await read_channels(
        HOST, UNIT, PROFILE, port=PORT,
        channels=[name for name, _ in WRITES] + ["BatChrgVtg", "BatVtg"],
    )
    print("before:")
    for c in before["channels"]:
        print(f"  {c['name']:<14} {c['value']} {c['unit']}")

    print("\nwriting:")
    for name, value in WRITES:
        result = await write_channel(HOST, UNIT, PROFILE, name, value, port=PORT)
        ok = "OK" if result["readback"] == value else f"MISMATCH (readback {result['readback']})"
        print(f"  {name:<14} -> {value}  {ok}")

    after = await read_channels(
        HOST, UNIT, PROFILE, port=PORT,
        channels=[name for name, _ in WRITES] + ["BatChrgVtg", "BatVtg", "BatChrgOp"],
    )
    print("\nafter:")
    for c in after["channels"]:
        label = f"  [{c['label']}]" if c.get("label") else ""
        print(f"  {c['name']:<14} {c['value']} {c['unit']}{label}")


if __name__ == "__main__":
    asyncio.run(main())
