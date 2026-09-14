# -*- coding: utf-8 -*-
"""Pruebas del controlador de enlace.

Es el archivo donde de verdad se esconden los errores del frontend -una senal
que no sale, una vista que queda desincronizada- y el unico del frontend que
se puede probar sin abrir QGIS. Por eso el controlador no importa QGIS.
"""

import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from conftest import BANDAS, cubo_patron, longitudes_patron
from hyperspectral_explorer.core.cube import HyperspectralCube
from hyperspectral_explorer.qgis_ui.controller import (
    MODO_AREA, MODO_PIXEL, MODO_X, MODO_Y, SpatialSpectralController)


class Espia(object):
    """Cuenta emisiones de una senal y guarda la ultima carga."""

    def __init__(self, senal):
        self.veces = 0
        self.ultimo = None
        senal.connect(self._recibir)

    def _recibir(self, *args):
        self.veces += 1
        self.ultimo = args[0] if len(args) == 1 else args


@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(), longitudes_patron(),
                                        name="escena")


@pytest.fixture
def ctrl(cubo):
    c = SpatialSpectralController()
    c.set_cube(cubo)
    return c


# -- cubo ---------------------------------------------------------------------
def test_abrir_un_cubo_avisa_a_todos(cubo):
    c = SpatialSpectralController()
    cubos, composiciones, curvas = (Espia(c.cuboCambiado),
                                    Espia(c.composicionCambiada),
                                    Espia(c.curvasCambiadas))
    c.set_cube(cubo)
    assert cubos.ultimo is cubo
    assert composiciones.veces == 1 and curvas.veces == 1


def test_cambiar_de_cubo_limpia_la_pantalla_pero_no_la_biblioteca(ctrl, cubo):
    """Es la distincion entre las dos colecciones: el grafico muestra lo que
    se esta mirando, la biblioteca guarda lo que se decidio conservar -que es
    justamente lo que sirve para comparar entre escenas-."""
    ctrl.on_pixel_changed(1, 1)
    ctrl.save_current("Vegetacion")
    otro = HyperspectralCube.from_array(cubo_patron(3, 3, BANDAS),
                                        longitudes_patron())
    ctrl.set_cube(otro)
    assert ctrl.pixel is None and ctrl.firma_actual is None
    assert ctrl.library.names() == ["Vegetacion"]


def test_al_abrir_se_elige_un_preset_que_el_sensor_alcance():
    """Un cubo VNIR con el compositor en un preset SWIR da una imagen gris:
    las tres bandas se resuelven a la ultima."""
    c = SpatialSpectralController()
    c.on_preset_selected("Suelos y geologia")        # pide 2200 nm
    vnir = HyperspectralCube.from_array(cubo_patron(4, 4, 6),
                                        np.linspace(450.0, 900.0, 6))
    c.set_cube(vnir)
    assert max(c.composer.red, c.composer.green, c.composer.blue) <= 960.0


def test_un_preset_que_ya_sirve_no_se_toca(cubo):
    c = SpatialSpectralController()
    c.on_preset_selected("Falso color IR")
    antes = (c.composer.red, c.composer.green, c.composer.blue)
    c.set_cube(cubo)
    assert (c.composer.red, c.composer.green, c.composer.blue) == antes


def test_un_cubo_sin_longitudes_de_onda_igual_recibe_tres_bandas():
    c = SpatialSpectralController()
    sin_wl = HyperspectralCube.from_array(cubo_patron(4, 4, 5))
    c.set_cube(sin_wl)
    r, g, b = c.composer.bands_of(sin_wl)
    assert len({r, g, b}) == 3


# -- pixel --------------------------------------------------------------------
def test_un_clic_produce_firma_senal_y_curva(ctrl, cubo):
    pixeles, curvas = Espia(ctrl.pixelCambiado), Espia(ctrl.curvasCambiadas)
    firma = ctrl.on_pixel_changed(3, 2)
    assert np.array_equal(firma.values, cubo.get_spectrum(3, 2))
    assert pixeles.ultimo == (3, 2)
    assert ctrl.modo == MODO_PIXEL and ctrl.pixel == (3, 2)
    assert len(curvas.ultimo) == 1


def test_un_clic_fuera_de_la_imagen_avisa_y_no_rompe(ctrl):
    mensajes = Espia(ctrl.mensaje)
    assert ctrl.on_pixel_changed(999, 999) is None
    assert "fuera de la imagen" in mensajes.ultimo
    assert ctrl.pixel is None


def test_sin_cubo_no_pasa_nada(cubo):
    c = SpatialSpectralController()
    assert c.on_pixel_changed(0, 0) is None
    assert c.on_x_changed(0) is None
    assert c.on_area_selected(0, 0, 1, 1) is None
    assert c.curvas() == []


# -- transectos ---------------------------------------------------------------
def test_mover_la_linea_en_x_resume_la_columna(ctrl, cubo):
    espia = Espia(ctrl.transectoCambiado)
    resumen = ctrl.on_x_changed(2)
    assert resumen["n"] == cubo.lines
    assert espia.ultimo == ("x", 2)
    assert ctrl.modo == MODO_X and ctrl.transecto == ("x", 2)
    esperado = cubo.get_transect("x", 2).mean(axis=0)
    assert np.allclose(resumen["mean"], esperado)


def test_mover_la_linea_en_y_resume_la_fila(ctrl, cubo):
    resumen = ctrl.on_y_changed(4)
    assert resumen["n"] == cubo.samples
    assert ctrl.modo == MODO_Y


def test_el_transecto_dibuja_media_y_extremos(ctrl):
    """La media sola esconde justamente la variacion que el usuario busca al
    mover la linea."""
    ctrl.on_x_changed(2)
    nombres = [c.nombre for c in ctrl.curvas()]
    assert any(n.startswith("media x=2") for n in nombres)
    assert "minimo" in nombres and "maximo" in nombres


def test_el_transecto_reemplaza_a_la_firma_de_pixel(ctrl):
    """Las dos cosas a la vez confundirian: el grafico mostraria un espectro
    de un pixel que ya no es el que la linea esta recorriendo."""
    ctrl.on_pixel_changed(1, 1)
    assert ctrl.firma_actual is not None
    ctrl.on_x_changed(2)
    assert ctrl.firma_actual is None
    ctrl.on_pixel_changed(1, 1)
    assert ctrl.transecto is not None      # se recuerda donde quedo la linea
    assert not any(c.nombre == "minimo" for c in ctrl.curvas())


def test_un_transecto_fuera_de_rango_avisa(ctrl):
    mensajes = Espia(ctrl.mensaje)
    assert ctrl.on_x_changed(999) is None
    assert "Columna" in mensajes.ultimo


# -- area ---------------------------------------------------------------------
def test_un_area_da_una_firma_media_con_envolvente(ctrl):
    firma = ctrl.on_area_selected(0, 0, 2, 2)
    assert ctrl.modo == MODO_AREA and firma.count == 9
    curva = ctrl.curvas()[-1]
    assert curva.banda is not None         # la envolvente sombreada


def test_varios_pixeles_sueltos(ctrl):
    firma = ctrl.on_pixels_selected([(0, 0), (4, 6)])
    assert firma.count == 2


# -- composicion --------------------------------------------------------------
def test_cambiar_una_banda_mueve_los_marcadores(ctrl):
    """Es la mitad del enlace entre las dos vistas: el grafico tiene que
    decir donde esta mirando la imagen."""
    espia = Espia(ctrl.composicionCambiada)
    ctrl.on_rgb_changed(red=2450.0)
    assert espia.veces == 1
    assert ctrl.marcadores_rgb()[0] == pytest.approx(2450.0)


def test_los_marcadores_se_ajustan_a_las_bandas_reales(ctrl):
    """Se pide 1000 nm y se marca la banda que de verdad existe, no 1000."""
    ctrl.on_rgb_changed(red=1000.0)
    assert ctrl.marcadores_rgb()[0] in list(ctrl.cube.wavelengths)


def test_un_preset_inexistente_avisa_y_no_cambia_nada(ctrl):
    mensajes = Espia(ctrl.mensaje)
    antes = ctrl.composer.red
    assert ctrl.on_preset_selected("Ultravioleta") is None
    assert "No existe el preset" in mensajes.ultimo
    assert ctrl.composer.red == antes


# -- biblioteca ---------------------------------------------------------------
def test_guardar_la_firma_actual(ctrl):
    ctrl.on_pixel_changed(2, 3)
    espia = Espia(ctrl.bibliotecaCambiada)
    firma = ctrl.save_current("Suelo", notas="parcela 4")
    assert firma.name == "Suelo" and firma.notes == "parcela 4"
    assert ctrl.library.names() == ["Suelo"] and espia.veces == 1


def test_la_firma_guardada_deja_de_ser_la_actual(ctrl):
    """Si siguiera siendolo, el proximo clic la modificaria ya dentro de la
    biblioteca."""
    ctrl.on_pixel_changed(2, 3)
    guardada = ctrl.save_current("Suelo")
    assert ctrl.firma_actual is None
    ctrl.on_pixel_changed(0, 0)
    assert np.array_equal(ctrl.library.get("Suelo").values, guardada.values)


def test_guardar_sin_nada_seleccionado_avisa(ctrl):
    mensajes = Espia(ctrl.mensaje)
    assert ctrl.save_current("X") is None
    assert "ninguna firma" in mensajes.ultimo


def test_cada_firma_guardada_recibe_un_color_distinto(ctrl):
    colores = []
    for i in range(3):
        ctrl.on_pixel_changed(i, i)
        colores.append(ctrl.save_current("f%d" % i).color)
    assert len(set(colores)) == 3


def test_elegir_una_firma_deja_solo_esa_visible(ctrl):
    for i in range(3):
        ctrl.on_pixel_changed(i, i)
        ctrl.save_current("f%d" % i)
    ctrl.on_signature_selected("f1")
    assert [f.name for f in ctrl.library if f.visible] == ["f1"]
    assert [c.nombre for c in ctrl.curvas()] == ["f1"]


def test_ocultar_y_mostrar(ctrl):
    ctrl.on_pixel_changed(1, 1)
    ctrl.save_current("f")
    ctrl.set_signature_visible("f", False)
    assert ctrl.curvas() == []
    ctrl.set_signature_visible("f", True)
    assert len(ctrl.curvas()) == 1


def test_borrar_y_renombrar(ctrl):
    ctrl.on_pixel_changed(1, 1)
    ctrl.save_current("f")
    assert ctrl.rename_signature("f", "Agua").name == "Agua"
    assert ctrl.remove_signature("Agua") is True
    assert ctrl.remove_signature("Agua") is False


def test_renombrar_a_uno_ocupado_avisa(ctrl):
    for i in range(2):
        ctrl.on_pixel_changed(i, i)
        ctrl.save_current("f%d" % i)
    mensajes = Espia(ctrl.mensaje)
    assert ctrl.rename_signature("f0", "f1") is None
    assert "Ya hay una firma" in mensajes.ultimo


def test_comparar_lo_que_se_ve_contra_lo_guardado(ctrl):
    ctrl.on_pixel_changed(2, 2)
    ctrl.save_current("referencia")
    ctrl.on_pixel_changed(2, 2)
    nombre, angulo = ctrl.compare_current()
    assert nombre == "referencia" and angulo == pytest.approx(0.0, abs=1e-4)


def test_comparar_sin_biblioteca_devuelve_nada(ctrl):
    ctrl.on_pixel_changed(1, 1)
    assert ctrl.compare_current() is None


# -- orden de dibujo ----------------------------------------------------------
def test_la_firma_actual_se_dibuja_encima_de_todo(ctrl):
    """Es la que el usuario acaba de pedir: tiene que distinguirse de un
    vistazo de las guardadas."""
    from hyperspectral_explorer.vista.spectral_plot import COLOR_ACTUAL
    ctrl.on_pixel_changed(0, 0)
    ctrl.save_current("guardada")
    ctrl.on_pixel_changed(4, 4)
    curvas = ctrl.curvas()
    assert curvas[0].nombre == "guardada"
    assert curvas[-1].color == COLOR_ACTUAL
