# -*- coding: utf-8 -*-
"""Pruebas de la vista del cubo.

Lo que de verdad hay que comprobar aca no es que se vea bonito sino dos cosas
concretas: que cada cara sea el transecto que dice ser -y no el borde de la
escena, que es lo que muestra un cubo estatico-, y que la proyeccion oblicua
sea invertible, porque de eso depende que un clic caiga donde el usuario
apunto.
"""

import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from conftest import BANDAS, cubo_patron, longitudes_patron
from hdfeos_extractor.core.cube import HyperspectralCube
from hdfeos_extractor.core.rgb import RGBComposer
from hdfeos_extractor.vista.cube_view import CubeView, a_qimage


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(40, 60, BANDAS),
                                        longitudes_patron())


@pytest.fixture
def vista(app, cubo):
    v = CubeView()
    v.resize(600, 420)
    v.set_cube(cubo, RGBComposer(2450.0, 1450.0, 450.0))
    return v


# -- conversion a QImage ------------------------------------------------------
def test_a_qimage_conserva_los_pixeles():
    arreglo = np.zeros((2, 3, 3), dtype=np.uint8)
    arreglo[0, 0] = (255, 0, 0)
    arreglo[1, 2] = (0, 255, 0)
    img = a_qimage(arreglo)
    assert (img.width(), img.height()) == (3, 2)
    from PyQt5.QtGui import QColor
    assert QColor(img.pixel(0, 0)).getRgb()[:3] == (255, 0, 0)
    assert QColor(img.pixel(2, 1)).getRgb()[:3] == (0, 255, 0)


def test_la_qimage_no_depende_del_buffer_de_numpy():
    """QImage no toma posesion del buffer. Sin la copia, el arreglo se libera
    mientras Qt todavia lo esta dibujando: una caida lejos de aca."""
    from PyQt5.QtGui import QColor
    arreglo = np.full((4, 4, 3), 200, dtype=np.uint8)
    img = a_qimage(arreglo)
    del arreglo
    import gc
    gc.collect()
    assert QColor(img.pixel(1, 1)).getRgb()[:3] == (200, 200, 200)


# -- las caras son los transectos ---------------------------------------------
def test_las_caras_tienen_la_forma_de_los_transectos(vista, cubo):
    """Superior = (x, banda) transpuesta; derecha = (y, banda) transpuesta."""
    assert vista._superior.width() == cubo.samples
    assert vista._superior.height() == cubo.bands
    assert vista._derecha.width() == cubo.lines
    assert vista._derecha.height() == cubo.bands


def test_mover_la_cruz_cambia_las_caras(vista):
    """Es toda la diferencia con un cubo estatico: las caras son el corte que
    pasa por la cruz, no el borde de la escena."""
    vista.set_posicion(5, 5)
    antes = vista._superior.copy()
    vista.set_posicion(5, 30)
    assert vista._superior != antes


def test_mover_solo_en_x_no_cambia_la_cara_superior(vista):
    """La cara superior es el corte en y: moverse en x no la toca."""
    vista.set_posicion(5, 12)
    antes = vista._superior.copy()
    vista.set_posicion(40, 12)
    assert vista._superior == antes


def test_la_posicion_se_recorta_a_la_imagen(vista, cubo):
    vista.set_posicion(9999, -5)
    assert vista.x == cubo.samples - 1 and vista.y == 0


def test_las_dos_caras_comparten_escala_de_color(vista, cubo):
    """Si cada cara se normalizara sola, el mismo valor saldria de dos colores
    distintos en las dos caras y el cubo mentiria donde se lo mira para
    comparar. Se comprueba sobre un cubo donde una cara es mucho mas brillante
    que la otra."""
    datos = np.ones((20, 20, 5), dtype=np.float32)
    datos[10, :, :] = 10.0                 # una fila mucho mas brillante
    c = HyperspectralCube.from_array(datos, np.linspace(400, 900, 5))
    v = CubeView()
    v.resize(400, 300)
    v.set_cube(c, RGBComposer(900.0, 600.0, 400.0))
    v.set_posicion(5, 0)                   # cara superior en una fila normal
    from PyQt5.QtGui import QColor
    gris_superior = QColor(v._superior.pixel(1, 1)).getRgb()[:3]
    gris_derecha = QColor(v._derecha.pixel(1, 1)).getRgb()[:3]
    assert gris_superior == gris_derecha


# -- geometria ----------------------------------------------------------------
def test_el_cubo_entra_en_el_widget(vista):
    origen, ancho, alto, d = vista._geometria()
    assert origen.x() >= 0 and origen.y() >= 0
    assert origen.x() + ancho + d.x() <= vista.width() + 1
    assert origen.y() + alto <= vista.height() + 1
    assert origen.y() + d.y() >= -1           # la cara superior no se corta


def test_la_profundidad_va_hacia_arriba_y_a_la_derecha(vista):
    _, _, _, d = vista._geometria()
    assert d.x() > 0 and d.y() < 0


def test_el_frente_conserva_la_proporcion_de_la_escena(vista, cubo):
    _, ancho, alto, _ = vista._geometria()
    assert ancho / alto == pytest.approx(cubo.samples / float(cubo.lines),
                                         rel=1e-6)


def test_la_geometria_se_adapta_al_tamano(vista):
    a = vista._geometria()[1]
    vista.resize(300, 210)
    b = vista._geometria()[1]
    assert b < a


def test_sin_cubo_no_hay_geometria(app):
    assert CubeView()._geometria() is None


# -- la proyeccion es invertible ----------------------------------------------
def test_la_transformacion_de_cada_cara_se_puede_invertir(vista):
    """De esto depende que un clic sobre una cara caiga en la banda correcta."""
    vista.render(_lienzo(vista))
    for nombre in ("superior", "derecha"):
        t = vista._transformadas[nombre]
        inversa, ok = t.inverted()
        assert ok, nombre
        for punto in ((0.0, 0.0), (10.0, 4.0)):
            from PyQt5.QtCore import QPointF
            ida = t.map(QPointF(*punto))
            vuelta = inversa.map(ida)
            assert vuelta.x() == pytest.approx(punto[0], abs=1e-6)
            assert vuelta.y() == pytest.approx(punto[1], abs=1e-6)


def _lienzo(widget):
    from PyQt5 import QtGui
    pix = QtGui.QPixmap(widget.width(), widget.height())
    pix.fill(QtGui.QColor("black"))
    return pix


# -- interaccion --------------------------------------------------------------
def test_un_clic_en_el_frente_elige_el_pixel_de_abajo(vista, cubo):
    from PyQt5.QtCore import QPointF
    vista.render(_lienzo(vista))
    origen, ancho, alto, _ = vista._geometria()
    objetivo = (17, 9)
    punto = QPointF(origen.x() + (objetivo[0] + 0.5) / cubo.samples * ancho,
                    origen.y() + (objetivo[1] + 0.5) / cubo.lines * alto)
    vista._mover_a(punto)
    assert (vista.x, vista.y) == objetivo


def test_un_clic_en_una_cara_espectral_devuelve_su_longitud_de_onda(vista,
                                                                    cubo):
    """Es lo que vuelve navegable el eje que en ENVI solo se mira: se ve una
    franja interesante en el costado y se salta a ella."""
    from PyQt5.QtCore import QPointF
    vista.render(_lienzo(vista))
    recibidas = []
    vista.longitudElegida.connect(recibidas.append)
    t = vista._transformadas["superior"]
    fila_banda = cubo.bands - 1                       # el fondo del cubo
    punto = t.map(QPointF(cubo.samples / 2.0, fila_banda + 0.5))
    vista._elegir_longitud("superior", punto)
    assert recibidas
    assert recibidas[0] == pytest.approx(float(cubo.wavelengths[-1]))


def test_un_clic_al_frente_de_la_cara_da_la_primera_banda(vista, cubo):
    from PyQt5.QtCore import QPointF
    vista.render(_lienzo(vista))
    recibidas = []
    vista.longitudElegida.connect(recibidas.append)
    t = vista._transformadas["derecha"]
    vista._elegir_longitud("derecha", t.map(QPointF(cubo.lines / 2.0, 0.0)))
    assert recibidas[0] == pytest.approx(float(cubo.wavelengths[0]))


def test_el_clic_fuera_de_toda_cara_no_hace_nada(vista):
    from PyQt5.QtCore import QPointF
    vista.render(_lienzo(vista))
    antes = (vista.x, vista.y)
    for nombre in ("frontal", "superior", "derecha"):
        assert not vista._en_cara(nombre, QPointF(-50.0, -50.0))
    assert (vista.x, vista.y) == antes


# -- pintado ------------------------------------------------------------------
def test_se_pinta_con_cubo_y_sin_cubo(app, vista):
    vacia = CubeView()
    vacia.resize(300, 200)
    vacia.render(_lienzo(vacia))           # el mensaje de "abra un cubo"
    vista.render(_lienzo(vista))
    assert set(vista._cuadros) == {"frontal", "superior", "derecha"}


def test_los_marcadores_rgb_se_dibujan_dentro_de_las_caras(vista, cubo):
    vista.set_marcadores_rgb([450.0, 1450.0, 2450.0])
    assert len(vista.marcadores) == 3
    assert vista._fraccion_de_banda(450.0) == pytest.approx(0.0)
    assert vista._fraccion_de_banda(2450.0) == pytest.approx(1.0)
    vista.render(_lienzo(vista))


def test_una_paleta_distinta_repinta_las_caras(vista):
    antes = vista._superior.copy()
    vista.set_paleta("viridis")
    assert vista._superior != antes


def test_un_cubo_de_una_sola_banda_no_revienta(app):
    c = HyperspectralCube.from_array(np.ones((4, 4, 1), dtype=np.float32),
                                     [550.0])
    v = CubeView()
    v.resize(300, 200)
    v.set_cube(c, RGBComposer(550.0, 550.0, 550.0))
    assert v._fraccion_de_banda(550.0) == 0.0
    v.render(_lienzo(v))


# -- banda unica --------------------------------------------------------------
def test_un_clic_en_el_costado_pone_esa_banda_en_el_frente(vista, cubo):
    """El gesto mas natural frente a un cubo: se ve una franja rara en el
    costado y uno quiere ver esa banda."""
    from PyQt5.QtCore import QPointF
    vista.render(_lienzo(vista))
    rgb = vista._frontal.copy()
    t = vista._transformadas["superior"]
    vista._elegir_longitud("superior", t.map(QPointF(cubo.samples / 2.0,
                                                     cubo.bands - 0.5)))
    assert vista.banda_unica == cubo.bands - 1
    assert vista._frontal != rgb


def test_la_banda_unica_se_recorta_al_cubo(vista, cubo):
    vista.set_banda_unica(9999)
    assert vista.banda_unica == cubo.bands - 1
    vista.set_banda_unica(-3)
    assert vista.banda_unica == 0


def test_volver_a_none_restaura_la_composicion(vista):
    vista.set_banda_unica(2)
    solo_banda = vista._frontal.copy()
    vista.set_banda_unica(None)
    assert vista.banda_unica is None
    assert vista._frontal != solo_banda


def test_la_banda_unica_comparte_el_rango_con_las_caras(vista):
    """Si el frente se normalizara solo, el mismo valor tendria un color en el
    frente y otro en el costado, y el cubo dejaria de ser un cubo."""
    vista.set_banda_unica(3)
    assert vista._rango is not None
