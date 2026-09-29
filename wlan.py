"""Thin ctypes wrapper over the Windows Native Wifi API (wlanapi.dll).

Used instead of `netsh wlan connect`, which on recent Windows 11 builds is
blocked unless Location services are on / the process is elevated.
"""
import ctypes
import re
import subprocess
from ctypes import wintypes

_wlan = ctypes.WinDLL("wlanapi")
_CREATE_NO_WINDOW = 0x08000000


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


def _ps(cmd: str) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                         text=True, creationflags=_CREATE_NO_WINDOW, timeout=15)
    return out.stdout.strip()


def saved_profiles():
    with Wlan() as w:
        ifaces = w.interfaces()
        return w.profiles(ifaces[0][0]) if ifaces else []


def current_network():
    """Name of the connected Wi-Fi network's saved profile, or None.

    Uses the network-connection profile (no location permission needed) and
    maps it onto a saved WLAN profile (Windows appends ' 2', ' 47'... to names).
    """
    name = _ps("(Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -like 'Wi-Fi*' } "
               "| Select-Object -First 1).Name")
    if not name:
        return None
    try:
        profiles = saved_profiles()
    except WlanError:
        return name
    if name in profiles:
        return name
    base = re.sub(r"\s+\d+$", "", name)
    return base if base in profiles else name


def reconnect(profile: str):
    """Disconnect the Wi-Fi adapter and reconnect to `profile`."""
    import time
    with Wlan() as w:
        ifaces = w.interfaces()
        if not ifaces:
            raise WlanError("No Wi-Fi interface found")
        guid = ifaces[0][0]
        w.disconnect(guid)
        time.sleep(1.5)
        w.connect(guid, profile)
