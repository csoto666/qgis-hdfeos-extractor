# -*- coding: utf-8 -*-
#
# HDF-EOS Extractor - plugin de QGIS para extraer cubos hiperespectrales
# HDF-EOS5 al formato nativo de ENVI
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
"""Punto de entrada del plugin: aporta dos cosas que son el mismo flujo.

1. Un algoritmo de Processing, "HDF-EOS5 to ENVI", para extraer el cubo por
   lotes, desde el modelador o desde la consola.
2. Un panel acoplable que abre el cubo -el HDF-EOS5 directamente, o un ENVI
   ya extraido- y lo explora: imagen, cubo y espectro enlazados.

Estaban separados y no tenia sentido: quien extrae un cubo lo hace para
mirarlo. Ahora es una sola herramienta y una sola linea de trabajo -abrir el
.h5, explorarlo, y extraer a ENVI solo si hace falta sacarlo a otro programa-.

El panel se construye la primera vez que se pide, no al cargar QGIS. Con
decenas de plugins instalados, construir interfaces que nadie abrio alarga el
arranque para todos.
"""

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .proveedor import HdfEosProveedor

MENU = "&HDF-EOS"
TITULO_EXPLORADOR = "Explorador hiperespectral"


class HdfEosPlugin(object):
    """Extraccion y exploracion de cubos hiperespectrales HDF-EOS5."""

    def __init__(self, iface):
        self.iface = iface
        self.proveedor = None
        self.accion = None
        self.dock = None

    # -- carga --------------------------------------------------------------
    def initGui(self):
        self.initProcessing()
        self.initExplorador()

    def initProcessing(self):
        """Registra el algoritmo en la Caja de herramientas.

        Sigue siendo un algoritmo de Processing y no un dialogo propio porque
        asi sale gratis lo que de otro modo hay que programar: procesamiento
        por lotes sobre una carpeta de escenas, uso dentro del modelador
        grafico, y llamada desde la consola de Python.
        """
        self.proveedor = HdfEosProveedor()
        QgsApplication.processingRegistry().addProvider(self.proveedor)

    def initExplorador(self):
        self.accion = QAction(self._icono("icono_explorador.png"),
                              TITULO_EXPLORADOR, self.iface.mainWindow())
        self.accion.setCheckable(True)
        self.accion.setToolTip(
            "Explorador espacial-espectral: un pixel no es un pixel, "
            "es un espectro")
        self.accion.triggered.connect(self._alternar)
        self.iface.addToolBarIcon(self.accion)
        self.iface.addPluginToRasterMenu(MENU, self.accion)

    def _icono(self, nombre):
        ruta = os.path.join(os.path.dirname(__file__), nombre)
        return QIcon(ruta) if os.path.exists(ruta) else QIcon()

    # -- panel --------------------------------------------------------------
    def _alternar(self, marcado):
        if marcado:
            self._mostrar()
        elif self.dock is not None:
            self.dock.hide()

    def _mostrar(self):
        if self.dock is None:
            # La importacion va aca y no arriba: construir el panel importa
            # numpy y, si esta, pyqtgraph. Hacerlo al arrancar QGIS le cuesta
            # tiempo de carga a todo el mundo, incluso a quien solo usa el
            # algoritmo de la Caja de herramientas.
            from .qgis_ui.dock import HyperspectralDock
            self.dock = HyperspectralDock(self.iface,
                                          self.iface.mainWindow())
            self.dock.visibilityChanged.connect(self._visibilidad_cambiada)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()

    def _visibilidad_cambiada(self, visible):
        """Mantiene el boton de la barra en sincronia con el panel.

        Sin esto, cerrar el panel con su propia X deja el boton hundido, y el
        siguiente clic lo "desmarca" sin mostrar nada: parece que el plugin
        dejo de funcionar.
        """
        if self.accion is not None:
            self.accion.setChecked(visible)

    # -- descarga -----------------------------------------------------------
    def unload(self):
        if self.dock is not None:
            self.dock.close()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.accion is not None:
            self.iface.removeToolBarIcon(self.accion)
            self.iface.removePluginRasterMenu(MENU, self.accion)
            self.accion = None
        if self.proveedor is not None:
            QgsApplication.processingRegistry().removeProvider(self.proveedor)
            self.proveedor = None
