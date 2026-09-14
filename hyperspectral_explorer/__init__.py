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
"""Punto de entrada que busca QGIS al cargar el complemento.

La importacion de ``plugin`` va adentro de la funcion y no arriba del archivo
a proposito: asi ``hyperspectral_explorer.core`` se puede importar desde
Python puro -pruebas, Jupyter, un script- sin que QGIS tenga que existir.
"""


def classFactory(iface):
    from .plugin import HyperspectralExplorerPlugin
    return HyperspectralExplorerPlugin(iface)
