"""Rutas a los recursos empaquetados (funciona instalado y con PyInstaller)."""
from pathlib import Path

HERE = Path(__file__).parent


def icon_path():
    return str(HERE / "icon.png")
