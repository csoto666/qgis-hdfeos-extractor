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
"""Proveedor de Processing del plugin."""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algoritmo import ExtraerHdfEosAlgoritmo


class HdfEosProveedor(QgsProcessingProvider):
    """Agrupa los algoritmos del plugin en la Caja de herramientas."""

    def loadAlgorithms(self):
        self.addAlgorithm(ExtraerHdfEosAlgoritmo())

    def id(self):
        return "hdfeos_extractor"

    def name(self):
        return "HDF-EOS Extractor"

    def longName(self):
        return "HDF-EOS Extractor - hyperspectral cubes to ENVI"

    def icon(self):
        ruta = os.path.join(os.path.dirname(__file__), "icon.png")
        return QIcon(ruta) if os.path.exists(ruta) else QgsProcessingProvider.icon(self)
