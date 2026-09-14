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
"""Punto de entrada del plugin: una accion que muestra y esconde el panel.

El panel se construye la primera vez que se pide, no al cargar QGIS. Con
decenas de plugins instalados, construir interfaces que nadie abrio alarga el
arranque para todos.
"""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import Qt

MENU = "&Hyperspectral Explorer"
TITULO = "Hyperspectral Explorer"


class HyperspectralExplorerPlugin(object):
    """Explorador espacial-espectral de cubos hiperespectrales."""

    def __init__(self, iface):
        self.iface = iface
        self.accion = None
        self.dock = None

    def initGui(self):
        icono = os.path.join(os.path.dirname(__file__), "icon.png")
        self.accion = QAction(
            QIcon(icono) if os.path.exists(icono) else QIcon(),
            TITULO, self.iface.mainWindow())
        self.accion.setCheckable(True)
        self.accion.setToolTip(
            "Explorador espacial-espectral: un pixel no es un pixel, "
            "es un espectro")
        self.accion.triggered.connect(self._alternar)
        self.iface.addToolBarIcon(self.accion)
        self.iface.addPluginToRasterMenu(MENU, self.accion)

    def _alternar(self, marcado):
        if marcado:
            self._mostrar()
        elif self.dock is not None:
            self.dock.hide()

    def _mostrar(self):
        if self.dock is None:
            # La importacion va aca y no arriba: construir el panel importa
            # numpy y, si esta, pyqtgraph. Hacerlo al arrancar QGIS le cuesta
            # tiempo de carga a todo el mundo, incluso a quien nunca abre
            # este plugin.
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
