"""Live check of the WebBox Modbus gateway: discovery + key SI registers."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webbox"))

from app.modbus.service import discover_units, read_channels  # noqa: E402

HOST = "192.168.100.180"
PORT = 502
UNIT = 3
PROFILE = "SI5048MBP"

KEY_CHANNELS = [
    "Serial Number", "Mode", "BatSoc", "BatVtg", "TotBatCur", "BatTmp",
    "TotInvPwrAt", "InvVtg", "InvFrq", "GdCsmpPwrAt", "GdFeedPwrAt",
]


async def main() -> None:
    devices = await discover_units(HOST, PORT)
    print("assignment table:", devices or "(empty)")

    data = await read_channels(HOST, UNIT, PROFILE, port=PORT, channels=KEY_CHANNELS)
    print(f"\nunit {UNIT} ({PROFILE}):")
    for c in data["channels"]:
        label = f"  [{c['label']}]" if c.get("label") else ""
        value = "n/a" if c["value"] is None else c["value"]
        print(f"  {c['name']:<14} {value} {c['unit']}{label}")
    if data["errors"]:
        print("errors:")
        for e in data["errors"]:
            print(" ", e)


if __name__ == "__main__":
    asyncio.run(main())
