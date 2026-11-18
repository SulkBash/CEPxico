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
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

# The one place the version is written (src/cepxico/__init__.py), read as text so the
# build doesn't depend on which cepxico is installed.
VERSION = re.search(
    r'__version__ = "([^"]+)"', (Path(SPECPATH).parent / "src" / "cepxico" / "__init__.py").read_text()
).group(1)


def windows_version_info(name, description):
    """Version details Windows shows in the file's Properties → Details, and code signing
    services check: the product is CEPxico, at the same version in every executable."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION))[:4]
    numbers += (0,) * (4 - len(numbers))  # Windows wants four: 2.1.0 -> 2.1.0.0
    strings = {
        "CompanyName": "CEPxico",
        "FileDescription": description,
        "FileVersion": VERSION,
        "InternalName": name,
        "LegalCopyright": "AGPL-3.0-or-later. https://github.com/SulkBash/CEPxico",
        "OriginalFilename": f"{name}.exe",
        "ProductName": "CEPxico",
        "ProductVersion": VERSION,
    }
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings.items()])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


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


def build(script, name, console, description):
    analysis = Analysis([script], datas=DATAS, excludes=EXCLUDES)
    analysis.binaries = keep(analysis.binaries)
    analysis.datas = keep(analysis.datas)
    exe = EXE(
        PYZ(analysis.pure),
        analysis.scripts,
        exclude_binaries=True,
        name=name,
        console=console,
        version=windows_version_info(name, description),
        upx=False,
    )
    return analysis, exe


cli, cli_exe = build("cepxico_cli.py", "cepxico", console=True, description="CEPxico command line")
gui, gui_exe = build("cepxico_gui.py", "cepxico-gui", console=False, description="CEPxico")

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
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": VERSION},
    )
