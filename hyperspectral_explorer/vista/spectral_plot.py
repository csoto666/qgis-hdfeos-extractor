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
"""El grafico de firmas espectrales.

Dos implementaciones detras de una sola clase publica, ``SpectralPlot``:

pyqtgraph  cuando esta instalado. Trae zoom, desplazamiento y redibujado
           rapido hechos, que es mucho codigo que no vale la pena reescribir.
lienzo     cuando no. Un QWidget que se pinta con QPainter.

El respaldo existe porque pyqtgraph no viene con QGIS. En algunas
distribuciones esta y en otras no, y un plugin que se cae al abrir el panel
porque falta un paquete no es un plugin: es una nota pidiendole al usuario
que instale cosas. Con el lienzo, quien tenga pyqtgraph obtiene la version
comoda y quien no, obtiene el grafico igual.

Un detalle que no es decorativo: las curvas se cortan en los NaN. Las bandas
malas -las ventanas de absorcion de vapor de agua, sobre todo- llegan como
NaN, y unirlas dibujaria una recta limpia de 1340 a 1460 nm que parece una
medicion y no lo es.
"""

import numpy as np

from .qt import QtCore, QtGui, QtWidgets, Qt, enum as _enum, pyqtSignal

try:
    import pyqtgraph as pg
except Exception:                          # pragma: no cover
    pg = None


LINEA_PUNTEADA = _enum(Qt, "PenStyle", "DashLine")
LINEA_CONTINUA = _enum(Qt, "PenStyle", "SolidLine")
ANTIALIAS = _enum(QtGui.QPainter, "RenderHint", "Antialiasing")

#: Paleta de curvas. Elegida para distinguirse tambien en escala de grises y
#: para no chocar con el rojo/verde/azul de los marcadores de banda.
PALETA = [
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
    "#8c564b", "#17becf", "#e377c2", "#7f7f7f", "#bcbd22",
]

COLOR_ACTUAL = "#111111"        # el pixel que se esta tocando ahora
COLOR_FONDO = "#ffffff"
COLOR_EJES = "#606060"
COLOR_REJILLA = "#e4e4e4"
COLOR_MARCADORES = ("#d62728", "#2ca02c", "#1f77b4")   # R, G, B


def color_de(indice):
    return PALETA[indice % len(PALETA)]


class Curva(object):
    """Lo que hay que dibujar de una firma. Ni mas ni menos.

    El grafico no recibe ``Signature`` directamente para no atarse al nucleo:
    asi tambien se le puede pedir que dibuje una media, una envolvente o una
    curva calculada que no es firma de nada.
    """

    def __init__(self, nombre, x, y, color="#1f77b4", ancho=2,
                 punteada=False, banda=None):
        self.nombre = nombre
        self.x = np.asarray(x, dtype=np.float64)
        self.y = np.asarray(y, dtype=np.float64)
        self.color = color
        self.ancho = ancho
        self.punteada = punteada
        # banda: desviacion por longitud de onda, para la envolvente sombreada
        self.banda = None if banda is None else np.asarray(banda,
                                                           dtype=np.float64)

    def tramos(self):
        """Parte la curva en tramos continuos, cortando donde hay NaN.

        Es lo que evita la recta falsa a traves de las ventanas de absorcion.
        """
        valido = np.isfinite(self.x) & np.isfinite(self.y)
        if not valido.any():
            return []
        # Los limites de cada tramo continuo de True.
        bordes = np.flatnonzero(np.diff(valido.astype(np.int8)))
        inicios = np.concatenate(([0], bordes + 1))
        finales = np.concatenate((bordes + 1, [valido.size]))
        return [(self.x[i:f], self.y[i:f])
                for i, f in zip(inicios, finales)
                if valido[i] and f - i >= 2]


# -----------------------------------------------------------------------------
#  Lienzo propio (respaldo sin pyqtgraph)
# -----------------------------------------------------------------------------
class _Lienzo(QtWidgets.QWidget):
    """Grafico de lineas dibujado con QPainter."""

    posicionCambiada = pyqtSignal(float)

    MARGEN_IZQ, MARGEN_DER, MARGEN_SUP, MARGEN_INF = 64, 12, 12, 40

    def __init__(self, parent=None):
        super(_Lienzo, self).__init__(parent)
        self.setMinimumHeight(110)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        self.curvas = []
        self.marcadores = []          # [(longitud_de_onda, color), ...]
        self.etiqueta_x = "Longitud de onda (nm)"
        self.etiqueta_y = "Reflectancia"
        self._cursor_x = None
        self._limites = None

    # -- datos --------------------------------------------------------------
    def set_curvas(self, curvas):
        self.curvas = list(curvas)
        self._limites = None
        self.update()

    def set_marcadores(self, marcadores):
        self.marcadores = list(marcadores)
        self.update()

    def set_etiquetas(self, x, y):
        self.etiqueta_x, self.etiqueta_y = x, y
        self.update()

    # -- limites y escalas --------------------------------------------------
    def limites(self):
        """(xmin, xmax, ymin, ymax) de todo lo dibujable, con un margen."""
        if self._limites is not None:
            return self._limites
        xs, ys = [], []
        for c in self.curvas:
            v = np.isfinite(c.x) & np.isfinite(c.y)
            if v.any():
                xs.append(c.x[v])
                alto = c.y[v]
                if c.banda is not None:
                    b = np.nan_to_num(c.banda[v])
                    alto = np.concatenate([alto - b, alto + b])
                ys.append(alto)
        if not xs:
            self._limites = (0.0, 1.0, 0.0, 1.0)
            return self._limites
        x0, x1 = float(np.min(np.concatenate(xs))), \
            float(np.max(np.concatenate(xs)))
        y0, y1 = float(np.min(np.concatenate(ys))), \
            float(np.max(np.concatenate(ys)))
        if x1 <= x0:
            x0, x1 = x0 - 0.5, x0 + 0.5
        if y1 <= y0:
            # Una firma plana -agua en el SWIR- tiene rango cero. Sin esto la
            # curva se dibujaria sobre el borde del grafico.
            y0, y1 = y0 - 0.05, y1 + 0.05
        margen = (y1 - y0) * 0.06
        self._limites = (x0, x1, y0 - margen, y1 + margen)
        return self._limites

    def _area(self):
        return QtCore.QRectF(
            self.MARGEN_IZQ, self.MARGEN_SUP,
            max(1, self.width() - self.MARGEN_IZQ - self.MARGEN_DER),
            max(1, self.height() - self.MARGEN_SUP - self.MARGEN_INF))

    def _a_pantalla(self, x, y):
        x0, x1, y0, y1 = self.limites()
        r = self._area()
        px = r.left() + (x - x0) / (x1 - x0) * r.width()
        py = r.bottom() - (y - y0) / (y1 - y0) * r.height()
        return px, py

    def _a_datos_x(self, px):
        x0, x1, _, _ = self.limites()
        r = self._area()
        return x0 + (px - r.left()) / max(1.0, r.width()) * (x1 - x0)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, evento):
        p = QtGui.QPainter(self)
        p.setRenderHint(ANTIALIAS, True)
        p.fillRect(self.rect(), QtGui.QColor(COLOR_FONDO))
        area = self._area()
        if not self.curvas:
            p.setPen(QtGui.QColor(COLOR_EJES))
            p.drawText(area, _enum(Qt, "AlignmentFlag", "AlignCenter"),
                       "Haga clic en un pixel del mapa para ver su espectro")
            p.end()
            return
        self._pintar_rejilla(p, area)
        self._pintar_marcadores(p, area)
        self._pintar_curvas(p)
        self._pintar_cursor(p, area)
        self._pintar_leyenda(p, area)
        p.end()

    def _pintar_rejilla(self, p, area):
        x0, x1, y0, y1 = self.limites()
        fuente = p.font()
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 1.0))
        p.setFont(fuente)
        izq = _enum(Qt, "AlignmentFlag", "AlignRight")
        vcentro = _enum(Qt, "AlignmentFlag", "AlignVCenter")
        centro = _enum(Qt, "AlignmentFlag", "AlignHCenter")

        for valor in _marcas(x0, x1, _cuantas(area.width(), 95)):
            px, _ = self._a_pantalla(valor, y0)
            p.setPen(QtGui.QPen(QtGui.QColor(COLOR_REJILLA), 1))
            p.drawLine(QtCore.QPointF(px, area.top()),
                       QtCore.QPointF(px, area.bottom()))
            p.setPen(QtGui.QColor(COLOR_EJES))
            p.drawText(QtCore.QRectF(px - 40, area.bottom() + 4, 80, 16),
                       centro, _formato(valor))
        for valor in _marcas(y0, y1, _cuantas(area.height(), 34)):
            _, py = self._a_pantalla(x0, valor)
            p.setPen(QtGui.QPen(QtGui.QColor(COLOR_REJILLA), 1))
            p.drawLine(QtCore.QPointF(area.left(), py),
                       QtCore.QPointF(area.right(), py))
            p.setPen(QtGui.QColor(COLOR_EJES))
            p.drawText(QtCore.QRectF(0, py - 8, self.MARGEN_IZQ - 6, 16),
                       izq | vcentro, _formato(valor))

        p.setPen(QtGui.QPen(QtGui.QColor(COLOR_EJES), 1))
        p.drawRect(area)
        p.drawText(QtCore.QRectF(area.left(), self.height() - 18,
                                 area.width(), 16), centro, self.etiqueta_x)
        # El rotulo rotado se dibuja en un rectangulo tan largo como el alto
        # del grafico, y se acorta con puntos suspensivos si no entra. Con un
        # largo fijo y sin acortar, en un panel bajo el texto sale partido por
        # la mitad -"ectancia"- en vez de encogerse.
        largo = max(40.0, area.height())
        metrica = QtGui.QFontMetrics(p.font())
        rotulo = metrica.elidedText(self.etiqueta_y,
                                    _enum(Qt, "TextElideMode", "ElideRight"),
                                    int(largo))
        p.save()
        p.translate(12, area.center().y())
        p.rotate(-90)
        p.drawText(QtCore.QRectF(-largo / 2.0, -8, largo, 16),
                   _enum(Qt, "AlignmentFlag", "AlignCenter"), rotulo)
        p.restore()

    def _pintar_marcadores(self, p, area):
        """Las tres verticales que dicen que bandas alimentan el RGB.

        Es la mitad del enlace entre las dos vistas: sin ellas el usuario ve
        una imagen y una curva y tiene que creer que se corresponden.
        """
        x0, x1, _, _ = self.limites()
        for valor, color in self.marcadores:
            if not (x0 <= valor <= x1):
                continue
            px, _ = self._a_pantalla(valor, 0)
            lapiz = QtGui.QPen(QtGui.QColor(color), 1, LINEA_PUNTEADA)
            p.setPen(lapiz)
            p.drawLine(QtCore.QPointF(px, area.top()),
                       QtCore.QPointF(px, area.bottom()))

    def _pintar_curvas(self, p):
        for c in self.curvas:
            color = QtGui.QColor(c.color)
            if c.banda is not None:
                self._pintar_envolvente(p, c, color)
            lapiz = QtGui.QPen(color, c.ancho,
                               LINEA_PUNTEADA if c.punteada else LINEA_CONTINUA)
            p.setPen(lapiz)
            for xs, ys in c.tramos():
                poligono = QtGui.QPolygonF(
                    [QtCore.QPointF(*self._a_pantalla(x, y))
                     for x, y in zip(xs, ys)])
                p.drawPolyline(poligono)

    def _pintar_envolvente(self, p, c, color):
        """Media +- desviacion de una firma de area, como banda sombreada."""
        relleno = QtGui.QColor(color)
        relleno.setAlpha(45)
        p.setPen(_enum(Qt, "PenStyle", "NoPen"))
        p.setBrush(relleno)
        for xs, ys in c.tramos():
            idx = np.searchsorted(c.x, xs)
            banda = np.nan_to_num(c.banda[idx])
            arriba = [QtCore.QPointF(*self._a_pantalla(x, y + b))
                      for x, y, b in zip(xs, ys, banda)]
            abajo = [QtCore.QPointF(*self._a_pantalla(x, y - b))
                     for x, y, b in reversed(list(zip(xs, ys, banda)))]
            p.drawPolygon(QtGui.QPolygonF(arriba + abajo))
        p.setBrush(_enum(Qt, "BrushStyle", "NoBrush"))

    def _pintar_cursor(self, p, area):
        """Cruz de lectura: la vertical y el valor de cada curva ahi."""
        if self._cursor_x is None:
            return
        x0, x1, _, _ = self.limites()
        if not (x0 <= self._cursor_x <= x1):
            return
        px, _ = self._a_pantalla(self._cursor_x, 0)
        p.setPen(QtGui.QPen(QtGui.QColor("#909090"), 1, LINEA_PUNTEADA))
        p.drawLine(QtCore.QPointF(px, area.top()),
                   QtCore.QPointF(px, area.bottom()))
        for c in self.curvas:
            v = _valor_en(c, self._cursor_x)
            if v is None:
                continue
            _, py = self._a_pantalla(self._cursor_x, v)
            p.setPen(QtGui.QPen(QtGui.QColor(c.color), 1))
            p.setBrush(QtGui.QColor(c.color))
            p.drawEllipse(QtCore.QPointF(px, py), 3.0, 3.0)
        p.setBrush(_enum(Qt, "BrushStyle", "NoBrush"))

    def _pintar_leyenda(self, p, area):
        visibles = [c for c in self.curvas if c.nombre]
        if not visibles:
            return
        metrica = QtGui.QFontMetrics(p.font())
        alto = metrica.height() + 2
        ancho = max(metrica.horizontalAdvance(c.nombre)
                    for c in visibles) + 34
        caja = QtCore.QRectF(area.right() - ancho - 6, area.top() + 6,
                             ancho, alto * len(visibles) + 6)
        fondo = QtGui.QColor(COLOR_FONDO)
        fondo.setAlpha(215)
        p.setPen(QtGui.QPen(QtGui.QColor(COLOR_REJILLA), 1))
        p.setBrush(fondo)
        p.drawRect(caja)
        p.setBrush(_enum(Qt, "BrushStyle", "NoBrush"))
        for i, c in enumerate(visibles):
            y = caja.top() + 3 + i * alto + alto / 2.0
            p.setPen(QtGui.QPen(QtGui.QColor(c.color), c.ancho,
                                LINEA_PUNTEADA if c.punteada
                                else LINEA_CONTINUA))
            p.drawLine(QtCore.QPointF(caja.left() + 6, y),
                       QtCore.QPointF(caja.left() + 24, y))
            p.setPen(QtGui.QColor("#303030"))
            p.drawText(QtCore.QRectF(caja.left() + 28, y - alto / 2.0,
                                     ancho - 32, alto),
                       _enum(Qt, "AlignmentFlag", "AlignVCenter"), c.nombre)

    # -- interaccion --------------------------------------------------------
    def mouseMoveEvent(self, evento):
        pos = evento.position() if hasattr(evento, "position") else evento.pos()
        if self._area().contains(QtCore.QPointF(pos.x(), pos.y())):
            self._cursor_x = self._a_datos_x(pos.x())
            self.posicionCambiada.emit(self._cursor_x)
            self.setToolTip(self._texto_cursor())
        else:
            self._cursor_x = None
            self.setToolTip("")
        self.update()

    def leaveEvent(self, evento):
        self._cursor_x = None
        self.update()

    def _texto_cursor(self):
        lineas = ["%s" % _formato(self._cursor_x)]
        for c in self.curvas:
            v = _valor_en(c, self._cursor_x)
            if v is not None:
                lineas.append("%s: %.4f" % (c.nombre or "-", v))
        return "\n".join(lineas)

    def resizeEvent(self, evento):
        self._limites = None
        super(_Lienzo, self).resizeEvent(evento)


def _valor_en(curva, x):
    """Valor de la curva en la longitud de onda mas cercana a ``x``."""
    if curva.x.size == 0:
        return None
    i = int(np.argmin(np.abs(curva.x - x)))
    v = curva.y[i]
    return None if not np.isfinite(v) else float(v)


def _cuantas(espacio, por_marca):
    """Cuantas marcas caben. Entre 2 y 6: menos no ubica, mas se pisa."""
    return int(min(6, max(2, espacio // por_marca)))


def _marcas(lo, hi, objetivo=6):
    """Marcas de eje en numeros redondos.

    El algoritmo clasico: se toma el paso crudo, se lleva a 1, 2, 5 o 10 por
    la decada correspondiente, y se recorre. Sin esto las etiquetas salen en
    valores como 437.83, que nadie lee.
    """
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return []
    crudo = (hi - lo) / float(objetivo)
    decada = 10.0 ** np.floor(np.log10(crudo))
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        paso = mult * decada
        if crudo <= paso:
            break
    inicio = np.ceil(lo / paso) * paso
    # El filtro final no sobra: ``arange`` con un tope holgado devuelve una
    # marca de mas, y esa marca se dibuja fuera del marco del grafico, con su
    # etiqueta pisando el eje.
    tolerancia = paso * 1e-9
    return [float(v) for v in np.arange(inicio, hi + paso, paso)
            if lo - tolerancia <= v <= hi + tolerancia]


def _formato(valor):
    # El redondeo puede dejar un cero negativo, y "-0" en un eje de
    # reflectancia se lee como un error del programa.
    valor = round(float(valor), 4) + 0.0
    if valor == 0.0:
        return "0"
    if abs(valor) >= 100 or valor == int(valor):
        return "%g" % round(valor, 2)
    return ("%.3f" % valor).rstrip("0").rstrip(".")


# -----------------------------------------------------------------------------
#  Fachada
# -----------------------------------------------------------------------------
class SpectralPlot(QtWidgets.QWidget):
    """El grafico espectral, con el respaldo elegido solo.

    La interfaz es la misma tenga o no pyqtgraph, asi que el resto del plugin
    no sabe -ni le importa- cual de los dos esta debajo.
    """

    posicionCambiada = pyqtSignal(float)

    def __init__(self, parent=None, forzar_lienzo=False):
        super(SpectralPlot, self).__init__(parent)
        self.usa_pyqtgraph = bool(pg) and not forzar_lienzo
        self._curvas = []
        self._marcadores = []
        self.etiqueta_x = "Longitud de onda (nm)"

        caja = QtWidgets.QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        if self.usa_pyqtgraph:
            pg.setConfigOptions(antialias=True, background=COLOR_FONDO,
                                foreground=COLOR_EJES)
            self._grafico = pg.PlotWidget()
            self._grafico.showGrid(x=True, y=True, alpha=0.25)
            # pyqtgraph reescala los ejes solo y le agrega un prefijo SI al
            # rotulo. En un eje de reflectancia eso pone "200" donde el valor
            # es 0.2 y manda el "x10^-3" a la etiqueta, que en un panel
            # angosto queda cortada: el usuario lee 200 de reflectancia. En
            # el eje espectral hace lo mismo con 2000 nm -> "2 k".
            for lado in ("left", "bottom"):
                self._grafico.getPlotItem().getAxis(lado)\
                    .enableAutoSIPrefix(False)
            self._grafico.addLegend(offset=(-10, 10))
            self._linea = pg.InfiniteLine(angle=90, movable=False)
            self._grafico.addItem(self._linea, ignoreBounds=True)
            self._grafico.scene().sigMouseMoved.connect(self._raton_pyqtgraph)
        else:
            self._grafico = _Lienzo()
            self._grafico.posicionCambiada.connect(self.posicionCambiada)
        caja.addWidget(self._grafico)
        self.set_unidad("nm")

    # -- configuracion ------------------------------------------------------
    def set_unidad(self, unidad):
        """Cambia el rotulo del eje X segun haya o no longitudes de onda."""
        self.etiqueta_x = ("Longitud de onda (nm)" if unidad == "nm"
                           else "Numero de banda")
        if self.usa_pyqtgraph:
            self._grafico.setLabel("bottom", self.etiqueta_x)
            self._grafico.setLabel("left", "Reflectancia")
        else:
            self._grafico.set_etiquetas(self.etiqueta_x, "Reflectancia")

    # -- contenido ----------------------------------------------------------
    def set_curvas(self, curvas):
        self._curvas = list(curvas)
        self._redibujar()

    def set_marcadores_rgb(self, longitudes):
        """Marca en el grafico las tres bandas que alimentan la imagen RGB.

        Junto con el pixel resaltado en el mapa, es lo que cierra el vinculo
        entre las dos vistas: el usuario ve en la curva donde esta mirando la
        imagen.
        """
        self._marcadores = [(float(w), c) for w, c
                            in zip(longitudes, COLOR_MARCADORES)
                            if w is not None and np.isfinite(w)]
        self._redibujar()

    def clear(self):
        self._curvas = []
        self._redibujar()

    def _redibujar(self):
        if not self.usa_pyqtgraph:
            self._grafico.set_curvas(self._curvas)
            self._grafico.set_marcadores(self._marcadores)
            return
        self._grafico.clear()
        self._grafico.addItem(self._linea, ignoreBounds=True)
        for valor, color in self._marcadores:
            self._grafico.addItem(
                pg.InfiniteLine(pos=valor, angle=90, pen=pg.mkPen(
                    color, width=1, style=LINEA_PUNTEADA)),
                ignoreBounds=True)
        for c in self._curvas:
            lapiz = pg.mkPen(c.color, width=c.ancho,
                             style=LINEA_PUNTEADA if c.punteada
                             else LINEA_CONTINUA)
            # connect="finite" es lo que corta la curva en los NaN. Sin eso
            # pyqtgraph une los extremos de la ventana de absorcion con una
            # recta que parece una medicion.
            self._grafico.plot(c.x, c.y, pen=lapiz, name=c.nombre,
                               connect="finite")

    def _raton_pyqtgraph(self, pos):        # pragma: no cover - necesita Qt
        vb = self._grafico.getPlotItem().vb
        if self._grafico.sceneBoundingRect().contains(pos):
            x = float(vb.mapSceneToView(pos).x())
            self._linea.setPos(x)
            self.posicionCambiada.emit(x)
