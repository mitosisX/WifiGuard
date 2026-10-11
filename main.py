import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMenu, QSystemTrayIcon, QVBoxLayout,
                               QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, ComboBox, ExpandLayout,
                            FluentIcon as FIF, FluentIconBase, FluentWindow, IconWidget,
                            NavigationAvatarWidget, NavigationItemPosition, OptionsSettingCard,
                            PlainTextEdit, PrimaryPushButton, PushButton, RangeSettingCard,
                            ScrollArea, SettingCard, SettingCardGroup,
                            StrongBodyLabel, SubtitleLabel, SwitchSettingCard, Theme, TitleLabel, ToggleButton,
                            qconfig, setCustomStyleSheet, setTheme, setThemeColor)

import config
import store
import wlan
from about import AboutDialog
from config import cfg
from monitor import Monitor
from splash import SplashScreen
from stats_page import StatsInterface

# The env override lets a test build run beside a live copy without pinging it.
SERVER_NAME = os.environ.get("WIFIGUARD_INSTANCE", "WifiGuard-single-instance")
PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "profile.png")

GREEN, RED, AMBER = QColor("#5E8C0A"), QColor("#D13438"), QColor("#B26A00")
GREEN_D, RED_D, AMBER_D = QColor("#B0D135"), QColor("#FF6B6F"), QColor("#FFB347")


def tinted(icon, light, dark):
    return icon.colored(light, dark)


class BrandButton(PrimaryPushButton):
    """Primary button with dark text/icon. White on the lime brand green is only 1.9:1."""
    INK = "#151C05"

    QSS = f"PrimaryPushButton{{color:{INK}}}"

    def style(self):
        """Apply the dark-ink stylesheet (a custom __init__ would break the library's overloads)."""
        setCustomStyleSheet(self, self.QSS, self.QSS)
        return self

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        if isinstance(icon, FluentIconBase) and self.isEnabled():
            icon = icon.icon(color=QColor(self.INK))
        PushButton._drawIcon(self, icon, painter, rect, state)


class StatCard(CardWidget):
    def __init__(self, icon, title, parent=None):
        super().__init__(parent)
        self.value = StrongBodyLabel("-", self)
        iconWidget = IconWidget(icon, self)
        iconWidget.setFixedSize(24, 24)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 20, 14)
        row.setSpacing(14)
        row.addWidget(iconWidget, 0)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(CaptionLabel(title, self))
        col.addWidget(self.value)
        row.addLayout(col, 1)


class HomeInterface(QWidget):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.setObjectName("home")
        self.monitor = monitor

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 30, 36, 30)
        root.setSpacing(18)
        root.addWidget(TitleLabel("WifiGuard", self))
        root.addWidget(BodyLabel("Watches your internet, and bounces Wi-Fi when it dies.", self))

        self.hero = CardWidget(self)
        hero = QHBoxLayout(self.hero)
        hero.setContentsMargins(28, 24, 28, 24)
        hero.setSpacing(22)
        self.icon = IconWidget(FIF.WIFI, self.hero)
        self.icon.setFixedSize(56, 56)
        hero.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = SubtitleLabel("Starting...", self.hero)
        self.sub = BodyLabel("", self.hero)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        hero.addLayout(col, 1)
        root.addWidget(self.hero)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.netCard = StatCard(FIF.GLOBE, "Network", self)
        self.countCard = StatCard(FIF.SYNC, "Reconnects today", self)
        self.dropCard = StatCard(FIF.HISTORY, "Last drop", self)
        self.countCard.value.setText(str(monitor.reconnects))
        self.dropCard.value.setText(monitor.last_drop)
        for c in (self.netCard, self.countCard, self.dropCard):
            stats.addWidget(c, 1)
        root.addLayout(stats)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.reconnectBtn = BrandButton(FIF.SYNC, "Reconnect now", self).style()
        self.pauseBtn = ToggleButton(FIF.PAUSE, "Pause monitoring", self)
        actions.addWidget(self.reconnectBtn)
        actions.addWidget(self.pauseBtn)
        actions.addStretch(1)
        root.addLayout(actions)
        root.addStretch(1)

        self.reconnectBtn.clicked.connect(monitor.reconnect_now)
        self.pauseBtn.toggled.connect(self.setPaused)
        monitor.status.connect(self.onStatus)
        monitor.stats.connect(self.onStats)
        monitor.recovering.connect(self.onRecovering)

    def setPaused(self, paused):
        self.monitor.set_paused(paused)
        self.pauseBtn.setText("Resume monitoring" if paused else "Pause monitoring")
        self.pauseBtn.setIcon(FIF.PLAY if paused else FIF.PAUSE)

    def onStatus(self, up, net):
        if net == "paused":
            self.title.setText("Monitoring paused")
            self.sub.setText("Nothing will be reconnected until you resume.")
            self.icon.setIcon(FIF.PAUSE)
            self.icon.setAccessibleName('Monitoring paused')
            return
        self.netCard.value.setText(net or "unknown")
        if up:
            self.title.setText("Internet connected")
            self.sub.setText("Everything looks healthy.")
            self.icon.setIcon(tinted(FIF.WIFI, GREEN, GREEN_D))
        else:
            self.title.setText("No internet detected")
            self.sub.setText("Will reconnect after several failed checks...")
            self.icon.setIcon(tinted(FIF.CLOSE, RED, RED_D))

    def onStats(self, count, drop):
        self.countCard.value.setText(str(count))
        self.dropCard.value.setText(drop)

    def onRecovering(self, on):
        self.reconnectBtn.setEnabled(not on)
        if on:
            self.title.setText("Reconnecting Wi-Fi...")
            self.sub.setText("Disconnecting and reconnecting to your network.")
            self.icon.setIcon(tinted(FIF.SYNC, AMBER, AMBER_D))


class LogInterface(QWidget):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.setObjectName("log")
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 30, 36, 30)
        root.setSpacing(14)
        root.addWidget(TitleLabel("Activity", self))
        self.text = PlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.document().setMaximumBlockCount(1000)
        root.addWidget(self.text, 1)
        # Earlier lines from today come back after a restart; this runs before the monitor thread
        # starts, so the new session's lines always land after them.
        for when, msg in store.log_today():
            self.text.appendPlainText(f"{store.clock(when)}  {msg}")
        monitor.log.connect(self.text.appendPlainText)


class NetworkCard(SettingCard):
    """Pick which network to reconnect to; 'Auto' follows the current one."""

    def __init__(self, parent=None):
        super().__init__(FIF.WIFI, "Network to reconnect to",
                         "Auto reconnects to whichever Wi-Fi you're currently on", parent)
        self.combo = ComboBox(self)
        self.combo.setMinimumWidth(220)
        self.hBoxLayout.addWidget(self.combo, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        try:
            names = wlan.saved_profiles()
        except Exception:  # noqa: BLE001
            names = []
        options = ["Auto"] + names
        self.combo.addItems(options)
        cur = cfg.network.value
        self.combo.setCurrentText(cur if cur in options else "Auto")
        self.combo.currentTextChanged.connect(lambda t: qconfig.set(cfg.network, t))


class SettingsInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settings")
        self.view = QWidget()
        self.view.setObjectName("scrollWidget")
        self.expand = ExpandLayout(self.view)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setViewportMargins(0, 70, 0, 20)
        self.label = TitleLabel("Settings", self)
        self.label.move(36, 30)

        mon = SettingCardGroup("Monitoring", self.view)
        mon.addSettingCard(RangeSettingCard(cfg.interval, FIF.STOP_WATCH, "Check every (seconds)",
                                            "How often to test the internet connection", mon))
        mon.addSettingCard(RangeSettingCard(cfg.threshold, FIF.CANCEL,
                                            "Failed checks before reconnecting",
                                            "Higher values avoid reacting to brief blips", mon))
        mon.addSettingCard(RangeSettingCard(cfg.grace, FIF.HISTORY,
                                            "Wait after reconnecting (seconds)",
                                            "Gives the router time to hand out an address", mon))
        mon.addSettingCard(NetworkCard(mon))

        note = SettingCardGroup("Notifications", self.view)
        note.addSettingCard(SwitchSettingCard(FIF.RINGER, "Notify when reconnecting",
                                              "Tray notification the moment WifiGuard bounces your Wi-Fi",
                                              cfg.notifyReconnect, note))
        note.addSettingCard(SwitchSettingCard(FIF.COMPLETED, "Notify when internet is back",
                                              "Tray notification after an outage ends, with its length",
                                              cfg.notifyRecovered, note))

        app = SettingCardGroup("Application", self.view)
        self.startup = SwitchSettingCard(FIF.POWER_BUTTON, "Start with Windows",
                                         "Launch minimized to the tray at sign-in", parent=app)
        self.startup.switchButton.setChecked(config.startup_enabled())
        self.startup.switchButton.checkedChanged.connect(config.set_startup)
        app.addSettingCard(self.startup)
        app.addSettingCard(SwitchSettingCard(FIF.MINIMIZE, "Keep running in tray on close",
                                             "On: closing the window keeps monitoring in the tray. Off: closing quits WifiGuard",
                                             cfg.closeToTray, app))

        self.expand.setSpacing(28)
        self.expand.setContentsMargins(36, 0, 36, 0)
        self.expand.addWidget(mon)
        look = SettingCardGroup("Appearance", self.view)
        look.addSettingCard(OptionsSettingCard(qconfig.themeMode, FIF.BRUSH, "Theme",
                                               "Change the appearance of the app",
                                               texts=["Light", "Dark", "Use system setting"],
                                               parent=look))

        self.expand.addWidget(look)
        self.expand.addWidget(note)
        self.expand.addWidget(app)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}"
                           "QWidget#scrollWidget{background:transparent}")


class MainWindow(FluentWindow):
    def __init__(self, monitor, startHidden):
        super().__init__()
        self.monitor = monitor
        self.quitting = False
        self.everShown = False
        self._quitDone = False
        self.home = HomeInterface(monitor, self)
        self.logPage = LogInterface(monitor, self)
        self.stats = StatsInterface(monitor, self)
        self.settings = SettingsInterface(self)
        self.addSubInterface(self.home, FIF.WIFI, "Status")
        self.addSubInterface(self.stats, FIF.PIE_SINGLE, "Statistics")
        self.addSubInterface(self.logPage, FIF.HISTORY, "Activity")
        self.navigationInterface.addWidget(
            routeKey="about",
            widget=NavigationAvatarWidget("About", PROFILE),
            onClick=self.showAbout,
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(self.settings, FIF.SETTING, "Settings", NavigationItemPosition.BOTTOM)

        self.resize(900, 620)
        self.setMinimumSize(720, 520)
        self.setWindowTitle("WifiGuard")
        self.setWindowIcon(FIF.WIFI.icon(color=GREEN))
        self.navigationInterface.setAcrylicEnabled(True)
        self.navigationInterface.setMinimumExpandWidth(700)   # show text labels next to icons
        self.navigationInterface.setExpandWidth(200)

        self.buildTray()
        monitor.notify.connect(self.onNotify)

    def buildTray(self):
        self.tray = QSystemTrayIcon(FIF.WIFI.icon(color=GREEN_D), self)
        self.tray.setToolTip("WifiGuard")
        menu = QMenu()
        menu.addAction("Open WifiGuard", self.showNormalAndRaise)
        menu.addAction("Reconnect now", self.monitor.reconnect_now)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.trayMenu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.showNormalAndRaise() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def showAbout(self):
        AboutDialog(self).exec()

    def onNotify(self, title, msg):
        """Tray balloon, regardless of whether the window is open; each kind has its own toggle."""
        item = cfg.notifyRecovered if title == "Internet is back" else cfg.notifyReconnect
        if item.value:
            self.tray.showMessage(title, msg, QSystemTrayIcon.Information, 4000)

    def showNormalAndRaise(self):
        firstShow = not self.everShown
        if firstShow:
            # size is re-applied here: while hidden behind the splash Qt reset it to 500x500
            self.everShown = True
            self.resize(900, 620)
            self.move(QApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        self.show()
        if firstShow:
            self.navigationInterface.panel.expand(useAni=False)   # icon + text label, not icon-only
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def quit(self):
        if self._quitDone:
            return
        self._quitDone = True
        self.quitting = True
        self.tray.hide()
        self.monitor.stop()
        self.monitor.wait(3000)
        QApplication.quit()

    def closeEvent(self, e):
        # Without a tray icon a hidden window could never be reopened, so only hide when it exists.
        if cfg.closeToTray.value and not self.quitting and self.tray.isVisible():
            e.ignore()
            self.hide()
            self.tray.showMessage("WifiGuard", "Still watching your connection from the tray.",
                                  QSystemTrayIcon.Information, 2500)
        else:
            # Setting off (or no tray icon): closing the window must end the whole process. The app
            # deliberately outlives its windows, so without this the monitor and tray icon kept
            # running with nothing on screen.
            e.accept()
            self.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # single instance: ask a running copy to show itself, then exit
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    if not server.listen(SERVER_NAME):   # lost a startup race with another instance
        return 0

    firstRun = not os.path.exists(config.CONFIG_PATH)
    config.load()
    if firstRun:   # new installs follow the system theme; afterwards the saved choice wins
        setTheme(Theme.AUTO)
    # The Theme option card only writes the config value; without this the stylesheets never
    # refresh, so switching Dark -> Light left half the UI dark (same wiring as the gallery example).
    qconfig.themeChanged.connect(setTheme)
    setThemeColor(config.BRAND)   # older config files still carry the previous accent
    store.prune_log()
    monitor = Monitor(cfg)
    silent = "--tray" in sys.argv
    win = MainWindow(monitor, startHidden=True)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.showNormalAndRaise()))
    # Windows logoff/shutdown asks every window to close; refusing (hide-to-tray) would block it.
    app.commitDataRequest.connect(lambda _mgr: setattr(win, "quitting", True), Qt.DirectConnection)
    monitor.start()   # monitoring begins immediately; the splash never delays protection
    if not silent:
        splash = SplashScreen()
        splash.finished.connect(win.showNormalAndRaise)
        splash.start()
    code = app.exec()
    monitor.stop()
    monitor.wait(3000)
    return code


if __name__ == "__main__":
    sys.exit(main())
