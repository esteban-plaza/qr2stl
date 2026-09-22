# qr2stl

App de escritorio (PySide6) que genera un código QR imprimible en 3D a partir de una URL.

- **Ender (Cura, 1 extrusor):** exporta **1 STL** (base + módulos en relieve) y, si le soltás el `.gcode` que sliceaste en Cura, le **inserta la pausa M0** para el cambio de filamento.
- **Bambu Lab:** exporta un **proyecto 3MF** con un objeto de dos partes (`base` y `codigo`), cada una asignada a un filamento.

## Descargas

Los builds de Windows y macOS (arm64 e Intel) salen de GitHub Actions:

- En cada push a `main` quedan como *artifacts* del workflow **build**.
- En cada tag `v*` (por ejemplo `git tag v0.1.0 && git push --tags`) se publican en **Releases**.

**macOS:** la app no está firmada, así que Gatekeeper la bloquea. La primera vez, abrila con clic derecho → Abrir, o corré:

```bash
xattr -dr com.apple.quarantine qr2stl.app
```

## Uso

### Configuración

| Campo | Default | Notas |
|---|---|---|
| URL | `https://` | Cuanto más larga, más versión de QR y módulos más chicos |
| Lado total | 50 mm | Incluye el borde |
| Espesor base | 1.2 mm | Conviene que sea múltiplo de la altura de capa |
| Relieve | 0.8 mm | Múltiplo de la altura de capa, y ≥ 2 capas |
| Borde | 2 módulos | El estándar pide 4; con la base de otro color, 2 alcanza |
| Corrección de error | M | Subir a H agrega módulos y los achica |
| Altura de capa / primera capa | 0.2 / 0.2 mm | Solo se usan para calcular la pausa manual |

La app avisa si el módulo mide menos de 1.5 mm, si la base no cae en un borde de capa, si el relieve no es múltiplo de la altura de capa o si el relieve es de una sola capa.

### Ender 3 Neo + Cura

1. **Exportar STL…**
2. Slicealo en Cura **sin raft** y guardá el `.gcode`.
3. Soltá el `.gcode` en la zona punteada. Se genera `<nombre>_pausa.gcode` al lado.

La pausa se inserta antes de la primera capa cuyo punto medio queda en Z ≥ base, detectada por la **Z real del G-code**. Por eso funciona con cualquier altura de capa o de primera capa, y también con capas adaptativas.

La secuencia que se inserta:

1. retrae y sube Z;
2. va al parking y deja los motores energizados (`M84 S3600`);
3. hace `M0 Cambiar filamento`;
4. si configuraste una purga, la extruye;
5. vuelve a la posición y restaura E (`G92`) y el modo de extrusión.

El parking, la elevación, la retracción y la purga se configuran en la misma pestaña.

**Alternativa manual en Cura:** Extensiones → Post Processing → Modify G-Code → Pause at Height → *By Layer* → **Pause Layer = N**, con N igual a la cantidad de capas de la base (la app lo muestra). Método M0.

> El handoff original decía `round(base / capa) + 1`, y eso le erra por uno. En Cura 5.x la pausa se inserta **antes** de `;LAYER:<N>` (con base 0), y en el `main` de Cura va **al final** de la capa N del preview (con base 1). En los dos casos se imprimen N capas antes de pausar: con 1.2 / 0.2, N = 6.

### Bambu Lab

Bambu Studio carga las partes con su filamento asignado **solo** si el 3MF trae un `project_settings.config` válido. Ese archivo depende de la impresora, de los filamentos y de la versión de Bambu Studio, así que la app lo copia de una **plantilla**: cualquier `.3mf` guardado con Bambu Studio, por ejemplo uno bajado de MakerWorld, con la impresora y los filamentos que quieras.

- **Con plantilla:** el proyecto abre con la impresora y los filamentos de la plantilla, y con la base y el código ya asignados a los slots que elegiste. Por defecto usa el filamento más claro para la base y el más oscuro para el código. La plantilla y los slots quedan guardados entre sesiones.
- **Sin plantilla:** se genera un 3MF estándar con la base en blanco y el código en negro (`basematerials`). Al abrirlo, Bambu Studio pide mapear esos colores a tus filamentos.

El CLI de Bambu Studio no sirve para esto: en la 2.08 se cae al leer cualquier 3MF, y cuando genera proyectos las listas por filamento salen inconsistentes con las del GUI.

## Desarrollo

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,dev]"
.venv/bin/python -m qr2stl
.venv/bin/pytest
```

Todo queda en `.venv/`, dentro del repo. El núcleo (`core.py`, `gcode.py`, `bambu.py`) no depende de Qt: sus tests corren sin PySide6, y los de la GUI se saltean si PySide6 no está instalado.

```
src/qr2stl/
  core.py    matriz QR, malla (sin caras internas), STL binario, cálculo de la capa de pausa
  gcode.py   inserta la pausa M0 en un G-code de Cura
  bambu.py   proyecto 3MF de Bambu Studio (con plantilla) o 3MF estándar coloreado
  gui.py     interfaz Qt
```

### Malla

- Cada celda es una columna `(z0, z1)`. La malla lleva techo y piso por celda, y paredes solo en los tramos expuestos contra el vecino.
- Las paredes se parten en todos los niveles Z usados, así no quedan uniones en T. Eso pasaba con borde 0 y dejaba aristas abiertas.
- Los módulos que se tocan solo en diagonal comparten aristas entre 4 caras (non-manifold). Es inherente al QR, y Cura y Bambu Studio lo slicean bien.

### Builds

`.github/workflows/build.yml` corre los tests del núcleo en Linux. Después, en `windows-latest`, `macos-latest` (arm64) y `macos-15-intel`:

1. instala todo y corre la suite completa con la GUI offscreen;
2. empaqueta con PyInstaller: `--onefile --windowed` en Windows y `.app` con `--windowed` en macOS;
3. corre el ejecutable con `--selftest`;
4. sube el zip.

Para buildear local en una Mac:

```bash
.venv/bin/pip install -e ".[gui,build]"
.venv/bin/pyinstaller --noconfirm --windowed --name qr2stl src/qr2stl/__main__.py
```

## Licencia de dependencias

PySide6 es LGPL. Se usa `PySide6-Essentials`, sin modificar y enlazado dinámicamente.
