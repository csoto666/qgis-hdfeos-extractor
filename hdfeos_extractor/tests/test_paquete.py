# -*- coding: utf-8 -*-
"""Pruebas de la forma del ZIP instalable.

Existen por un error real: alguien instalo el plugin con el boton "Download
ZIP" de GitHub y QGIS fallo con

    ModuleNotFoundError: No module named
    'qgis-hdfeos-extractor-main/hdfeos_extractor'

QGIS deriva el nombre del modulo del nombre de la carpeta que encuentra en el
ZIP. Si esa carpeta no es exactamente el nombre del paquete -y un identificador
valido de Python- la carga falla, y falla en la maquina del usuario, que es el
peor lugar para enterarse.

Estas pruebas comprueban esa forma aca, donde el error sale gratis.
"""

import os
import shutil
import subprocess
import zipfile

import pytest

PAQUETE = "hdfeos_extractor"
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def zip_construido(tmp_path_factory):
    """Corre empaquetar.sh de verdad y devuelve la ruta del ZIP.

    Se ejecuta el script real y no una imitacion: lo que hay que comprobar es
    lo que ese script produce, que es lo que el usuario termina instalando.
    """
    if shutil.which("zip") is None:
        pytest.skip("hace falta el comando zip")
    script = os.path.join(RAIZ, "empaquetar.sh")
    if not os.path.isfile(script):
        pytest.skip("no esta empaquetar.sh")
    salida = subprocess.run([script], cwd=RAIZ, capture_output=True,
                            text=True)
    assert salida.returncode == 0, salida.stderr
    zips = [f for f in os.listdir(RAIZ)
            if f.startswith(PAQUETE + "-") and f.endswith(".zip")]
    assert len(zips) == 1, "se esperaba un solo ZIP, hay %s" % zips
    ruta = os.path.join(RAIZ, zips[0])
    yield ruta
    os.remove(ruta)


@pytest.fixture(scope="module")
def nombres(zip_construido):
    with zipfile.ZipFile(zip_construido) as z:
        return z.namelist()


def raices(nombres):
    return {n.split("/")[0] for n in nombres if n.strip("/")}


# -- la forma que QGIS necesita -----------------------------------------------
def test_hay_una_sola_carpeta_raiz_y_se_llama_como_el_paquete(nombres):
    """Es la comprobacion central. QGIS toma el nombre de esta carpeta como
    nombre del modulo."""
    assert raices(nombres) == {PAQUETE}


def test_el_nombre_de_la_carpeta_es_un_identificador_de_python(nombres):
    """"qgis-hdfeos-extractor-main" no lo es, y por eso el import fallaba."""
    unica = raices(nombres).pop()
    assert unica.isidentifier(), unica
    assert "-" not in unica and "/" not in unica


def test_los_archivos_de_carga_estan_en_la_raiz_del_paquete(nombres):
    """Un nivel mas adentro, QGIS no encuentra el plugin o arma un nombre de
    modulo con una barra en el medio."""
    for archivo in ("__init__.py", "metadata.txt", "plugin.py"):
        assert "%s/%s" % (PAQUETE, archivo) in nombres, archivo


def test_estan_los_tres_subpaquetes_con_su_init(nombres):
    for sub in ("core", "vista", "qgis_ui"):
        assert "%s/%s/__init__.py" % (PAQUETE, sub) in nombres, sub


def test_el_nucleo_va_completo(nombres):
    """Falta un modulo del nucleo y el plugin carga pero revienta al abrir el
    panel, que es mas dificil de diagnosticar que no cargar."""
    for modulo in ("cube", "envi", "hdf5", "geo", "rgb", "colormap",
                   "spectral", "library", "sources"):
        assert "%s/core/%s.py" % (PAQUETE, modulo) in nombres, modulo


def test_classfactory_esta_donde_QGIS_lo_busca(zip_construido):
    with zipfile.ZipFile(zip_construido) as z:
        texto = z.read(PAQUETE + "/__init__.py").decode("utf-8")
    assert "def classFactory(" in texto


def test_la_version_del_zip_es_la_del_metadata(zip_construido):
    with zipfile.ZipFile(zip_construido) as z:
        meta = z.read(PAQUETE + "/metadata.txt").decode("utf-8")
    version = [linea.split("=", 1)[1].strip() for linea in meta.splitlines()
               if linea.startswith("version=")][0]
    assert os.path.basename(zip_construido) == "%s-%s.zip" % (PAQUETE,
                                                              version)


# -- lo que no debe viajar ----------------------------------------------------
def test_las_pruebas_y_los_ejemplos_no_van_en_el_paquete(nombres):
    """No los usa QGIS y engordan la descarga."""
    assert not [n for n in nombres if "/tests/" in n or "/examples/" in n]


def test_no_viajan_pycache_ni_zips(nombres):
    assert not [n for n in nombres if "__pycache__" in n or n.endswith(".pyc")]
    assert not [n for n in nombres if n.endswith(".zip")]


def test_van_la_licencia_y_el_readme(nombres):
    """La GPL obliga a distribuir la licencia con el binario."""
    assert "%s/LICENSE" % PAQUETE in nombres
    assert "%s/README.md" % PAQUETE in nombres
