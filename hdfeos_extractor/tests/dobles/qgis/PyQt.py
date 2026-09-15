# -*- coding: utf-8 -*-
"""Doble de qgis.PyQt: reenvia a PyQt5, que es lo que hace el shim real."""

import sys

from PyQt5 import QtCore, QtGui, QtWidgets

for _nombre, _sub in (("QtCore", QtCore), ("QtGui", QtGui),
                      ("QtWidgets", QtWidgets)):
    setattr(sys.modules[__name__], _nombre, _sub)
    sys.modules["qgis.PyQt." + _nombre] = _sub
