# -*- coding: utf-8 -*-
"""Pruebas de la conversion mapa <-> pixel."""

import numpy as np
import pytest

from hyperspectral_explorer.core.geo import GeoError, GeoTransform

# Escena tipica: origen en (500000, 4600000), pixel de 30 m, norte arriba.
GT = (500000.0, 30.0, 0.0, 4600000.0, 0.0, -30.0)


@pytest.fixture
def gt():
    return GeoTransform(GT)


def test_la_esquina_superior_izquierda_es_el_pixel_cero(gt):
    assert gt.to_pixel(500000.0, 4600000.0) == (0, 0)


def test_el_eje_y_va_al_reves_que_las_filas(gt):
    """Y crece hacia el norte y las filas crecen hacia el sur. Confundirlo
    espeja la imagen y nadie lo nota hasta comparar con otra capa."""
    assert gt.to_pixel(500000.0, 4600000.0 - 3 * 30.0) == (0, 3)
    assert gt.to_pixel(500000.0 + 5 * 30.0, 4600000.0) == (5, 0)


def test_ida_y_vuelta_por_el_centro_del_pixel(gt):
    for col, fila in [(0, 0), (7, 3), (123, 456)]:
        x, y = gt.to_map(col, fila)
        assert gt.to_pixel(x, y) == (col, fila)


def test_to_map_devuelve_el_centro_no_la_esquina(gt):
    """Para marcar el pixel seleccionado. Con la esquina, la marca queda
    corrida medio pixel arriba y a la izquierda."""
    assert gt.to_map(0, 0) == (500015.0, 4599985.0)
    assert gt.to_map(0, 0, centro=False) == (500000.0, 4600000.0)


def test_el_pixel_se_toma_por_piso_no_por_redondeo(gt):
    """El pixel 0 va de 0.0 a 1.0. Con round(), medio pixel de cada lado
    caeria en el vecino y el clic cerca del borde daria el espectro de al
    lado."""
    casi_uno = 500000.0 + 0.9 * 30.0
    assert gt.to_pixel(casi_uno, 4600000.0) == (0, 0)
    justo_uno = 500000.0 + 1.0 * 30.0
    assert gt.to_pixel(justo_uno, 4600000.0) == (1, 0)


def test_sin_redondear_devuelve_la_posicion_continua(gt):
    col, fila = gt.to_pixel(500000.0 + 2.5 * 30.0, 4600000.0 - 1.25 * 30.0,
                            redondear=False)
    assert col == pytest.approx(2.5) and fila == pytest.approx(1.25)


def test_fuera_de_la_imagen_da_indices_fuera_de_rango(gt):
    """No se recorta aca: quien llama tiene que poder distinguir un clic
    afuera de un clic en el borde."""
    col, fila = gt.to_pixel(499000.0, 4601000.0)
    assert col < 0 and fila < 0
    assert not gt.contiene(col, fila, 100, 100)
    assert gt.contiene(0, 0, 100, 100)
    assert not gt.contiene(100, 0, 100, 100)


def test_el_pixel_tiene_cuatro_esquinas_cerradas(gt):
    caja = gt.pixel_bbox(2, 3)
    assert len(caja) == 4
    assert caja[0] == (500060.0, 4599910.0)
    assert caja[2] == (500090.0, 4599880.0)


def test_tamano_de_pixel(gt):
    assert gt.tamano_pixel == (30.0, 30.0)
    assert not gt.tiene_rotacion


# -- rotacion -----------------------------------------------------------------
def test_una_escena_rotada_necesita_la_matriz_inversa():
    """Sin ortorectificar, gt2 y gt4 no son cero y dividir por el tamano de
    pixel deja de funcionar. Es el caso que justifica invertir la matriz."""
    angulo = np.radians(30.0)
    p = 10.0
    rotada = GeoTransform((1000.0,
                           p * np.cos(angulo), -p * np.sin(angulo),
                           2000.0,
                           -p * np.sin(angulo), -p * np.cos(angulo)))
    assert rotada.tiene_rotacion
    for col, fila in [(0, 0), (4, 9), (37, 12)]:
        x, y = rotada.to_map(col, fila)
        assert rotada.to_pixel(x, y) == (col, fila)
    assert rotada.tamano_pixel[0] == pytest.approx(p)


def test_una_geotransformacion_degenerada_falla_al_construir():
    """Es el unico momento util para avisar: despues cada conversion
    devolveria infinitos en silencio."""
    with pytest.raises(GeoError, match="degenerada"):
        GeoTransform((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))


def test_una_geotransformacion_con_otro_largo():
    with pytest.raises(GeoError, match="6 numeros"):
        GeoTransform((0.0, 1.0, 0.0))


# -- sin georreferencia -------------------------------------------------------
def test_la_identidad_usa_el_indice_de_pixel_como_coordenada():
    """Un cubo en geometria de sensor no tiene coordenadas de mapa; en vez de
    negarse a trabajar se usa el propio indice."""
    ident = GeoTransform.identidad()
    assert ident.to_pixel(0.5, -0.5) == (0, 0)
    assert ident.to_pixel(3.5, -7.5) == (3, 7)
    assert ident.to_map(3, 7) == (3.5, -7.5)
