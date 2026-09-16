# -*- coding: utf-8 -*-
#
# Hyperspectral Explorer - plugin de QGIS para exploracion espacial-espectral
# de cubos hiperespectrales
# Copyright (C) 2026 Carlo Soto Castro
#
# Este programa es software libre: usted puede redistribuirlo y/o modificarlo
# bajo los terminos de la Licencia Publica General GNU publicada por la Free
# Software Foundation, ya sea la version 2 de la Licencia o (a su eleccion)
# cualquier version posterior.
#
# Este programa se distribuye con la esperanza de que sea util, pero SIN
# NINGUNA GARANTIA; ni siquiera la garantia implicita de COMERCIABILIDAD o
# APTITUD PARA UN PROPOSITO DETERMINADO. Vea la Licencia Publica General GNU
# para mas detalles.
#
# Usted deberia haber recibido una copia de la Licencia Publica General GNU
# junto con este programa (archivo LICENSE). Si no, vea
# <https://www.gnu.org/licenses/>.
#
"""Pruebas del vinculo entre la vista del cubo y el lienzo de QGIS.

La geometria se prueba aparte, en test_coordinates. Lo que se prueba aqui es
lo otro: que los dos lados se sigan, que se dejen de seguir al apagarlo, y
sobre todo que no se empujen sin parar. Un bucle de realimentacion no falla
con una excepcion, cuelga QGIS, y no hay traza que leer despues.
"""

import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from conftest import cubo_patron, escribir_envi, longitudes_patron
from dobles import instalar_si_falta_qgis

instalar_si_falta_qgis()

from test_dock import FalsoIface, desmontar
from qgis.core import QgsRectangle
from hdfeos_extractor.core.georef import Georreferencia
from hdfeos_extractor.qgis_ui.dock import HyperspectralDock

#: 100x80 pixeles de 30 m, esquina en un UTM cualquiera.
GT = (400000.0, 30.0, 0.0, 4500000.0, 0.0, -30.0)
MUESTRAS, LINEAS = 100, 80


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def panel(app, tmp_path):
    """Un panel con una escena georreferenciada ya abierta."""
    ruta = escribir_envi(
        tmp_path, cubo_patron(LINEAS, MUESTRAS, 9), "bil",
        longitudes_patron(9),
        extras={"map info": ("{UTM, 1.000, 1.000, 400000.000, 4500000.000, "
                             "30.0, 30.0, 18, North, WGS-84, units=Meters}")})
    p = HyperspectralDock(FalsoIface())
    p._cargar_cubo(ruta, None)
    yield p
    desmontar(p)


def test_la_escena_de_prueba_esta_georreferenciada(panel):
    """Si esto falla, lo demas prueba otra cosa."""
    assert panel.controller.georref.tiene_mapa
    assert panel.controller.geo.gt == pytest.approx(GT)


def test_sin_vincular_el_mapa_no_se_mueve(panel):
    antes = panel.canvas.extent()
    panel.cubo.set_vista((10, 5, 40, 35))
    assert panel.canvas.extent() is antes


def test_al_vincular_el_mapa_va_a_donde_mira_el_cubo(panel):
    panel.cubo.set_vista((10, 5, 39, 34))
    panel._vincular(True)
    assert panel.vinculo.activo
    e = panel.canvas.extent()
    # El pixel 10 empieza en 400300; el 39 termina en la esquina del 40.
    assert e.xMinimum() == pytest.approx(400000.0 + 10 * 30.0)
    assert e.xMaximum() == pytest.approx(400000.0 + 40 * 30.0)
    assert e.yMaximum() == pytest.approx(4500000.0 - 5 * 30.0)
    assert e.yMinimum() == pytest.approx(4500000.0 - 35 * 30.0)


def test_acercarse_en_el_cubo_arrastra_al_mapa(panel):
    panel._vincular(True)
    panel.cubo.set_vista((50, 40, 69, 59))
    e = panel.canvas.extent()
    assert e.xMinimum() == pytest.approx(400000.0 + 50 * 30.0)
    assert e.yMaximum() == pytest.approx(4500000.0 - 40 * 30.0)


def test_mover_el_mapa_arrastra_al_cubo(panel):
    panel._vincular(True)
    # Una zona que en pixeles es (20, 10) a (39, 29).
    panel.canvas.setExtent(QgsRectangle(
        400000.0 + 20 * 30.0, 4500000.0 - 30 * 30.0,
        400000.0 + 40 * 30.0, 4500000.0 - 10 * 30.0))
    assert panel.cubo.ventana() == (20, 10, 39, 29)


def test_al_apagarlo_dejan_de_seguirse(panel):
    panel._vincular(True)
    panel._vincular(False)
    assert not panel.vinculo.activo

    antes_mapa = panel.canvas.extent()
    panel.cubo.set_vista((5, 5, 25, 25))
    assert panel.canvas.extent() is antes_mapa

    antes_cubo = panel.cubo.ventana()
    panel.canvas.setExtent(QgsRectangle(400000.0, 4499000.0,
                                        401000.0, 4500000.0))
    assert panel.cubo.ventana() == antes_cubo


# -- lo que de verdad importa ----------------------------------------------
def test_no_se_empujan_sin_parar(panel):
    """El bucle de realimentacion, que es el fallo caro de esta funcion.

    Cada lado avisa de sus cambios y el aviso mueve al otro, que avisa a su
    vez. Sin corte, esto no lanza una excepcion: cuelga QGIS, y no queda
    traza que leer. Aqui se cuenta cuantas veces se movio cada lado y se
    exige que la cosa se pare sola.
    """
    panel._vincular(True)
    movimientos = []
    panel.cubo.vistaCambiada.connect(lambda v: movimientos.append(("cubo", v)))
    panel.canvas.extentsChanged.connect(lambda: movimientos.append(("mapa",)))

    panel.cubo.set_vista((30, 20, 59, 49))

    # Un movimiento del cubo y uno del mapa. Si hubiera rebote, cada uno
    # arrastraria al otro y la lista crecería sin control.
    assert len(movimientos) <= 4, movimientos
    assert panel.cubo.ventana() == (30, 20, 59, 49)


def test_el_redondeo_no_hace_derivar_la_vista(panel):
    """Pixeles y metros no cuadran exactamente, y esa diferencia se acumula.

    Se mueve el mapa una sola vez y se comprueba que el cubo acaba donde
    tiene que estar, sin que las idas y venidas lo dejen corrido.
    """
    panel._vincular(True)
    for _ in range(5):
        panel.canvas.setExtent(QgsRectangle(
            400000.0 + 20 * 30.0, 4500000.0 - 30 * 30.0,
            400000.0 + 40 * 30.0, 4500000.0 - 10 * 30.0))
    assert panel.cubo.ventana() == (20, 10, 39, 29)


def test_si_el_mapa_se_va_lejos_el_cubo_se_queda(panel):
    """Irse a otro continente no debe tirar el encuadre del cubo.

    Saltar a la vista completa por un desplazamiento que a lo mejor es de
    paso es peor que no hacer nada: se pierde el trabajo de encuadrar.
    """
    panel._vincular(True)
    panel.cubo.set_vista((10, 10, 29, 29))
    antes = panel.cubo.ventana()
    panel.canvas.setExtent(QgsRectangle(0.0, 0.0, 1000.0, 1000.0))
    assert panel.cubo.ventana() == antes


# -- cuando no se puede ----------------------------------------------------
def test_sin_georreferencia_no_se_vincula_y_se_dice(app, tmp_path):
    ruta = escribir_envi(tmp_path, cubo_patron(20, 20, 9), "bil",
                         longitudes_patron(9))
    p = HyperspectralDock(FalsoIface())
    try:
        p._cargar_cubo(ruta, None)
        assert not p.controller.georref.tiene_mapa
        assert not p.panel_cubo.boton_vinculo.isEnabled()
        p._vincular(True)
        assert not p.vinculo.activo
        assert "no dice donde esta" in p.estado.text()
        # Y el boton no se queda hundido sobre un vinculo que no existe.
        assert not p.panel_cubo.boton_vinculo.isChecked()
    finally:
        desmontar(p)


def test_una_escena_de_sensor_avisa_de_que_es_aproximado(panel):
    """Con puntos de control la correspondencia es un ajuste, no una
    equivalencia. Sirve para navegar; decir lo contrario seria mentir."""
    f, c = np.meshgrid(np.arange(LINEAS), np.arange(MUESTRAS), indexing="ij")
    lon = -70.0 + 0.001 * c - 0.0003 * f
    lat = -33.0 - 0.001 * f - 0.0003 * c
    panel.controller.georref = Georreferencia.de_rejilla(lon, lat, por_lado=8)
    panel.controller.geo = panel.controller.georref.transformacion
    se_puede, motivo = panel.vinculo.utilizable()
    assert se_puede
    assert "aproximada" in motivo


def test_cambiar_de_escena_apaga_el_vinculo(panel, tmp_path):
    """Si no, queda escuchando al lienzo con un cubo que ya no esta."""
    panel._vincular(True)
    assert panel.vinculo.activo
    otra = escribir_envi(tmp_path, cubo_patron(30, 30, 9), "bil",
                         longitudes_patron(9), nombre="otra")
    panel._cargar_cubo(otra, None)
    assert not panel.vinculo.activo
    assert not panel.panel_cubo.boton_vinculo.isChecked()
