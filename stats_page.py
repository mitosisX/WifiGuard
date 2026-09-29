from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QTableWidgetItem, QVBoxLayout,
                               QWidget)
from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, FluentIcon as FIF, InfoBar,
                            InfoBarPosition, MessageBox, PushButton, ScrollArea, StrongBodyLabel, SubtitleLabel,
                            TableWidget, TitleLabel, isDarkTheme)

import store

KIND_TEXT = {"drop": "Internet dropped", "auto": "Auto-reconnect",
             "manual": "Manual reconnect", "recovered": "Internet restored"}


def fmt_duration(seconds):
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"


class DayChart(QWidget):
    """Reconnects per day. Every bar has its value printed on it, so nothing relies on colour alone."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.setMinimumHeight(190)

    def setData(self, data):
        self.data = data
        total = sum(n for _, n in data)
        self.setAccessibleName(f"Automatic reconnects per day, last {len(data)} days: {total} in total")
        self.update()

    def paintEvent(self, e):
        if not self.data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = isDarkTheme()
        bar = QColor("#B0D135" if dark else "#5E8C0A")
        idle = QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 18)
        text = QColor(255, 255, 255, 190) if dark else QColor(0, 0, 0, 170)

        n = len(self.data)
        top, bottom = 22, 30
        plotH = self.height() - top - bottom
        slot = self.width() / n
        barW = min(slot * 0.62, 34)
        peak = max(max(c for _, c in self.data), 1)
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        today = datetime.now().date()
        for i, (day, count) in enumerate(self.data):
            x = i * slot + (slot - barW) / 2
            p.setPen(Qt.NoPen)
            p.setBrush(idle)
            p.drawRoundedRect(QRectF(x, top, barW, plotH), 5, 5)
            if count:
                h = max(plotH * count / peak, 6)
                p.setBrush(bar)
                p.drawRoundedRect(QRectF(x, top + plotH - h, barW, h), 5, 5)
            p.setPen(text)
            if count:
                p.drawText(QRectF(i * slot, top + plotH - max(plotH * count / peak, 6) - 20, slot, 18),
                           Qt.AlignCenter, str(count))
            label = "Today" if day == today else (f"{day:%d}" if n > 8 else f"{day:%a}")
            if n <= 8 or i % 2 == (n - 1) % 2 or day == today:
                p.drawText(QRectF(i * slot - 8, top + plotH + 6, slot + 16, 18), Qt.AlignCenter, label)


class MiniStat(CardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 14, 20, 14)
        col.setSpacing(2)
        col.addWidget(CaptionLabel(title, self))
        self.value = SubtitleLabel("-", self)
        col.addWidget(self.value)


class StatsInterface(ScrollArea):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.setObjectName("stats")
        view = QWidget()
        view.setObjectName("statsView")
        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea{background:transparent;border:none}"
                           "QWidget#statsView{background:transparent}")
        root = QVBoxLayout(view)
        root.setContentsMargins(36, 30, 36, 24)
        root.setSpacing(14)

        head = QHBoxLayout()
        head.addWidget(TitleLabel("Statistics", self))
        head.addStretch(1)
        self.exportBtn = PushButton(FIF.SAVE, "Export CSV", self)
        self.clearBtn = PushButton(FIF.DELETE, "Clear history", self)
        head.addWidget(self.exportBtn)
        head.addWidget(self.clearBtn)
        root.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.today = MiniStat("Reconnects today", self)
        self.week = MiniStat("Last 7 days", self)
        self.avg = MiniStat("Average outage (30 days)", self)
        for c in (self.today, self.week, self.avg):
            row.addWidget(c, 1)
        root.addLayout(row)

        card = CardWidget(self)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 10)
        cl.addWidget(StrongBodyLabel("Automatic reconnects per day", card))
        self.chart = DayChart(card)
        cl.addWidget(self.chart)
        root.addWidget(card)

        root.addWidget(StrongBodyLabel("History", self))
        self.table = TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["When", "Event", "Network", "Outage length"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(TableWidget.NoEditTriggers)
        self.table.setSelectionMode(TableWidget.NoSelection)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.empty = BodyLabel("No events yet. Drops and reconnects will show up here.", self)
        self.empty.setAlignment(Qt.AlignCenter)
        self.table.setMinimumHeight(300)
        root.addWidget(self.table)
        root.addWidget(self.empty)

        self.exportBtn.clicked.connect(self.exportCsv)
        self.clearBtn.clicked.connect(self.clearHistory)
        monitor.historyChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        days = store.reconnects_per_day(14)
        self.chart.setData(days)
        self.today.value.setText(str(days[-1][1]))
        self.week.value.setText(str(sum(n for _, n in days[-7:])))
        avg = store.average_downtime()
        self.avg.value.setText(fmt_duration(avg) if avg is not None else "-")

        rows = store.recent(200)
        self.table.setRowCount(len(rows))
        for r, (ts, kind, network, downtime) in enumerate(rows):
            when = datetime.fromisoformat(ts)
            cells = [when.strftime("%b %d, %H:%M:%S"), KIND_TEXT.get(kind, kind), network or "-",
                     fmt_duration(downtime) if kind == "recovered" else "-"]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)

    def exportCsv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export history", "wifiguard-history.csv",
                                              "CSV files (*.csv)")
        if path:
            n = store.export_csv(path)
            InfoBar.success("Exported", f"{n} events saved.", duration=3000,
                            position=InfoBarPosition.TOP, parent=self.window())

    def clearHistory(self):
        box = MessageBox("Clear history?", "All recorded drops and reconnects will be deleted. "
                         "This can't be undone.", self.window())
        box.yesButton.setText("Clear")
        box.cancelButton.setText("Cancel")
        if box.exec():
            store.clear()
            self.refresh()
