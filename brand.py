"""Logo helpers shared by the title bar (the splash draws its own, larger copy)."""
import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QLabel
from qfluentwidgets import isDarkTheme, qconfig

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.svg")
# Brand green on dark; a deeper green of the same hue on light (the brand green is 1.9:1 on white).
GREEN_ON_DARK, GREEN_ON_LIGHT = "#B0D135", "#5E8C0A"


def logo_pixmap(height, dark):
    """The logo tinted for the theme, rendered crisply for the screen's pixel ratio."""
    with open(LOGO, "rb") as f:
        svg = f.read().replace(b"#b0d135", (GREEN_ON_DARK if dark else GREEN_ON_LIGHT).encode())
    r = QSvgRenderer(svg)
    size = r.defaultSize()
    dpr = QApplication.primaryScreen().devicePixelRatio()
    w = height * size.width() / size.height()
    pm = QPixmap(int(w * dpr) + 1, int(height * dpr) + 1)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    r.render(p, QRectF(0, 0, w, height))
    p.end()
    return pm


class TitleLogo(QLabel):
    """Company logo for the title bar; recolours itself when the theme changes."""

    def __init__(self, parent=None, height=13):
        super().__init__(parent)
        self._h = height
        self.setAccessibleName("WifiGuard")
        self.setToolTip("WifiGuard")
        self.setStyleSheet("background: transparent")
        self._refresh()
        qconfig.themeChangedFinished.connect(self._refresh)

    def _refresh(self):
        pm = logo_pixmap(self._h, isDarkTheme())
        self.setPixmap(pm)
        self.setFixedSize(int(pm.width() / pm.devicePixelRatio()) + 1, self._h + 2)
