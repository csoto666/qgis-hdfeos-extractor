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
"""Punto de entrada del plugin: registra y quita el proveedor."""

from qgis.core import QgsApplication

from .proveedor import HdfEosProveedor


class HdfEosExtractorPlugin(object):
    """El plugin solo aporta un proveedor de Processing: no crea barras ni
    menus propios. Toda la interfaz la pone QGIS en la Caja de herramientas,
    y eso da procesamiento por lotes y uso desde el modelador sin codigo
    adicional."""

    def __init__(self, iface):
        self.iface = iface
        self.proveedor = None

    def initProcessing(self):
        self.proveedor = HdfEosProveedor()
        QgsApplication.processingRegistry().addProvider(self.proveedor)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.proveedor is not None:
            QgsApplication.processingRegistry().removeProvider(self.proveedor)
            self.proveedor = None
