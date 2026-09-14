# -*- coding: utf-8 -*-
"""Pruebas del grafico espectral.

Solo corren si hay enlaces de Qt. Dentro de QGIS siempre los hay; en una
maquina de integracion continua pelada, no, y ahi la suite se salta estas y
sigue -el nucleo no depende de Qt-.
"""

import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from hyperspectral_explorer.vista.spectral_plot import (Curva, SpectralPlot,
                                                        _formato, _marcas,
                                                        color_de)


@pytest.fixture(scope="module")
def app():
    """Una sola QApplication para todo el modulo, sin pantalla."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets
    instancia = QtWidgets.QApplication.instance()
    return instancia or QtWidgets.QApplication([])


# -- corte en los NaN ---------------------------------------------------------
def test_una_curva_sin_huecos_es_un_solo_tramo():
    c = Curva("a", [1.0, 2.0, 3.0, 4.0], [0.1, 0.2, 0.3, 0.4])
    tramos = c.tramos()
    assert len(tramos) == 1
    assert np.array_equal(tramos[0][0], [1.0, 2.0, 3.0, 4.0])


def test_la_curva_se_corta_en_las_bandas_malas():
    """El detalle que no es decorativo.

    Las ventanas de absorcion de vapor de agua llegan como NaN. Unirlas
    dibuja una recta limpia de 1340 a 1460 nm que parece una medicion y no lo
    es.
    """
    x = np.array([1300.0, 1320.0, 1400.0, 1420.0, 1500.0, 1520.0])
    y = np.array([0.30, 0.31, np.nan, np.nan, 0.28, 0.27])
    tramos = Curva("veg", x, y).tramos()
    assert len(tramos) == 2
    assert np.array_equal(tramos[0][0], [1300.0, 1320.0])
    assert np.array_equal(tramos[1][0], [1500.0, 1520.0])


def test_un_hueco_al_principio_y_al_final():
    y = [np.nan, 0.2, 0.3, 0.4, np.nan]
    tramos = Curva("a", [1.0, 2.0, 3.0, 4.0, 5.0], y).tramos()
    assert len(tramos) == 1
    assert np.array_equal(tramos[0][0], [2.0, 3.0, 4.0])


def test_un_punto_aislado_no_es_un_tramo():
    """Un solo punto valido entre dos NaN no dibuja ninguna linea."""
    y = [np.nan, 0.2, np.nan, 0.4, 0.5]
    tramos = Curva("a", [1.0, 2.0, 3.0, 4.0, 5.0], y).tramos()
    assert len(tramos) == 1
    assert np.array_equal(tramos[0][0], [4.0, 5.0])


def test_una_curva_toda_nan_no_tiene_tramos():
    assert Curva("a", [1.0, 2.0], [np.nan, np.nan]).tramos() == []


def test_muchos_huecos():
    x = np.arange(12.0)
    y = np.arange(12.0)
    y[[2, 3, 7]] = np.nan
    assert len(Curva("a", x, y).tramos()) == 3


# -- marcas de eje ------------------------------------------------------------
def test_las_marcas_caen_en_numeros_redondos():
    """Sin esto las etiquetas salen en valores como 437.83, que nadie lee."""
    marcas = _marcas(400.0, 2450.0)
    assert all(m % 250.0 == 0 or m % 500.0 == 0 for m in marcas)
    assert 3 <= len(marcas) <= 12


def test_las_marcas_quedan_dentro_del_rango():
    for lo, hi in [(0.0, 1.0), (0.02, 0.47), (400.0, 2450.0), (-3.0, 3.0)]:
        marcas = _marcas(lo, hi)
        assert marcas, (lo, hi)
        assert all(lo - 1e-9 <= m <= hi + 1e-9 for m in marcas), (lo, hi)


def test_un_rango_degenerado_no_produce_marcas():
    assert _marcas(1.0, 1.0) == []
    assert _marcas(np.nan, 1.0) == []


def test_formato_de_etiquetas():
    assert _formato(1500.0) == "1500"
    assert _formato(0.25) == "0.25"
    assert _formato(0.5) == "0.5"


def test_la_paleta_da_la_vuelta():
    assert color_de(0) == color_de(10)
    assert color_de(0) != color_de(1)


# -- widget -------------------------------------------------------------------
@pytest.mark.parametrize("forzar_lienzo", [True, False])
def test_el_grafico_se_construye_con_los_dos_respaldos(app, forzar_lienzo):
    """La interfaz publica tiene que ser la misma con y sin pyqtgraph."""
    g = SpectralPlot(forzar_lienzo=forzar_lienzo)
    g.set_unidad("nm")
    g.set_curvas([Curva("veg", np.linspace(400, 2400, 50),
                        np.random.default_rng(0).random(50))])
    g.set_marcadores_rgb([842.0, 665.0, 560.0])
    g.clear()
    assert g.etiqueta_x.startswith("Longitud de onda")


def test_sin_longitudes_de_onda_el_eje_cambia_de_rotulo(app):
    g = SpectralPlot(forzar_lienzo=True)
    g.set_unidad("banda")
    assert g.etiqueta_x == "Numero de banda"


def test_el_lienzo_se_pinta_sin_datos_y_con_datos(app):
    """Pintar de verdad sobre un QPixmap: es la unica forma de que un error
    en paintEvent salga como fallo de prueba y no como un panel en blanco."""
    from PyQt5 import QtGui, QtCore
    g = SpectralPlot(forzar_lienzo=True)
    g.resize(420, 260)

    def pintar():
        pix = QtGui.QPixmap(420, 260)
        pix.fill(QtGui.QColor("white"))
        g._grafico.resize(420, 260)
        g._grafico.render(pix, QtCore.QPoint(),
                          QtGui.QRegion(g._grafico.rect()))
        return pix

    pintar()                                     # vacio: el mensaje de ayuda
    wl = np.linspace(400.0, 2450.0, 120)
    valores = 0.3 + 0.1 * np.sin(wl / 200.0)
    valores[40:46] = np.nan                      # ventana de absorcion
    g.set_curvas([
        Curva("Vegetacion", wl, valores, color_de(0)),
        Curva("Suelo", wl, valores * 0.6 + 0.1, color_de(1), punteada=True,
              banda=np.full(wl.size, 0.02)),      # firma de area
    ])
    g.set_marcadores_rgb([842.0, 665.0, 560.0])
    assert not pintar().isNull()


def test_el_cursor_lee_el_valor_de_cada_curva(app):
    from hyperspectral_explorer.vista.spectral_plot import _valor_en
    c = Curva("a", [400.0, 500.0, 600.0], [0.1, 0.2, 0.3])
    assert _valor_en(c, 505.0) == pytest.approx(0.2)
    assert _valor_en(c, 10.0) == pytest.approx(0.1)     # se pega al extremo
    assert _valor_en(Curva("b", [1.0], [np.nan]), 1.0) is None


def test_una_firma_plana_no_se_dibuja_sobre_el_borde(app):
    """Agua en el SWIR: rango cero. Sin abrir el rango la curva quedaria
    pegada al marco del grafico."""
    g = SpectralPlot(forzar_lienzo=True)
    g.set_curvas([Curva("agua", [400.0, 500.0, 600.0], [0.01, 0.01, 0.01])])
    _, _, y0, y1 = g._grafico.limites()
    assert y1 > y0
    assert y0 < 0.01 < y1
