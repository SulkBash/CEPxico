# PyInstaller build: one folder, dist/cepxico/, with two executables sharing it:
#   cepxico      console: command line, or the desktop app when run without files
#   cepxico-gui  desktop app without a console window
# (cepxico.exe and cepxico-gui.exe on Windows). On macOS there is also
# dist/CEPxico.app, the desktop app as a double-clickable application.
#
# Build on each system for that system (PyInstaller doesn't cross-compile):
#   pip install -e ".[build]"  then  pyinstaller packaging/cepxico.spec --noconfirm
# A folder (not --onefile) starts quickly; onefile would unpack everything to a temp
# folder on every launch.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# On a venv made from Anaconda's Python, the DLLs that _ctypes, _bz2, _lzma, pyexpat and
# _ssl load (ffi-8.dll, ...) live in <conda>/Library/bin. PyInstaller only looks there
# for conda environments themselves, so without this the app fails with
# "DLL load failed while importing _ctypes".
_conda_bin = Path(sys.base_prefix, "Library", "bin")
if _conda_bin.is_dir():
    os.environ["PATH"] = f"{_conda_bin}{os.pathsep}{os.environ.get('PATH', '')}"

DATAS = (
    # The AGPL travels with every copy of the app (its source is the GitHub repository).
    [(str(Path(SPECPATH).parent / "LICENSE"), ".")]
    + collect_data_files("cepxico")  # data/banks.toml
    + collect_data_files("rapidocr")  # bundled ONNX models and their YAML configs
)
EXCLUDES = [
    # Optional OCR engines/backends: gigabytes if they happen to be installed.
    "torch",
    "torchvision",
    "easyocr",
    "paddle",
    "openvino",
    "tensorrt",
    # Installed alongside PyMuPDF but unused.
    "pymupdf4llm",
    "pymupdf_layout",
    "matplotlib",
    "IPython",
    "pytest",
    # Qt modules the desktop app doesn't use (it needs only QtCore, QtGui and QtWidgets).
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtOpenGL",
    "PySide6.QtSvg",
    "PySide6.QtPdf",
    "tkinter",
]

# Files pulled in by packages but never used here (about 95 MB).
UNUSED = (
    "pymupdf/layout/",  # PyMuPDF's layout-analysis models
    "pymupdf/mupdf-devel/",  # C headers and import libraries
    "cv2/opencv_videoio_ffmpeg",  # OpenCV video codecs
    "PySide6/opengl32sw.dll",  # Qt's software OpenGL; the app draws no OpenGL
)


def needed(path):
    path = path.replace("\\", "/")
    if path.startswith("PySide6/translations/"):  # Qt's own words: only Spanish (English is built in)
        return path.endswith("_es.qm")
    return not path.startswith(UNUSED)


def keep(entries):
    return [e for e in entries if needed(e[0])]


def build(script, name, console):
    analysis = Analysis([script], datas=DATAS, excludes=EXCLUDES)
    analysis.binaries = keep(analysis.binaries)
    analysis.datas = keep(analysis.datas)
    exe = EXE(
        PYZ(analysis.pure),
        analysis.scripts,
        exclude_binaries=True,
        name=name,
        console=console,
        upx=False,
    )
    return analysis, exe


cli, cli_exe = build("cepxico_cli.py", "cepxico", console=True)
gui, gui_exe = build("cepxico_gui.py", "cepxico-gui", console=False)

# On macOS the app bundle starts the first executable, so the desktop app goes first.
executables = [gui_exe, cli_exe] if sys.platform == "darwin" else [cli_exe, gui_exe]
folder = COLLECT(
    *executables,
    cli.binaries + gui.binaries,
    cli.datas + gui.datas,
    name="cepxico",
    upx=False,
)

if sys.platform == "darwin":
    BUNDLE(
        folder,
        name="CEPxico.app",
        bundle_identifier="mx.cepxico.app",
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "2.1.0"},
    )
