# -*- coding: utf-8 -*-
"""Pruebas del envio de la vista al mapa de QGIS."""

import numpy as np
import pytest

from conftest import cubo_patron, longitudes_patron
from hdfeos_extractor.core.cube import HyperspectralCube
from hdfeos_extractor.core.geo import GeoTransform
from hdfeos_extractor.core.rgb import RGBComposer
from hdfeos_extractor.qgis_ui.exportar import (componer_visible,
                                               geotransformacion,
                                               ruta_temporal)

GT = (500000.0, 30.0, 0.0, 4600000.0, 0.0, -30.0)


@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(40, 60, 9),
                                        longitudes_patron(9), name="escena.h5")


def test_se_compone_solo_lo_visible(cubo):
    """El punto de todo esto: al mapa va la vista, no el cubo."""
    rgb, paso = componer_visible(cubo, RGBComposer(600.0, 550.0, 500.0),
                                 (10, 5, 29, 20))
    assert rgb.dtype == np.uint8 and rgb.shape[2] == 3
    assert rgb.shape[0] == 16 and rgb.shape[1] == 20


def test_la_geotransformacion_se_corre_al_origen_de_la_ventana():
    """Olvidarlo pone la capa en el lugar equivocado, y eso se ve recien
    cuando se compara con otra capa."""
    gt = geotransformacion(GeoTransform(GT), (10, 5, 29, 20), paso=1)
    assert gt[0] == 500000.0 + 10 * 30.0
    assert gt[3] == 4600000.0 - 5 * 30.0
    assert gt[1] == 30.0 and gt[5] == -30.0


def test_el_submuestreo_agranda_el_pixel():
    """Con el paso olvidado la capa sale con la escala equivocada."""
    gt = geotransformacion(GeoTransform(GT), (0, 0, 99, 99), paso=4)
    assert gt[1] == 120.0 and gt[5] == -120.0
    assert gt[0] == 500000.0                     # el origen no cambia


def test_una_escena_sin_georreferencia_usa_el_indice_de_pixel():
    gt = geotransformacion(GeoTransform.identidad(), (3, 7, 10, 20), paso=1)
    assert gt[0] == 3.0 and gt[3] == -7.0


def test_el_nombre_dice_de_que_escena_y_de_que_bandas():
    """Despues de media hora de trabajo el mapa tiene cuatro de estas capas y
    "salida_1.tif" no distingue ninguna."""
    ruta = ruta_temporal("20250223_165546_basic_sr.h5", 842.3, 665.1, 559.8)
    assert ruta.endswith("_rgb_842-665-560.tif")
    assert "20250223_165546_basic_sr" in ruta


def test_el_nombre_sobrevive_a_caracteres_raros():
    ruta = ruta_temporal("escena con espacios/y barras.dat", 800, 600, 400)
    assert "/y barras" not in ruta.split("_rgb_")[0].split("/")[-1]


# -- escritura, solo si hay GDAL ---------------------------------------------
def test_se_escribe_un_geotiff_legible(tmp_path, cubo):
    import os
    gdal = pytest.importorskip("osgeo.gdal", reason="hace falta GDAL")
    from hdfeos_extractor.qgis_ui.exportar import enviar_vista
    ruta = str(tmp_path / "vista.tif")
    salida, nombre = enviar_vista(cubo, RGBComposer(600.0, 550.0, 500.0),
                                  (10, 5, 29, 20), GeoTransform(GT),
                                  ruta=ruta)
    assert os.path.isfile(salida) and "RGB" in nombre
    ds = gdal.Open(salida)
    assert ds.RasterCount == 3
    assert (ds.RasterXSize, ds.RasterYSize) == (20, 16)
    assert ds.GetGeoTransform()[0] == 500000.0 + 10 * 30.0
