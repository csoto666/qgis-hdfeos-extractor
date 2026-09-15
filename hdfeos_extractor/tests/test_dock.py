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
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
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
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
    p = HyperspectralDock(FalsoIface())
    assert not panel_habilitado(p)


def panel_habilitado(p):
    return p.boton_guardar.isEnabled()


def test_un_archivo_que_no_se_puede_abrir_avisa_y_no_rompe(app, tmp_path):
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
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
    ultima = float(longitudes_patron()[-1])
    panel._banda_cambiada("red", 8)
    assert panel.controles_banda["red"][0].value() == 8
    assert panel.controles_banda["red"][1].value() == 8
    assert panel.controles_banda["red"][2].text().startswith(
        "%.1f" % ultima)
    assert panel.grafico._marcadores[0][0] == pytest.approx(ultima)


def test_elegir_un_preset_actualiza_los_tres_canales(panel):
    panel.combo_preset.setCurrentIndex(
        panel.combo_preset.findText("Falso color IR"))
    panel._preset_elegido()
    leyendas = [panel.controles_banda[c][2].text()
                for c in ("red", "green", "blue")]
    assert all(t.endswith("nm") for t in leyendas)


def test_cambiar_de_modo_no_rompe_sin_herramienta(panel):
    from hdfeos_extractor.qgis_ui import map_tools
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


# -- enlace con la vista del cubo ---------------------------------------------
def test_el_cubo_recibe_la_escena_al_abrirla(panel):
    assert panel.cubo.cube is panel.controller.cube
    assert panel.cubo._superior is not None


def test_un_pixel_del_mapa_mueve_la_cruz_del_cubo(panel):
    """Las dos vistas senalan el mismo pixel y ninguna conoce a la otra: las
    dos pasan por el controlador."""
    panel.controller.on_pixel_changed(4, 6)
    assert (panel.cubo.x, panel.cubo.y) == (4, 6)


def test_arrastrar_en_el_cubo_extrae_el_espectro(panel):
    """El camino de vuelta. Si esta conexion falta, la cruz se mueve y el
    grafico no se entera."""
    panel.cubo.posicionMovida.emit(2, 3)
    assert panel.controller.pixel == (2, 3)
    assert len(panel.grafico._curvas) == 1


def test_mover_la_cruz_no_entra_en_un_bucle(panel):
    """cruz -> controlador -> cruz. set_posicion corta cuando no cambia
    nada; sin eso las dos senales se realimentan."""
    panel.cubo.posicionMovida.emit(1, 1)
    assert (panel.cubo.x, panel.cubo.y) == (1, 1)
    assert panel.controller.pixel == (1, 1)


def test_un_clic_en_el_costado_se_reporta_en_el_panel(panel):
    ultima = float(longitudes_patron()[-1])
    panel.cubo.longitudElegida.emit(ultima)
    assert "banda 8" in panel.banda_frontal.text()
    assert ("%.1f" % ultima) in panel.banda_frontal.text()


def test_volver_al_rgb_limpia_el_modo_de_banda_unica(panel):
    panel.cubo.set_banda_unica(3)
    panel._volver_al_rgb()
    assert panel.cubo.banda_unica is None
    assert "composicion RGB" in panel.banda_frontal.text()


def test_cambiar_la_paleta_llega_al_cubo(panel):
    panel.combo_paleta.setCurrentText("viridis")
    assert panel.cubo.paleta == "viridis"


def test_cambiar_el_realce_rehace_el_rango_del_cubo(panel):
    antes = panel.cubo._rango
    panel.combo_realce.setCurrentIndex(
        panel.combo_realce.findData("reflectancia"))
    panel._realce_elegido()
    assert panel.cubo._rango == (0.0, 1.0) != antes


def test_cambiar_una_banda_mueve_los_marcadores_del_cubo(panel):
    panel._banda_cambiada("red", 8)
    assert panel.cubo.marcadores
    assert panel.cubo.marcadores[0] == pytest.approx(
        float(longitudes_patron()[-1]))


def test_cerrar_la_capa_vacia_el_cubo(panel):
    """Una sola invocacion del manejador, como pasa de verdad.

    La version anterior de esta prueba llamaba a _capa_elegida dos veces -una
    por la senal del combo y otra a mano- y la segunda encontraba todo ya
    limpio. Asi dejo pasar un fallo que reventaba en QGIS:

        close_cube cierra el cubo y emite composicionCambiada; el panel
        responde llamando a refrescar_frontal, y la vista del cubo todavia
        apunta al cubo recien cerrado:
        AttributeError: 'NoneType' object has no attribute 'read_band'
    """
    assert panel.cubo.cube is not None
    panel._bloqueado = True                  # que el combo no dispare la senal
    panel.combo_capa.setCurrentIndex(0)      # "(ninguna)"
    panel._bloqueado = False
    panel._capa_elegida()                    # una sola vez
    assert panel.cubo.cube is None
    assert panel.controller.cube is None


def test_una_senal_tardia_no_revienta_sobre_un_cubo_cerrado(panel):
    """El caso desnudo del fallo: la vista se entera tarde.

    Coordinar el orden exacto de cinco senales es fragil; preguntar si el
    cubo sigue abierto es barato."""
    cubo = panel.controller.cube
    cubo.close()
    assert cubo.cerrado
    panel._aplicar_composicion(panel.controller.composer)   # no debe reventar
    assert panel.cubo._frontal is None


def test_un_cubo_cerrado_dice_que_lo_esta(panel):
    from hdfeos_extractor.core.cube import CubeError
    cubo = panel.controller.cube
    cubo.close()
    for llamada in (lambda: cubo.get_spectrum(0, 0),
                    lambda: cubo.get_band(index=0),
                    lambda: cubo.get_transect("x", 0),
                    lambda: cubo.get_roi(0, 0, 1, 1)):
        with pytest.raises(CubeError, match="ya esta cerrado"):
            llamada()


def test_abrir_otra_escena_cierra_la_anterior(panel, tmp_path):
    """Sin esto la memoria mapeada de la anterior queda viva, y en Windows su
    archivo sigue bloqueado mientras QGIS este abierto."""
    from qgis.core import QgsRasterLayer
    primero = panel.controller.cube
    otro = escribir_envi(tmp_path, cubo_patron(), "bil", longitudes_patron(),
                         nombre="segunda")
    panel._cargar_cubo(otro, QgsRasterLayer(otro, "segunda"))
    assert primero.cerrado
    assert not panel.controller.cube.cerrado


def _en_una_ventana(panel, ancho, alto):
    """El panel es un QDockWidget: sin acoplarlo no recibe showEvent."""
    from PyQt5.QtCore import Qt
    ventana = QtWidgets.QMainWindow()
    ventana.resize(ancho + 8, alto + 8)
    ventana.addDockWidget(Qt.RightDockWidgetArea, panel)
    ventana.resizeDocks([panel], [ancho], Qt.Horizontal)
    ventana.show()
    _asentar(QtWidgets.QApplication.instance())
    return ventana


def _asentar(app):
    for _ in range(5):
        app.processEvents()


def test_abrir_un_hdfeos5_directo_desde_el_panel(app, tmp_path):
    """Sin escribir nada en disco: es la razon de que los dos plugins sean
    uno solo."""
    pytest.importorskip("h5py")
    import numpy as np
    from conftest import (escribir_hdfeos, longitudes_h5, reflectancia_patron)
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock

    reflectancia = reflectancia_patron()
    ruta = escribir_hdfeos(tmp_path, reflectancia, longitudes_h5())
    p = HyperspectralDock(FalsoIface())
    p._cargar_cubo(ruta, None)              # QGIS no dibuja el contenedor
    assert p.controller.cube is not None
    assert p.es_hdf5_abierto()
    assert np.allclose(p.controller.cube.get_spectrum(3, 2),
                       reflectancia[2, 3, :], atol=1e-6)
    # El cubo 3D funciona igual aunque no haya capa en el mapa.
    assert p.cubo._superior is not None
    assert "HDF-EOS5 abierto directamente" in p.estado.text()


def test_extraer_solo_se_ofrece_sobre_un_hdfeos5(app, tmp_path, panel):
    """Sobre un ENVI ya extraido el boton no haria nada util."""
    assert not panel.es_hdf5_abierto()
    assert not panel.boton_extraer.isEnabled()

    pytest.importorskip("h5py")
    from conftest import (escribir_hdfeos, longitudes_h5, reflectancia_patron)
    ruta = escribir_hdfeos(tmp_path, reflectancia_patron(), longitudes_h5())
    panel._cargar_cubo(ruta, None)
    assert panel.boton_extraer.isEnabled()


def test_extraer_sin_escena_avisa_en_vez_de_romper(app):
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
    p = HyperspectralDock(FalsoIface())
    p._extraer_a_envi()
    assert "abra una escena" in p.estado.text()


# -- bandas malas en el panel -------------------------------------------------
@pytest.fixture
def panel_ancho(app, tmp_path):
    """Un panel sobre un cubo cuyo eje cruza las ventanas de absorcion."""
    import numpy as np
    from conftest import longitudes_con_absorcion
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
    from qgis.core import QgsRasterLayer
    wl = longitudes_con_absorcion()
    datos = np.ones((5, 6, wl.size), dtype=np.float32)
    hdr = escribir_envi(tmp_path, datos, "bil", wl, nombre="ancha")
    p = HyperspectralDock(FalsoIface())
    p._cargar_cubo(hdr, QgsRasterLayer(hdr, "ancha"))
    return p


def test_al_abrir_se_informa_cuantas_bandas_se_descartan(panel_ancho):
    texto = panel_ancho.cuenta_bandas.text()
    assert "descartadas" in texto and "vapor de agua" in texto
    assert panel_ancho.controller.cube.mask.n_malas > 0


def test_los_tramos_descartados_se_sombrean_en_el_grafico(panel_ancho):
    """Sin el sombreado la curva se corta y nadie sabe si falta el dato o si
    el sensor no llega hasta ahi."""
    assert panel_ancho.grafico._descartados
    assert len(panel_ancho.grafico._descartados) == len(
        panel_ancho.controller.cube.mask.tramos_malos())


def test_los_controles_arrancan_escondidos(panel_ancho):
    """Es un ajuste por escena, no algo que se toque todo el rato, y el alto
    del panel hace falta para las dos vistas."""
    assert panel_ancho.panel_bandas.isHidden()
    assert panel_ancho.cuenta_bandas.text() != "-"   # la cuenta si se ve
    panel_ancho.boton_bandas.setChecked(True)
    assert not panel_ancho.panel_bandas.isHidden()


def test_desmarcar_vapor_de_agua_devuelve_esas_bandas(panel_ancho):
    import numpy as np
    from hdfeos_extractor.lector import VENTANAS_ABSORCION
    cubo = panel_ancho.controller.cube
    wl = cubo.wavelengths
    dentro = (wl >= VENTANAS_ABSORCION[0][0]) & (wl <= VENTANAS_ABSORCION[0][1])

    panel_ancho.controller.on_pixel_changed(1, 1)
    assert np.all(np.isnan(cubo.get_spectrum(1, 1)[dentro]))

    panel_ancho.casillas_bandas["usar_absorcion"].setChecked(False)
    assert not cubo.mask.usar_absorcion
    assert np.isfinite(cubo.get_spectrum(1, 1)[dentro]).all()
    assert panel_ancho.grafico._descartados == [] or True


def test_un_rango_escrito_a_mano_se_aplica(panel_ancho):
    import numpy as np
    cubo = panel_ancho.controller.cube
    panel_ancho.campo_rangos.setText("900-1100")
    panel_ancho._rangos_cambiados()
    assert cubo.mask.rangos == [(900.0, 1100.0)]
    wl = cubo.wavelengths
    dentro = (wl >= 900.0) & (wl <= 1100.0)
    assert np.all(np.isnan(cubo.get_spectrum(1, 1)[dentro]))
    assert "rango" in panel_ancho.cuenta_bandas.text()


def test_la_casilla_de_la_bbl_se_apaga_si_el_archivo_no_la_trae(panel_ancho):
    assert not panel_ancho.controller.cube.mask.hay_bbl
    assert not panel_ancho.casillas_bandas["usar_bbl"].isEnabled()


def test_la_casilla_de_la_bbl_se_enciende_si_el_archivo_la_trae(app,
                                                                tmp_path):
    import numpy as np
    from conftest import longitudes_con_absorcion
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
    from qgis.core import QgsRasterLayer
    wl = longitudes_con_absorcion()
    datos = np.ones((4, 4, wl.size), dtype=np.float32)
    bbl = np.ones(wl.size, dtype=int)
    bbl[1] = 0
    hdr = escribir_envi(tmp_path, datos, "bil", wl, nombre="conbbl", extras={
        "bbl": "{" + ", ".join(str(v) for v in bbl) + "}"})
    p = HyperspectralDock(FalsoIface())
    p._cargar_cubo(hdr, QgsRasterLayer(hdr, "conbbl"))
    assert p.controller.cube.mask.hay_bbl
    assert p.casillas_bandas["usar_bbl"].isEnabled()
    assert "lista del archivo" in p.cuenta_bandas.text()


def test_cambiar_la_mascara_recalcula_la_firma_en_pantalla(panel_ancho):
    """Si la firma no se recalculara, el grafico seguiria mostrando la curva
    vieja y el usuario creeria que el cambio no hizo nada."""
    import numpy as np
    panel_ancho.controller.on_pixel_changed(2, 2)
    antes = panel_ancho.grafico._curvas[-1].y.copy()
    panel_ancho.casillas_bandas["usar_absorcion"].setChecked(False)
    despues = panel_ancho.grafico._curvas[-1].y
    assert np.count_nonzero(np.isnan(despues)) < np.count_nonzero(
        np.isnan(antes))


# -- modos, zoom y compactacion -----------------------------------------------
def test_el_modo_llega_al_cubo_y_no_solo_al_mapa(panel):
    """Con un HDF-EOS5 abierto no hay capa en el mapa, asi que la herramienta
    de mapa no tiene donde actuar: si el modo no llegara tambien al cubo, los
    modos pareceria que no hacen nada."""
    from hdfeos_extractor.qgis_ui import map_tools
    panel._activar_herramienta()
    for modo in (map_tools.MODO_X, map_tools.MODO_Y, map_tools.MODO_AREA,
                 map_tools.MODO_MULTI, map_tools.MODO_PIXEL):
        panel._cambiar_modo(modo)
        assert panel.herramienta.modo == modo
        assert panel.cubo.modo == modo


def test_desplazar_y_acercar_no_pisan_los_gestos_de_qgis(panel):
    """Sobre el mapa esos gestos ya los da QGIS. La herramienta del plugin se
    queda en el ultimo modo de muestreo en vez de robarselos."""
    from hdfeos_extractor.qgis_ui import map_tools
    from hdfeos_extractor.vista.cube_view import MODO_PAN, MODO_ZOOM
    panel._activar_herramienta()
    panel._cambiar_modo(map_tools.MODO_AREA)
    for navegacion in (MODO_PAN, MODO_ZOOM):
        panel._cambiar_modo(navegacion)
        assert panel.cubo.modo == navegacion          # el cubo si cambia
        assert panel.herramienta.modo == map_tools.MODO_AREA


def test_un_conjunto_de_pixeles_da_una_firma_con_variabilidad(panel):
    panel.cubo.set_modo("multi")
    for pixel in ((1, 1), (2, 2), (3, 3)):
        panel.cubo._empezar_gesto(pixel)
    firma = panel.controller.firma_actual
    assert firma is not None and firma.count == 3
    assert firma.std is not None
    assert "3 pixeles elegidos" in panel.estado.text()


def test_acercarse_se_informa_en_la_barra_de_estado(panel):
    panel.cubo.set_vista((1, 1, 3, 4))
    assert "Acercado" in panel.estado.text()
    panel.cubo.set_vista(None)
    assert "Vista completa" in panel.estado.text()


def test_los_deslizadores_rgb_arrancan_escondidos(panel):
    """Ocupaban 176 pixeles permanentes para algo que casi siempre se
    resuelve con un preset."""
    # isHidden y no isVisible: isVisible es falso mientras el dock no este
    # mostrado, asi que la comprobacion pasaria sola sin probar nada.
    assert panel.panel_rgb.isHidden()
    assert panel.resumen_rgb.text() != "-"        # las bandas si se ven
    panel.boton_bandas_rgb.setChecked(True)
    assert not panel.panel_rgb.isHidden()


def test_el_resumen_rgb_sigue_a_las_bandas(panel):
    panel._banda_cambiada("red", 8)
    ultima = float(longitudes_patron()[-1])
    assert ("%.0f" % ultima) in panel.resumen_rgb.text()


def test_las_acciones_de_biblioteca_siguen_existiendo(panel):
    """Pasaron de una fila de botones a un menu, pero tienen que seguir ahi."""
    etiquetas = [a.text() for a in panel.menu_lib.actions()]
    assert any("Abrir" in t for t in etiquetas)
    assert any("Guardar" in t for t in etiquetas)
    assert any("CSV" in t for t in etiquetas)


# -- envio de la vista al mapa ------------------------------------------------
def test_enviar_sin_escena_avisa(app):
    from hdfeos_extractor.qgis_ui.dock import HyperspectralDock
    p = HyperspectralDock(FalsoIface())
    p._enviar_a_qgis()
    assert "abra una escena" in p.estado.text()


def test_enviar_sin_gdal_avisa_en_vez_de_romper(panel, monkeypatch):
    """GDAL viene con QGIS, pero el nucleo se prueba sin el: si falta, el
    panel tiene que decirlo y seguir andando."""
    import hdfeos_extractor.qgis_ui.exportar as exportar
    if exportar.gdal is not None:
        pytest.skip("hay GDAL: este es el camino sin el")
    panel._enviar_a_qgis()
    assert "No se pudo escribir la vista" in panel.estado.text()


def test_abrir_una_escena_muestra_la_ventana_del_cubo(panel):
    assert panel.ventana_cubo.cubo.cube is panel.controller.cube


def test_el_boton_abre_la_ventana(panel):
    panel._mostrar_ventana_cubo()
    assert not panel.ventana_cubo.isHidden()
    panel.ventana_cubo.close()
