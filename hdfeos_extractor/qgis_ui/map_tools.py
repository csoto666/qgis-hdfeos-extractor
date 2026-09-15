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
"""La herramienta de mapa: convierte gestos sobre el lienzo en pixeles.

Una sola herramienta con cuatro modos -pixel, linea en X, linea en Y y area-
en vez de cuatro herramientas. El motivo es practico: QGIS solo deja una
herramienta activa a la vez, y con cuatro el usuario tendria que elegir en la
barra cual esta usando antes de cada gesto. Con una, cambiar de modo es un
boton del panel y el mapa no se entera.

Las marcas -el pixel resaltado, la linea de muestreo, el rectangulo- son
``QgsRubberBand``: se dibujan sobre el lienzo sin tocar ninguna capa y
desaparecen al desactivar la herramienta.
"""

import time

from qgis.core import (QgsCoordinateTransform, QgsGeometry, QgsPointXY,
                       QgsProject, QgsWkbTypes)
from qgis.gui import QgsMapTool, QgsRubberBand

from ..vista.qt import QtGui, Qt, pyqtSignal

# Los modos se definen en la vista del cubo, que no depende de QGIS, para que
# el cubo y el mapa usen exactamente los mismos.
from ..vista.cube_view import (MODO_AREA, MODO_MULTI, MODO_PIXEL,  # noqa: E402
                               MODO_X, MODO_Y)

COLOR_PIXEL = QtGui.QColor(255, 220, 0)
COLOR_LINEA = QtGui.QColor(106, 81, 163)
COLOR_AREA = QtGui.QColor(0, 160, 255)

#: Minimo entre actualizaciones al arrastrar la linea, en segundos. Sin este
#: freno, mover el raton rapido sobre un cubo grande encola una lectura de
#: transecto por cada pixel recorrido y la interfaz se congela persiguiendo
#: posiciones que el usuario ya dejo atras.
INTERVALO_MINIMO = 0.05


class HerramientaExplorar(QgsMapTool):
    """Traduce clics y movimientos a coordenadas de pixel del cubo."""

    pixelElegido = pyqtSignal(int, int)
    lineaMovida = pyqtSignal(str, int)       # eje, posicion
    areaElegida = pyqtSignal(int, int, int, int)
    pixelesElegidos = pyqtSignal(object)
    fueraDeLaImagen = pyqtSignal()

    def __init__(self, canvas, controller):
        super(HerramientaExplorar, self).__init__(canvas)
        self.canvas = canvas
        self.controller = controller
        self.modo = MODO_PIXEL
        self._ultimo_envio = 0.0
        self._ultima_posicion = None
        self._arrastre = None                # esquina inicial del rectangulo
        self.seleccion = []                  # pixeles sueltos, en modo multi

        self.marca_pixel = self._banda(QgsWkbTypes.PolygonGeometry,
                                       COLOR_PIXEL, 2)
        self.marca_linea = self._banda(QgsWkbTypes.LineGeometry,
                                       COLOR_LINEA, 2)
        self.marca_area = self._banda(QgsWkbTypes.PolygonGeometry,
                                      COLOR_AREA, 2)

    def _banda(self, tipo, color, ancho):
        banda = QgsRubberBand(self.canvas, tipo)
        banda.setColor(color)
        banda.setWidth(ancho)
        if tipo == QgsWkbTypes.PolygonGeometry:
            relleno = QtGui.QColor(color)
            relleno.setAlpha(45)
            banda.setFillColor(relleno)
        return banda

    # -- modo ---------------------------------------------------------------
    def set_modo(self, modo):
        self.modo = modo
        if modo != MODO_MULTI:
            self.seleccion = []
        self.limpiar_marcas(pixel=(modo != MODO_PIXEL))
        self.canvas.setCursor(QtGui.QCursor(
            Qt.CrossCursor if modo == MODO_PIXEL else Qt.SizeAllCursor))

    def limpiar_marcas(self, pixel=True):
        if pixel:
            self.marca_pixel.reset(QgsWkbTypes.PolygonGeometry)
        self.marca_linea.reset(QgsWkbTypes.LineGeometry)
        self.marca_area.reset(QgsWkbTypes.PolygonGeometry)

    # -- conversion ---------------------------------------------------------
    def _a_pixel(self, evento):
        """Punto del lienzo -> (columna, fila) del cubo, o None si no aplica.

        El SRC del lienzo y el de la capa no tienen por que coincidir -basta
        con que el usuario tenga otra capa proyectada de fondo-, asi que hay
        que reproyectar antes de convertir a pixel. Saltarse este paso da
        coordenadas verosimiles y equivocadas, que es el peor error posible:
        el espectro sale, pero de otro sitio.
        """
        if self.controller.cube is None:
            return None
        punto = self.toMapCoordinates(evento.pos())
        capa = self.controller.layer
        if capa is not None:
            origen = self.canvas.mapSettings().destinationCrs()
            destino = capa.crs()
            if origen.isValid() and destino.isValid() and origen != destino:
                try:
                    transformacion = QgsCoordinateTransform(
                        origen, destino, QgsProject.instance())
                    punto = transformacion.transform(punto)
                except Exception:
                    return None
        col, fila = self.controller.geo.to_pixel(punto.x(), punto.y())
        cubo = self.controller.cube
        if not self.controller.geo.contiene(col, fila, cubo.samples,
                                            cubo.lines):
            return None
        return col, fila

    def _reproyectar(self, mx, my):
        """Punto en el SRC de la capa -> punto en el SRC del lienzo.

        El reves de lo que hace ``_a_pixel``, y por el mismo motivo: si el
        proyecto esta en otro SRC, la marca del pixel se dibujaria lejos del
        pixel que representa.
        """
        punto = QgsPointXY(mx, my)
        capa = self.controller.layer
        if capa is None:
            return punto
        origen = capa.crs()
        destino = self.canvas.mapSettings().destinationCrs()
        if origen.isValid() and destino.isValid() and origen != destino:
            try:
                punto = QgsCoordinateTransform(
                    origen, destino, QgsProject.instance()).transform(punto)
            except Exception:
                pass
        return punto

    def _a_mapa(self, x, y):
        """Centro de un pixel, en el SRC del lienzo."""
        return self._reproyectar(*self.controller.geo.to_map(x, y))

    # -- eventos ------------------------------------------------------------
    def canvasPressEvent(self, evento):
        if self.modo == MODO_AREA:
            self._arrastre = self._a_pixel(evento)

    def canvasMoveEvent(self, evento):
        if self.modo in (MODO_X, MODO_Y):
            self._mover_linea(evento)
        elif self.modo == MODO_AREA and self._arrastre is not None:
            actual = self._a_pixel(evento)
            if actual is not None:
                self._dibujar_area(self._arrastre, actual)

    def canvasReleaseEvent(self, evento):
        pixel = self._a_pixel(evento)
        if pixel is None:
            self.fueraDeLaImagen.emit()
            self._arrastre = None
            return
        x, y = pixel
        if self.modo == MODO_MULTI:
            # Cada clic suma un pixel. Un solo espectro dice poco de una
            # cubierta; lo que hace falta para conocer su variabilidad es un
            # conjunto.
            self.seleccion.append((x, y))
            self.resaltar_pixel(x, y)
            self.pixelesElegidos.emit(list(self.seleccion))
        elif self.modo == MODO_PIXEL:
            self.resaltar_pixel(x, y)
            self.pixelElegido.emit(x, y)
        elif self.modo == MODO_AREA and self._arrastre is not None:
            x0, y0 = self._arrastre
            self._arrastre = None
            if (x0, y0) == (x, y):
                # Un clic sin arrastre en modo area es un clic de pixel: mas
                # util que no hacer nada y esperar que el usuario adivine.
                self.resaltar_pixel(x, y)
                self.pixelElegido.emit(x, y)
            else:
                self._dibujar_area((x0, y0), (x, y))
                self.areaElegida.emit(x0, y0, x, y)
        else:
            self._mover_linea(evento, forzar=True)

    def _mover_linea(self, evento, forzar=False):
        pixel = self._a_pixel(evento)
        if pixel is None:
            return
        x, y = pixel
        posicion = x if self.modo == MODO_X else y
        ahora = time.monotonic()
        if not forzar:
            if posicion == self._ultima_posicion:
                return
            if ahora - self._ultimo_envio < INTERVALO_MINIMO:
                return
        self._ultima_posicion = posicion
        self._ultimo_envio = ahora
        self.dibujar_linea(self.modo, posicion)
        self.lineaMovida.emit(self.modo, posicion)

    # -- marcas -------------------------------------------------------------
    def resaltar_pixel(self, x, y):
        """Dibuja el contorno del pixel seleccionado sobre el lienzo.

        Se usan las cuatro esquinas y no un rectangulo alineado con los ejes
        porque con una escena rotada el pixel no es un rectangulo.
        """
        self.marca_pixel.reset(QgsWkbTypes.PolygonGeometry)
        esquinas = self.controller.geo.pixel_bbox(x, y)
        puntos = [self._reproyectar(mx, my) for mx, my in esquinas]
        self.marca_pixel.setToGeometry(
            QgsGeometry.fromPolygonXY([puntos]), None)

    def dibujar_linea(self, eje, posicion):
        """La linea de muestreo, de borde a borde de la imagen."""
        cubo = self.controller.cube
        if cubo is None:
            return
        self.marca_linea.reset(QgsWkbTypes.LineGeometry)
        if eje == MODO_X:
            extremos = [(posicion, 0), (posicion, cubo.lines - 1)]
        else:
            extremos = [(0, posicion), (cubo.samples - 1, posicion)]
        for x, y in extremos:
            self.marca_linea.addPoint(self._a_mapa(x, y))

    def _dibujar_area(self, inicio, fin):
        x0, y0 = inicio
        x1, y1 = fin
        xs, xe = sorted((x0, x1))
        ys, ye = sorted((y0, y1))
        self.marca_area.reset(QgsWkbTypes.PolygonGeometry)
        esquinas = [(xs, ys), (xe + 1, ys), (xe + 1, ye + 1), (xs, ye + 1)]
        puntos = [self._reproyectar(
            *self.controller.geo.to_map(c, f, centro=False))
            for c, f in esquinas]
        self.marca_area.setToGeometry(
            QgsGeometry.fromPolygonXY([puntos]), None)

    # -- ciclo de vida ------------------------------------------------------
    def deactivate(self):
        self.limpiar_marcas()
        super(HerramientaExplorar, self).deactivate()
