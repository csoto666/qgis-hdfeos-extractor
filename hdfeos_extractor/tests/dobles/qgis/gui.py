# -*- coding: utf-8 -*-
"""Doble minimo de qgis.gui."""

from PyQt5.QtCore import QObject


class QgsMapTool(QObject):
    """QgsMapTool es un QObject, y de eso depende que pyqtSignal funcione en
    la herramienta del plugin. El doble hereda de QObject por lo mismo."""

    def __init__(self, canvas):
        super(QgsMapTool, self).__init__()
        self._canvas = canvas

    def toMapCoordinates(self, pos):
        from qgis.core import QgsPointXY
        return QgsPointXY(pos.x(), pos.y())

    def deactivate(self):
        pass


class QgsRubberBand(object):
    def __init__(self, canvas, tipo):
        self.puntos = []
        self.geometria = None

    def setColor(self, color):
        pass

    def setWidth(self, ancho):
        pass

    def setFillColor(self, color):
        pass

    def reset(self, tipo=None):
        self.puntos = []

    def addPoint(self, punto):
        self.puntos.append(punto)

    def setToGeometry(self, geometria, capa):
        self.geometria = geometria
