"""Quick live smoke test against the WebBox Modbus gateway.

Reads the gateway assignment table (unit ID 1, registers 42109+) which maps
attached SMA devices to Modbus unit IDs. Read-only; no writes.
"""
import socket
import struct
import sys

HOST = "192.168.100.180"
PORT = 502

def read_holding(sock, unit, address, count, tid=1):
    pdu = struct.pack(">BHH", 0x03, address, count)
    adu = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu
    sock.sendall(adu)
    header = sock.recv(7)
    if len(header) < 7:
        raise RuntimeError("short MBAP header")
    _, _, length, runit = struct.unpack(">HHHB", header)
    body = b""
    while len(body) < length - 1:
        chunk = sock.recv(length - 1 - len(body))
        if not chunk:
            raise RuntimeError("connection closed")
        body += chunk
    fc = body[0]
    if fc & 0x80:
        raise RuntimeError(f"modbus exception code {body[1]} (fc {fc & 0x7F})")
    byte_count = body[1]
    regs = struct.unpack(f">{byte_count // 2}H", body[2:2 + byte_count])
    return regs

def main():
    sock = socket.create_connection((HOST, PORT), timeout=8)
    print(f"connected to {HOST}:{PORT}")

    # Gateway info (unit 1): 42101 profile version per SMA doc region
    # Assignment table: 42109 onward, 4 registers per device:
    #   [susyid, serial_hi, serial_lo, unit_id]
    print("\nGateway assignment table (unit 1, 42109+):")
    found = 0
    addr = 42109
    for slot in range(10):
        try:
            regs = read_holding(sock, 1, addr, 4, tid=slot + 1)
        except RuntimeError as e:
            print(f"  slot {slot} @ {addr}: {e}")
            break
        susyid, ser_hi, ser_lo, unit_id = regs
        serial = (ser_hi << 16) | ser_lo
        if susyid in (0, 0xFFFF) and serial in (0, 0xFFFFFFFF):
            break
        print(f"  slot {slot}: susyid={susyid} serial={serial} unit_id={unit_id}")
        found += 1
        addr += 4
    print(f"  -> {found} device(s) in table")
    sock.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
