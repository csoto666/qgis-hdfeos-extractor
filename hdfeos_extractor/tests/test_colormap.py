# -*- coding: utf-8 -*-
"""Pruebas de las paletas."""

import numpy as np
import pytest

from hdfeos_extractor.core.colormap import (COLOR_SIN_DATO, PALETAS,
                                            colorear, nombres, tabla)


def test_la_tabla_tiene_la_forma_y_el_tipo_de_una_paleta():
    for nombre in nombres():
        lut = tabla(nombre)
        assert lut.shape == (256, 3) and lut.dtype == np.uint8


def test_los_extremos_de_la_tabla_son_los_puntos_de_control():
    for nombre, puntos in PALETAS.items():
        lut = tabla(nombre)
        assert tuple(lut[0]) == tuple(puntos[0][1:])
        assert tuple(lut[-1]) == tuple(puntos[-1][1:])


def test_la_paleta_predeterminada_va_primero():
    assert nombres()[0] == "arcoiris"


def test_una_paleta_inexistente_dice_cuales_hay():
    with pytest.raises(KeyError, match="arcoiris"):
        tabla("psicodelica")


def test_grises_es_monotona_en_los_tres_canales():
    lut = tabla("grises").astype(int)
    assert (np.diff(lut[:, 0]) >= 0).all()
    assert (lut[:, 0] == lut[:, 1]).all() and (lut[:, 1] == lut[:, 2]).all()


def test_viridis_sube_en_luminancia_de_punta_a_punta():
    """Es lo que la vuelve legible en escala de grises, que es justamente lo
    que el arcoiris no hace."""
    lut = tabla("viridis").astype(float)
    luz = 0.2126 * lut[:, 0] + 0.7152 * lut[:, 1] + 0.0722 * lut[:, 2]
    assert luz[-1] > luz[0]
    # Monotona salvo el ruido de la interpolacion entre puntos de control.
    assert (np.diff(luz) > -2.0).all()


# -- coloreado ----------------------------------------------------------------
def test_colorear_devuelve_una_imagen():
    img = colorear(np.arange(12, dtype=np.float32).reshape(3, 4))
    assert img.shape == (3, 4, 3) and img.dtype == np.uint8


def test_el_minimo_y_el_maximo_caen_en_los_extremos_de_la_paleta():
    datos = np.array([[0.0, 1.0]], dtype=np.float32)
    img = colorear(datos, "grises")
    assert tuple(img[0, 0]) == (0, 0, 0)
    assert tuple(img[0, 1]) == (255, 255, 255)


def test_un_rango_explicito_permite_compartir_escala_entre_caras():
    """Si cada cara se normaliza sola, la de arriba y la de la derecha dicen
    cosas distintas con el mismo color y el cubo miente."""
    cara_a = np.array([[0.0, 0.5]], dtype=np.float32)
    cara_b = np.array([[0.5, 1.0]], dtype=np.float32)
    ia = colorear(cara_a, "grises", lo=0.0, hi=1.0)
    ib = colorear(cara_b, "grises", lo=0.0, hi=1.0)
    assert tuple(ia[0, 1]) == tuple(ib[0, 0])       # el 0.5 sale igual
    # Sin rango compartido, el mismo 0.5 sale blanco en una y negro en la otra.
    assert tuple(colorear(cara_a, "grises")[0, 1]) != \
        tuple(colorear(cara_b, "grises")[0, 0])


def test_las_bandas_malas_salen_como_hueco_y_no_de_un_color_vivo():
    """Sin tratar el NaN, se vuelve un indice cualquiera de la tabla y la
    ventana de absorcion aparece pintada de un color al azar."""
    datos = np.array([[0.0, np.nan, 1.0]], dtype=np.float32)
    img = colorear(datos, "arcoiris")
    assert tuple(img[0, 1]) == COLOR_SIN_DATO
    assert tuple(img[0, 0]) != COLOR_SIN_DATO


def test_una_matriz_toda_nan_no_revienta():
    img = colorear(np.full((2, 2), np.nan, dtype=np.float32))
    assert img.shape == (2, 2, 3)
    assert (img == np.asarray(COLOR_SIN_DATO, dtype=np.uint8)).all()


def test_una_matriz_constante_no_revienta():
    img = colorear(np.full((2, 3), 7.0, dtype=np.float32))
    assert img.shape == (2, 3, 3)


def test_los_valores_fuera_del_rango_se_recortan():
    datos = np.array([[-5.0, 0.5, 99.0]], dtype=np.float32)
    img = colorear(datos, "grises", lo=0.0, hi=1.0)
    assert tuple(img[0, 0]) == (0, 0, 0)
    assert tuple(img[0, 2]) == (255, 255, 255)


def test_solo_matrices_2d():
    with pytest.raises(ValueError, match="2D"):
        colorear(np.zeros((2, 2, 2), dtype=np.float32))
