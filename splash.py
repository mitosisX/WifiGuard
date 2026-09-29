import os

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.svg")

SURFACE = QColor("#0E1310")
TAGLINE = QColor("#A3ADA8")   # 8:1 on SURFACE

SHOW_MS = 3000
FADE_IN_MS = 450
FADE_OUT_MS = 250


class SplashScreen(QWidget):
    """Brand splash: fades in, holds, fades out after SHOW_MS. Click or Esc skips."""
    finished = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAccessibleName("WifiGuard is starting")
        self.resize(560, 340)
        self.renderer = QSvgRenderer(LOGO)
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
        p.fillPath(path, SURFACE)

        logoW = 340.0
        ar = self.renderer.defaultSize().height() / self.renderer.defaultSize().width()
        logoH = logoW * ar
        x = (self.width() - logoW) / 2
        y = (self.height() - logoH) / 2 - 14
        self.renderer.render(p, QRectF(x, y, logoW, logoH))

        f = QFont(self.font())
        f.setPixelSize(13)
        f.setLetterSpacing(QFont.PercentageSpacing, 104)   # small text: slightly positive tracking
        p.setFont(f)
        p.setPen(TAGLINE)
        p.drawText(QRectF(0, y + logoH + 26, self.width(), 24), Qt.AlignCenter, "WifiGuard")
