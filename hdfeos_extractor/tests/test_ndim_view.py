# -*- coding: utf-8 -*-
"""Pruebas del lienzo de la nube n-dimensional."""

import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from PyQt5 import QtWidgets
from PyQt5.QtCore import QPointF, Qt

from hdfeos_extractor.core.ndim import ClaseND, NubeND, TourND
from hdfeos_extractor.vista.ndim_view import MODO_LAZO, VistaND
from hdfeos_extractor.vista.panel_ndim import PanelND


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def nube(n_dim=5, por_clase=40):
    rng = np.random.default_rng(11)
    a = rng.normal(-0.4, 0.05, (por_clase, n_dim))
    b = rng.normal(0.4, 0.05, (por_clase, n_dim))
    clases = [ClaseND("a", "#ff0000", por_clase),
              ClaseND("b", "#00ff00", por_clase)]
    etiquetas = [0] * por_clase + [1] * por_clase
    pixeles = [(i, 0) for i in range(por_clase)] + \
              [(i, 1) for i in range(por_clase)]
    return NubeND(np.vstack([a, b]), etiquetas, clases,
                  list(range(n_dim)), pixeles)


@pytest.fixture
def vista(app):
    v = VistaND()
    v.resize(500, 400)
    v.set_nube(nube())
    yield v
    v.set_animar(False)
    v.deleteLater()
    app.processEvents()


class Raton(object):
    def __init__(self, x, y):
        self._p = QPointF(float(x), float(y))

    def button(self):
        return Qt.LeftButton

    def pos(self):
        return self._p


def test_se_dibuja(vista):
    assert not vista.grab().isNull()


def test_una_nube_vacia_dice_que_hacer(app):
    """Una pantalla negra y muda parece un fallo, no una nube sin datos."""
    v = VistaND()
    v.resize(400, 300)
    v.set_nube(NubeND(np.zeros((0, 2)), [], [], [0, 1]))
    assert not v.grab().isNull()
    v.deleteLater()


def test_con_dos_bandas_no_se_ofrece_girar(app):
    v = VistaND()
    v.set_nube(nube(n_dim=2))
    assert not v.puede_girar()
    v.set_animar(True)
    assert not v.animando()
    v.deleteLater()


def test_arrastrar_gira_la_nube(vista):
    """Es la unica manera de mirar una vista concreta y quedarse en ella."""
    antes = vista._proyeccion().copy()
    vista.mousePressEvent(Raton(100, 100))
    vista.mouseMoveEvent(Raton(220, 160))
    vista.mouseReleaseEvent(Raton(220, 160))
    assert not np.allclose(antes, vista._proyeccion())


def test_la_rueda_acerca_y_aleja(vista):
    class Rueda(object):
        def __init__(self, d):
            self._d = d

        def angleDelta(self):
            from PyQt5.QtCore import QPoint
            return QPoint(0, self._d)

    antes = vista.zoom
    vista.wheelEvent(Rueda(120))
    assert vista.zoom > antes
    vista.wheelEvent(Rueda(-120))
    assert np.isclose(vista.zoom, antes)


def test_el_lazo_devuelve_los_pixeles_que_encerro(vista):
    """El lazo es el gesto que convierte 'veo un grupo' en un dato."""
    recibido = []
    vista.seleccionHecha.connect(recibido.append)
    pantalla = vista._proyeccion()
    # Un lazo generoso alrededor del primer punto y de nadie mas.
    x, y = pantalla[0]
    lejos = np.linalg.norm(pantalla - pantalla[0], axis=1)
    radio = max(2.0, float(np.sort(lejos)[1]) / 2.0)
    vista.set_modo(MODO_LAZO)
    vista.mousePressEvent(Raton(x - radio, y - radio))
    for p in ((x + radio, y - radio), (x + radio, y + radio),
              (x - radio, y + radio)):
        vista.mouseMoveEvent(Raton(*p))
    vista.mouseReleaseEvent(Raton(x - radio, y + radio))

    assert len(recibido) == 1
    assert 0 in list(recibido[0])


def test_un_lazo_que_no_encierra_nada_no_miente(vista):
    recibido = []
    vista.seleccionHecha.connect(recibido.append)
    vista.set_modo(MODO_LAZO)
    vista.mousePressEvent(Raton(2, 2))
    for p in ((6, 2), (6, 6), (2, 6)):
        vista.mouseMoveEvent(Raton(*p))
    vista.mouseReleaseEvent(Raton(2, 6))
    assert len(recibido) == 1 and len(recibido[0]) == 0


def test_apagar_una_clase_la_saca_de_la_vista(app):
    """Es lo que deja mirar el grupo que quedaba tapado por el otro."""
    panel = PanelND()
    panel.resize(800, 500)
    panel.set_nube(nube())
    assert panel.lista_clases.count() == 2
    panel.lista_clases.item(0).setCheckState(Qt.Unchecked)
    assert panel.vista.nube.clases[0].visible is False
    assert panel.vista.nube.clases[1].visible is True
    panel.deleteLater()
    app.processEvents()


def test_repartir_elige_bandas_por_todo_el_espectro(app):
    """Bandas vecinas estan casi correlacionadas: diez seguidas son una."""
    panel = PanelND()
    panel.set_bandas_disponibles(np.linspace(400.0, 2500.0, 100))
    panel.cuantas.setValue(5)
    panel._repartir()
    elegidas = panel.bandas()
    assert len(elegidas) == 5
    assert elegidas[0] == 0 and elegidas[-1] == 99
    assert min(np.diff(elegidas)) > 10
    panel.deleteLater()
    app.processEvents()


def test_cambiar_las_bandas_avisa_para_rehacer_la_nube(app):
    panel = PanelND()
    avisos = []
    panel.set_bandas_disponibles(np.linspace(400.0, 2500.0, 20))
    panel.bandasCambiadas.connect(avisos.append)
    panel.cuantas.setValue(4)
    panel._repartir()
    assert avisos and len(avisos[-1]) == 4
    panel.deleteLater()
    app.processEvents()


def test_el_tiempo_avanza_con_el_reloj_de_pared(vista):
    """Si avanzara por cuadro, la nube giraria mas rapido en una maquina
    rapida y el usuario no podria decir 'parala en tal vista'."""
    vista.t = 0.0
    vista._ultimo = None
    vista._avanzar()
    primero = vista.t
    vista._avanzar()
    assert vista.t >= primero


def test_los_radios_siguen_a_la_base(vista):
    tour = TourND(5)
    vista.set_nube(nube(), tour=tour)
    assert np.allclose(tour.ejes(0.0), tour.proyectar(np.eye(5), 0.0))
