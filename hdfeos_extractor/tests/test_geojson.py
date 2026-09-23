# -*- coding: utf-8 -*-
"""Pruebas del GeoJSON de las huellas."""

import json

import numpy as np

from hdfeos_extractor.core.geo import GeoTransform
from hdfeos_extractor.core.geojson import (coleccion, colecciones_de_firmas,
                                           escribir, feature_de)
from hdfeos_extractor.core.huella import huella_de_firma
from hdfeos_extractor.core.spectral import Signature

GT = GeoTransform((-70.0, 0.001, 0.0, -33.0, 0.0, -0.001))
WL = np.array([450.0, 650.0, 850.0])


def firma(pixeles, nombre="una"):
    return Signature(nombre, WL, np.ones(3), pixels=pixeles,
                     color="#00ff00", count=len(pixeles), source="escena")


def huellas_de(firmas):
    return [huella_de_firma(f, GT) for f in firmas]


def test_un_pixel_sale_como_Point():
    f = feature_de(huella_de_firma(firma([(2, 3)]), GT), {"nombre": "una"})
    assert f["geometry"]["type"] == "Point"
    assert f["geometry"]["coordinates"] == [-69.9975, -33.0035]
    assert f["properties"]["nombre"] == "una"


def test_un_area_sale_como_Polygon_cerrado():
    pixeles = [(x, y) for y in (0, 1) for x in (0, 1)]
    f = feature_de(huella_de_firma(firma(pixeles), GT), {})
    anillo = f["geometry"]["coordinates"][0]
    assert f["geometry"]["type"] == "Polygon"
    assert anillo[0] == anillo[-1] and len(anillo) == 5


def test_pixeles_sueltos_salen_como_MultiPoint():
    """Y no como un poligono: su caja envolvente es terreno que nadie midio."""
    f = feature_de(huella_de_firma(firma([(0, 0), (9, 9)]), GT), {})
    assert f["geometry"]["type"] == "MultiPoint"
    assert len(f["geometry"]["coordinates"]) == 2


def test_los_puntos_y_las_areas_van_a_colecciones_distintas():
    """Casi ningun programa abre una capa con dos tipos de geometria."""
    firmas = [firma([(1, 1)], "punto"),
              firma([(x, y) for y in (0, 1) for x in (0, 1)], "area"),
              firma([(0, 0), (5, 5)], "sueltos")]
    puntos, areas = colecciones_de_firmas(firmas, huellas_de(firmas))
    assert len(puntos["features"]) == 2
    assert len(areas["features"]) == 1
    assert areas["features"][0]["properties"]["nombre"] == "area"


def test_una_firma_sin_pixeles_no_aparece_en_ninguna():
    firmas = [firma([]), firma([(1, 1)])]
    puntos, areas = colecciones_de_firmas(firmas, huellas_de(firmas))
    assert len(puntos["features"]) == 1 and not areas["features"]


def test_lo_escrito_se_vuelve_a_leer_igual(tmp_path):
    firmas = [firma([(1, 1)], "con acentos y comas, si")]
    puntos, _ = colecciones_de_firmas(firmas, huellas_de(firmas))
    ruta = str(tmp_path / "firmas_puntos.geojson")
    assert escribir(ruta, puntos) == 1
    with open(ruta) as f:
        vuelta = json.load(f)
    assert vuelta["type"] == "FeatureCollection"
    assert vuelta["features"][0]["properties"]["nombre"] == \
        "con acentos y comas, si"


def test_una_coleccion_vacia_sigue_siendo_un_geojson_valido(tmp_path):
    ruta = str(tmp_path / "vacio.geojson")
    assert escribir(ruta, coleccion([])) == 0
    with open(ruta) as f:
        assert json.load(f)["features"] == []


def test_las_coordenadas_no_llevan_ruido_de_coma_flotante():
    """Siete decimales son 11 mm: de sobra, y sin llenar el archivo de
    digitos que solo son error de representacion."""
    f = feature_de(huella_de_firma(firma([(1, 1)]), GT), {})
    for valor in f["geometry"]["coordinates"]:
        assert len(str(valor).split(".")[-1]) <= 7
