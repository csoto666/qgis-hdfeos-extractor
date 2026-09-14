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
"""Puente de importacion de Qt.

Dentro de QGIS lo correcto es importar por ``qgis.PyQt``, que es el shim que
resuelve Qt5 o Qt6 segun la version. Fuera de QGIS ese modulo no existe, y
sin este puente los widgets de ``vista/`` solo se podrian importar con QGIS
abierto -es decir, no se podrian probar-.

El orden es deliberado: qgis.PyQt primero, para que dentro de QGIS se use
exactamente el mismo Qt que usa QGIS. Mezclar dos enlaces de Qt en el mismo
proceso no da un error de importacion, da una caida.
"""

try:
    from qgis.PyQt import QtCore, QtGui, QtWidgets
    from qgis.PyQt.QtCore import Qt, pyqtSignal
    DENTRO_DE_QGIS = True
except ImportError:                       # pragma: no cover
    DENTRO_DE_QGIS = False
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets
        from PyQt5.QtCore import Qt, pyqtSignal
    except ImportError:
        try:
            from PyQt6 import QtCore, QtGui, QtWidgets
            from PyQt6.QtCore import Qt
            from PyQt6.QtCore import pyqtSignal
        except ImportError:
            raise ImportError(
                "No hay enlaces de Qt disponibles. Dentro de QGIS esto no "
                "deberia pasar; fuera, hace falta PyQt5 o PyQt6.")


def enum(raiz, grupo, nombre):
    """Resuelve un enum de Qt en Qt5 y en Qt6.

    Qt6 metio los enums dentro de su propia clase -``Qt.PenStyle.DashLine``-
    mientras que en Qt5 cuelgan del espacio de nombres -``Qt.DashLine``-.
    QGIS se compila contra los dos segun la version, asi que el plugin no
    puede elegir uno.
    """
    if hasattr(raiz, grupo):
        return getattr(getattr(raiz, grupo), nombre)
    return getattr(raiz, nombre)


__all__ = ["QtCore", "QtGui", "QtWidgets", "Qt", "pyqtSignal", "enum",
           "DENTRO_DE_QGIS"]
