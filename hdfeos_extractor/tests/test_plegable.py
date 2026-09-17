# -*- coding: utf-8 -*-
"""Pruebas de la seccion que se pliega al pulsar su nombre."""

import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from PyQt5 import QtWidgets

from hdfeos_extractor.vista.plegable import GrupoPlegable


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def grupo(app):
    g = GrupoPlegable("Perfil espectral")
    caja = QtWidgets.QVBoxLayout()
    etiqueta = QtWidgets.QLabel("contenido")
    caja.addWidget(etiqueta)
    g.poner(caja)
    g.etiqueta = etiqueta
    yield g
    g.setParent(None)
    g.deleteLater()
    app.processEvents()


def test_arranca_abierta(grupo):
    assert grupo.abierto()
    assert not grupo.cuerpo.isHidden()


def test_pulsar_el_nombre_la_pliega_y_la_despliega(grupo):
    """Es todo el mecanismo: el nombre de la seccion es el boton."""
    grupo.cabecera.click()
    assert not grupo.abierto()
    assert grupo.cuerpo.isHidden()

    grupo.cabecera.click()
    assert grupo.abierto()
    assert not grupo.cuerpo.isHidden()


def test_el_nombre_dice_en_que_estado_esta(grupo):
    """Sin la flecha, una seccion plegada parece una seccion vacia."""
    assert "Perfil espectral" in grupo.cabecera.text()
    abierta = grupo.cabecera.text()
    grupo.cabecera.click()
    assert "Perfil espectral" in grupo.cabecera.text()
    assert grupo.cabecera.text() != abierta


def test_plegada_no_se_queda_con_el_alto(grupo):
    """Si siguiera reservando su alto, plegarla no le daria sitio al cubo."""
    grupo.resize(300, 200)
    alto_abierta = grupo.sizeHint().height()
    cuerpo = grupo.cuerpo.sizeHint().height()
    grupo.cabecera.click()
    alto_plegada = grupo.sizeHint().height()
    assert alto_plegada < alto_abierta
    # Lo que se solto es exactamente el cuerpo, no un poco de relleno.
    assert alto_plegada + cuerpo <= alto_abierta + 4


def test_plegarla_no_reconstruye_nada(grupo):
    """El contenido es el mismo objeto: no se pierde nada al plegar."""
    dentro = grupo.etiqueta
    grupo.cabecera.click()
    grupo.cabecera.click()
    assert grupo.etiqueta is dentro
    assert dentro.parent() is grupo.cuerpo


def test_desplegarla_no_reenciende_lo_que_estaba_apagado(grupo):
    """La trampa de QGroupBox marcable, que es por lo que no se usa.

    Un QGroupBox con setCheckable apaga y enciende a TODOS sus hijos al
    marcarlo. Ahi, desplegar la seccion volveria a encender botones que el
    panel habia apagado a proposito -no hay escena abierta- y el usuario
    podria pulsarlos.
    """
    grupo.etiqueta.setEnabled(False)
    grupo.cabecera.click()
    grupo.cabecera.click()
    assert not grupo.etiqueta.isEnabled()


def test_avisa_cuando_cambia(grupo):
    """Quien la contiene necesita enterarse para repartir el espacio."""
    avisos = []
    grupo.plegado.connect(avisos.append)
    grupo.cabecera.click()
    grupo.cabecera.click()
    assert avisos == [False, True]


def test_se_puede_plegar_sin_pasar_por_el_boton(grupo):
    grupo.set_abierto(False)
    assert not grupo.abierto()
    assert not grupo.cabecera.isChecked()
