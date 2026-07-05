"""Minimal asyncio Modbus TCP client.

Implements just what the SMA WebBox gateway needs:

* FC 0x03 *Read Holding Registers*
* FC 0x10 *Write Multiple Registers* — SMA requires that multi-word
  values (and the unit-ID assignment blocks) are written in one request,
  so single-register writes also go through FC 0x10.

No third-party dependency; frames are built/parsed by hand (MBAP header
+ PDU, big-endian throughout).
"""

from __future__ import annotations

import asyncio
import itertools
import struct


class ModbusError(Exception):
    """Connection, protocol, or Modbus-exception failure.

    ``exception_code`` carries the Modbus exception code (e.g. 0x02
    *Illegal data address*) when the server answered with an exception
    frame; it is ``None`` for connection/protocol failures.
    """

    def __init__(self, message: str, *, exception_code: int | None = None) -> None:
        super().__init__(message)
        self.exception_code = exception_code


ILLEGAL_DATA_ADDRESS = 0x02


_EXCEPTIONS = {
    0x01: "Illegal function",
    0x02: "Illegal data address",
    0x03: "Illegal data value",
    0x04: "Slave device failure",
    0x05: "Acknowledge",
    0x06: "Slave device busy",
    0x0A: "Gateway path unavailable",
    0x0B: "Gateway target device failed to respond",
}


class ModbusTcpClient:
    """One TCP connection to a Modbus server; use as an async context manager."""

    def __init__(self, host: str, port: int = 502, *, timeout: float = 10.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._tid = itertools.count(1)
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "ModbusTcpClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._writer is not None:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), self._timeout
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ModbusError(
                f"Cannot connect to Modbus server {self._host}:{self._port}: {exc}"
            ) from exc

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
            self._reader = None
            self._writer = None

    async def _request(self, unit_id: int, pdu: bytes) -> bytes:
        """Send one PDU and return the response PDU (sans function byte checks)."""
        await self.connect()
        assert self._reader is not None and self._writer is not None
        tid = next(self._tid) & 0xFFFF
        frame = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit_id) + pdu
        async with self._lock:
            try:
                self._writer.write(frame)
                await asyncio.wait_for(self._writer.drain(), self._timeout)
                header = await asyncio.wait_for(
                    self._reader.readexactly(7), self._timeout
                )
                rtid, _proto, length, runit = struct.unpack(">HHHB", header)
                if length < 2:
                    await self.close()
                    raise ModbusError(
                        f"Malformed Modbus frame from {self._host}:{self._port} "
                        f"(MBAP length {length})"
                    )
                body = await asyncio.wait_for(
                    self._reader.readexactly(length - 1), self._timeout
                )
            except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as exc:
                await self.close()
                raise ModbusError(
                    f"Modbus I/O error with {self._host}:{self._port}: {exc}"
                ) from exc
        if rtid != tid:
            await self.close()
            raise ModbusError(f"Transaction ID mismatch (sent {tid}, got {rtid})")
        if runit != unit_id:
            raise ModbusError(f"Unit ID mismatch (sent {unit_id}, got {runit})")
        if not body:
            raise ModbusError("Empty Modbus response")
        function = body[0]
        if function & 0x80:
            code = body[1] if len(body) > 1 else 0
            reason = _EXCEPTIONS.get(code, f"exception 0x{code:02X}")
            raise ModbusError(
                f"Modbus exception from unit {unit_id}: {reason} "
                f"(function 0x{function & 0x7F:02X})",
                exception_code=code,
            )
        return body

    async def read_holding_registers(
        self, unit_id: int, address: int, count: int
    ) -> list[int]:
        """FC 0x03 — returns ``count`` 16-bit register words."""
        if not 1 <= count <= 125:
            raise ValueError(f"Register count {count} out of range 1..125")
        pdu = struct.pack(">BHH", 0x03, address, count)
        body = self._validate_read(await self._request(unit_id, pdu), count)
        return list(struct.unpack(f">{count}H", body))

    @staticmethod
    def _validate_read(body: bytes, count: int) -> bytes:
        if body[0] != 0x03 or len(body) < 2:
            raise ModbusError(f"Unexpected response function 0x{body[0]:02X}")
        byte_count = body[1]
        data = body[2:]
        if byte_count != count * 2 or len(data) != byte_count:
            raise ModbusError(
                f"Short read: expected {count * 2} bytes, got {len(data)}"
            )
        return data

    async def write_registers(
        self, unit_id: int, address: int, values: list[int]
    ) -> None:
        """FC 0x10 — write one or more consecutive registers in one block."""
        if not 1 <= len(values) <= 123:
            raise ValueError(f"Write count {len(values)} out of range 1..123")
        pdu = struct.pack(
            f">BHHB{len(values)}H",
            0x10,
            address,
            len(values),
            len(values) * 2,
            *[v & 0xFFFF for v in values],
        )
        body = await self._request(unit_id, pdu)
        if body[0] != 0x10:
            raise ModbusError(f"Unexpected response function 0x{body[0]:02X}")
        echo_addr, echo_count = struct.unpack(">HH", body[1:5])
        if echo_addr != address or echo_count != len(values):
            raise ModbusError(
                f"Write echo mismatch (@{echo_addr} x{echo_count}, "
                f"expected @{address} x{len(values)})"
            )
