# qr2stl

App de escritorio (Python + Qt 6) que genera un código QR imprimible en 3D a partir de una URL, con **marco** y **texto debajo** opcionales, y una **vista previa 3D** en tiempo real.

Todo lo que está en relieve (código, marco y texto) sale del segundo color con **un solo cambio de filamento por capa**:

- **Ender 3 · Cura (1 extrusor):** exportás el STL, lo sliceás en Cura y le soltás el `.gcode` a la app, que le **inserta la pausa M0**.
- **Bambu Lab:** exportás el STL y en Bambu Studio agregás un **cambio de filamento** en la capa que te indica la app (con AMS es automático).

> El export de **proyecto 3MF multicolor** para Bambu Lab está **deshabilitado**: Bambu Studio no lo cargaba bien. El cambio de filamento por capa da el mismo resultado con un solo STL. El código anterior quedó en el historial de git (`src/qr2stl/bambu.py` en `2428ef6`).

## Descargas

Los builds de Windows y macOS (arm64 e Intel) salen de GitHub Actions:

- En cada push a `main` quedan como *artifacts* del workflow **build**.
- En cada tag `v*` (por ejemplo `git tag v0.2.0 && git push --tags`) se publican en **Releases**.

**macOS:** la app tiene firma ad-hoc, sin notarizar, así que Gatekeeper la bloquea. La primera vez, abrila con clic derecho → Abrir, o corré:

```bash
xattr -dr com.apple.quarantine qr2stl.app
```

## Uso

La ventana tiene la vista 3D a la izquierda y el inspector a la derecha. Cada cambio se ve al instante en la vista previa.

### Vista previa 3D

- **Arrastrar:** girar · **clic derecho / rueda apretada:** desplazar · **rueda o pellizco:** zoom · **doble clic:** volver a centrar.
- Botones **3D / Arriba / Frente** (o ⌘1, ⌘2, ⌘3) y **↻** para la rotación automática, que arranca sola después de unos segundos sin tocar nada.
- Los colores de la vista previa se eligen en *Colores de la vista previa*. Son solo para ver cómo queda: el color real lo da el filamento.

### Parámetros

| Sección | Campo | Default | Notas |
|---|---|---|---|
| Contenido | URL | `https://` | Cuanto más larga, más versión de QR y módulos más chicos |
| | Corrección de errores | M | Subir a H agrega módulos y los achica |
| Tamaño | Lado del QR | 50 mm | Incluye el borde blanco |
| | Borde blanco | 2 módulos | El estándar pide 4; con la base de otro color, 2 alcanza |
| | Esquinas redondeadas | 0 mm | Radio de la placa; el marco lo sigue |
| Alturas | Espesor de la base | 1,2 mm | Conviene que sea múltiplo de la altura de capa |
| | Relieve | 0,8 mm | Múltiplo de la altura de capa, y ≥ 2 capas |
| Marco | Ancho | 2 mm | Se agrega alrededor del QR, en relieve |
| Texto debajo | Texto, fuente, negrita | — | Fuentes del sistema; se vectoriza con Qt |
| | Alto de las mayúsculas | 6 mm | Si no entra a lo ancho, se achica solo (y avisa) |
| Impresión | Altura de capa / primera capa | 0,2 / 0,2 mm | Para calcular la capa del cambio de color |

La app avisa, entre otras cosas, si el módulo mide menos de 1,5 mm, si el texto es muy chico, si el marco se pega al código, si la base no cae en un borde de capa o si el relieve es de una sola capa.

Las preferencias se recuerdan entre sesiones. *Archivo → Restablecer valores* vuelve a los defaults.

### Ender 3 Neo + Cura

1. **Exportar STL…** (⌘E)
2. Slicealo en Cura **sin raft** y guardá el `.gcode`.
3. Soltá el `.gcode` en la zona punteada (o *Archivo → Insertar pausa en un G-code…*, ⌘G). Se genera `<nombre>_pausa.gcode` al lado.

La pausa se inserta antes de la primera capa cuyo punto medio queda en Z ≥ base, detectada por la **Z real del G-code**. Por eso funciona con cualquier altura de capa o de primera capa, y también con capas adaptativas.

La secuencia que se inserta:

1. retrae y sube Z;
2. va al parking y deja los motores energizados (`M84 S3600`);
3. hace `M0 Cambiar filamento`;
4. si configuraste una purga, la extruye;
5. vuelve a la posición y restaura E (`G92`) y el modo de extrusión.

El parking, la elevación, la retracción y la purga están en *Opciones de la pausa*.

**Alternativa manual en Cura:** Extensiones → Post Processing → Modify G-Code → Pause at Height → *By Layer* → **Pause Layer = N**, con N igual a la cantidad de capas de la base (la app lo muestra). Método M0.

> En Cura 5.x la pausa se inserta **antes** de `;LAYER:<N>` (con base 0), y en el `main` de Cura va **al final** de la capa N del preview (con base 1). En los dos casos se imprimen N capas antes de pausar: con 1,2 / 0,2, N = 6.

### Bambu Lab

1. **Exportar STL…** y abrilo en Bambu Studio.
2. Sliceá y, en la vista previa, subí el deslizador de capas hasta la capa N + 1 (la app te dice cuál y a qué Z).
3. Hacé clic en el **+** del deslizador (o clic derecho → cambio de filamento) y elegí el filamento del código.

## Desarrollo

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,dev]"
.venv/bin/python -m qr2stl
.venv/bin/pytest
```

Todo queda en `.venv/`, dentro del repo. El núcleo (`core.py`, `gcode.py`) no depende de Qt: sus tests corren sin PySide6, y los de la GUI se saltean si PySide6 no está instalado (corren con la plataforma `offscreen`, sin el visor 3D).

```
src/qr2stl/
  core.py        matriz QR, geometría 2D (placa, código, marco, texto) → malla con manifold3d, STL
  gcode.py       inserta la pausa M0 en un G-code de Cura
  textshape.py   vectoriza texto con las fuentes del sistema (QPainterPath)
  app.py         punto de entrada (--selftest para CI)
  ui/
    window.py    ventana principal: inspector, toolbar, menús, exportación, preferencias
    widgets.py   widgets animados: switch, control segmentado, slider+campo, secciones
                 desplegables, banner de avisos, toast, zona de drop, selector de color
    viewer.py    puente Python ↔ Qt Quick 3D (MeshGeometry)
    viewer.qml   escena 3D, cámara orbital con amortiguación, presets animados, HUD
tools/
  build_app.py   empaqueta con PyInstaller, poda Qt, corre --selftest y arma el zip
  make_icon.py   genera ui/icon.png
```

### Geometría

- Todo se arma en 2D con manifold3d (`CrossSection`): la placa (rectángulo con esquinas redondeadas), el código (tramos horizontales de módulos), el marco (placa menos la placa achicada) y el texto (contornos de Qt, regla NonZero para respetar los agujeros de letras como la «o»).
- Para **exportar**: placa extruida de 0 a `base` ∪ relieve extruido de `base` a `base + relieve`. manifold3d devuelve una malla cerrada y manifold: cada arista la comparten exactamente 2 caras, incluso donde los módulos se tocan en diagonal.
- Para la **vista previa**: los mismos cuerpos sin la unión 3D, y el código como una caja por tramo (sin triangular). Tiene el mismo volumen que la exacta y se arma en ~7 ms aun con un QR versión 40.

### Interfaz

- Qt Widgets para el inspector (sigue el modo claro/oscuro y el color de acento del sistema) y Qt Quick 3D para la vista previa, embebida con `QQuickWidget`. Quick 3D usa RHI: Metal en macOS y Direct3D 11 en Windows.
- Animaciones con el framework de Qt (`QPropertyAnimation`, `QVariantAnimation`, grupos paralelos) en los widgets, y `Behavior` / `FrameAnimation` en QML.

### Builds

```bash
.venv/bin/pip install -e ".[gui,build]"
.venv/bin/python tools/build_app.py          # dist/qr2stl.app (macOS) o dist/qr2stl/ (Windows)
```

`tools/build_app.py`:

1. empaqueta con PyInstaller (`.app` en macOS, carpeta con `qr2stl.exe` en Windows);
2. **poda Qt**: el hook de QML de PyInstaller mete todos los módulos QML (QtWebEngine, Qt3D, Charts…). Se dejan solo QtQml, QtQuick y QtQuick3D y se borran las bibliotecas de Qt que ningún binario referencia (457 MB → ~130 MB en macOS);
3. en macOS completa el `Info.plist` (modo oscuro, versión) y firma ad-hoc;
4. corre el ejecutable con `--selftest`, que genera un modelo con marco y texto y carga el visor 3D;
5. con `--zip NOMBRE`, arma el zip.

`.github/workflows/build.yml` corre los tests del núcleo en Linux y después, en `windows-latest`, `macos-latest` (arm64) y `macos-15-intel`, la suite completa con la GUI offscreen y `tools/build_app.py --zip`.

## Licencia de dependencias

PySide6 es LGPL. Se usa sin modificar y enlazado dinámicamente. manifold3d es Apache 2.0.
