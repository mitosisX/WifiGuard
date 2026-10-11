import os

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import isDarkTheme

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")
LOGO_SIZE = 160.0   # drawn size on screen; the PNG is 200px so it never upscales

# (surface, muted text, border): the main window's content area, so the splash and the
# About card look like part of the app
DARK = (QColor("#272727"), QColor("#9D9D9D"), QColor(255, 255, 255, 20))
LIGHT = (QColor("#F9F9F9"), QColor("#6B6B6B"), QColor(0, 0, 0, 25))

SHOW_MS = 3000
FADE_IN_MS = 450
FADE_OUT_MS = 250


class SplashScreen(QWidget):
    """Splash: fades in, holds, fades out after SHOW_MS. Click or Esc skips."""
    finished = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAccessibleName("WifiGuard is starting")
        self.resize(560, 340)
        self.surface, self.tagline, self.border = DARK if isDarkTheme() else LIGHT
        self.logo = QPixmap(LOGO)
        self._done = False
        self.setWindowOpacity(0.0)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

        self.fadeIn = QPropertyAnimation(self, b"windowOpacity", self)
        self.fadeIn.setDuration(FADE_IN_MS)
        self.fadeIn.setStartValue(0.0)
        self.fadeIn.setEndValue(1.0)
        self.fadeIn.setEasingCurve(QEasingCurve.OutCubic)

        self.fadeOut = QPropertyAnimation(self, b"windowOpacity", self)
        self.fadeOut.setDuration(FADE_OUT_MS)
        self.fadeOut.setStartValue(1.0)
        self.fadeOut.setEndValue(0.0)
        self.fadeOut.setEasingCurve(QEasingCurve.InCubic)   # exits faster than it enters
        self.fadeOut.finished.connect(self._finish)

        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.dismiss)

    def start(self):
        self.show()
        self.fadeIn.start()
        self.timer.start(SHOW_MS - FADE_OUT_MS)   # total on screen == SHOW_MS

    def dismiss(self):
        if self._done or self.fadeOut.state() == QPropertyAnimation.Running:
            return
        self.fadeIn.stop()
        self.fadeOut.setStartValue(self.windowOpacity())
        self.fadeOut.start()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self.hide()
        self.finished.emit()

    def mousePressEvent(self, e):
        self.dismiss()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Space):
            self.dismiss()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 20, 20)
        p.fillPath(path, self.surface)
        p.setPen(self.border)
        p.drawPath(path)

        p.setRenderHint(QPainter.SmoothPixmapTransform)
        logoW = LOGO_SIZE
        logoH = logoW * self.logo.height() / self.logo.width()
        x = (self.width() - logoW) / 2
        y = (self.height() - logoH) / 2 - 14
        p.drawPixmap(QRectF(x, y, logoW, logoH), self.logo, QRectF(self.logo.rect()))

        f = QFont(self.font())
        f.setPixelSize(13)
        f.setLetterSpacing(QFont.PercentageSpacing, 104)   # small text: slightly positive tracking
        p.setFont(f)
        p.setPen(self.tagline)
        p.drawText(QRectF(0, y + logoH + 26, self.width(), 24), Qt.AlignCenter, "WifiGuard")
