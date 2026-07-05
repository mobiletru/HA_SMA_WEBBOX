"""Quick check of the SI's active charge stage and target voltage."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webbox"))

from app.modbus.service import read_channels  # noqa: E402


async def main() -> None:
    data = await read_channels(
        "192.168.100.180", 3, "SI5048MBP", port=502,
        channels=["BatChrgOp", "BatChrgVtg", "BatVtg", "TotBatCur", "BatSoc",
                  "ChrgVtgBoost", "ChrgVtgFul", "ChrgVtgEqu", "ChrgVtgFlo"],
    )
    for c in data["channels"]:
        label = f"  [{c['label']}]" if c.get("label") else ""
        print(f"{c['name']:<14} {c['value']} {c['unit']}{label}")


if __name__ == "__main__":
    asyncio.run(main())
