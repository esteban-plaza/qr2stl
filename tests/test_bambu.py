import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

from qr2stl import bambu, core
from test_core import _bounds, _edge_balance, _volume

URL = "https://example.com/qr2stl"
NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


@pytest.fixture
def matrix():
    return core.qr_matrix(URL, core.ECC["M (15%)"], 2)[0]


@pytest.fixture
def template_path(tmp_path):
    """Imita un proyecto guardado por Bambu Studio (solo lo que lee load_template)."""
    cfg = {"printer_settings_id": "Bambu Lab H2S 0.4 nozzle",
           "printable_area": ["0x0", "340x0", "340x320", "0x320"],
           "filament_settings_id": ["Bambu PLA Basic @BBL H2S"] * 3,
           "filament_type": ["PLA", "PLA", "PETG"],
           "filament_colour": ["#FFFFFF", "#161616", "#2850E0"]}
    path = tmp_path / "plantilla.3mf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps(cfg))
        z.writestr("3D/3dmodel.model",
                   '<model><metadata name="Application">BambuStudio-02.08.02.61</metadata></model>')
    return path


def _meshes(z, name):
    out = {}
    for obj in ET.fromstring(z.read(name)).iter(f"{NS}object"):
        verts = [tuple(float(v.get(k)) for k in "xyz") for v in obj.iter(f"{NS}vertex")]
        if verts:
            out[obj.get("id")] = [tuple(verts[int(t.get(k))] for k in ("v1", "v2", "v3"))
                                  for t in obj.iter(f"{NS}triangle")]
    return out


def _check_meshes(meshes, matrix):
    n = len(matrix)
    base, code = meshes["1"], meshes["2"]
    for tris in (base, code):
        assert _edge_balance(tris) == {}
    lo, hi = _bounds(base)
    assert lo == pytest.approx((-25, -25, 0), abs=1e-4) and hi == pytest.approx((25, 25, 1.2), abs=1e-4)
    lo, hi = _bounds(code)
    assert (lo[2], hi[2]) == pytest.approx((1.2, 2.0))
    assert _volume(code) == pytest.approx(sum(map(sum, matrix)) * (50 / n) ** 2 * 0.8, rel=1e-4)


def test_load_template(template_path):
    t = bambu.load_template(template_path)
    assert t.printer == "Bambu Lab H2S 0.4 nozzle"
    assert t.plate_center == (170, 160)
    assert [(f.slot, f.type, f.colour) for f in t.filaments] == [
        (1, "PLA", "#FFFFFF"), (2, "PLA", "#161616"), (3, "PETG", "#2850E0")]


def test_load_template_rejects(tmp_path):
    bad = tmp_path / "x.3mf"
    bad.write_bytes(b"no es un zip")
    with pytest.raises(ValueError):
        bambu.load_template(bad)
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("Metadata/project_settings.config", "{}")
        z.writestr("3D/3dmodel.model", '<model><metadata name="Application">PrusaSlicer</metadata></model>')
    with pytest.raises(ValueError, match="Bambu Studio"):
        bambu.load_template(bad)


def test_project_with_template(tmp_path, matrix, template_path):
    t = bambu.load_template(template_path)
    path = tmp_path / "qr.3mf"
    bambu.write_project(path, matrix, 50, 1.2, 0.8, "qr & co", t, base_slot=1, code_slot=3)
    with zipfile.ZipFile(path) as z:
        assert z.read("Metadata/project_settings.config").decode() == t.settings_json
        main = ET.fromstring(z.read("3D/3dmodel.model"))
        assert main.find(f"{NS}metadata[@name='Application']").text == t.application
        assert main.find(f"{NS}metadata[@name='Title']").text == "qr & co"
        item = main.find(f"{NS}build/{NS}item")
        assert item.get("transform").endswith("170 160 0")
        assert [c.get("objectid") for c in main.iter(f"{NS}component")] == ["1", "2"]
        settings = ET.fromstring(z.read("Metadata/model_settings.config"))
        parts = {p.find("metadata[@key='name']").get("value"): p.find("metadata[@key='extruder']").get("value")
                 for p in settings.iter("part")}
        assert parts == {"base": "1", "codigo": "3"}
        _check_meshes(_meshes(z, "3D/Objects/object_1.model"), matrix)


def test_project_bad_slot(tmp_path, matrix, template_path):
    t = bambu.load_template(template_path)
    with pytest.raises(ValueError, match="slot 4"):
        bambu.write_project(tmp_path / "qr.3mf", matrix, 50, 1.2, 0.8, template=t, code_slot=4)


def test_standard_3mf_without_template(tmp_path, matrix):
    path = tmp_path / "qr.3mf"
    bambu.write_project(path, matrix, 50, 1.2, 0.8)
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"}
        main = ET.fromstring(z.read("3D/3dmodel.model"))
        assert not main.find(f"{NS}metadata[@name='Application']").text.startswith("BambuStudio")
        colours = [b.get("displaycolor") for b in main.iter(f"{NS}base")]
        assert colours == ["#FFFFFFFF", "#000000FF"]
        objs = {o.get("id"): o for o in main.iter(f"{NS}object")}
        assert (objs["1"].get("pindex"), objs["2"].get("pindex")) == ("0", "1")
        _check_meshes(_meshes(z, "3D/3dmodel.model"), matrix)
