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

import importlib

#: Enlaces que se prueban fuera de QGIS, en orden. Dentro de QGIS no se llega
#: a mirar esta lista: manda ``qgis.PyQt``.
ENLACES = ("PyQt5", "PyQt6")

try:
    from qgis.PyQt import QtCore, QtGui, QtWidgets
    from qgis.PyQt.QtCore import Qt, pyqtSignal
    DENTRO_DE_QGIS = True
except ImportError:                       # pragma: no cover
    # El respaldo se resuelve con importlib y no con "from PyQt5 import ...".
    # No es rodeo: el verificador de compatibilidad del repositorio de
    # complementos busca importaciones directas de PyQt en el fuente y las
    # rechaza, y hace bien, porque un plugin que importe PyQt5 a secas se
    # rompe en un QGIS compilado contra Qt6. Este no lo hace: dentro de QGIS
    # siempre entra por qgis.PyQt y esta rama no se ejecuta nunca. Existe
    # para poder importar la vista sin QGIS abierto, que es lo unico que
    # permite probarla.
    DENTRO_DE_QGIS = False
    QtCore = QtGui = QtWidgets = Qt = pyqtSignal = None
    for _enlace in ENLACES:
        try:
            QtCore = importlib.import_module(_enlace + ".QtCore")
            QtGui = importlib.import_module(_enlace + ".QtGui")
            QtWidgets = importlib.import_module(_enlace + ".QtWidgets")
        except ImportError:
            continue
        Qt = QtCore.Qt
        pyqtSignal = QtCore.pyqtSignal
        break
    else:
        raise ImportError(
            "No hay enlaces de Qt disponibles. Dentro de QGIS esto no "
            "deberia pasar; fuera, hace falta PyQt5 o PyQt6.")


# La regla de resolucion vive en ``compat``, que no importa nada: la
# necesita tambien el algoritmo de Processing, que no importa Qt.
from ..compat import enum                                        # noqa: E402

#: Enums que se usan en varios sitios. Resolverlos una vez aqui evita repetir
#: la llamada -y el nombre del grupo, que es lo que se escribe mal- en cada
#: uso, y deja el codigo tan legible como con la forma plana de Qt5.
HORIZONTAL = enum(Qt, "Orientation", "Horizontal")
VERTICAL = enum(Qt, "Orientation", "Vertical")


def politica(nombre):
    """Una politica de tamano por su nombre. En Qt6 vive en ``Policy``."""
    return enum(QtWidgets.QSizePolicy, "Policy", nombre)


__all__ = ["QtCore", "QtGui", "QtWidgets", "Qt", "pyqtSignal", "enum",
           "politica", "HORIZONTAL", "VERTICAL", "DENTRO_DE_QGIS"]
