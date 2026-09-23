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
"""Construye la interfaz con PyQt6 de verdad y la dibuja.

Las pruebas normales corren con PyQt5, que es lo que hay en la mayoria de
las instalaciones de QGIS de hoy. Eso deja sin comprobar justamente lo que
cambia en Qt6, y un enum sin calificar no falla al importar: falla en la
maquina del usuario, al abrir el panel, a media construccion de la interfaz.

``test_qt6.py`` revisa el codigo sin ejecutarlo y atrapa el patron conocido.
Esto hace lo otro: lo ejecuta. Un arnes que construye el panel del cubo, lo
llena con una escena y lo dibuja, con PyQt6 cargado a proposito. Lo que se
escape al detector se cae aqui.

Va aparte de la suite y no dentro porque la eleccion de vinculacion se hace
una vez por proceso, al importar: mezclar PyQt5 y PyQt6 en la misma sesion
de pytest no da un resultado dudoso, da una caida.

Se ejecuta solo -``python3 comprobar_qt6.py``- y lo llama ``verificar.sh``
cuando PyQt6 esta instalado. Sin PyQt6 no falla: avisa y se aparta.
"""

import builtins
import os
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))


def hay_pyqt6():
    import importlib
    try:
        importlib.import_module("PyQt6.QtWidgets")
        return True
    except ImportError:
        return False


def importar_puente():
    """Carga el puente de Qt del complemento forzandolo a PyQt6.

    Se esconden PyQt5 y qgis durante el import. Sin eso el puente
    encontraria PyQt5 -que tambien esta instalado para las pruebas- y esta
    comprobacion no comprobaria nada, que es peor que no tenerla.
    """
    original = builtins.__import__

    def sin_qt5(nombre, *args, **kwargs):
        if nombre.split(".")[0] in ("PyQt5", "qgis"):
            raise ImportError("escondido a proposito: %s" % nombre)
        return original(nombre, *args, **kwargs)

    builtins.__import__ = sin_qt5
    try:
        from hdfeos_extractor.vista import qt
        return qt
    finally:
        builtins.__import__ = original


def main():
    if not hay_pyqt6():
        print("PyQt6 no esta instalado: no se comprueba Qt6.")
        return 0

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, AQUI)
    sys.path.insert(0, os.path.join(AQUI, "hdfeos_extractor", "tests"))

    puente = importar_puente()
    from PyQt6 import QtCore
    if puente.DENTRO_DE_QGIS:
        print("El puente encontro QGIS: no se puede forzar PyQt6 aqui.")
        return 0
    print("puente -> PyQt6 %s / Qt %s"
          % (QtCore.PYQT_VERSION_STR, QtCore.QT_VERSION_STR))

    import numpy as np
    from conftest import cubo_patron, escribir_envi
    from hdfeos_extractor.core.cube import HyperspectralCube
    from hdfeos_extractor.core.rgb import RGBComposer
    from hdfeos_extractor.vista.cube_view import (MODO_AREA, MODO_MULTI,
                                                  MODO_X, MODO_ZOOM)
    from hdfeos_extractor.vista.panel_cubo import (PanelCubo,
                                                   VentanaSuelta)
    from hdfeos_extractor.vista.panel_ndim import PanelND
    from hdfeos_extractor.vista.plegable import GrupoPlegable
    from hdfeos_extractor.vista.spectral_plot import Curva, SpectralPlot
    from hdfeos_extractor.vista import spectral_plot

    QtWidgets = puente.QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    carpeta = tempfile.mkdtemp()
    ruta = escribir_envi(carpeta, cubo_patron(60, 80, 30), "bil",
                         np.linspace(420.0, 2400.0, 30))
    cubo = HyperspectralCube.load(ruta)
    try:
        panel = PanelCubo()
        panel.cubo.set_cube(cubo, RGBComposer(660.0, 550.0, 470.0))
        panel.habilitar(True)

        # El divisor es lo que empotra el cubo con el espectro, y su
        # orientacion es un enum: aqui se resuelve de verdad.
        # El grafico con curvas de verdad. pyqtgraph es opcional y su
        # compatibilidad con Qt6 depende de su version; cuando no carga, el
        # lienzo propio dibuja lo mismo. Se dice cual de los dos se probo,
        # porque "el grafico funciona" significa cosas distintas.
        grafico = SpectralPlot()
        longitudes = np.linspace(420.0, 2400.0, 60)
        valores = 0.2 + 0.1 * np.sin(longitudes / 200.0)
        valores[20:25] = np.nan            # un tramo descartado, que corta
        grafico.set_curvas([
            Curva("una", longitudes, valores, color="#d62728"),
            Curva("otra", longitudes, valores * 0.6, color="#2ca02c",
                  punteada=True)])
        print("grafico espectral: %s"
              % ("pyqtgraph %s" % getattr(spectral_plot.pg, "__version__", "?")
                 if spectral_plot.pg is not None else "lienzo propio"))

        # El grafico dentro de una seccion plegable, que es como vive en el
        # panel: la politica de tamano que usa al plegarse es un enum, y en
        # Qt6 vive dentro de QSizePolicy.Policy.
        seccion = GrupoPlegable("Perfil espectral")
        caja_seccion = QtWidgets.QVBoxLayout()
        caja_seccion.addWidget(grafico, 1)
        seccion.poner(caja_seccion)

        divisor = QtWidgets.QSplitter(puente.HORIZONTAL)
        divisor.addWidget(panel)
        divisor.addWidget(seccion)
        divisor.resize(1100, 680)
        divisor.show()
        app.processEvents()

        # Dibujar es el paso que importa: los enums de QPainter, de QImage y
        # de las banderas de alineacion solo se tocan al pintar.
        if divisor.grab().isNull():
            raise SystemExit("la interfaz no se pudo dibujar")

        for modo in (MODO_ZOOM, MODO_X, MODO_AREA, MODO_MULTI):
            panel.set_herramienta(modo)
            panel.cubo.set_modo(modo)
            divisor.grab()
        panel.cubo.zoom_a_los_datos()
        panel.cubo.acercar(2.0, None)
        panel.cubo.desplazar(12, -8)
        divisor.grab()

        seccion.set_abierto(False)
        app.processEvents()
        if seccion.cuerpo.isVisible() or divisor.grab().isNull():
            raise SystemExit("la seccion plegada no quedo bien")
        seccion.set_abierto(True)
        app.processEvents()
        divisor.grab()

        # Soltar el cubo y empotrarlo de vuelta, con el arbol ya visible.
        # Es el camino que colgo QGIS en macOS, asi que se recorre entero y
        # se dibuja en los dos sitios: las banderas de ventana se resuelven
        # en el constructor de VentanaSuelta y ahi Qt6 no perdona un enum
        # mal escrito.
        suelta = VentanaSuelta()
        suelta.resize(900, 600)
        suelta.alojar(panel)
        app.processEvents()
        if suelta.grab().isNull():
            raise SystemExit("la ventana suelta no se pudo dibujar")
        divisor.insertWidget(0, panel)
        panel.show()
        suelta.hide()
        app.processEvents()
        if divisor.grab().isNull():
            raise SystemExit("el cubo empotrado de vuelta no se pudo dibujar")
        if panel.isWindow():
            raise SystemExit("el cubo quedo convertido en ventana")

        # La nube n-D: sus listas con casilla, el lienzo negro y el giro.
        # Los enums de casilla y de politica de tamano son distintos en Qt6.
        from hdfeos_extractor.core.ndim import nube_de_firmas
        nd = PanelND()
        nd.resize(900, 600)
        nd.set_bandas_disponibles(cubo.wavelengths, cubo.unidad_espectral)
        clase = type("F", (), {})()
        clase.pixels = [(x, y) for y in range(4) for x in range(6)]
        clase.name, clase.color, clase.visible = "prueba", "#33cc66", True
        nd.set_nube(nube_de_firmas(cubo, [clase], nd.bandas()))
        nd.show()
        app.processEvents()
        if nd.grab().isNull():
            raise SystemExit("la nube n-D no se pudo dibujar")
        nd.vista.t = 1.7
        nd.vista._proyectados = None
        if nd.grab().isNull():
            raise SystemExit("la nube n-D no se pudo redibujar girada")
        nd.close()
    finally:
        cubo.close()

    print("interfaz construida, dibujada y recorrida sin incidencias.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
