# -*- coding: utf-8 -*-
"""Doble minimo de qgis.core: solo los nombres que usa el plugin."""


class Senal(object):
    """Una senal de Qt reducida a lo que las pruebas necesitan observar."""

    def __init__(self):
        self.conectados = []

    def connect(self, receptor):
        self.conectados.append(receptor)

    def disconnect(self, receptor):
        # PyQt levanta TypeError al soltar algo que no estaba conectado, y
        # el doble tiene que hacer lo mismo: soltar dos veces es normal
        # -cerrar el panel y despues descargar el complemento- y si aqui
        # saliera otra excepcion la prueba pasaria por un camino que en QGIS
        # no existe.
        if receptor not in self.conectados:
            raise TypeError("ese receptor no estaba conectado")
        self.conectados.remove(receptor)

    def emit(self, *args):
        for receptor in list(self.conectados):
            receptor(*args)


class Crs(object):
    """SRC de mentira. ``valido`` existe para poder probar el camino en que
    QGIS no reconoce lo que la escena declara."""

    def __init__(self, wkt=None, epsg=None, valido=True):
        # Sin WKT se construye INVALIDO, como el de QGIS: es el estado del
        # que se parte para llamar a createFromWkt.
        self._wkt = wkt
        self._epsg = epsg
        self._valido = valido and bool(wkt or epsg)

    def isValid(self):
        return self._valido

    def authid(self):
        return "EPSG:%d" % self._epsg if self._epsg else "EPSG:32619"

    def toWkt(self):
        return self._wkt

    def __eq__(self, otro):
        return True


class QgsCoordinateReferenceSystem(Crs):
    def createFromWkt(self, wkt):
        """Como el de QGIS: se construye vacio y se le da el WKT despues.

        Es la forma que existe en todo QGIS 3.x, y por eso es la que usa el
        complemento; fromWkt es mas nueva.
        """
        self._wkt = wkt
        self._valido = bool(wkt)
        return self._valido

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
    """Un proyecto que si recuerda las capas que se le agregan.

    Recordarlas hace falta desde que las capas de huellas se ponen al dia
    solas: el panel comprueba que sigan en el proyecto antes de tocarlas,
    porque quitarlas es una decision del usuario y hay que respetarla.
    """

    _unico = None

    def __init__(self):
        self.layersAdded = Senal()
        self.layersRemoved = Senal()
        self.capas = {}

    @classmethod
    def instance(cls):
        if cls._unico is None:
            cls._unico = cls()
        return cls._unico

    def mapLayers(self):
        return dict(self.capas)

    def mapLayer(self, identificador):
        return self.capas.get(identificador)

    def addMapLayer(self, capa):
        self.capas[capa.id()] = capa
        return capa

    def removeMapLayer(self, identificador):
        self.capas.pop(identificador, None)


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


class QgsRectangle(object):
    """Una extension rectangular, con lo justo para el vinculo de vistas."""

    def __init__(self, xmin=0.0, ymin=0.0, xmax=0.0, ymax=0.0):
        self._x0, self._y0 = float(xmin), float(ymin)
        self._x1, self._y1 = float(xmax), float(ymax)

    def xMinimum(self):
        return self._x0

    def yMinimum(self):
        return self._y0

    def xMaximum(self):
        return self._x1

    def yMaximum(self):
        return self._y1

    def width(self):
        return self._x1 - self._x0

    def height(self):
        return self._y1 - self._y0

    def __repr__(self):
        return ("QgsRectangle(%.3f, %.3f, %.3f, %.3f)"
                % (self._x0, self._y0, self._x1, self._y1))


class QgsCsException(Exception):
    """Lo que QGIS lanza cuando una reproyeccion no es posible."""


class QgsCoordinateTransform(object):
    def __init__(self, *args):
        pass

    def transform(self, punto):
        return punto

    def transformBoundingBox(self, rect):
        # El doble no reproyecta: devuelve la misma caja. Basta para probar
        # el vinculo, cuya geometria es la de la escena, no la del SRC.
        return rect


class QgsPointXY(object):
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class QgsGeometry(object):
    """Guarda que clase de geometria se le pidio y con que puntos.

    No calcula nada: lo que las pruebas comprueban es que a un area le toque
    un poligono y a unos pixeles sueltos varios puntos, no que QGIS sepa
    hacer poligonos.
    """

    def __init__(self, clase=None, partes=None):
        self.clase = clase
        self.partes = partes or []

    @staticmethod
    def fromPolygonXY(anillos):
        return QgsGeometry("poligono", anillos)

    @staticmethod
    def fromPointXY(punto):
        return QgsGeometry("punto", [punto])

    @staticmethod
    def fromMultiPointXY(puntos):
        return QgsGeometry("multipunto", list(puntos))


class QgsWkbTypes(object):
    PolygonGeometry = 2
    LineGeometry = 1


# -- capas vectoriales -------------------------------------------------------
# Lo minimo para probar que las huellas de las firmas salen a dos capas con
# la geometria, los campos y el SRC que corresponden. El doble NO dibuja ni
# valida geometrias: eso es trabajo de QGIS, y probarlo aqui seria probar el
# doble.
class QgsField(object):
    def __init__(self, nombre, tipo=None):
        self._nombre, self._tipo = nombre, tipo

    def name(self):
        return self._nombre

    def type(self):
        return self._tipo


class QgsFeature(object):
    def __init__(self):
        self._geometria = None
        self._atributos = []

    def setGeometry(self, geometria):
        self._geometria = geometria

    def geometry(self):
        return self._geometria

    def setAttributes(self, atributos):
        self._atributos = list(atributos)

    def attributes(self):
        return list(self._atributos)


class ProveedorVector(object):
    def __init__(self):
        self.campos = []
        self.rasgos = []

    def addAttributes(self, campos):
        self.campos.extend(campos)
        return True

    def addFeatures(self, rasgos):
        self.rasgos.extend(rasgos)
        return True, rasgos

    def truncate(self):
        """Vacia la capa conservandola. Es lo que permite poner al dia las
        huellas sin quitar y volver a poner la capa, que le cambiaria el
        identificador y la sacaria del sitio que el usuario le dio."""
        self.rasgos = []
        return True


class QgsVectorLayer(object):
    def __init__(self, ruta="", nombre="", proveedor="memory"):
        self._ruta, self._nombre = ruta, nombre
        self._proveedor = ProveedorVector()
        self._crs = None
        self.renderer = None

    def isValid(self):
        return True

    def name(self):
        return self._nombre

    def geometria_declarada(self):
        return self._ruta

    def dataProvider(self):
        return self._proveedor

    def updateFields(self):
        pass

    def updateExtents(self):
        pass

    def fields(self):
        return list(self._proveedor.campos)

    def getFeatures(self):
        return list(self._proveedor.rasgos)

    def featureCount(self):
        return len(self._proveedor.rasgos)

    def geometryType(self):
        return QgsWkbTypes.PolygonGeometry

    def setCrs(self, src):
        self._crs = src

    def crs(self):
        return self._crs

    def setRenderer(self, renderer):
        self.renderer = renderer

    def id(self):
        return "%s_%d" % (self._nombre, id(self))


class QgsSymbol(object):
    def __init__(self):
        self._color = None

    @staticmethod
    def defaultSymbol(tipo):
        return QgsSymbol()

    def setColor(self, color):
        self._color = color

    def color(self):
        return self._color


class QgsRendererCategory(object):
    def __init__(self, valor, simbolo, etiqueta):
        self.valor, self.simbolo, self.etiqueta = valor, simbolo, etiqueta


class QgsCategorizedSymbolRenderer(object):
    def __init__(self, campo, categorias):
        self.campo = campo
        self.categorias = list(categorias)
