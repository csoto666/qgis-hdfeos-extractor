# -*- coding: utf-8 -*-
"""Pruebas de la ventana propia del cubo."""

import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from hdfeos_extractor.vista.cube_view import (MODO_AREA, MODO_PAN, MODO_PIXEL,
                                              MODO_X, MODO_ZOOM)
from hdfeos_extractor.vista.ventana_cubo import HERRAMIENTAS, VentanaCubo


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ventana(app):
    v = VentanaCubo()
    yield v
    v.close()


def test_es_una_ventana_propia_y_redimensionable(ventana):
    """El cubo competia por el alto dentro del panel acoplado. Aca se agranda,
    se mueve y se va a otra pantalla como cualquier ventana."""
    from PyQt5.QtCore import Qt
    assert ventana.windowFlags() & Qt.Window
    assert ventana.cubo.minimumWidth() >= 320


def test_estan_las_siete_herramientas(ventana):
    assert set(ventana.herramientas) == {c for c, _, _ in HERRAMIENTAS}
    assert MODO_PAN in ventana.herramientas
    assert MODO_ZOOM in ventana.herramientas


def test_las_herramientas_son_excluyentes(ventana):
    """Todas definen que hace el boton izquierdo: con dos activas a la vez no
    habria forma de saber cual manda."""
    ventana.herramientas[MODO_AREA].setChecked(True)
    marcadas = [c for c, b in ventana.herramientas.items() if b.isChecked()]
    assert marcadas == [MODO_AREA]


def test_arranca_en_pixel(ventana):
    assert ventana.herramienta() == MODO_PIXEL


def test_elegir_una_herramienta_avisa(ventana):
    recibidas = []
    ventana.herramientaCambiada.connect(recibidas.append)
    ventana.herramientas[MODO_X].setChecked(True)
    assert recibidas == [MODO_X]


def test_marcarla_desde_afuera_no_reemite(ventana):
    """Si reemitiera, el panel volveria a avisarle a la ventana y los dos se
    quedarian rebotando la misma senal."""
    recibidas = []
    ventana.herramientaCambiada.connect(recibidas.append)
    ventana.set_herramienta(MODO_AREA)
    assert ventana.herramienta() == MODO_AREA
    assert recibidas == []


def test_habilitar_y_deshabilitar_todo(ventana):
    ventana.habilitar(False)
    assert not ventana.herramientas[MODO_PIXEL].isEnabled()
    assert not ventana.boton_enviar.isEnabled()
    ventana.habilitar(True)
    assert ventana.boton_enviar.isEnabled()


def test_los_deslizadores_rgb_arrancan_escondidos(ventana):
    assert ventana.panel_rgb.isHidden()


def test_cerrarla_avisa(ventana):
    avisos = []
    ventana.cerrada.connect(lambda: avisos.append(True))
    ventana.close()
    assert avisos == [True]
