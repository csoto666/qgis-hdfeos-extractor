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
"""El lienzo de la nube n-dimensional.

Dibuja la sombra de la nube sobre el plano que gira, los radios de cada banda
y el lazo de seleccion. La geometria vive en ``core.ndim``, que se prueba sin
abrir Qt; aqui queda solo lo que es dibujar y responder al raton.

Se dibuja con QPainter y no con OpenGL a proposito: el complemento no puede
pedir dependencias que QGIS no traiga, y veinte mil puntos por cuadro los
mueve QPainter sin despeinarse si se le pasan todos juntos -un drawPoints por
clase- en vez de uno por uno.
"""

import time

import numpy as np

from .qt import QtCore, QtGui, QtWidgets, Qt, enum, pyqtSignal

#: Fondo negro como el de ENVI, y no por nostalgia: sobre negro el ojo
#: separa mucho mejor puntos de colores saturados, que es todo el trabajo.
COLOR_FONDO = QtGui.QColor(12, 12, 16)
COLOR_RADIO = QtGui.QColor(190, 190, 200)
COLOR_LAZO = QtGui.QColor(255, 220, 60)

MODO_GIRAR = "girar"
MODO_LAZO = "lazo"

#: Cuantos radios se etiquetan. Con cuarenta bandas seleccionadas, cuarenta
#: numeros encima de la nube tapan justamente lo que se vino a mirar: se
#: rotulan los mas largos, que son los que de verdad estan apuntando a algo.
RADIOS_ROTULADOS = 8

#: Y no se rotula ningun radio mas corto que esta fraccion del mas largo. Un
#: radio corto es una banda que en esta vista apunta casi de frente a la
#: pantalla: su punta cae encima del centro, y ahi los numeros se amontonan
#: unos sobre otros justo donde esta el nudo de la nube.
LARGO_MINIMO_PARA_ROTULAR = 0.35


class VistaND(QtWidgets.QWidget):
    """La nube proyectada, girando."""

    #: Se cerro un lazo. Lleva los indices de los puntos que quedaron dentro.
    seleccionHecha = pyqtSignal(object)
    #: Cambio la vista (giro o zoom): sirve para refrescar rotulos de estado.
    vistaCambiada = pyqtSignal()

    def __init__(self, parent=None):
        super(VistaND, self).__init__(parent)
        self.nube = None
        self.tour = None
        self.modo = MODO_GIRAR
        self.tamano_punto = 2
        self.zoom = 1.0
        self.t = 0.0
        self._proyectados = None      # cache de la proyeccion del cuadro
        self._lazo = []
        self._arrastre = None
        self._resaltados = None       # indices de la ultima seleccion

        self.setMinimumSize(320, 260)
        self.setAutoFillBackground(True)
        self.setCursor(QtGui.QCursor(enum(Qt, "CursorShape", "CrossCursor")))
        self.setSizePolicy(
            enum(QtWidgets.QSizePolicy, "Policy", "Expanding"),
            enum(QtWidgets.QSizePolicy, "Policy", "Expanding"))

        self._reloj = QtCore.QTimer(self)
        self._reloj.setInterval(33)               # ~30 cuadros por segundo
        self._reloj.timeout.connect(self._avanzar)
        self._ultimo = None

    # -- datos --------------------------------------------------------------
    def set_nube(self, nube, tour=None):
        from ..core.ndim import TourND
        self.nube = nube
        n = nube.n_dimensiones if nube is not None else 0
        self.tour = tour or (TourND(max(2, n)) if n else None)
        self._proyectados = None
        self._resaltados = None
        self._lazo = []
        self.update()

    def set_velocidad(self, velocidad):
        if self.tour is not None:
            self.tour.velocidad = float(velocidad)

    def set_animar(self, animar):
        """Arranca o para el giro. Con dos bandas no hay nada que girar."""
        if animar and self.puede_girar():
            self._ultimo = time.monotonic()
            self._reloj.start()
        else:
            self._reloj.stop()

    def animando(self):
        return self._reloj.isActive()

    def puede_girar(self):
        return self.nube is not None and self.nube.n_dimensiones >= 3

    def set_modo(self, modo):
        self.modo = modo
        self.setCursor(QtGui.QCursor(enum(
            Qt, "CursorShape",
            "PointingHandCursor" if modo == MODO_LAZO else "CrossCursor")))

    def set_tamano_punto(self, tamano):
        self.tamano_punto = max(1, int(tamano))
        self.update()

    def resaltar(self, indices):
        self._resaltados = indices
        self.update()

    def _avanzar(self):
        ahora = time.monotonic()
        paso = ahora - (self._ultimo or ahora)
        self._ultimo = ahora
        # El tiempo avanza con el reloj de pared y no con el numero de
        # cuadros: asi la nube gira a la misma velocidad en una maquina
        # lenta que en una rapida, solo que con menos cuadros.
        self.t += min(paso, 0.25)
        self._proyectados = None
        self.update()

    # -- geometria ----------------------------------------------------------
    def _escala(self):
        return min(self.width(), self.height()) * 0.42 * self.zoom

    def _centro(self):
        return QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)

    def _proyeccion(self):
        """La nube proyectada, en pixeles de pantalla."""
        if self._proyectados is not None:
            return self._proyectados
        if self.nube is None or self.nube.vacia or self.tour is None:
            self._proyectados = np.zeros((0, 2))
            return self._proyectados
        plano = self.tour.proyectar(self.nube.X, self.t)
        c, k = self._centro(), self._escala()
        self._proyectados = np.column_stack(
            (c.x() + plano[:, 0] * k, c.y() - plano[:, 1] * k))
        return self._proyectados

    # -- dibujo -------------------------------------------------------------
    def paintEvent(self, evento):
        pintor = QtGui.QPainter(self)
        pintor.fillRect(self.rect(), COLOR_FONDO)
        if self.nube is None or self.nube.vacia:
            self._dibujar_aviso(pintor)
            return
        pintor.setRenderHint(
            enum(QtGui.QPainter, "RenderHint", "Antialiasing"), False)
        self._dibujar_puntos(pintor)
        self._dibujar_radios(pintor)
        self._dibujar_lazo(pintor)

    def _dibujar_aviso(self, pintor):
        pintor.setPen(QtGui.QColor(160, 160, 170))
        pintor.drawText(
            self.rect(), enum(Qt, "AlignmentFlag", "AlignCenter"),
            "Guarde firmas y elija bandas para ver la nube.\n"
            "Cada pixel de cada firma es un punto aqui.")

    def _dibujar_puntos(self, pintor):
        pantalla = self._proyeccion()
        for numero, clase in enumerate(self.nube.clases):
            if not clase.visible:
                continue
            indices = self.nube.indices_de(numero)
            if not indices.size:
                continue
            color = QtGui.QColor(clase.color)
            pintor.setPen(QtGui.QPen(color, self.tamano_punto))
            # Todos los puntos de la clase en una sola llamada: pasarlos de
            # uno en uno multiplica por veinte el costo del cuadro.
            puntos = QtGui.QPolygonF(
                [QtCore.QPointF(x, y) for x, y in pantalla[indices]])
            pintor.drawPoints(puntos)
        if self._resaltados is not None and len(self._resaltados):
            pintor.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255),
                                     self.tamano_punto + 2))
            pintor.drawPoints(QtGui.QPolygonF(
                [QtCore.QPointF(x, y)
                 for x, y in pantalla[self._resaltados]]))

    def _dibujar_radios(self, pintor):
        """Los ejes de cada banda, que es lo que vuelve leible la nube.

        Un radio apuntando hacia donde se alarga un grupo dice que esa banda
        es la que lo separa. Sin ellos la nube es una mancha bonita que gira.
        """
        if self.tour is None:
            return
        ejes = self.tour.ejes(self.t)
        c, k = self._centro(), self._escala() * 0.75
        largos = np.linalg.norm(ejes, axis=1)
        mayor = float(largos.max()) if largos.size else 0.0
        umbral = mayor * LARGO_MINIMO_PARA_ROTULAR
        rotulados = set(int(i) for i in np.argsort(-largos)[:RADIOS_ROTULADOS]
                        if largos[int(i)] >= umbral)
        fuente = pintor.font()
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 1))
        pintor.setFont(fuente)
        # Dos bandas casi paralelas ponen su numero en el mismo sitio y el
        # resultado es ilegible: se lleva la cuenta de lo ya escrito y el
        # segundo se calla. Se recorren de mayor a menor, asi que el que
        # sobrevive es el radio mas largo, que es el que mas dice.
        ocupados = []
        orden_dibujo = sorted(range(len(ejes)), key=lambda i: -largos[i])
        for i in orden_dibujo:
            dx, dy = ejes[i]
            punta = QtCore.QPointF(c.x() + dx * k, c.y() - dy * k)
            # El radio se dibuja mas tenue cuanto mas corto: un radio corto
            # es una banda que en esta vista apunta casi de frente a la
            # pantalla, y verlo apagarse al girar es justamente la
            # informacion -esa banda ahora no esta separando nada-.
            color = QtGui.QColor(COLOR_RADIO)
            color.setAlpha(int(70 + 185 * (largos[i] / mayor if mayor else 0)))
            pintor.setPen(QtGui.QPen(color, 1))
            pintor.drawLine(c, punta)
            if i not in rotulados:
                continue
            sitio = punta + QtCore.QPointF(3, -3)
            if any(abs(sitio.x() - x) < 26 and abs(sitio.y() - y) < 11
                   for x, y in ocupados):
                continue
            ocupados.append((sitio.x(), sitio.y()))
            pintor.drawText(sitio, self._rotulo(i))

    def _rotulo(self, i):
        etiquetas = getattr(self.nube, "rotulos", None)
        if etiquetas and i < len(etiquetas):
            return etiquetas[i]
        return str(self.nube.bandas[i]) if i < len(self.nube.bandas) else ""

    def _dibujar_lazo(self, pintor):
        if len(self._lazo) < 2:
            return
        pintor.setPen(QtGui.QPen(COLOR_LAZO, 1,
                                 enum(Qt, "PenStyle", "DashLine")))
        pintor.drawPolyline(QtGui.QPolygonF(
            [QtCore.QPointF(x, y) for x, y in self._lazo]))

    # -- raton --------------------------------------------------------------
    def _punto(self, evento):
        p = evento.pos() if hasattr(evento, "pos") else evento.position()
        return float(p.x()), float(p.y())

    def mousePressEvent(self, evento):
        x, y = self._punto(evento)
        if self.modo == MODO_LAZO:
            self._lazo = [(x, y)]
        else:
            self._arrastre = (x, y)

    def mouseMoveEvent(self, evento):
        x, y = self._punto(evento)
        if self.modo == MODO_LAZO and self._lazo:
            self._lazo.append((x, y))
            self.update()
            return
        if self._arrastre is None or self.tour is None:
            return
        x0, y0 = self._arrastre
        self._arrastre = (x, y)
        # Un ancho de ventana entero da media vuelta: es el ritmo con el que
        # arrastrar se siente como empujar la nube y no como un tirador.
        self.tour.girar_a_mano((x - x0) / max(1.0, self.width()) * np.pi,
                               (y - y0) / max(1.0, self.height()) * np.pi)
        self._proyectados = None
        self.update()
        self.vistaCambiada.emit()

    def mouseReleaseEvent(self, evento):
        self._arrastre = None
        if self.modo != MODO_LAZO or len(self._lazo) < 3:
            self._lazo = []
            self.update()
            return
        from ..core.ndim import puntos_en_poligono
        dentro = puntos_en_poligono(self._proyeccion(), self._lazo)
        self._lazo = []
        indices = np.flatnonzero(dentro)
        self.resaltar(indices)
        self.seleccionHecha.emit(indices)

    def wheelEvent(self, evento):
        delta = evento.angleDelta().y() if hasattr(evento, "angleDelta") else 0
        if not delta:
            return
        self.zoom *= 1.15 if delta > 0 else 1.0 / 1.15
        self.zoom = float(np.clip(self.zoom, 0.15, 12.0))
        self._proyectados = None
        self.update()
        self.vistaCambiada.emit()


__all__ = ["VistaND", "MODO_GIRAR", "MODO_LAZO"]
