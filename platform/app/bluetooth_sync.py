"""Enterprise Bluetooth calendar synchronization.

Replaces cloud OAuth calendar services: the calendar is transferred directly
to the user's smartphone (Android / iPhone) over Bluetooth, with no third-party
account required — ideal for air-gapped and privacy-sensitive deployments.

Pipeline (state machine, fully observable through /api/bluetooth/*):
  1. adapter_status()  — is a Bluetooth radio present & enabled on THIS computer
  2. scan()            — discover nearby phones (user chooses the right one)
  3. pair(address)     — OS-level pairing; reports "paired successfully"/"failed"
  4. sync(address)     — immediately after pairing: builds a vCalendar (.ics)
                         of the user's events and pushes it over OBEX Object
                         Push (RFCOMM) with per-stage progress reporting.

Transport: standard Bluetooth OBEX Object Push Profile (OPP) — natively
understood by Android. iPhones do not accept OPP; when the push is rejected the
sync reports a precise, actionable error (iOS requires the paired computer to
share items via its own UI). Every stage streams progress (0-100 %) and a
human-readable detail line to the frontend.

Developed by Sin Chi Chi · MAP Studio
"""

from __future__ import annotations

import datetime as dt
import platform as _platform
import re
import socket
import struct
import subprocess
import threading
import time

_IS_WIN = _platform.system() == "Windows"
_IS_MAC = _platform.system() == "Darwin"

_lock = threading.Lock()
_state: dict = {"running": False, "stage": "idle", "detail": "", "pct": 0,
                "status": "", "error": "", "log": []}


def _set(stage: str, detail: str, pct: int, status: str = "running", error: str = "") -> None:
    with _lock:
        _state.update({"stage": stage, "detail": detail, "pct": pct,
                       "status": status, "error": error,
                       "running": status == "running"})
        _state["log"].append({"t": dt.datetime.now().strftime("%H:%M:%S"),
                              "stage": stage, "detail": detail, "pct": pct})
        _state["log"] = _state["log"][-100:]


def get_state() -> dict:
    with _lock:
        return dict(_state)


def _run(cmd: list | str, timeout: int = 30, shell: bool = False) -> tuple[int, str]:
    try:
        flags = 0x08000000 if _IS_WIN else 0  # CREATE_NO_WINDOW
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           shell=shell, creationflags=flags)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def _ps(script: str, timeout: int = 60) -> tuple[int, str]:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=timeout)


# ==================== 1) adapter availability ====================
def adapter_status() -> dict:
    """Whether this computer has a working Bluetooth radio."""
    info = {"available": False, "enabled": False, "adapter": "", "os": _platform.system()}
    if _IS_WIN:
        rc, out = _ps(
            "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
            "Where-Object { $_.FriendlyName -match 'Radio|Adapter|Bluetooth' -or "
            "$_.InstanceId -like 'USB*' -or $_.InstanceId -like 'BTH*' } | "
            "Select-Object -First 5 Status,FriendlyName | ConvertTo-Csv -NoTypeInformation")
        for line in out.splitlines()[1:]:
            m = re.match(r'"(\w+)","(.+)"', line.strip())
            if m:
                info["available"] = True
                info["adapter"] = m.group(2)
                if m.group(1).upper() == "OK":
                    info["enabled"] = True
                    break
    elif _IS_MAC:
        rc, out = _run(["system_profiler", "SPBluetoothDataType"], timeout=20)
        if rc == 0 and "Bluetooth" in out:
            info["available"] = True
            info["enabled"] = "State: On" in out or "Bluetooth Power: On" in out
            m = re.search(r"Chipset: (.+)", out)
            info["adapter"] = m.group(1).strip() if m else "Built-in Bluetooth"
    else:  # Linux
        rc, out = _run(["bluetoothctl", "list"], timeout=10)
        if rc == 0 and out.strip():
            info["available"] = True
            info["adapter"] = out.strip().splitlines()[0]
            rc2, out2 = _run(["bluetoothctl", "show"], timeout=10)
            info["enabled"] = "Powered: yes" in out2
    # RFCOMM socket support (needed for the OBEX push itself)
    info["rfcomm"] = hasattr(socket, "AF_BLUETOOTH")
    return info


# ==================== 2) discover nearby phones ====================
# AQS protocol GUIDs for Association Endpoints (AEP)
_BT_CLASSIC = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"
_BT_LE = "{bb7bb05e-5972-42b5-94fc-76eaa7084d49}"


_PS_AWAIT = r'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
$null = [Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime]
'''


def _win_watch(seconds: int = 12) -> str:
    """Active Bluetooth discovery over classic + BLE Association Endpoints —
    the same enumeration the Windows Settings “Add device” dialog uses, and
    the only way to see iPhones (they advertise over BLE while their
    Bluetooth Settings screen is open). Runs repeated FindAllAsync sweeps
    (each triggers an inquiry) until the time budget is used."""
    script = _PS_AWAIT + r'''
$aqs = 'System.Devices.Aep.ProtocolId:="''' + _BT_CLASSIC + r'''" OR System.Devices.Aep.ProtocolId:="''' + _BT_LE + r'''"'
$found = @{}
$deadline = (Get-Date).AddSeconds(''' + str(seconds) + r''')
do {
  $op = [Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($aqs, $null, [Windows.Devices.Enumeration.DeviceInformationKind]::AssociationEndpoint)
  $r = Await $op ([Windows.Devices.Enumeration.DeviceInformationCollection])
  foreach ($d in $r) {
    $found[$d.Id] = ($d.Name + '|' + $d.Pairing.IsPaired + '|' + $d.Id)
  }
} while ((Get-Date) -lt $deadline)
$found.Values | ForEach-Object { Write-Output $_ }
'''
    rc, out = _ps(script, timeout=seconds + 60)
    return out


def _win_resolve_names(devices: dict) -> None:
    """Resolve names of unnamed BLE devices (iPhones use rotating private
    addresses whose name only appears after a GATT name request)."""
    unnamed = [mac for mac, d in devices.items() if d["name"] == mac and not d.get("classic")]
    for mac in unnamed[:5]:  # cap the extra time
        addr_num = int(mac.replace(":", ""), 16)
        script = _PS_AWAIT + r'''
$null = [Windows.Devices.Bluetooth.BluetoothLEDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime]
$op = [Windows.Devices.Bluetooth.BluetoothLEDevice]::FromBluetoothAddressAsync(''' + str(addr_num) + r''')
$dev = Await $op ([Windows.Devices.Bluetooth.BluetoothLEDevice])
if ($dev -and $dev.Name) { Write-Output $dev.Name }
'''
        rc, out = _ps(script, timeout=20)
        nm = out.strip().splitlines()[0].strip() if out.strip() else ""
        if nm:
            devices[mac]["name"] = nm


def scan(seconds: int = 12) -> list[dict]:
    """Discover nearby Bluetooth devices so the user can choose their phone."""
    devices: dict[str, dict] = {}
    if _IS_WIN:
        out = _win_watch(seconds)
        for line in out.splitlines():
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            name, paired, dev_id = parts[0], parts[1], "|".join(parts[2:])
            # device MAC is the LAST mac-like token in the AEP Id
            macs = re.findall(r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})", dev_id, re.I)
            if not macs:
                continue
            mac = macs[-1].upper()
            is_le = "BluetoothLE" in dev_id
            known = devices.get(mac)
            if known:
                if paired.lower() == "true":
                    known["paired"] = True
                if not known.get("classic") and not is_le:
                    known["classic"] = True
                if (known["name"] == mac or not known["name"]) and name.strip():
                    known["name"] = name.strip()
                continue
            devices[mac] = {"address": mac, "name": name.strip() or mac,
                            "paired": paired.lower() == "true", "rssi": None,
                            "classic": not is_le}
        _win_resolve_names(devices)
    elif _IS_MAC:
        rc, out = _run(["system_profiler", "SPBluetoothDataType"], timeout=25)
        for m in re.finditer(r"(\S[^\n:]*):\n\s+Address: ([0-9A-F:‑-]{17})", out, re.I):
            mac = m.group(2).replace("‑", ":").replace("-", ":").upper()
            devices[mac] = {"address": mac, "name": m.group(1).strip(),
                            "paired": "Paired: Yes" in out, "rssi": None}
    else:  # Linux — bluetoothctl scan
        _run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], timeout=seconds + 5)
        rc, out = _run(["bluetoothctl", "devices"], timeout=10)
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-F:]{17}) (.+)", line.strip(), re.I)
            if m:
                devices[m.group(1).upper()] = {"address": m.group(1).upper(),
                                               "name": m.group(2), "paired": False,
                                               "rssi": None}
        rc, out = _run(["bluetoothctl", "paired-devices"], timeout=10)
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-F:]{17}) ", line.strip(), re.I)
            if m and m.group(1).upper() in devices:
                devices[m.group(1).upper()]["paired"] = True
    # phones first, then named devices, then the rest
    def rank(d: dict) -> tuple:
        n = d["name"].lower()
        phone = any(k in n for k in ("iphone", "phone", "galaxy", "pixel", "xiaomi",
                                     "huawei", "oppo", "redmi", "samsung", "oneplus"))
        return (not phone, not d["paired"], d["name"] == d["address"], n)
    return sorted(devices.values(), key=rank)


# ==================== 3) pairing ====================
def _win_pair_native(address: str) -> dict:
    """Windows pairing through the Win32 Bluetooth Authentication API (ctypes).

    Unlike WinRT-from-PowerShell, the authentication callback runs in THIS
    process, so we can positively confirm the numeric-comparison ceremony —
    the phone then shows its “Bluetooth Pairing Request” dialog and the user
    taps Pair.
    """
    import ctypes
    from ctypes import wintypes

    bt = ctypes.WinDLL("bthprops.cpl")  # Bluetooth API lives in bthprops.cpl
    mac_int = int(address.replace(":", "").replace("-", ""), 16)

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [("y", wintypes.WORD), ("mo", wintypes.WORD), ("dow", wintypes.WORD),
                    ("d", wintypes.WORD), ("h", wintypes.WORD), ("mi", wintypes.WORD),
                    ("s", wintypes.WORD), ("ms", wintypes.WORD)]

    class BT_ADDR(ctypes.Union):
        _fields_ = [("ullLong", ctypes.c_ulonglong), ("rgBytes", ctypes.c_ubyte * 6)]

    class DEVICE_INFO(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("Address", BT_ADDR),
                    ("ulClassofDevice", wintypes.ULONG),
                    ("fConnected", wintypes.BOOL), ("fRemembered", wintypes.BOOL),
                    ("fAuthenticated", wintypes.BOOL),
                    ("stLastSeen", SYSTEMTIME), ("stLastUsed", SYSTEMTIME),
                    ("szName", ctypes.c_wchar * 248)]

    class AUTH_CB_PARAMS(ctypes.Structure):
        _fields_ = [("deviceInfo", DEVICE_INFO),
                    ("authenticationMethod", ctypes.c_int),
                    ("ioCapability", ctypes.c_int),
                    ("authenticationRequirements", ctypes.c_int),
                    ("Numeric_Value", wintypes.ULONG)]

    class AUTH_RESP_UNION(ctypes.Union):
        _fields_ = [("pin", ctypes.c_ubyte * 20),      # PIN_INFO (16 + length)
                    ("oob", ctypes.c_ubyte * 32),       # OOB_DATA_INFO
                    ("NumericValue", wintypes.ULONG),   # NUMERIC_COMPARISON_INFO
                    ("Passkey", wintypes.ULONG)]        # PASSKEY_INFO

    class AUTH_RESPONSE(ctypes.Structure):
        _fields_ = [("bthAddressRemote", BT_ADDR),
                    ("authMethod", ctypes.c_int),
                    ("u", AUTH_RESP_UNION),
                    ("negativeResponse", ctypes.c_ubyte)]

    CB_TYPE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPVOID,
                                 ctypes.POINTER(AUTH_CB_PARAMS))
    cb_result = {"fired": False, "send_rc": None, "method": None}

    def _auth_cb(param, p):
        try:
            cb_result["fired"] = True
            cb_result["method"] = p.contents.authenticationMethod
            resp = AUTH_RESPONSE()
            resp.bthAddressRemote = p.contents.deviceInfo.Address
            resp.authMethod = p.contents.authenticationMethod
            # 1=legacy PIN, 2=OOB, 3=numeric comparison, 4=passkey notify, 5=passkey
            if p.contents.authenticationMethod == 3:
                resp.u.NumericValue = p.contents.Numeric_Value
            elif p.contents.authenticationMethod == 5:
                resp.u.Passkey = p.contents.Numeric_Value
            resp.negativeResponse = 0
            cb_result["send_rc"] = bt.BluetoothSendAuthenticationResponseEx(
                None, ctypes.byref(resp))
        except Exception:  # noqa: BLE001
            pass
        return True

    cb = CB_TYPE(_auth_cb)
    bdi = DEVICE_INFO()
    bdi.dwSize = ctypes.sizeof(DEVICE_INFO)
    bdi.Address.ullLong = mac_int

    def _attempt() -> int:
        hreg = wintypes.HANDLE()
        rc_reg = bt.BluetoothRegisterForAuthenticationEx(
            None, ctypes.byref(hreg), cb, None)
        if rc_reg != 0:
            return -rc_reg
        try:
            # 0 = MITMProtectionNotRequired — device decides the actual ceremony
            return bt.BluetoothAuthenticateDeviceEx(None, None, ctypes.byref(bdi), None, 0)
        finally:
            bt.BluetoothUnregisterAuthentication(hreg)

    def _remove_bond() -> int:
        addr = BT_ADDR()
        addr.ullLong = mac_int
        return bt.BluetoothRemoveDevice(ctypes.byref(addr))

    # A stale half-bond (Windows remembers the phone, the phone forgot the
    # computer — e.g. after a failed/cancelled ceremony) makes every new
    # pairing fail with ERROR_NOT_AUTHENTICATED. Clear it before pairing.
    _remove_bond()
    time.sleep(1.0)
    rc = _attempt()
    if rc == 1244:  # ERROR_NOT_AUTHENTICATED — clear any bond debris and retry once
        _remove_bond()
        time.sleep(2.0)
        cb_result["fired"] = False
        rc = _attempt()

    if rc < 0:
        return {"paired": False,
                "detail": f"Cannot register the pairing handler (error {-rc})"}
    if rc == 0:
        return {"paired": True, "detail": "Paired successfully"}
    dbg = (f" [ceremony callback fired: {cb_result['fired']}, method: {cb_result['method']}, "
           f"response rc: {cb_result['send_rc']}]") if cb_result["fired"] else ""
    if rc == 1244:   # ERROR_NOT_AUTHENTICATED
        return {"paired": False, "detail": "Pairing failed after retry. On the iPhone open "
                "Settings → Bluetooth, tap ⓘ next to this computer and choose "
                "“Forget This Device”, then scan & pair again" + dbg}
    if rc in (183, 0x8007048F):
        return {"paired": True, "detail": "Already paired"}
    err_map = {
        1460: "Pairing failed: timed out — the phone showed no dialog or it was ignored. "
              "Keep the phone unlocked with Bluetooth Settings open and retry",
        1223: "Pairing failed: cancelled on the phone",
        87:   "Pairing failed: device not reachable — scan again and retry",
        1168: "Pairing failed: device not found — keep the phone's Bluetooth Settings screen open and rescan",
    }
    return {"paired": False,
            "detail": err_map.get(rc, f"Pairing failed (Windows error {rc}) — "
                                      "tap Pair on the phone when the request appears")}


def pair(address: str) -> dict:
    """Pair this computer with the chosen phone. Returns paired True/False."""
    address = address.strip().upper()
    if _IS_WIN:
        # Always run the full native ceremony: a cached "IsPaired" flag can be
        # a stale half-bond (Windows remembers the phone, the phone forgot the
        # computer), which would break the transfer later.
        return _win_pair_native(address)
    if _IS_MAC:
        rc, out = _run(["blueutil", "--pair", address], timeout=60)
        if rc == 0:
            return {"paired": True, "detail": "Paired successfully"}
        return {"paired": False, "detail": f"Pairing failed: {out.strip() or 'install blueutil (brew install blueutil)'}"}
    # Linux
    rc, out = _run(["bluetoothctl", "pair", address], timeout=60)
    if rc == 0 and ("Pairing successful" in out or "already" in out.lower()):
        _run(["bluetoothctl", "trust", address], timeout=15)
        return {"paired": True, "detail": "Paired successfully"}
    return {"paired": False, "detail": f"Pairing failed: {out.strip()[:300]}"}


# ==================== vCalendar builder ====================
def build_ics(events: list) -> bytes:
    """Full calendar of the user as one standards-compliant .ics file."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//MAP Studio//NexaCrew Bluetooth Sync//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for ev in events:
        fmt = "%Y%m%d" if ev.all_day else "%Y%m%dT%H%M%S"
        val = ";VALUE=DATE:" if ev.all_day else ":"
        lines += ["BEGIN:VEVENT",
                  f"UID:nexacrew-{ev.id}@mapstudio",
                  f"DTSTAMP:{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
                  f"DTSTART{val}{ev.start_at.strftime(fmt)}",
                  f"DTEND{val}{ev.end_at.strftime(fmt)}",
                  f"SUMMARY:{_esc(ev.title)}",
                  f"DESCRIPTION:{_esc(ev.description or '')}",
                  f"LOCATION:{_esc(ev.location or '')}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


# ==================== OBEX Object Push (minimal client) ====================
_OPP_CHANNELS = (12, 9, 4, 5, 10, 1)  # common RFCOMM channels for OPP


def _obex_connect(sock: socket.socket) -> None:
    pkt = struct.pack(">BHBBH", 0x80, 7, 0x10, 0x00, 8192)
    sock.sendall(pkt)
    resp = sock.recv(1024)
    if not resp or resp[0] != 0xA0:
        raise ConnectionError("Phone refused the OBEX connection "
                              f"(0x{resp[0]:02X} — on iPhone, OPP file push is not supported "
                              "by iOS; on Android, accept the incoming file prompt)"
                              if resp else "no OBEX response")


def _obex_put(sock: socket.socket, filename: str, payload: bytes,
              progress) -> None:
    name = filename.encode("utf-16-be") + b"\x00\x00"
    name_hdr = struct.pack(">BH", 0x01, len(name) + 3) + name
    len_hdr = struct.pack(">BI", 0xC3, len(payload))
    type_b = b"text/calendar\x00"
    type_hdr = struct.pack(">BH", 0x42, len(type_b) + 3) + type_b
    chunk_size = 4000
    sent = 0
    first = True
    while sent < len(payload):
        chunk = payload[sent:sent + chunk_size]
        sent += len(chunk)
        final = sent >= len(payload)
        body_id = 0x49 if final else 0x48
        body_hdr = struct.pack(">BH", body_id, len(chunk) + 3) + chunk
        headers = (name_hdr + type_hdr + len_hdr if first else b"") + body_hdr
        first = False
        opcode = 0x82 if final else 0x02
        pkt = struct.pack(">BH", opcode, len(headers) + 3) + headers
        sock.sendall(pkt)
        resp = sock.recv(1024)
        code = resp[0] if resp else 0
        if code not in (0x90, 0xA0):  # CONTINUE / SUCCESS
            raise ConnectionError(f"Phone rejected the transfer (OBEX 0x{code:02X}) — "
                                  "accept the incoming file on the phone screen")
        progress(sent, len(payload))


def _obex_disconnect(sock: socket.socket) -> None:
    try:
        sock.sendall(struct.pack(">BH", 0x81, 3))
        sock.recv(256)
    except OSError:
        pass


def _push_file(address: str, filename: str, payload: bytes, progress,
               stage=None) -> None:
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise RuntimeError("This computer's OS/Python build has no Bluetooth RFCOMM "
                           "socket support — Bluetooth push unavailable")
    last_err: Exception | None = None
    for i, ch in enumerate(_OPP_CHANNELS):
        if stage:
            stage(f"Trying file-transfer channel {i + 1}/{len(_OPP_CHANNELS)} (RFCOMM {ch})…")
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                          socket.BTPROTO_RFCOMM)
        s.settimeout(10)
        try:
            s.connect((address, ch))
            _obex_connect(s)
            _obex_put(s, filename, payload, progress)
            _obex_disconnect(s)
            s.close()
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            try:
                s.close()
            except OSError:
                pass
    raise ConnectionError(f"Could not reach the phone's file-transfer service "
                          f"on any channel: {last_err}")


# ==================== 4) full sync job (thread + progress) ====================
def start_sync(address: str, device_name: str, events: list) -> bool:
    """Run the whole pipeline in the background with live progress."""
    with _lock:
        if _state["running"]:
            return False
        _state.update({"running": True, "log": [], "status": "running",
                       "error": "", "pct": 0})

    ev_data = [type("E", (), {"id": e.id, "title": e.title,
                              "description": e.description, "location": e.location,
                              "start_at": e.start_at, "end_at": e.end_at,
                              "all_day": e.all_day})() for e in events]

    def job() -> None:
        try:
            _set("prepare", f"Preparing calendar export — {len(ev_data)} event(s)", 5)
            payload = build_ics(ev_data)
            fname = f"NexaCrew_Calendar_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.ics"
            _set("prepare", f"Calendar file built: {fname} ({len(payload):,} bytes)", 12)

            _set("verify", "Verifying Bluetooth adapter…", 16)
            st = adapter_status()
            if not st["available"]:
                raise RuntimeError("No Bluetooth adapter found on this computer")
            if not st["enabled"]:
                raise RuntimeError("Bluetooth is turned OFF — enable it in the OS settings")

            _set("pair", f"Pairing with “{device_name}” ({address})…", 22)
            pres = pair(address)
            if not pres["paired"]:
                _set("pair", pres["detail"], 22, "error", pres["detail"])
                return
            _set("pair", f"✅ {pres['detail']}", 35)

            _set("connect", f"Opening Bluetooth file-transfer channel to “{device_name}”…", 42)

            def prog(sent: int, total: int) -> None:
                pct = 45 + int(sent / max(total, 1) * 50)
                _set("transfer", f"Transferring calendar… {sent:,} / {total:,} bytes", pct)

            def chan(detail: str) -> None:
                _set("connect", detail, min(_state.get("pct", 42) + 1, 44))

            is_iphone = "iphone" in device_name.lower()
            try:
                _push_file(address, fname, payload, prog, stage=chan)
            except ConnectionError as ce:
                if is_iphone:
                    raise RuntimeError(
                        "iPhone does not accept Bluetooth file transfer (iOS blocks the "
                        "OBEX push service for all computers — an Apple restriction, not a "
                        "pairing problem). Use the “📱 iPhone subscription” shown on this "
                        "page instead: open the link on the iPhone and its Calendar app "
                        "subscribes and auto-syncs your NexaCrew calendar.") from ce
                raise
            _set("done",
                 f"✅ Sync complete — {len(ev_data)} event(s) sent to “{device_name}”. "
                 "Open the received file on the phone to import the events into its calendar.",
                 100, "done")
        except Exception as e:  # noqa: BLE001
            _set(_state.get("stage", "error"), f"❌ {e}", _state.get("pct", 0),
                 "error", str(e))

    threading.Thread(target=job, daemon=True, name="bt-calendar-sync").start()
    return True
