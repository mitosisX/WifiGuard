"""Freeze WifiGuard into a Windows executable with PyInstaller.

    python build.py              folder build  -> dist/WifiGuard/WifiGuard.exe   (recommended)
    python build.py --onefile    single file   -> dist/WifiGuard.exe
    python build.py --zip        also zip the result for sharing
    python build.py --clean      delete build/ and dist/ first

Folder builds start faster (a onefile exe unpacks itself on every launch, which delays the
tray icon at sign-in) and trip antivirus heuristics less often, so they are the default.
Needs:  pip install pyinstaller   (plus the packages in requirements.txt)
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))

# Qt files PyInstaller copies as dependencies although a QtWidgets-only app never loads them.
# (Folder builds only: a onefile exe is packed in one step, so it can't be pruned afterwards.)
PRUNE = ("PySide6/opengl32sw.dll", "PySide6/translations", "PySide6/Qt6Quick*.dll", "PySide6/Qt6Qml*.dll",
         "PySide6/Qt6Pdf*.dll", "PySide6/Qt6VirtualKeyboard*.dll", "PySide6/Qt6Designer*.dll",
         "PySide6/Qt6ShaderTools.dll", "PySide6/Qt6OpenGL.dll", "PySide6/plugins/generic",
         "PySide6/plugins/networkinformation", "PySide6/plugins/tls", "PySide6/plugins/qmltooling")
NAME = "WifiGuard"
ICON = os.path.join(ROOT, "assets", "wifiguard.ico")
BRAND, SURFACE = "#B0D135", "#0E1310"


def make_icon():
    """Draw the app icon (brand-green Wi-Fi glyph on a dark rounded tile) into assets/wifiguard.ico."""
    if os.path.exists(ICON):
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import FluentIcon as FIF

    app = QApplication.instance() or QApplication([])   # noqa: F841 - Qt needs an app object
    size = 256
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, size, size), 56, 56)
    p.fillPath(tile, QColor(SURFACE))
    FIF.WIFI.icon(color=QColor(BRAND)).paint(p, 40, 40, size - 80, size - 80)
    p.end()
    tmp = os.path.join(ROOT, "assets", "_icon.png")
    img.save(tmp)
    Image.open(tmp).save(ICON, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    os.remove(tmp)
    print(f"created {os.path.relpath(ICON, ROOT)}")


def prune(folder):
    """Delete the PRUNE globs from a folder build; returns MB freed."""
    import glob
    freed = 0
    for pattern in PRUNE:
        for path in glob.glob(os.path.join(folder, "_internal", *pattern.split("/"))):
            if os.path.isdir(path):
                freed += sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)
                shutil.rmtree(path)
            else:
                freed += os.path.getsize(path)
                os.remove(path)
    return freed / 1e6


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onefile", action="store_true", help="build a single exe instead of a folder")
    ap.add_argument("--zip", action="store_true", help="zip the build output")
    ap.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller is missing.  Run:  python -m pip install pyinstaller")

    if args.clean:
        for d in ("build", "dist"):
            shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)

    make_icon()

    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--name", NAME,
        "--windowed",                                   # no console window
        "--icon", ICON,
        "--add-data", f"{os.path.join(ROOT, 'assets')}{os.pathsep}assets",   # logo svg (splash, title bar)
        "--collect-submodules", "qfluentwidgets",       # its resources/icons are imported dynamically
        "--collect-submodules", "qframelesswindow",
        "--hidden-import", "PySide6.QtSvg",
        # Big Qt parts this app never touches; keeps the bundle small.
        *[f"--exclude-module={m}" for m in (
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest",
            # dragged in by other packages' hooks, never imported by the app at runtime
            "babel", "sphinx", "docutils", "jinja2", "cryptography", "setuptools", "pytest",
            "IPython", "matplotlib", "pandas", "tkinter")],
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    if args.onefile:
        cmd.append("--onefile")
    cmd.append(os.path.join(ROOT, "main.py"))

    print("running:", " ".join(cmd[3:8]), "...")
    subprocess.run(cmd, check=True, cwd=ROOT)

    out = os.path.join(ROOT, "dist", f"{NAME}.exe" if args.onefile else NAME)
    exe = out if args.onefile else os.path.join(out, f"{NAME}.exe")
    if not os.path.exists(exe):
        sys.exit("build finished but the exe is missing - check the PyInstaller output above")
    if not args.onefile:
        print(f"pruned {prune(out):.0f} MB of unused Qt files")
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(out) for f in fs) if not args.onefile \
        else os.path.getsize(out)
    print(f"\nbuilt {os.path.relpath(exe, ROOT)}  ({size / 1e6:.0f} MB)")

    if args.zip:
        archive = os.path.join(ROOT, "dist", f"{NAME}-{'onefile' if args.onefile else 'folder'}.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            if args.onefile:
                z.write(out, os.path.basename(out))
            else:
                for dp, _, fs in os.walk(out):
                    for f in fs:
                        full = os.path.join(dp, f)
                        z.write(full, os.path.relpath(full, os.path.dirname(out)))
        print(f"zipped {os.path.relpath(archive, ROOT)}  ({os.path.getsize(archive) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
