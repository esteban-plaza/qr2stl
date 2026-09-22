"""Exporta el QR como proyecto 3MF de Bambu Studio: un objeto con dos partes
(«base» y «codigo»), cada una asignada a un slot de filamento.

Bambu Studio solo acepta el proyecto completo (partes + filamentos asignados) si trae un
Metadata/project_settings.config válido. Esa config depende de la impresora, de los
filamentos y de la versión de Bambu Studio, así que no se arma a mano: se copia de una
**plantilla**, es decir, cualquier .3mf guardado desde Bambu Studio con la impresora y
los filamentos que se quieren usar. Sin plantilla, Bambu Studio avisa "invalid config,
load geometry data only" y descarta la asignación; por eso sin plantilla se genera un
3MF estándar con las partes coloreadas (basematerials), que Bambu Studio 2.x mapea a
filamentos al importar.
"""
import json
import re
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from .core import build_mesh, split_cells

DEFAULT_PLATE_CENTER = (128.0, 128.0)  # X1/P1/A1; en la A1 mini (180 mm) igual entra
STANDARD_COLOURS = ("#FFFFFFFF", "#000000FF")  # base, código (mayúsculas: Bambu ignora minúsculas)
_SETTINGS = "Metadata/project_settings.config"
_NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
       'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
       'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
       'requiredextensions="p"')


@dataclass
class Filament:
    slot: int      # 1-based, como lo muestra Bambu Studio
    name: str
    type: str
    colour: str


@dataclass
class Template:
    settings_json: str
    application: str
    printer: str
    plate_center: tuple
    filaments: list = field(default_factory=list)


def load_template(path) -> Template:
    """Lee un .3mf guardado desde Bambu Studio. Lanza ValueError si no sirve."""
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read(_SETTINGS).decode("utf-8")
            model = z.read("3D/3dmodel.model").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError) as ex:
        raise ValueError(f"No es un proyecto de Bambu Studio ({ex}).") from None
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("La config del proyecto no es JSON válido.") from None
    m = re.search(r'<metadata name="Application">([^<]*)</metadata>', model)
    app = m.group(1) if m else ""
    if not app.startswith("BambuStudio"):
        raise ValueError("La plantilla tiene que estar guardada con Bambu Studio.")

    ids = cfg.get("filament_settings_id") or []
    types = cfg.get("filament_type") or []
    colours = cfg.get("filament_colour") or []
    filaments = [Filament(i + 1, name,
                          types[i] if i < len(types) else "",
                          colours[i] if i < len(colours) else "")
                 for i, name in enumerate(ids)]
    if not filaments:
        raise ValueError("La plantilla no tiene filamentos.")
    return Template(raw, app, cfg.get("printer_settings_id", ""),
                    _plate_center(cfg.get("printable_area")), filaments)


def _plate_center(area):
    try:
        pts = [tuple(float(c) for c in p.split("x")) for p in area]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_PLATE_CENTER


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
    ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
    ' <Default Extension="png" ContentType="image/png"/>\n'
    ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')


def _uuid(i):
    return f"{i:08x}-71cb-4c03-9d28-80fed5dfa1dc"


def _mesh_xml(obj_id, tris, dx, dy):
    index, verts, faces = {}, [], []
    for t in tris:
        ids = []
        for v in t:
            if v not in index:
                index[v] = len(verts)
                verts.append(v)
            ids.append(index[v])
        faces.append(ids)
    out = [f'  <object id="{obj_id}" p:UUID="{_uuid(obj_id)}" type="model">', "   <mesh>", "    <vertices>"]
    out += [f'     <vertex x="{x + dx:.6g}" y="{y + dy:.6g}" z="{z:.6g}"/>' for x, y, z in verts]
    out += ["    </vertices>", "    <triangles>"]
    out += [f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces]
    out += ["    </triangles>", "   </mesh>", "  </object>"]
    return "\n".join(out), len(faces)


def write_project(path, matrix, size, base, relief, name="qr",
                  template: Template | None = None, base_slot=1, code_slot=2):
    """Escribe el 3MF. Con `template`, el proyecto abre con la impresora y los
    filamentos de la plantilla, y las partes asignadas a `base_slot` / `code_slot`."""
    if template is not None:
        count = len(template.filaments)
        for slot in (base_slot, code_slot):
            if not 1 <= slot <= count:
                raise ValueError(f"La plantilla tiene {count} filamento(s); no existe el slot {slot}.")
    n = len(matrix)
    cell = size / n
    base_cells, code_cells = split_cells(matrix, base, relief)
    half = size / 2
    parts = [(1, "base", base_slot, build_mesh(base_cells, n, cell)),
             (2, "codigo", code_slot, build_mesh(code_cells, n, cell))]
    meshes, stats = [], []
    for pid, _, _, tris in parts:
        xml, count = _mesh_xml(pid, tris, -half, -half)  # centrado en XY; el item lo lleva a la cama
        meshes.append(xml)
        stats.append(count)
    cx, cy = template.plate_center if template else DEFAULT_PLATE_CENTER
    obj_id = len(parts) + 1
    item = (f' <build>\n  <item objectid="{obj_id}" '
            f'transform="1 0 0 0 1 0 0 0 1 {cx:g} {cy:g} 0" printable="1"/>\n </build>\n')
    rel = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
           ' <Relationship Target="{}" Id="rel-1" '
           'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')

    if template is None:
        # 3MF estándar (sin marca de Bambu): Bambu Studio 2.x lee los colores de
        # basematerials y ofrece mapearlos a filamentos al importar.
        colored = [m.replace(f'<object id="{pid}" p:UUID="{_uuid(pid)}" type="model">',
                             f'<object id="{pid}" type="model" pid="10" pindex="{i}" name="{pname}">')
                   for i, (m, (pid, pname, *_)) in enumerate(zip(meshes, parts))]
        comps = "\n".join(f'    <component objectid="{pid}"/>' for pid, *_ in parts)
        model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
                 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
                 ' <metadata name="Application">qr2stl</metadata>\n'
                 f' <metadata name="Title">{escape(name)}</metadata>\n <resources>\n'
                 '  <basematerials id="10">\n'
                 + "".join(f'   <base name="{pname}" displaycolor="{c}"/>\n'
                           for (_, pname, *_), c in zip(parts, STANDARD_COLOURS))
                 + '  </basematerials>\n' + "\n".join(colored) + "\n"
                 f'  <object id="{obj_id}" type="model" name={quoteattr(name)}>\n'
                 f'   <components>\n{comps}\n   </components>\n  </object>\n'
                 ' </resources>\n' + item + '</model>\n')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("_rels/.rels", rel.format("/3D/3dmodel.model"))
            z.writestr("3D/3dmodel.model", model)
        return path

    objects_model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" '
                     f'xml:lang="en-US" {_NS}>\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
                     f' <resources>\n' + "\n".join(meshes) + "\n </resources>\n <build/>\n</model>\n")
    components = "\n".join(
        f'    <component p:path="/3D/Objects/object_1.model" objectid="{pid}" '
        f'p:UUID="{_uuid(0x10000 + pid)}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
        for pid, *_ in parts)
    main_model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" '
                  f'xml:lang="en-US" {_NS}>\n'
                  f' <metadata name="Application">{escape(template.application)}</metadata>\n'
                  f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
                  f' <metadata name="Title">{escape(name)}</metadata>\n'
                  f' <resources>\n  <object id="{obj_id}" p:UUID="{_uuid(obj_id)}" type="model">\n'
                  f'   <components>\n{components}\n   </components>\n  </object>\n </resources>\n'
                  + item.replace("<build>", f'<build p:UUID="{_uuid(0x20000)}">')
                        .replace('printable="1"', f'p:UUID="{_uuid(0x30000)}" printable="1"')
                  + '</model>\n')
    part_xml = "\n".join(
        f'    <part id="{pid}" subtype="normal_part">\n'
        f'      <metadata key="name" value={quoteattr(pname)}/>\n'
        f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
        f'      <metadata key="extruder" value="{slot}"/>\n'
        f'      <mesh_stat face_count="{fc}" edges_fixed="0" degenerate_facets="0" '
        f'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
        f'    </part>'
        for (pid, pname, slot, _), fc in zip(parts, stats))
    settings = (f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
                f'  <object id="{obj_id}">\n'
                f'    <metadata key="name" value={quoteattr(name)}/>\n'
                f'    <metadata key="extruder" value="{base_slot}"/>\n'
                f'    <metadata face_count="{sum(stats)}"/>\n{part_xml}\n  </object>\n'
                f'  <plate>\n    <metadata key="plater_id" value="1"/>\n'
                f'    <metadata key="plater_name" value=""/>\n'
                f'    <metadata key="locked" value="false"/>\n'
                f'    <model_instance>\n      <metadata key="object_id" value="{obj_id}"/>\n'
                f'      <metadata key="instance_id" value="0"/>\n'
                f'      <metadata key="identify_id" value="{100 + obj_id}"/>\n'
                f'    </model_instance>\n  </plate>\n  <assemble>\n  </assemble>\n</config>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", rel.format("/3D/3dmodel.model"))
        z.writestr("3D/3dmodel.model", main_model)
        z.writestr("3D/_rels/3dmodel.model.rels", rel.format("/3D/Objects/object_1.model"))
        z.writestr("3D/Objects/object_1.model", objects_model)
        z.writestr("Metadata/model_settings.config", settings)
        z.writestr(_SETTINGS, template.settings_json)
    return path
