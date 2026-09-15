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
"""El cubo hiperespectral dibujado como cubo: la imagen y sus dos costados.

Es la vista de referencia de todo el mundo en hiperespectral -la que se ve en
ENVI- y aca no es un adorno: las dos caras laterales son exactamente lo que
``get_transect`` ya devuelve.

    cara superior  = get_transect("y", fila)     -> (x, banda)
    cara derecha   = get_transect("x", columna)  -> (y, banda)

Es decir, el cubo de ENVI es estatico -las caras son el borde de la escena- y
este no: las caras son el corte que pasa por la cruz. Mover la cruz recorre el
cubo de verdad. Esa es la diferencia entre mirar un cubo y explorarlo.

No hay OpenGL ni ninguna biblioteca 3D. La proyeccion es oblicua y se dibuja
con QPainter aplicando una transformacion afin a cada cara. Alcanza de sobra
para tres caras, y mantiene la regla del proyecto: nada obligatorio mas alla
de lo que trae QGIS.
"""

import numpy as np

from ..core.colormap import PALETA_POR_DEFECTO, colorear
from ..core.rgb import limites
from .qt import QtCore, QtGui, QtWidgets, Qt, enum, pyqtSignal

ANTIALIAS = enum(QtGui.QPainter, "RenderHint", "Antialiasing")
INTERPOLAR = enum(QtGui.QPainter, "RenderHint", "SmoothPixmapTransform")
FORMATO_RGB = enum(QtGui.QImage, "Format", "Format_RGB888")
SIN_PINCEL = enum(Qt, "BrushStyle", "NoBrush")
LINEA_PUNTEADA = enum(Qt, "PenStyle", "DashLine")

#: Profundidad del cubo como fraccion del ancho de la cara frontal, y cuanto
#: de esa profundidad sube en pantalla. 0.55 da el escorzo habitual.
PROFUNDIDAD = 0.38
INCLINACION = 0.55

#: Lado maximo de las caras antes de dibujarlas. Una escena de 5000 columnas
#: no necesita 5000 pixeles de cara para verse: se decima por salto, que
#: ademas conserva los espectros reales en vez de promediar vecinos.
LADO_MAXIMO = 1400

#: Cuantas filas se leen para fijar el rango de color del cubo. Cinco cortes
#: repartidos dan un realce estable sin leer la escena entera al abrir.
MUESTRAS_DE_RANGO = 5

COLOR_CRUZ = QtGui.QColor(255, 60, 40)
COLOR_ARISTA = QtGui.QColor(225, 225, 235)
COLOR_MARCADORES = ("#ff4136", "#2ecc40", "#0074d9")   # R, G, B
COLOR_FONDO = QtGui.QColor(16, 16, 20)


def a_qimage(arreglo):
    """Convierte ``(alto, ancho, 3)`` uint8 en QImage.

    El ``.copy()` final no sobra: QImage no toma posesion del buffer de numpy,
    y sin la copia el arreglo se libera mientras Qt todavia lo esta dibujando.
    Es una caida que aparece mucho despues y lejos de aca.
    """
    datos = np.ascontiguousarray(arreglo, dtype=np.uint8)
    alto, ancho = datos.shape[:2]
    imagen = QtGui.QImage(datos.data, ancho, alto, 3 * ancho, FORMATO_RGB)
    return imagen.copy()


def _decimar(plano, maximo=LADO_MAXIMO):
    """Submuestrea por salto para dibujar. Devuelve (plano, paso)."""
    paso = max(1, int(np.ceil(max(plano.shape) / float(maximo))))
    return (plano if paso == 1 else plano[::paso, ::paso]), paso


class CubeView(QtWidgets.QWidget):
    """Las tres caras del cubo, enlazadas a la posicion de la cruz."""

    #: La cruz se movio, arrastrando (x, y). Sale de forma continua.
    posicionMovida = pyqtSignal(int, int)
    #: Se solto el boton: este es el pixel elegido.
    pixelElegido = pyqtSignal(int, int)
    #: Se hizo clic sobre una cara espectral, a esta longitud de onda.
    longitudElegida = pyqtSignal(float)

    def __init__(self, parent=None):
        super(CubeView, self).__init__(parent)
        # Un minimo chico a proposito: acoplado al costado el panel es
        # angosto, y un minimo grande no agranda el cubo -hace que la fila de
        # controles de abajo se dibuje encima de el-.
        self.setMinimumSize(160, 110)
        self.setMouseTracking(False)
        self.cube = None
        self.composer = None
        self.paleta = PALETA_POR_DEFECTO
        self.x = 0
        self.y = 0
        self.banda_unica = None       # None = el frente es la composicion RGB
        self.marcadores = []          # longitudes de onda del RGB

        self._frontal = None          # QImage de la composicion
        self._superior = None         # QImage de la cara (x, banda)
        self._derecha = None          # QImage de la cara (y, banda)
        self._rango = None            # (lo, hi) del color, fijo para el cubo
        self._cuadros = {}            # nombre -> QPolygonF, para acertar clics
        self._transformadas = {}      # nombre -> QTransform de cada cara
        self._arrastrando = False

    # -- datos --------------------------------------------------------------
    def set_cube(self, cube, composer=None):
        self.cube = cube
        self.composer = composer
        self._frontal = self._superior = self._derecha = None
        self._rango = None
        if cube is not None:
            self.x = cube.samples // 2
            self.y = cube.lines // 2
            self.recalcular_rango()
            self.refrescar_frontal()
            self._recalcular_caras()
        self.update()

    def set_paleta(self, nombre):
        self.paleta = nombre
        self._recalcular_caras()
        self.refrescar_frontal()

    def set_marcadores_rgb(self, longitudes):
        """Marca sobre las caras las tres bandas que arman la imagen frontal.

        Es el vinculo que ENVI no tiene: se ve, dentro del cubo, de que
        rebanadas esta hecha la imagen que se esta mirando.
        """
        self.marcadores = [float(w) for w in longitudes
                           if w is not None and np.isfinite(w)]
        self.update()

    def set_modo_realce(self, modo):
        """El realce cambio: hay que rehacer el rango y repintar las caras."""
        if self.composer is not None:
            self.composer.modo = modo
        self.recalcular_rango()
        self._recalcular_caras()
        self.update()

    def set_banda_unica(self, indice):
        """Muestra una sola banda en el frente, o vuelve al RGB con None.

        Es la respuesta al gesto mas natural frente a un cubo: se ve una
        franja rara en el costado y uno quiere ver esa banda. En ENVI hay que
        ir a otro dialogo, elegir el numero y abrir otra ventana.
        """
        if indice is not None and self.cube is not None:
            indice = int(np.clip(indice, 0, self.cube.bands - 1))
        self.banda_unica = indice
        self.refrescar_frontal()

    def _utilizable(self):
        """True si hay un cubo y todavia se puede leer.

        El cubo lo cierra el controlador, y las senales que llegan despues
        -por ejemplo la de composicion cambiada- encuentran a esta vista
        apuntando todavia al cubo viejo. Preguntar es mas barato que
        coordinar el orden exacto de cinco senales.
        """
        return self.cube is not None and not self.cube.cerrado

    def refrescar_frontal(self):
        """Recompone la cara frontal. Se llama al cambiar R, G o B."""
        if not self._utilizable():
            self._frontal = None
            return
        if self.banda_unica is not None:
            banda, _ = self.cube.preview_band(index=self.banda_unica,
                                              max_lado=LADO_MAXIMO)
            if self._rango is None:
                self.recalcular_rango()
            lo, hi = self._rango if self._rango else (None, None)
            self._frontal = a_qimage(colorear(banda, self.paleta, lo, hi))
        elif self.composer is not None:
            rgb = self.composer.create_composite(self.cube, preview=True,
                                                 max_lado=LADO_MAXIMO)
            self._frontal = a_qimage(rgb)
        self.update()

    def set_posicion(self, x, y, recalcular=True):
        """Mueve la cruz. Es lo que hace que las caras recorran el cubo."""
        if not self._utilizable():
            return
        x = int(np.clip(x, 0, self.cube.samples - 1))
        y = int(np.clip(y, 0, self.cube.lines - 1))
        if (x, y) == (self.x, self.y) and self._superior is not None:
            return
        self.x, self.y = x, y
        if recalcular:
            self._recalcular_caras()
        self.update()

    def recalcular_rango(self):
        """Fija el rango de color del cubo, una sola vez.

        Dos razones para no calcularlo en cada movimiento de la cruz:

        Primero, el color tiene que querer decir lo mismo siempre. Si el rango
        saliera de las dos caras actuales, arrastrar la cruz recolorearia la
        cara superior aunque su dato no hubiera cambiado -porque cambio la
        otra-, y el usuario veria variar una imagen que no vario.

        Segundo, y por lo mismo, las dos caras comparten escala: un valor sale
        del mismo color en las dos, que es lo unico que permite compararlas.

        La muestra son unas pocas filas repartidas por la escena en vez del
        cubo entero: alcanza para un realce estable y no obliga a leer
        cientos de megabytes al abrir.
        """
        if not self._utilizable():
            self._rango = None
            return
        modo = self.composer.modo if self.composer is not None else "percentil"
        cuantas = min(MUESTRAS_DE_RANGO, self.cube.lines)
        filas = np.linspace(0, self.cube.lines - 1, cuantas).astype(int)
        try:
            muestra = np.concatenate(
                [self.cube.get_transect("y", int(f)).ravel() for f in filas])
        except Exception:
            self._rango = None
            return
        self._rango = limites(muestra, modo)

    def _recalcular_caras(self):
        """Extrae los dos transectos que pasan por la cruz y los pinta."""
        if not self._utilizable():
            self._superior = self._derecha = None
            return
        try:
            arriba = self.cube.get_transect("y", self.y)      # (x, banda)
            derecha = self.cube.get_transect("x", self.x)     # (y, banda)
        except Exception:
            self._superior = self._derecha = None
            return

        if self._rango is None:
            self.recalcular_rango()
        lo, hi = self._rango if self._rango else (None, None)

        arriba, _ = _decimar(arriba)
        derecha, _ = _decimar(derecha)
        # Transpuestas: la imagen necesita la banda en las filas.
        self._superior = a_qimage(colorear(arriba.T, self.paleta, lo, hi))
        self._derecha = a_qimage(colorear(derecha.T, self.paleta, lo, hi))

    # -- geometria ----------------------------------------------------------
    def _geometria(self):
        """Devuelve (A, ancho, alto, d) de la cara frontal, o None.

        A es la esquina superior izquierda del frente; d es el vector de
        profundidad, hacia arriba y a la derecha. Todo lo demas se deduce de
        estos cuatro valores, aca y en el pintado.
        """
        if not self._utilizable():
            return None
        margen = 10.0
        disponible_w = max(1.0, self.width() - 2 * margen)
        disponible_h = max(1.0, self.height() - 2 * margen)
        cols = float(self.cube.samples)
        filas = float(self.cube.lines)

        # El contenido mide (s + PROFUNDIDAD*s) de ancho y
        # (l + INCLINACION*PROFUNDIDAD*s) de alto, en unidades de pixel de
        # escena. Se elige la escala que hace entrar el conjunto.
        ancho_total = cols * (1.0 + PROFUNDIDAD)
        alto_total = filas + INCLINACION * PROFUNDIDAD * cols
        escala = min(disponible_w / ancho_total, disponible_h / alto_total)

        ancho, alto = cols * escala, filas * escala
        profundo = PROFUNDIDAD * ancho
        d = QtCore.QPointF(profundo, -INCLINACION * profundo)
        # El cubo se centra en el hueco que sobra: cuando el widget es mas
        # ancho que alto -un panel acoplado abajo- la escala la fija la altura
        # y sin centrar el cubo queda pegado a la izquierda con medio panel
        # vacio al lado.
        sobra_x = disponible_w - (ancho + d.x())
        sobra_y = disponible_h - (alto - d.y())
        origen = QtCore.QPointF(margen + max(0.0, sobra_x) / 2.0,
                                margen + max(0.0, sobra_y) / 2.0 - d.y())
        return origen, ancho, alto, d

    def _transformacion(self, origen, borde, d, ancho_fuente, alto_fuente):
        """Mapea una imagen fuente al paralelogramo (origen, borde, d).

        ``borde`` es el vector del lado que se apoya en el frente y ``d`` el
        de la profundidad. QTransform lleva (col, fila) a
        (m11*col + m21*fila + dx, m12*col + m22*fila + dy), asi que basta con
        poner cada vector en su columna.
        """
        return QtGui.QTransform(
            borde.x() / ancho_fuente, borde.y() / ancho_fuente,
            d.x() / alto_fuente, d.y() / alto_fuente,
            origen.x(), origen.y())

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, evento):
        p = QtGui.QPainter(self)
        p.setRenderHint(ANTIALIAS, True)
        p.setRenderHint(INTERPOLAR, True)
        p.fillRect(self.rect(), COLOR_FONDO)

        geometria = self._geometria()
        if geometria is None or self._frontal is None:
            p.setPen(QtGui.QColor(190, 190, 190))
            p.drawText(self.rect(), enum(Qt, "AlignmentFlag", "AlignCenter"),
                       "Abra un cubo para verlo")
            p.end()
            return

        origen, ancho, alto, d = geometria
        A = origen
        B = QtCore.QPointF(A.x() + ancho, A.y())
        C = QtCore.QPointF(A.x() + ancho, A.y() + alto)
        self._cuadros, self._transformadas = {}, {}

        self._pintar_cara(p, "superior", self._superior, A,
                          QtCore.QPointF(ancho, 0.0), d)
        self._pintar_cara(p, "derecha", self._derecha, B,
                          QtCore.QPointF(0.0, alto), d)
        self._pintar_frontal(p, A, ancho, alto)

        self._pintar_aristas(p, A, B, C, d)
        self._pintar_marcadores(p, ancho, alto, d)
        self._pintar_cruz(p, A, B, ancho, alto, d)
        p.end()

    def _pintar_cara(self, p, nombre, imagen, origen, borde, d):
        if imagen is None:
            return
        t = self._transformacion(origen, borde, d,
                                 imagen.width(), imagen.height())
        p.save()
        p.setTransform(t)
        p.drawImage(0, 0, imagen)
        p.restore()
        self._transformadas[nombre] = t
        self._cuadros[nombre] = QtGui.QPolygonF([
            origen,
            QtCore.QPointF(origen.x() + borde.x(), origen.y() + borde.y()),
            QtCore.QPointF(origen.x() + borde.x() + d.x(),
                           origen.y() + borde.y() + d.y()),
            QtCore.QPointF(origen.x() + d.x(), origen.y() + d.y())])

    def _pintar_frontal(self, p, A, ancho, alto):
        destino = QtCore.QRectF(A.x(), A.y(), ancho, alto)
        p.drawImage(destino, self._frontal)
        self._cuadros["frontal"] = QtGui.QPolygonF(destino)

    def _pintar_aristas(self, p, A, B, C, d):
        p.setPen(QtGui.QPen(COLOR_ARISTA, 1))
        p.setBrush(SIN_PINCEL)
        atras_A = QtCore.QPointF(A.x() + d.x(), A.y() + d.y())
        atras_B = QtCore.QPointF(B.x() + d.x(), B.y() + d.y())
        atras_C = QtCore.QPointF(C.x() + d.x(), C.y() + d.y())
        for desde, hasta in ((A, B), (B, C), (A, atras_A), (B, atras_B),
                             (C, atras_C), (atras_A, atras_B),
                             (atras_B, atras_C)):
            p.drawLine(desde, hasta)

    def _pintar_marcadores(self, p, ancho, alto, d):
        """Las tres bandas del RGB, dibujadas dentro de las caras."""
        if not self.marcadores or self.cube is None:
            return
        for longitud, color in zip(self.marcadores, COLOR_MARCADORES):
            fraccion = self._fraccion_de_banda(longitud)
            if fraccion is None:
                continue
            for nombre, borde in (("superior", QtCore.QPointF(ancho, 0.0)),
                                  ("derecha", QtCore.QPointF(0.0, alto))):
                if nombre not in self._cuadros:
                    continue
                base = self._cuadros[nombre].at(0)
                desde = QtCore.QPointF(base.x() + d.x() * fraccion,
                                       base.y() + d.y() * fraccion)
                hasta = QtCore.QPointF(desde.x() + borde.x(),
                                       desde.y() + borde.y())
                # Una linea oscura debajo: el arcoiris tiene rojo, verde y
                # azul saturados, y sobre ellos un marcador del mismo color
                # desaparece justo donde mas importa.
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 170), 3))
                p.drawLine(desde, hasta)
                p.setPen(QtGui.QPen(QtGui.QColor(color), 1.6,
                                    LINEA_PUNTEADA))
                p.drawLine(desde, hasta)

    def _fraccion_de_banda(self, longitud):
        indice = self.cube.band_index(longitud)
        if self.cube.bands < 2:
            return 0.0
        return indice / float(self.cube.bands - 1)

    def _pintar_cruz(self, p, A, B, ancho, alto, d):
        """La cruz sobre el frente, prolongada hacia el fondo de cada cara.

        Las prolongaciones importan: son las que dicen que la cara superior es
        el corte que pasa por esta fila y no el borde de la escena.
        """
        cols, filas = self.cube.samples, self.cube.lines
        px = A.x() + (self.x + 0.5) / cols * ancho
        py = A.y() + (self.y + 0.5) / filas * alto

        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 3))
        self._trazar_cruz(p, A, B, px, py, alto, d)
        p.setPen(QtGui.QPen(COLOR_CRUZ, 1.4))
        self._trazar_cruz(p, A, B, px, py, alto, d)

    def _trazar_cruz(self, p, A, B, px, py, alto, d):
        """Los cuatro segmentos de la cruz, para poder trazarlos dos veces:
        una oscura debajo y otra roja encima."""
        p.drawLine(QtCore.QPointF(px, A.y()),
                   QtCore.QPointF(px, A.y() + alto))
        p.drawLine(QtCore.QPointF(A.x(), py), QtCore.QPointF(B.x(), py))
        # hacia el fondo de la cara superior, en la columna actual
        p.drawLine(QtCore.QPointF(px, A.y()),
                   QtCore.QPointF(px + d.x(), A.y() + d.y()))
        # hacia el fondo de la cara derecha, en la fila actual
        p.drawLine(QtCore.QPointF(B.x(), py),
                   QtCore.QPointF(B.x() + d.x(), py + d.y()))

    # -- interaccion --------------------------------------------------------
    def _posicion(self, evento):
        pos = evento.position() if hasattr(evento, "position") else evento.pos()
        return QtCore.QPointF(pos.x(), pos.y())

    def mousePressEvent(self, evento):
        if self.cube is None:
            return
        punto = self._posicion(evento)
        if self._en_cara("frontal", punto):
            self._arrastrando = True
            self._mover_a(punto)
            return
        for nombre in ("superior", "derecha"):
            if self._en_cara(nombre, punto):
                self._elegir_longitud(nombre, punto)
                return

    def mouseMoveEvent(self, evento):
        if self._arrastrando:
            self._mover_a(self._posicion(evento))

    def mouseReleaseEvent(self, evento):
        if self._arrastrando:
            self._arrastrando = False
            self.pixelElegido.emit(self.x, self.y)

    def mouseDoubleClickEvent(self, evento):
        """Doble clic en el frente: vuelve a la composicion RGB.

        Hace falta una salida del modo de banda unica que no obligue a buscar
        un boton, porque a ese modo se entra de un solo clic.
        """
        if self._en_cara("frontal", self._posicion(evento)):
            self.set_banda_unica(None)

    def _en_cara(self, nombre, punto):
        cuadro = self._cuadros.get(nombre)
        return cuadro is not None and cuadro.containsPoint(
            punto, enum(Qt, "FillRule", "OddEvenFill"))

    def _mover_a(self, punto):
        geometria = self._geometria()
        if geometria is None:
            return
        A, ancho, alto, _ = geometria
        x = int((punto.x() - A.x()) / ancho * self.cube.samples)
        y = int((punto.y() - A.y()) / alto * self.cube.lines)
        antes = (self.x, self.y)
        self.set_posicion(x, y)
        if (self.x, self.y) != antes:
            self.posicionMovida.emit(self.x, self.y)

    def _elegir_longitud(self, nombre, punto):
        """Un clic en una cara espectral salta a esa longitud de onda.

        Es lo que vuelve navegable el eje que en ENVI solo se mira: se ve una
        franja interesante en el costado del cubo y se va a ella.
        """
        t = self._transformadas.get(nombre)
        if t is None or self.cube is None:
            return
        inversa, ok = t.inverted()
        if not ok:
            return
        fuente = inversa.map(punto)
        imagen = self._superior if nombre == "superior" else self._derecha
        if imagen is None or imagen.height() < 1:
            return
        fraccion = np.clip(fuente.y() / float(imagen.height()), 0.0, 1.0)
        indice = int(round(fraccion * (self.cube.bands - 1)))
        self.set_banda_unica(indice)
        self.longitudElegida.emit(float(self.cube.wavelengths[indice]))
