# -*- coding: utf-8 -*-
"""Doble de qgis.PyQt: reenvia a los enlaces que haya, como el shim real.

PyQt5 primero, que es lo que trae hoy la mayoria de las instalaciones de
QGIS. PyQt6 de respaldo para poder correr la suite contra Qt6 donde solo
este ese.
"""

import sys

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:                       # pragma: no cover - entorno Qt6
    from PyQt6 import QtCore, QtGui, QtWidgets

for _nombre, _sub in (("QtCore", QtCore), ("QtGui", QtGui),
                      ("QtWidgets", QtWidgets)):
    setattr(sys.modules[__name__], _nombre, _sub)
    sys.modules["qgis.PyQt." + _nombre] = _sub
