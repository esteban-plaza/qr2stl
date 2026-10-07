"""Empaqueta qr2stl con PyInstaller (lo usan la build local y GitHub Actions).

    .venv/bin/python tools/build_app.py           # macOS: dist/qr2stl.app · Windows: dist/qr2stl/
    .venv/bin/python tools/build_app.py --zip NAME  # además, NAME.zip listo para subir

Después de empaquetar corre el ejecutable con --selftest (genera un modelo y carga el
visor 3D), así una build que no arranca falla acá y no en la máquina de alguien.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "qr2stl" / "ui"
NAME = "qr2stl"
BUNDLE_ID = "io.github.esteban-plaza.qr2stl"

# Módulos de Qt que no se usan: achican bastante el paquete
EXCLUDES = [
    "tkinter", "PIL", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets",
    "PySide6.QtWebChannel", "PySide6.QtHttpServer", "PySide6.QtVirtualKeyboard",
]


# Módulos QML que importa viewer.qml (con sus dependencias internas). El resto se borra.
KEEP_QML = {"QtQml", "QtQuick", "QtQuick3D"}
KEEP_QML_SUBDIRS = {"QtQml": {"Models", "WorkerScript"}, "QtQuick": {"Window"}, "QtQuick3D": set()}
DROP_PLUGINS = {"qmltooling", "networkinformation", "tls", "platforminputcontexts"}


def _bundle_root():
    if sys.platform == "darwin":
        return ROOT / "dist" / f"{NAME}.app" / "Contents"
    return ROOT / "dist" / NAME


def _qt_key(name):
    """Nombre de una biblioteca de Qt a partir de una ruta o un nombre de import:
    «@rpath/QtGui.framework/Versions/A/QtGui» o «Qt6Gui.dll» → «QtGui»."""
    m = re.search(r"(Qt\w+)\.framework", name)
    if m:
        return m.group(1)
    m = re.match(r"^Qt6(\w+)\.dll$", os.path.basename(name), re.I)
    if m:
        return "Qt" + m.group(1)
    m = re.match(r"^libQt6(\w+)\.so", os.path.basename(name))
    if m:
        return "Qt" + m.group(1)
    m = re.match(r"^(Qt\w+)$", os.path.basename(name))   # «@rpath/QtCore» (PyInstaller)
    return m.group(1) if m else None


def _rmtree(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def prune():
    """Saca lo que el hook de QML de PyInstaller junta de más (QtWebEngine, Qt3D, Charts…):
    deja solo los módulos QML usados y borra las bibliotecas de Qt que ya nadie referencia."""
    from PyInstaller.depend.bindepend import get_imports
    root = _bundle_root()
    before = _size(root)

    qml_roots = [p for p in root.rglob("qml")
                 if p.is_dir() and not p.is_symlink() and (p / "QtQuick").is_dir()]
    for qml in qml_roots:
        for module in qml.iterdir():
            if module.name not in KEEP_QML:
                _rmtree(module)
            elif module.name in KEEP_QML_SUBDIRS:
                for sub in module.iterdir():
                    if sub.is_dir() and sub.name not in KEEP_QML_SUBDIRS[module.name]:
                        _rmtree(sub)
    for plugins in [p for p in root.rglob("plugins") if p.is_dir() and not p.is_symlink()]:
        for d in plugins.iterdir():
            if d.name in DROP_PLUGINS:
                _rmtree(d)
        for f in plugins.glob("imageformats/*qpdf*"):   # arrastra QtPdf (7 MB)
            _rmtree(f)
    for tr in [p for p in root.rglob("translations") if p.is_dir() and not p.is_symlink()]:
        for f in tr.iterdir():
            if not f.name.startswith("qtbase_"):
                _rmtree(f)

    # Cierre de dependencias: desde todos los binarios que no son bibliotecas de Qt
    libs, roots = {}, []
    for f in root.rglob("*"):
        if f.is_symlink() or not f.is_file():
            continue
        is_bin = f.suffix.lower() in (".so", ".dylib", ".pyd", ".dll", ".exe") or (
            ".framework/Versions/" in f.as_posix() and f.parent.name in ("A", "5", "6")
            and f.name == f.parts[-4].removesuffix(".framework")) or f == executable()
        if not is_bin:
            continue
        key = _qt_key(f.as_posix())
        is_qt_lib = key is not None and (f.suffix.lower() in ("", ".dll") or ".so." in f.name)
        if is_qt_lib and "plugins" not in f.parts and "qml" not in f.parts:
            libs[key] = f
        else:
            roots.append(f)
    needed, todo = set(), list(roots)
    while todo:
        f = todo.pop()
        try:
            names = get_imports(str(f))
        except Exception:  # noqa: BLE001 - un binario raro no tiene que frenar la build
            continue
        for n in names:
            name = n[0] if isinstance(n, tuple) else n
            key = _qt_key(name)
            if key and key in libs and key not in needed:
                needed.add(key)
                todo.append(libs[key])
    for key, f in libs.items():
        if key not in needed:
            fw = next((p for p in f.parents if p.suffix == ".framework"), None)
            _rmtree(fw or f)
    for f in root.rglob("*"):                     # symlinks que quedaron colgando
        if f.is_symlink() and not f.exists():
            f.unlink()
    print(f"prune: {before / 1e6:.0f} MB → {_size(root) / 1e6:.0f} MB; "
          f"Qt: {', '.join(sorted(needed))}")


def _size(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def executable():
    if sys.platform == "darwin":
        return ROOT / "dist" / f"{NAME}.app" / "Contents" / "MacOS" / NAME
    if sys.platform.startswith("win"):
        return ROOT / "dist" / NAME / f"{NAME}.exe"
    return ROOT / "dist" / NAME / NAME


def build():
    sep = os.pathsep
    args = [
        str(ROOT / "src" / "qr2stl" / "__main__.py"),
        "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        "--icon", str(UI / "icon.png"),
        "--add-data", f"{UI / 'viewer.qml'}{sep}qr2stl/ui",
        "--add-data", f"{UI / 'icon.png'}{sep}qr2stl/ui",
        "--hidden-import", "PySide6.QtQuick3D",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", BUNDLE_ID]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    PyInstaller.__main__.run(args)
    prune()

    if sys.platform == "darwin":
        plist = ROOT / "dist" / f"{NAME}.app" / "Contents" / "Info.plist"
        _plist_set(plist, {
            "CFBundleDisplayName": NAME,
            "CFBundleShortVersionString": _version(),
            "CFBundleVersion": _version(),
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,   # sigue el modo oscuro del sistema
            "LSMinimumSystemVersion": "12.0",
            "LSApplicationCategoryType": "public.app-category.graphics-design",
        })
        # firma ad-hoc: sin esto, en Apple Silicon el binario modificado no arranca
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-",
                        str(ROOT / "dist" / f"{NAME}.app")], check=True)


def _version():
    ns = {}
    exec((ROOT / "src" / "qr2stl" / "__init__.py").read_text(), ns)
    return ns["__version__"]


def _plist_set(path, values):
    import plistlib
    with open(path, "rb") as f:
        data = plistlib.load(f)
    data.update(values)
    with open(path, "wb") as f:
        plistlib.dump(data, f)


def selftest():
    exe = executable()
    print(f"selftest: {exe}")
    res = subprocess.run([str(exe), "--selftest"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180)
    print(res.stdout, res.stderr)
    if res.returncode != 0:
        sys.exit(f"selftest falló (código {res.returncode})")


def make_zip(name):
    out = ROOT / f"{name}.zip"
    out.unlink(missing_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(ROOT / "dist" / f"{NAME}.app"), str(out)], check=True)
    else:
        shutil.make_archive(str(ROOT / name), "zip", ROOT / "dist", NAME)
    print(f"zip: {out} ({out.stat().st_size / 1e6:.1f} MB)")


def main():
    for stream in (sys.stdout, sys.stderr):   # la consola de Windows usa cp1252
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", metavar="NAME", help="crear NAME.zip con el resultado")
    ap.add_argument("--skip-selftest", action="store_true")
    opts = ap.parse_args()
    build()
    if not opts.skip_selftest:
        selftest()
    if opts.zip:
        make_zip(opts.zip)


if __name__ == "__main__":
    main()
