# -*- coding: utf-8 -*-
"""Pruebas de las capas de huellas: que cada firma acabe donde le toca."""

import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from dobles import instalar_si_falta_qgis

instalar_si_falta_qgis()

from hdfeos_extractor.core.geo import GeoTransform
from hdfeos_extractor.core.georef import Georreferencia
from hdfeos_extractor.core.spectral import Signature
from hdfeos_extractor.qgis_ui.capas import (agregar_al_proyecto,
                                            aviso_de_huellas,
                                            capas_de_firmas,
                                            exportar_geojson)

GT = GeoTransform((500000.0, 10.0, 0.0, 4000000.0, 0.0, -10.0))
WL = np.array([450.0, 650.0, 850.0])
CON_SRC = Georreferencia(gt=GT.gt, epsg=32619)
SIN_SRC = Georreferencia.ninguna()


def firma(pixeles, nombre="una", color="#00ff00"):
    return Signature(nombre, WL, np.ones(3), pixels=pixeles, color=color,
                     count=len(pixeles), source="escena.h5")


def rectangulo(x0, y0, x1, y1):
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def test_los_puntos_y_las_areas_van_a_capas_distintas():
    """Es lo que se pidio, y ademas casi ninguna herramienta abre una capa
    con dos tipos de geometria."""
    firmas = [firma([(1, 1)], "un pixel"),
              firma(rectangulo(2, 2, 4, 4), "un area"),
              firma([(0, 0), (9, 9)], "sueltos")]
    puntos, areas, _ = capas_de_firmas(firmas, GT, CON_SRC)

    assert puntos.name() == "Firmas - puntos"
    assert areas.name() == "Firmas - areas"
    assert puntos.featureCount() == 2          # el pixel y los sueltos
    assert areas.featureCount() == 1
    assert puntos.geometria_declarada() == "MultiPoint"
    assert areas.geometria_declarada() == "Polygon"


def test_el_area_sale_como_poligono_y_el_pixel_como_punto():
    firmas = [firma([(1, 1)], "un pixel"),
              firma(rectangulo(2, 2, 3, 3), "un area")]
    puntos, areas, _ = capas_de_firmas(firmas, GT, CON_SRC)
    assert puntos.getFeatures()[0].geometry().clase == "multipunto"
    assert areas.getFeatures()[0].geometry().clase == "poligono"


def test_si_no_hay_areas_no_se_crea_una_capa_vacia():
    """Una capa vacia llamada 'Firmas - areas' hace pensar que algo fallo."""
    puntos, areas, _ = capas_de_firmas([firma([(1, 1)])], GT, CON_SRC)
    assert puntos is not None
    assert areas is None


def test_cada_huella_lleva_los_campos_de_su_firma():
    firmas = [firma([(1, 1)], "agua turbia", color="#3388ff")]
    puntos, _, _ = capas_de_firmas(firmas, GT, CON_SRC)
    campos = [c.name() for c in puntos.fields()]
    assert campos[:3] == ["nombre", "tipo", "pixeles"]
    valores = puntos.getFeatures()[0].attributes()
    assert valores[0] == "agua turbia"
    assert valores[1] == "punto"
    assert "#3388ff" in valores


def test_las_capas_llevan_el_sistema_de_la_escena():
    puntos, _, _ = capas_de_firmas([firma([(1, 1)])], GT, CON_SRC)
    assert puntos.crs() is not None


def test_sin_sistema_de_referencia_la_capa_sale_igual_pero_se_avisa():
    """Sale igual porque la forma sirve; el aviso es para que nadie crea que
    esta ubicada."""
    puntos, _, aviso = capas_de_firmas([firma([(1, 1)])], GT, SIN_SRC)
    assert puntos is not None
    assert "coordenadas de pixel" in aviso


def test_una_firma_sin_pixeles_se_queda_fuera_y_se_dice():
    """Una firma leida de un CSV ajeno no trae pixeles. Ponerla en cualquier
    sitio del mapa seria afirmar algo falso."""
    firmas = [firma([], "de fuera"), firma([(1, 1)], "de aqui")]
    puntos, _, aviso = capas_de_firmas(firmas, GT, CON_SRC)
    assert puntos.featureCount() == 1
    assert "no traen pixeles" in aviso


def test_cada_huella_se_pinta_del_color_de_su_curva():
    """Es lo que relaciona el mapa con el grafico sin leer ninguna leyenda."""
    firmas = [firma([(1, 1)], "verde", "#00ff00"),
              firma([(2, 2)], "azul", "#0000ff")]
    puntos, _, _ = capas_de_firmas(firmas, GT, CON_SRC)
    assert puntos.renderer is not None
    assert puntos.renderer.campo == "color"
    assert len(puntos.renderer.categorias) == 2


def test_solo_se_agregan_al_proyecto_las_capas_que_existen():
    puntos, areas, _ = capas_de_firmas([firma([(1, 1)])], GT, CON_SRC)
    assert agregar_al_proyecto([puntos, areas]) == 1


def test_el_aviso_dice_cuantas_huellas_salieron():
    assert "2 punto(s) y 1 area(s)" in aviso_de_huellas(CON_SRC, 2, 1, 0)


# -- el GeoJSON --------------------------------------------------------------
def test_se_escriben_dos_geojson(tmp_path):
    firmas = [firma([(1, 1)], "un pixel"),
              firma(rectangulo(2, 2, 3, 3), "un area")]
    escritos, _ = exportar_geojson(firmas, GT, CON_SRC,
                                   str(tmp_path / "firmas"))
    nombres = sorted(r.rsplit("/", 1)[-1] for r, _ in escritos)
    assert nombres == ["firmas_areas.geojson", "firmas_puntos.geojson"]
    assert all(cuantos == 1 for _, cuantos in escritos)


def test_no_se_escribe_un_geojson_vacio(tmp_path):
    escritos, _ = exportar_geojson([firma([(1, 1)])], GT, CON_SRC,
                                   str(tmp_path / "firmas"))
    assert len(escritos) == 1
    assert escritos[0][0].endswith("_puntos.geojson")


def test_sin_src_el_geojson_sale_igual_pero_lo_dice(tmp_path):
    """GeoJSON asume WGS84. Sin SRC no hay desde donde reproyectar, y callar
    eso es entregar un archivo que el vecino abrira en el sitio equivocado.
    """
    escritos, aviso = exportar_geojson([firma([(1, 1)])], GT, SIN_SRC,
                                       str(tmp_path / "firmas"))
    assert len(escritos) == 1
    assert "no declara sistema" in aviso
