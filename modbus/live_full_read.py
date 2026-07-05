"""Full-profile live read: dump every register the Sunny Island reports."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webbox"))

from app.modbus.service import read_channels  # noqa: E402

HOST = "192.168.100.180"
PORT = 502
UNIT = 3
PROFILE = "SI5048MBP"


async def main() -> None:
    data = await read_channels(HOST, UNIT, PROFILE, port=PORT)
    have, nan = [], []
    for c in data["channels"]:
        (have if c["value"] is not None else nan).append(c)

    print(f"unit {UNIT} ({PROFILE}): {len(have)} channels with values, "
          f"{len(nan)} n/a, {len(data['errors'])} errors\n")
    print(f"{'addr':<6} {'rw':<3} {'channel':<18} value")
    for c in have:
        label = f"  [{c['label']}]" if c.get("label") else ""
        rw = "RW" if c["writable"] else "RO"
        print(f"{c['address']:<6} {rw:<3} {c['name']:<18} {c['value']} {c['unit']}{label}")
    if nan:
        print("\nn/a (NaN) channels:", ", ".join(c["name"] for c in nan))
    if data["errors"]:
        print("\nerrors:")
        for e in data["errors"]:
            print(" ", e)


if __name__ == "__main__":
    asyncio.run(main())
