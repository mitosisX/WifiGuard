"""Thin ctypes wrapper over the Windows Native Wifi API (wlanapi.dll).

Used instead of `netsh wlan connect`, which on recent Windows 11 builds is
blocked unless Location services are on / the process is elevated.
"""
import ctypes
import struct
import subprocess
import time
from ctypes import wintypes

_wlan = ctypes.WinDLL("wlanapi")
_WLAN_INTF_OPCODE_CURRENT_CONNECTION = 7
_INTERFACE_STATE_CONNECTED = 1


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", ctypes.c_wchar * 256),
                ("isState", wintypes.DWORD)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class WLAN_PROFILE_INFO(ctypes.Structure):
    _fields_ = [("strProfileName", ctypes.c_wchar * 256), ("dwFlags", wintypes.DWORD)]


class WLAN_PROFILE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("ProfileInfo", WLAN_PROFILE_INFO * 1)]


class WLAN_CONNECTION_PARAMETERS(ctypes.Structure):
    _fields_ = [("wlanConnectionMode", wintypes.DWORD), ("strProfile", wintypes.LPCWSTR),
                ("pDot11Ssid", ctypes.c_void_p), ("pDesiredBssidList", ctypes.c_void_p),
                ("dot11BssType", wintypes.DWORD), ("dwFlags", wintypes.DWORD)]


_WLAN_CONNECTION_MODE_PROFILE = 0
_DOT11_BSS_TYPE_ANY = 3


class WlanError(RuntimeError):
    pass


class Wlan:
    """Context-managed handle to the WLAN service."""

    def __enter__(self):
        self.h = wintypes.HANDLE()
        ver = wintypes.DWORD()
        rc = _wlan.WlanOpenHandle(2, None, ctypes.byref(ver), ctypes.byref(self.h))
        if rc:
            raise WlanError(f"WlanOpenHandle failed ({rc})")
        return self

    def __exit__(self, *exc):
        _wlan.WlanCloseHandle(self.h, None)

    def is_connected(self, guid):
        """True while the adapter reports the 'connected' state (wlan_interface_state_connected == 1)."""
        p = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        if _wlan.WlanEnumInterfaces(self.h, None, ctypes.byref(p)):
            return True
        try:
            arr = ctypes.cast(ctypes.byref(p.contents.InterfaceInfo), ctypes.POINTER(WLAN_INTERFACE_INFO))
            for i in range(p.contents.dwNumberOfItems):
                if bytes(arr[i].InterfaceGuid) == bytes(guid):
                    return arr[i].isState == 1
            return True
        finally:
            _wlan.WlanFreeMemory(p)

    def connected_profile(self, guid):
        """Profile name of the current connection, or None when not connected.

        WlanQueryInterface(current_connection) returns the profile name without the Location
        permission that `netsh wlan show interfaces` now demands, and needs no PowerShell.
        """
        size, data = wintypes.DWORD(), ctypes.c_void_p()
        rc = _wlan.WlanQueryInterface(self.h, ctypes.byref(guid), _WLAN_INTF_OPCODE_CURRENT_CONNECTION,
                                      None, ctypes.byref(size), ctypes.byref(data), None)
        if rc:
            raise WlanError(f"WlanQueryInterface failed ({rc})")
        try:
            # WLAN_CONNECTION_ATTRIBUTES: DWORD isState, DWORD mode, WCHAR strProfileName[256], ...
            raw = ctypes.string_at(data.value, size.value)
        finally:
            _wlan.WlanFreeMemory(data)
        if struct.unpack_from("<I", raw, 0)[0] != _INTERFACE_STATE_CONNECTED:
            return None
        return raw[8:8 + 512].decode("utf-16-le").split(chr(0))[0] or None

    def interfaces(self):
        p = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        rc = _wlan.WlanEnumInterfaces(self.h, None, ctypes.byref(p))
        if rc:
            raise WlanError(f"WlanEnumInterfaces failed ({rc})")
        try:
            n = p.contents.dwNumberOfItems
            arr = ctypes.cast(ctypes.byref(p.contents.InterfaceInfo),
                              ctypes.POINTER(WLAN_INTERFACE_INFO))
            return [(arr[i].InterfaceGuid, arr[i].strInterfaceDescription) for i in range(n)]
        finally:
            _wlan.WlanFreeMemory(p)

    def profiles(self, guid):
        p = ctypes.POINTER(WLAN_PROFILE_INFO_LIST)()
        rc = _wlan.WlanGetProfileList(self.h, ctypes.byref(guid), None, ctypes.byref(p))
        if rc:
            raise WlanError(f"WlanGetProfileList failed ({rc})")
        try:
            n = p.contents.dwNumberOfItems
            arr = ctypes.cast(ctypes.byref(p.contents.ProfileInfo),
                              ctypes.POINTER(WLAN_PROFILE_INFO))
            return [arr[i].strProfileName for i in range(n)]
        finally:
            _wlan.WlanFreeMemory(p)

    def disconnect(self, guid):
        rc = _wlan.WlanDisconnect(self.h, ctypes.byref(guid), None)
        if rc:
            raise WlanError(f"WlanDisconnect failed ({rc})")

    def connect(self, guid, profile):
        params = WLAN_CONNECTION_PARAMETERS(_WLAN_CONNECTION_MODE_PROFILE, profile,
                                            None, None, _DOT11_BSS_TYPE_ANY, 0)
        rc = _wlan.WlanConnect(self.h, ctypes.byref(guid), ctypes.byref(params), None)
        if rc:
            raise WlanError(f"WlanConnect failed ({rc})")


def saved_profiles():
    with Wlan() as w:
        ifaces = w.interfaces()
        return w.profiles(ifaces[0][0]) if ifaces else []


def _net_connection_profile():
    """Fallback that works even when Windows' Location switch is off (the API call is denied)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -like 'Wi-Fi*' } "
             "| Select-Object -First 1).Name"],
            capture_output=True, text=True, timeout=15, creationflags=0x08000000).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    try:
        profiles = saved_profiles()
    except WlanError:
        return out
    if out in profiles:
        return out
    base = out.rsplit(" ", 1)[0] if out.rsplit(" ", 1)[-1].isdigit() else out   # Windows adds " 2", " 47"
    return base if base in profiles else out


def current_network():
    """Saved-profile name of the Wi-Fi network we're connected to, or None."""
    try:
        with Wlan() as w:
            ifaces = w.interfaces()
            return w.connected_profile(ifaces[0][0]) if ifaces else None
    except WlanError:
        return _net_connection_profile()


def reconnect(profile: str):
    """Disconnect the Wi-Fi adapter and reconnect to `profile`."""
    with Wlan() as w:
        ifaces = w.interfaces()
        if not ifaces:
            raise WlanError("No Wi-Fi interface found")
        guid = ifaces[0][0]
        w.disconnect(guid)
        deadline = time.monotonic() + 2.0    # reconnect as soon as the adapter has really dropped
        while w.is_connected(guid) and time.monotonic() < deadline:
            time.sleep(0.05)
        w.connect(guid, profile)
