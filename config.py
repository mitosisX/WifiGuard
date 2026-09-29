import os
import sys
import winreg

from qfluentwidgets import (QConfig, ConfigItem, RangeConfigItem, RangeValidator, BoolValidator,
                            qconfig)

APP_NAME = "WifiGuard"
BRAND = "#B0D135"
DATA_DIR = os.path.join(os.environ.get("APPDATA", "."), APP_NAME)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class Config(QConfig):
    interval = RangeConfigItem("Monitor", "IntervalSeconds", 5, RangeValidator(2, 60))
    threshold = RangeConfigItem("Monitor", "FailuresBeforeReconnect", 3, RangeValidator(1, 10))
    grace = RangeConfigItem("Monitor", "GraceSeconds", 15, RangeValidator(5, 60))
    network = ConfigItem("Monitor", "Network", "Auto")
    closeToTray = ConfigItem("App", "CloseToTray", True, BoolValidator())
    notifyReconnect = ConfigItem("Notifications", "OnReconnect", True, BoolValidator())
    notifyRecovered = ConfigItem("Notifications", "OnRecovered", True, BoolValidator())


cfg = Config()


def load():
    os.makedirs(DATA_DIR, exist_ok=True)
    qconfig.load(CONFIG_PATH, cfg)


def _launch_command():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    # __file__-relative, not sys.argv[0]: a relative argv[0] breaks once the cwd changes
    # (e.g. after a file dialog), which would register a Run entry that points nowhere.
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return f'"{exe}" "{script}" --tray'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass
