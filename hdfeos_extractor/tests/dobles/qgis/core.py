# -*- coding: utf-8 -*-
"""Doble minimo de qgis.core: solo los nombres que usa el plugin."""


class Senal(object):
    """Una senal de Qt reducida a lo que las pruebas necesitan observar."""

    def __init__(self):
        self.conectados = []

    def connect(self, receptor):
        self.conectados.append(receptor)

    def disconnect(self, receptor):
        self.conectados.remove(receptor)

    def emit(self, *args):
        for receptor in list(self.conectados):
            receptor(*args)


class Crs(object):
    """SRC de mentira. ``valido`` existe para poder probar el camino en que
    QGIS no reconoce lo que la escena declara."""

    def __init__(self, wkt=None, epsg=None, valido=True):
        self._wkt = wkt or 'PROJCS["WGS 84 / UTM zone 19S"]'
        self._epsg = epsg
        self._valido = valido

    def isValid(self):
        return self._valido

    def authid(self):
        return "EPSG:%d" % self._epsg if self._epsg else "EPSG:32619"

    def toWkt(self):
        return self._wkt

    def __eq__(self, otro):
        return True


class QgsCoordinateReferenceSystem(Crs):
    @staticmethod
    def fromWkt(wkt):
        return QgsCoordinateReferenceSystem(wkt=wkt, valido=bool(wkt))

    @staticmethod
    def fromEpsgId(codigo):
        return QgsCoordinateReferenceSystem(epsg=int(codigo),
                                            valido=bool(codigo))


class Extent(object):
    def xMinimum(self):
        return 0.0

    def yMaximum(self):
        return 7.0

    def width(self):
        return 5.0

    def height(self):
        return 7.0


class Proveedor(object):
    def bandCount(self):
        return 9

    def dataType(self, banda):
        return 6


class QgsRasterLayer(object):
    def __init__(self, ruta="", nombre=""):
        self._ruta = ruta
        self._nombre = nombre
        self.renderizador = None

    def isValid(self):
        return True

    def source(self):
        return self._ruta

    def name(self):
        return self._nombre

    def id(self):
        return "capa1"

    def crs(self):
        return Crs()

    def width(self):
        return 5

    def height(self):
        return 7

    def extent(self):
        return Extent()

    def dataProvider(self):
        return Proveedor()

    def setRenderer(self, renderizador):
        self.renderizador = renderizador

    def triggerRepaint(self):
        pass


class QgsProject(object):
    _unico = None

    def __init__(self):
        self.layersAdded = Senal()
        self.layersRemoved = Senal()

    @classmethod
    def instance(cls):
        if cls._unico is None:
            cls._unico = cls()
        return cls._unico

    def mapLayers(self):
        return {}

    def mapLayer(self, identificador):
        return None

    def addMapLayer(self, capa):
        return capa


class QgsContrastEnhancement(object):
    StretchToMinimumMaximum = 1

    def __init__(self, tipo):
        self.lo = self.hi = None

    def setContrastEnhancementAlgorithm(self, algoritmo, generar=True):
        pass

    def setMinimumValue(self, valor):
        self.lo = valor

    def setMaximumValue(self, valor):
        self.hi = valor


class QgsMultiBandColorRenderer(object):
    def __init__(self, proveedor, rojo, verde, azul):
        self.bandas = (rojo, verde, azul)

    def setRedContrastEnhancement(self, realce):
        self.rojo = realce

    def setGreenContrastEnhancement(self, realce):
        self.verde = realce

    def setBlueContrastEnhancement(self, realce):
        self.azul = realce


class QgsCoordinateTransform(object):
    def __init__(self, *args):
        pass

    def transform(self, punto):
        return punto


class QgsPointXY(object):
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class QgsGeometry(object):
    @staticmethod
    def fromPolygonXY(anillos):
        return QgsGeometry()


class QgsWkbTypes(object):
    PolygonGeometry = 2
    LineGeometry = 1
