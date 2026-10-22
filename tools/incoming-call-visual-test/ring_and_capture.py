"""
Local SIP INVITE to MicroSIP → wait for 180 Ringing → screenshot all MicroSIP windows.

Requires:
  - MicroSIP running with Enable Local Account
  - SIP UDP listen port (default 5060), e.g. sourcePort=5060 in MicroSIP.ini

Usage (from repo root):
  py -3 tools/incoming-call-visual-test/ring_and_capture.py
  py -3 tools/incoming-call-visual-test/ring_and_capture.py --port 5060 --hold 8
"""
from __future__ import annotations

import argparse
import ctypes
import socket
import struct
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002

OUT_DIR = Path(__file__).resolve().parent / "out"


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def get_microsip_pid() -> int:
    out = subprocess.check_output(
        'tasklist /FI "IMAGENAME eq MicroSIP.exe" /FO CSV /NH',
        shell=True,
        text=True,
    )
    for line in out.splitlines():
        if "MicroSIP" in line:
            parts = [p.strip('"') for p in line.split(",")]
            return int(parts[1])
    raise SystemExit("MicroSIP.exe is not running")


def enum_windows(pid: int) -> list[tuple[int, str, RECT]]:
    results: list[tuple[int, str, RECT]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            rc = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rc))
            results.append((int(hwnd), buf.value, rc))
        return True

    user32.EnumWindows(callback, 0)
    return results


def save_bitmap(hwnd: int, path: Path) -> tuple[int, int]:
    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w = max(1, rc.right - rc.left)
    h = max(1, rc.bottom - rc.top)

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
    screen_dc = user32.GetDC(0)
    gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, rc.left, rc.top, SRCCOPY)
    user32.ReleaseDC(0, screen_dc)

    bi_size = 40
    bmi = BITMAPINFOHEADER()
    bmi.biSize = bi_size
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    pixels = bytes(buf)
    row = w * 4
    file_size = 14 + bi_size + row * h
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI", file_size, 0, 0, 14 + bi_size))
        f.write(struct.pack("<IiiHHIIiiII", bi_size, w, h, 1, 32, 0, row * h, 0, 0, 0, 0))
        for y in range(h - 1, -1, -1):
            f.write(pixels[y * row : (y + 1) * row])
    return w, h


def sip_invite_and_capture(
    host: str = "127.0.0.1",
    port: int = 5060,
    local_port: int = 5098,
    hold_s: float = 6.0,
) -> bool:
    call_id = str(uuid.uuid4())
    from_tag = uuid.uuid4().hex[:8]
    branch = "z9hG4bK" + uuid.uuid4().hex[:12]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", local_port))
    sock.settimeout(0.3)

    contact = f"<sip:preview@127.0.0.1:{local_port}>"
    from_uri = '"Visual Test" <sip:preview@127.0.0.1>'
    to_uri = f"<sip:local@{host}:{port}>"
    req_uri = f"sip:local@{host}:{port}"
    sdp = (
        "v=0\r\n"
        "o=preview 0 0 IN IP4 127.0.0.1\r\n"
        "s=Visual Test\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "t=0 0\r\n"
        "m=audio 4000 RTP/AVP 0 8\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
    )
    invite = (
        f"INVITE {req_uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:{local_port};branch={branch};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: {from_uri};tag={from_tag}\r\n"
        f"To: {to_uri}\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 INVITE\r\n"
        f"Contact: {contact}\r\n"
        f"User-Agent: CursorVisualTest/1.0\r\n"
        f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
    )

    print(f"Sending INVITE → {host}:{port} ...")
    sock.sendto(invite.encode(), (host, port))

    to_tag = None
    ringing = False
    t_end = time.time() + 8
    while time.time() < t_end:
        try:
            data, _ = sock.recvfrom(65535)
        except socket.timeout:
            continue
        text = data.decode(errors="replace")
        first = text.split("\r\n", 1)[0]
        print("SIP", first)
        for line in text.split("\r\n"):
            if line.lower().startswith("to:") and "tag=" in line.lower():
                to_tag = line.split("tag=")[-1].split(";")[0].strip()
        if " 180 " in first or " 183 " in first:
            ringing = True
            break
        if first.startswith(("SIP/2.0 4", "SIP/2.0 5", "SIP/2.0 6")):
            print(text[:500])
            sock.close()
            return False

    if not ringing:
        print("No 180/183 Ringing")
        sock.close()
        return False

    pid = get_microsip_pid()
    print("MicroSIP pid", pid)
    time.sleep(0.5)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    wins = enum_windows(pid)
    if not wins:
        print("No visible MicroSIP windows")
    for i, (hwnd, title, _rc) in enumerate(wins):
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60] or "untitled"
        path = OUT_DIR / f"{stamp}_{i}_{safe}.bmp"
        w, h = save_bitmap(hwnd, path)
        print(f"SAVED {path.name} title={title!r} {w}x{h}")

    print(f"Holding {hold_s:.0f}s (look at Incoming Call dialog)...")
    time.sleep(hold_s)

    cancel = (
        f"CANCEL {req_uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:{local_port};branch={branch};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: {from_uri};tag={from_tag}\r\n"
        f"To: {to_uri}" + (f";tag={to_tag}" if to_tag else "") + "\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 CANCEL\r\n"
        f"Content-Length: 0\r\n\r\n"
    )
    sock.sendto(cancel.encode(), (host, port))
    time.sleep(0.5)
    sock.close()
    print("CANCEL sent. Screenshots:", OUT_DIR)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger MicroSIP RinginDlg via local SIP INVITE")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5060, help="MicroSIP SIP UDP port")
    parser.add_argument("--local-port", type=int, default=5098, help="This script's UDP port")
    parser.add_argument("--hold", type=float, default=6.0, help="Seconds to keep ringing")
    args = parser.parse_args()
    ok = sip_invite_and_capture(args.host, args.port, args.local_port, args.hold)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
