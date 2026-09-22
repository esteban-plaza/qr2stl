"""Inserta una pausa de cambio de filamento (M0) en un G-code de Cura ya sliceado.

La capa se elige por la Z real que figura en el G-code, no por un número calculado:
así no importa qué altura de capa o de primera capa se usó en Cura, ni si hay capas
adaptativas. Una capa es de relieve si su punto medio está en Z >= base (Cura slicea
por el medio de la capa por defecto).
"""
import re
from dataclasses import dataclass

MARKER = ";qr2stl: pausa de cambio de filamento"
_EPS = 1e-4
_WORD = re.compile(r"([A-Z])(-?\d*\.?\d+)")


@dataclass
class PauseSettings:
    park_x: float = 0.0
    park_y: float = 0.0
    lift: float = 10.0        # mm que sube Z antes de ir a la posición de parking
    retract: float = 5.0      # mm de retracción antes de pausar (Bowden)
    purge: float = 0.0        # mm a extruir en el parking después de reanudar (0 = purga a mano)
    message: str = "Cambiar filamento"  # ASCII: los LCD de Marlin no muestran tildes


@dataclass
class PauseResult:
    text: str
    layer: int        # número de ;LAYER: antes del cual se insertó la pausa (0-based)
    layer_z: float    # Z de esa capa (la primera del relieve)
    base_top_z: float  # Z de la última capa de base


def _words(line):
    code = line.split(";", 1)[0].upper()
    return {k: float(v) for k, v in _WORD.findall(code)}


def _layers(lines):
    """[(índice de la línea ;LAYER:, número de capa, Z de la capa)] en orden de impresión.
    La Z de la capa es la vigente en su primer movimiento que extruye con XY, así un
    Z-hop al empezar la capa no la confunde."""
    out = []
    current = None
    z = None
    for i, line in enumerate(lines):
        if line.startswith(";LAYER:"):
            try:
                num = int(line[7:].strip())
            except ValueError:
                continue
            current = [i, num, None]
            out.append(current)
            continue
        if line[:3] not in ("G0 ", "G1 "):
            continue
        w = _words(line)
        z = w.get("Z", z)
        if (current is not None and current[2] is None and z is not None
                and w.get("G") == 1 and "E" in w and ("X" in w or "Y" in w)):
            current[2] = z
    return [tuple(l) for l in out if l[2] is not None]


def _state_before(lines, stop):
    """Posición, E, modo de extrusión y feedrate vigentes justo antes de la línea `stop`."""
    st = {"X": 0.0, "Y": 0.0, "Z": 0.0, "E": 0.0, "F": None, "rel_e": False, "rel_xyz": False}
    for line in lines[:stop]:
        w = _words(line)
        if not w:
            continue
        if "G" in w:
            g = int(w["G"])
            if g in (0, 1):
                for k in "XYZ":
                    if k in w and not st["rel_xyz"]:
                        st[k] = w[k]
                if "E" in w:
                    st["E"] = st["E"] + w["E"] if st["rel_e"] else w["E"]
                if "F" in w:
                    st["F"] = w["F"]
            elif g == 90:
                st["rel_xyz"] = False
            elif g == 91:
                st["rel_xyz"] = True
            elif g == 92 and "E" in w:
                st["E"] = w["E"]
        elif "M" in w:
            m = int(w["M"])
            if m == 82:
                st["rel_e"] = False
            elif m == 83:
                st["rel_e"] = True
    return st


def _pause_block(st, layer, s: PauseSettings):
    f = lambda v: f"{v:.3f}".rstrip("0").rstrip(".")  # noqa: E731
    z_up = st["Z"] + s.lift
    b = [
        f"{MARKER} antes de LAYER:{layer}",
        "M400",
        "M83 ; extrusion relativa",
        f"G1 E-{f(s.retract)} F2400",
        f"G0 Z{f(z_up)} F600",
        f"G0 X{f(s.park_x)} Y{f(s.park_y)} F6000",
        "M84 S3600 ; que no se apaguen los motores durante la pausa",
        f"M117 {s.message}",
        f"M0 {s.message}",
    ]
    if s.purge > 0:
        b.append(f"G1 E{f(s.purge)} F150 ; purga")
        b.append(f"G1 E-{f(s.retract)} F2400")
    b += [
        f"G0 X{f(st['X'])} Y{f(st['Y'])} F6000",
        f"G0 Z{f(st['Z'])} F600",
        f"G1 E{f(s.retract)} F2400",
    ]
    if not st["rel_e"]:
        b += ["M82 ; extrusion absoluta", f"G92 E{f(st['E'])}"]
    if st["F"] is not None:
        b.append(f"G1 F{f(st['F'])}")
    b.append(";qr2stl: fin de la pausa")
    return b


def insert_pause(text, base, settings: PauseSettings | None = None) -> PauseResult:
    """Devuelve el G-code con la pausa antes de la primera capa de relieve.
    Lanza ValueError si el G-code no sirve."""
    s = settings or PauseSettings()
    if MARKER in text:
        raise ValueError("Este G-code ya tiene la pausa de qr2stl.")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    flavor = next((l for l in lines[:50] if l.startswith(";FLAVOR:")), None)
    if flavor is None or not any(l.startswith(";LAYER:") for l in lines):
        raise ValueError("No parece un G-code de Cura (faltan ;FLAVOR: o ;LAYER:).")
    if "marlin" not in flavor.lower():
        raise ValueError(f"El G-code es {flavor[8:]}; la pausa M0 es para Marlin.")
    if any(l.startswith(";LAYER:-") for l in lines):
        raise ValueError("El G-code tiene raft; no está soportado (desactivá el raft en Cura).")
    if s.retract < 0 or s.purge < 0 or s.lift < 0:
        raise ValueError("Retracción, purga y elevación tienen que ser ≥ 0.")

    layers = _layers(lines)
    if not layers:
        raise ValueError("No se encontraron capas con Z en el G-code.")
    prev_z = 0.0
    for idx, num, z in layers:
        if z - (z - prev_z) / 2 >= base - _EPS:
            break
        prev_z = z
    else:
        raise ValueError(f"Ninguna capa supera Z = {base:.2f} mm: ¿es el STL de este QR?")
    if idx == layers[0][0]:
        raise ValueError("La primera capa ya es relieve: la base es demasiado fina.")

    st = _state_before(lines, idx)
    new = lines[:idx] + _pause_block(st, num, s) + lines[idx:]
    return PauseResult(nl.join(new), num, z, prev_z)
