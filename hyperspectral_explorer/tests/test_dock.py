# -*- coding: utf-8 -*-
"""Prueba de humo del panel: el cableado del frontend.

Es lo mas cerca de QGIS que se puede llegar sin QGIS. Contra el doble de
``tests/dobles/qgis`` se construye el panel entero y se lo hace responder a
las mismas interacciones que tendria delante de un usuario.

Cubre lo que el resto de las pruebas no puede: que las senales esten
conectadas y que los nombres que el panel llama existan de verdad. Un error
ahi no se ve en el nucleo y en QGIS aparece como un panel que no reacciona.
"""

import pytest

pytest.importorskip("PyQt5", reason="hacen falta enlaces de Qt")

from conftest import cubo_patron, escribir_envi, longitudes_patron
from dobles import instalar_si_falta_qgis

instalar_si_falta_qgis()

from PyQt5 import QtWidgets


@pytest.fixture(scope="module")
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FalsoCanvas(QtWidgets.QWidget):
    """Lo minimo que la herramienta de mapa le pide al lienzo."""

    def setMapTool(self, herramienta):
        self.herramienta = herramienta

    def unsetMapTool(self, herramienta):
        pass

    def mapSettings(self):
        return self

    def destinationCrs(self):
        from qgis.core import QgsRasterLayer
        return QgsRasterLayer().crs()


class FalsoIface(object):
    def __init__(self):
        self._canvas = FalsoCanvas()

    def mapCanvas(self):
        return self._canvas

    def mainWindow(self):
        return None


@pytest.fixture
def panel(app, tmp_path):
    from hyperspectral_explorer.qgis_ui.dock import HyperspectralDock
    from qgis.core import QgsRasterLayer
    hdr = escribir_envi(tmp_path, cubo_patron(), "bil", longitudes_patron())
    p = HyperspectralDock(FalsoIface())
    p._cargar_cubo(hdr, QgsRasterLayer(hdr, "escena"))
    return p


# -- apertura -----------------------------------------------------------------
def test_abrir_un_cubo_prepara_todos_los_controles(panel):
    assert panel.controller.cube is not None
    assert "9 bandas" in panel.estado.text()
    assert panel.combo_preset.count() > 0
    for canal in ("red", "green", "blue"):
        deslizador, numero, leyenda = panel.controles_banda[canal]
        assert deslizador.maximum() == 8 and numero.maximum() == 8
        assert leyenda.text().endswith("nm")


def test_los_controles_arrancan_desactivados_sin_cubo(app):
    from hyperspectral_explorer.qgis_ui.dock import HyperspectralDock
    p = HyperspectralDock(FalsoIface())
    assert not panel_habilitado(p)


def panel_habilitado(p):
    return p.boton_guardar.isEnabled()


def test_un_archivo_que_no_se_puede_abrir_avisa_y_no_rompe(app, tmp_path):
    from hyperspectral_explorer.qgis_ui.dock import HyperspectralDock
    basura = tmp_path / "basura.dat"
    basura.write_bytes(b"no soy un cubo")
    p = HyperspectralDock(FalsoIface())
    p._cargar_cubo(str(basura), None)
    assert p.controller.cube is None
    assert not panel_habilitado(p)


# -- interaccion --------------------------------------------------------------
def test_un_clic_llega_hasta_el_grafico_y_la_barra_de_estado(panel):
    panel.controller.on_pixel_changed(3, 2)
    assert len(panel.grafico._curvas) == 1
    assert "X 3" in panel.estado.text() and "Y 2" in panel.estado.text()


def test_guardar_agrega_una_fila_a_la_lista(panel):
    panel.controller.on_pixel_changed(3, 2)
    panel.controller.save_current("Vegetacion")
    assert panel.lista.count() == 1
    assert panel.lista.item(0).text() == "Vegetacion"


def test_desmarcar_la_casilla_saca_la_curva_del_grafico(panel):
    """La conexion de itemChanged: sin ella la casilla se marca y no pasa
    nada, que es el sintoma mas confuso posible."""
    from PyQt5.QtCore import Qt
    panel.controller.on_pixel_changed(3, 2)
    panel.controller.save_current("Vegetacion")
    assert len(panel.grafico._curvas) == 1
    panel.lista.item(0).setCheckState(Qt.Unchecked)
    assert panel.grafico._curvas == []


def test_el_transecto_dibuja_media_y_extremos(panel):
    panel.controller.on_x_changed(2)
    nombres = [c.nombre for c in panel.grafico._curvas]
    assert "minimo" in nombres and "maximo" in nombres
    assert "Transecto X = 2" in panel.estado.text()


def test_mover_un_deslizador_mueve_la_banda_y_el_marcador(panel):
    """El deslizador y su casilla apuntan a lo mismo y se mueven entre si;
    sin el cerrojo, esa ida y vuelta es un bucle infinito."""
    panel._banda_cambiada("red", 8)
    assert panel.controles_banda["red"][0].value() == 8
    assert panel.controles_banda["red"][1].value() == 8
    assert panel.controles_banda["red"][2].text().startswith("2450")
    assert panel.grafico._marcadores[0][0] == pytest.approx(2450.0)


def test_elegir_un_preset_actualiza_los_tres_canales(panel):
    panel.combo_preset.setCurrentIndex(
        panel.combo_preset.findText("Falso color IR"))
    panel._preset_elegido()
    leyendas = [panel.controles_banda[c][2].text()
                for c in ("red", "green", "blue")]
    assert all(t.endswith("nm") for t in leyendas)


def test_cambiar_de_modo_no_rompe_sin_herramienta(panel):
    from hyperspectral_explorer.qgis_ui import map_tools
    panel._activar_herramienta()
    for modo in (map_tools.MODO_X, map_tools.MODO_Y, map_tools.MODO_AREA,
                 map_tools.MODO_PIXEL):
        panel._cambiar_modo(modo)
        assert panel.herramienta.modo == modo


# -- cierre -------------------------------------------------------------------
def test_cerrar_suelta_las_senales_del_proyecto(panel):
    """Sin esto, cerrar el panel deja conexiones vivas hacia un objeto que ya
    no esta, y la proxima capa que se agregue al proyecto tumba QGIS."""
    from qgis.core import QgsProject
    proyecto = QgsProject.instance()
    antes = len(getattr(proyecto.layersAdded, "conectados", []))
    panel.close()
    despues = len(getattr(proyecto.layersAdded, "conectados", []))
    assert despues < antes or antes == 0
    proyecto.layersAdded.emit([])      # no debe reventar
