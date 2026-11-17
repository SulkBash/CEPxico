# PyInstaller build: one folder, dist/cepxico/, with two executables sharing it:
#   cepxico.exe      console: command line, or the desktop app when run without files
#   cepxico-gui.exe  desktop app without a console window
#
# Build:  pip install -e ".[build]"  then  pyinstaller packaging/cepxico.spec --noconfirm
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
    collect_data_files("cepxico")  # data/banks.toml
    + collect_data_files("rapidocr")  # bundled ONNX models and their YAML configs
    + collect_data_files("tkinterdnd2")  # tkdnd native library for drag & drop
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
]

# Files pulled in by packages but never used here (about 95 MB).
UNUSED = (
    "pymupdf/layout/",  # PyMuPDF's layout-analysis models
    "pymupdf/mupdf-devel/",  # C headers and import libraries
    "cv2/opencv_videoio_ffmpeg",  # OpenCV video codecs
)


def keep(entries):
    return [e for e in entries if not e[0].replace("\\", "/").startswith(UNUSED)]


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

COLLECT(
    cli_exe,
    gui_exe,
    cli.binaries + gui.binaries,
    cli.datas + gui.datas,
    name="cepxico",
    upx=False,
)
