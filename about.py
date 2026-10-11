from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QDialog
from qfluentwidgets import FluentIcon as FIF, ThemeColor, TransparentToolButton, isDarkTheme, themeColor

from splash import DARK, FADE_IN_MS, FADE_OUT_MS, LIGHT, LOGO, LOGO_SIZE

AUTHOR = "Omega Msiska"
GITHUB = "https://github.com/mitosisx"
TAGLINE = "Watches your internet, and bounces Wi-Fi when it dies."

SIZE = (560, 420)
LOGO_CENTER_Y = 118

# (name, body text): the app's own text colours; surface, muted text and border come from the splash
DARK_TEXT = (QColor("#FFFFFF"), QColor("#D1D1D1"))
LIGHT_TEXT = (QColor("#1A1A1A"), QColor("#5C5C5C"))


class AboutDialog(QDialog):
    """About: the splash screen's card with the app's details under the logo.

    Fades in when opened; the close button, a click, Esc, Enter or Space fades it out again.
    The GitHub line is a link.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAccessibleName("About WifiGuard")
        self.setModal(True)
        self.setFixedSize(*SIZE)
        self.setMouseTracking(True)   # pointing-hand cursor over the link
        dark = isDarkTheme()
        self.surface, self.muted, self.border = DARK if dark else LIGHT
        self.bright, self.text = DARK_TEXT if dark else LIGHT_TEXT
        # the accent as the app shows it; on the light surface the lime is too faint for text,
        # so it uses the accent's darker shade (6:1)
        self.link = themeColor() if dark else ThemeColor.DARK_2.color()
        self.logo = QPixmap(LOGO)
        self.linkRect = QRectF()
        self._closing = False
        self.setWindowOpacity(0.0)

        self.closeBtn = TransparentToolButton(FIF.CLOSE, self)
        self.closeBtn.setFixedSize(32, 32)
        self.closeBtn.setToolTip("Close")
        self.closeBtn.setAccessibleName("Close")
        self.closeBtn.move(self.width() - 32 - 12, 12)
        self.closeBtn.clicked.connect(self.dismiss)

        self.fadeIn = QPropertyAnimation(self, b"windowOpacity", self)
        self.fadeIn.setDuration(FADE_IN_MS)
        self.fadeIn.setStartValue(0.0)
        self.fadeIn.setEndValue(1.0)
        self.fadeIn.setEasingCurve(QEasingCurve.OutCubic)

        self.fadeOut = QPropertyAnimation(self, b"windowOpacity", self)
        self.fadeOut.setDuration(FADE_OUT_MS)
        self.fadeOut.setEndValue(0.0)
        self.fadeOut.setEasingCurve(QEasingCurve.InCubic)   # exits faster than it enters
        self.fadeOut.finished.connect(lambda: QDialog.accept(self))

    def showEvent(self, e):
        super().showEvent(e)
        if self.parentWidget():
            win = self.parentWidget().window()
            self.move(win.geometry().center() - self.rect().center())
        if not self._closing:
            self.fadeIn.start()

    def dismiss(self):
        if self._closing:
            return
        self._closing = True
        self.fadeIn.stop()
        # from wherever the fade-in got to, so an early exit never pops back to full
        self.fadeOut.setStartValue(self.windowOpacity())
        self.fadeOut.start()

    def reject(self):   # Esc arrives here; let it fade too
        self.dismiss()

    def mousePressEvent(self, e):
        if self.linkRect.contains(e.position()):
            QDesktopServices.openUrl(QUrl(GITHUB))
        self.dismiss()

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.PointingHandCursor if self.linkRect.contains(e.position()) else Qt.ArrowCursor)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.dismiss()
            return
        super().keyPressEvent(e)

    def line(self, p, y, text, color, size=13, bold=False):
        """One centred line with the card's small-text tracking; returns where it was drawn."""
        f = QFont(self.font())
        f.setPixelSize(size)
        f.setBold(bold)
        f.setLetterSpacing(QFont.PercentageSpacing, 104)
        p.setFont(f)
        p.setPen(color)
        rect = QRectF(0, y, self.width(), size + 11)
        p.drawText(rect, Qt.AlignCenter, text)
        return p.boundingRect(rect, Qt.AlignCenter, text)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        # inset half a pixel so the 1px border is not clipped at the window edge
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
        p.fillPath(path, self.surface)
        p.setPen(self.border)
        p.drawPath(path)

        logoH = LOGO_SIZE * self.logo.height() / self.logo.width()
        top = LOGO_CENTER_Y - logoH / 2
        p.drawPixmap(QRectF((self.width() - LOGO_SIZE) / 2, top, LOGO_SIZE, logoH),
                     self.logo, QRectF(self.logo.rect()))

        y = top + logoH + 30
        self.line(p, y, "WifiGuard", self.bright, size=26, bold=True)
        self.line(p, y + 40, TAGLINE, self.text, size=14)
        self.line(p, y + 82, f"Software Engineer: {AUTHOR}", self.text)
        link = self.line(p, y + 108, GITHUB.removeprefix("https://"), self.link)
        self.linkRect = link.adjusted(-8, -6, 8, 6)   # a comfortable click target
        self.line(p, y + 140, "Copyright 2026", self.muted, size=12)
