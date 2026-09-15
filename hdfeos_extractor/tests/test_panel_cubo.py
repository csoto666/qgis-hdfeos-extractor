# -*- coding: utf-8 -*-
"""Pruebas del bloque del cubo: la vista grande y sus herramientas."""

import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from hdfeos_extractor.vista.cube_view import (MODO_AREA, MODO_PAN, MODO_PIXEL,
                                              MODO_X, MODO_ZOOM)
from hdfeos_extractor.vista.panel_cubo import HERRAMIENTAS, PanelCubo


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ventana(app):
    v = PanelCubo()
    yield v
    v.close()


def test_se_deja_empotrar(app, ventana):
    """Es un widget corriente: quien lo usa decide si va dentro o suelto.

    Con la bandera de ventana forzada en el constructor -que es como estaba
    cuando el cubo tenia ventana propia-, meterlo en un divisor lo dejaba
    como una ventana flotante vacia encima del panel. Qt le pone la bandera
    a cualquier widget sin padre, asi que lo que hay que comprobar es que se
    la quita al darle uno.
    """
    from PyQt5 import QtWidgets
    divisor = QtWidgets.QSplitter()
    divisor.addWidget(ventana)
    assert not ventana.isWindow()
    assert divisor.indexOf(ventana) == 0
    assert ventana.cubo.minimumWidth() >= 200
    # El divisor es local y se lleva al hijo consigo al morir; devolverlo
    # deja el objeto vivo para que la fixture pueda cerrarlo.
    ventana.setParent(None)


def test_el_boton_de_soltar_avisa_en_los_dos_sentidos(ventana):
    recibido = []
    ventana.soltarPedido.connect(recibido.append)
    ventana.boton_soltar.setChecked(True)
    ventana.boton_soltar.setChecked(False)
    assert recibido == [True, False]


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
