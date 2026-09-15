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

from ..core.colormap import PALETA_POR_DEFECTO, colorear, tabla
from ..core.rgb import limites
from .qt import QtCore, QtGui, QtWidgets, Qt, enum, pyqtSignal

BOTON_IZQUIERDO = enum(Qt, "MouseButton", "LeftButton")
BOTON_DERECHO = enum(Qt, "MouseButton", "RightButton")
BOTON_CENTRAL = enum(Qt, "MouseButton", "MiddleButton")
CURSOR_MANO = enum(Qt, "CursorShape", "OpenHandCursor")
CURSOR_AGARRE = enum(Qt, "CursorShape", "ClosedHandCursor")
CURSOR_CRUZ = enum(Qt, "CursorShape", "CrossCursor")
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

#: Modos de navegacion. Viven aca y no en la herramienta de mapa porque esta
#: vista no depende de QGIS y la herramienta si: asi los dos usan los mismos.
MODO_PIXEL, MODO_X, MODO_Y, MODO_AREA, MODO_MULTI = (
    "pixel", "x", "y", "area", "multi")
#: Herramientas de navegacion. Separadas de las de muestreo porque no miden
#: nada: solo cambian que parte se esta mirando.
MODO_PAN, MODO_ZOOM = "pan", "zoom"
MODOS_NAVEGACION = (MODO_PAN, MODO_ZOOM)

#: Ancho reservado a la derecha para la barra de color, en pixeles.
#: Ancho de la franja de la barra de color: el degradado, sus numeros y el
#: rotulo girado. Es un minimo y no un ancho fijo -ver ``_ancho_barra``-:
#: con cuentas crudas los numeros no entran en sesenta pixeles.
ANCHO_BARRA = 62
ANCHO_BARRA_MAX = 96

COLOR_CRUZ = QtGui.QColor(255, 60, 40)
COLOR_ARISTA = QtGui.QColor(225, 225, 235)
COLOR_MARCADORES = ("#ff4136", "#2ecc40", "#0074d9")   # R, G, B
COLOR_FONDO = QtGui.QColor(16, 16, 20)
COLOR_SELECCION = QtGui.QColor(255, 220, 0)
COLOR_AREA = QtGui.QColor(0, 200, 255)
COLOR_ZOOM = QtGui.QColor(255, 255, 255)
COLOR_TEXTO = QtGui.QColor(225, 225, 235)


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


def _corto(valor):
    """Un numero corto para la barra: reflectancia con tres decimales,
    cuentas con notacion cientifica.

    El exponente va sin signo ni ceros de relleno -``1.8e4`` y no
    ``1.8e+04``-. No es cosmetica: la franja de la barra es angosta y con la
    forma larga el ultimo digito se cortaba, dejando ``1.8e``, que no es un
    numero.
    """
    v = float(valor)
    if abs(v) >= 1000 or (v != 0 and abs(v) < 0.001):
        mantisa, exponente = ("%.1e" % v).split("e")
        return "%se%d" % (mantisa, int(exponente))
    if abs(v) >= 10:
        return "%.0f" % v
    return ("%.3f" % v).rstrip("0").rstrip(".")


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
    #: Cambio el rectangulo visible. None cuando se ve la escena entera.
    vistaCambiada = pyqtSignal(object)
    #: Se movio la linea de muestreo: (eje, posicion).
    transectoPedido = pyqtSignal(str, int)
    #: Se arrastro un rectangulo sobre la imagen: (x0, y0, x1, y1).
    areaElegida = pyqtSignal(int, int, int, int)
    #: Cambio el conjunto de pixeles sueltos elegidos: [(x, y), ...].
    pixelesElegidos = pyqtSignal(object)

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
        #: Rectangulo visible (x0, y0, x1, y1), extremos incluidos. None es
        #: la escena entera.
        self.vista = None
        self.banda_unica = None       # None = el frente es la composicion RGB
        self.marcadores = []          # longitudes de onda del RGB
        self.modo = MODO_PIXEL
        self.seleccion = []           # pixeles sueltos, en modo multi
        self._area = None             # rectangulo en curso, en modo area
        self._zoom = None             # rectangulo de zoom en curso
        self._zoom_desde = None
        self._pan_desde = None        # punto de pantalla donde empezo el pan

        self._frontal = None          # QImage de la composicion
        self._superior = None         # QImage de la cara (x, banda)
        self._derecha = None          # QImage de la cara (y, banda)
        self._rango = None            # (lo, hi) del color, fijo para el cubo
        self.unidad = "reflectancia"  # rotulo de la barra de color
        self._cuadros = {}            # nombre -> QPolygonF, para acertar clics
        self._transformadas = {}      # nombre -> QTransform de cada cara
        self._arrastrando = False

    # -- datos --------------------------------------------------------------
    def set_cube(self, cube, composer=None):
        self.cube = cube
        self.composer = composer
        self._frontal = self._superior = self._derecha = None
        self._rango = None
        self.vista = None
        if cube is not None:
            self.x = cube.samples // 2
            self.y = cube.lines // 2
            self.recalcular_rango()
            self.refrescar_frontal()
            self._recalcular_caras()
        self.update()

    # -- zoom ---------------------------------------------------------------
    def ventana(self):
        """(x0, y0, x1, y1) visible, recortado a la escena. Extremos dentro."""
        if self.cube is None:
            return (0, 0, 0, 0)
        if self.vista is None:
            return (0, 0, self.cube.samples - 1, self.cube.lines - 1)
        x0, y0, x1, y1 = self.vista
        return (max(0, x0), max(0, y0),
                min(self.cube.samples - 1, x1), min(self.cube.lines - 1, y1))

    def ancho_visible(self):
        x0, _, x1, _ = self.ventana()
        return x1 - x0 + 1

    def alto_visible(self):
        _, y0, _, y1 = self.ventana()
        return y1 - y0 + 1

    def set_vista(self, rect):
        """Acerca a un rectangulo de la escena, o vuelve a todo con None.

        Rehace tambien el rango de color, y es lo que el usuario esta
        buscando al acercarse: una escena en geometria de sensor viene rodeada
        de relleno y de ceros, y con el realce calculado sobre la escena
        entera el terreno queda aplastado. Al acercarse, el realce solo ve lo
        que quedo dentro.
        """
        if self.cube is None:
            return
        if rect is not None:
            x0, y0, x1, y1 = rect
            x0, x1 = sorted((int(x0), int(x1)))
            y0, y1 = sorted((int(y0), int(y1)))
            # Menos de dos pixeles de lado no es un zoom, es un clic con
            # temblor: se ignora en vez de dejar la vista inservible.
            if x1 - x0 < 1 or y1 - y0 < 1:
                return
            rect = (max(0, x0), max(0, y0),
                    min(self.cube.samples - 1, x1),
                    min(self.cube.lines - 1, y1))
        self.vista = rect
        x0, y0, x1, y1 = self.ventana()
        self.x = int(np.clip(self.x, x0, x1))
        self.y = int(np.clip(self.y, y0, y1))
        self.recalcular_rango()
        self.refrescar_frontal()
        self._recalcular_caras()
        self.vistaCambiada.emit(self.vista)
        self.update()

    def desplazar(self, dx_pantalla, dy_pantalla):
        """Corre la vista, en pixeles de PANTALLA.

        Se convierte a pixeles de escena con la escala vigente para que la
        imagen siga al cursor exactamente: si se arrastra 40 pixeles, la
        escena se mueve 40 pixeles, este donde este el zoom. Desplazar en
        unidades de escena hace que el arrastre se sienta lento al acercarse
        y disparado al alejarse.
        """
        geometria = self._geometria()
        if geometria is None:
            return
        _, ancho, alto, _ = geometria
        if ancho <= 0 or alto <= 0:
            return
        dx = -dx_pantalla * self.ancho_visible() / float(ancho)
        dy = -dy_pantalla * self.alto_visible() / float(alto)
        x0, y0, x1, y1 = self.ventana()
        # El corrimiento se recorta antes de aplicarlo, para que la vista no
        # encoja al llegar al borde: arrastrar contra el canto deberia
        # detenerse, no ir estrechando lo que se ve.
        dx = max(-x0, min(dx, self.cube.samples - 1 - x1))
        dy = max(-y0, min(dy, self.cube.lines - 1 - y1))
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        self.set_vista((x0 + dx, y0 + dy, x1 + dx, y1 + dy))

    def acercar(self, factor, centro=None):
        """Acerca (factor < 1) o aleja (factor > 1) alrededor de un pixel."""
        if not self._utilizable():
            return
        x0, y0, x1, y1 = self.ventana()
        cx, cy = centro if centro else ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        ancho = max(2.0, (x1 - x0 + 1) * factor)
        alto = max(2.0, (y1 - y0 + 1) * factor)
        if ancho >= self.cube.samples and alto >= self.cube.lines:
            self.set_vista(None)
            return
        self.set_vista((cx - ancho / 2.0, cy - alto / 2.0,
                        cx + ancho / 2.0, cy + alto / 2.0))

    def zoom_a_los_datos(self, margen=2):
        """Encuadra lo que tiene dato, dejando fuera el relleno y los ceros.

        Es el gesto que se quiere apenas se abre una escena sin ortorectificar:
        el cubo llega dentro de un rectangulo mucho mas grande que la franja
        que el sensor recorrio, y el resto es relleno.
        """
        if not self._utilizable():
            return
        banda, paso = self.cube.preview_band(index=self.cube.bands // 2,
                                             max_lado=LADO_MAXIMO)
        util = np.isfinite(banda) & (banda != 0)
        if not util.any():
            self.set_vista(None)
            return
        filas = np.flatnonzero(util.any(axis=1))
        columnas = np.flatnonzero(util.any(axis=0))
        self.set_vista((columnas[0] * paso - margen, filas[0] * paso - margen,
                        columnas[-1] * paso + margen,
                        filas[-1] * paso + margen))

    def set_modo(self, modo):
        """Cambia que hace el boton izquierdo sobre la cara frontal."""
        self.modo = modo
        self._area = None
        if modo != MODO_MULTI:
            self.limpiar_seleccion()
        self.setCursor(QtGui.QCursor(
            CURSOR_MANO if modo == MODO_PAN else CURSOR_CRUZ))
        self.update()

    def limpiar_seleccion(self):
        if self.seleccion:
            self.seleccion = []
            self.pixelesElegidos.emit([])
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
        x0, y0, x1, y1 = self.ventana()
        if self.banda_unica is not None:
            banda, paso = self.cube.preview_band(index=self.banda_unica,
                                                 max_lado=LADO_MAXIMO)
            banda = banda[y0 // paso:y1 // paso + 1,
                          x0 // paso:x1 // paso + 1]
            if self._rango is None:
                self.recalcular_rango()
            lo, hi = self._rango if self._rango else (None, None)
            self._frontal = a_qimage(colorear(banda, self.paleta, lo, hi))
        elif self.composer is not None:
            rgb = self.composer.create_composite(
                self.cube, preview=True, max_lado=LADO_MAXIMO,
                ventana=(x0, y0, x1, y1))
            self._frontal = a_qimage(rgb)
        self.update()

    def set_posicion(self, x, y, recalcular=True):
        """Mueve la cruz. Es lo que hace que las caras recorran el cubo."""
        if not self._utilizable():
            return
        vx0, vy0, vx1, vy1 = self.ventana()
        x = int(np.clip(x, vx0, vx1))
        y = int(np.clip(y, vy0, vy1))
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
        x0, y0, x1, y1 = self.ventana()
        cuantas = min(MUESTRAS_DE_RANGO, y1 - y0 + 1)
        filas = np.linspace(y0, y1, cuantas).astype(int)
        try:
            muestra = np.concatenate(
                [self.cube.get_transect("y", int(f))[x0:x1 + 1].ravel()
                 for f in filas])
        except Exception:
            self._rango = None
            return
        self._rango = limites(muestra, modo)

    def _recalcular_caras(self):
        """Extrae los dos transectos que pasan por la cruz y los pinta."""
        if not self._utilizable():
            self._superior = self._derecha = None
            return
        x0, y0, x1, y1 = self.ventana()
        try:
            # Recortadas a la ventana: si no, al acercarse las caras seguirian
            # mostrando toda la fila y la columna, y no coincidirian con el
            # frente.
            arriba = self.cube.get_transect("y", self.y)[x0:x1 + 1]
            derecha = self.cube.get_transect("x", self.x)[y0:y1 + 1]
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
        reservado = self._ancho_barra() if self._rango else 0.0
        disponible_w = max(1.0, self.width() - 2 * margen - reservado)
        disponible_h = max(1.0, self.height() - 2 * margen)
        cols = float(self.ancho_visible())
        filas = float(self.alto_visible())

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
        self._pintar_seleccion(p, A, ancho, alto)
        self._pintar_cruz(p, A, B, ancho, alto, d)
        self._pintar_rectangulos(p)
        self._pintar_barra_color(p)
        p.end()

    def _ancho_barra(self):
        """Cuanto reserva la barra de color, segun lo que midan sus numeros.

        Era una constante. Con reflectancia -0 a 1- sesenta pixeles sobran,
        pero un cubo en cuentas crudas rotula ``1.8e4`` y ahi no entra: el
        texto se cortaba y la barra quedaba mintiendo. Se mide con la misma
        fuente con que se va a dibujar y se reserva lo que haga falta.
        """
        if not self._rango:
            return 0.0
        lo, hi = self._rango
        fuente = QtGui.QFont(self.font())
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 1.5))
        metrica = QtGui.QFontMetricsF(fuente)
        # horizontalAdvance es lo que hay en Qt6; width se quito ahi y es lo
        # unico que existe en los Qt5 mas viejos que QGIS todavia arrastra.
        medir = getattr(metrica, "horizontalAdvance", None) or metrica.width
        ancho_texto = max(medir(_corto(v))
                          for v in (lo, hi, (lo + hi) / 2.0))
        # 8 de sangria + 14 del degradado + 5 de separacion + el numero + 4.
        return min(ANCHO_BARRA_MAX, max(ANCHO_BARRA, 31.0 + ancho_texto))

    def _pintar_barra_color(self, p):
        """La escala del cubo, en las unidades del dato.

        Sin ella el arcoiris de las caras es decorativo: se ve que una zona
        es distinta de otra y no cuanto. Los extremos son los mismos que usa
        el coloreado, asi que lo que dice la barra es lo que se esta viendo.
        """
        if not self._rango:
            return
        lo, hi = self._rango
        alto = max(40.0, self.height() - 60.0)
        arriba = (self.height() - alto) / 2.0
        izquierda = self.width() - self._ancho_barra() + 8.0
        ancho = 14.0

        # El degradado se arma con la misma tabla que pinta las caras.
        lut = tabla(self.paleta)
        gradiente = QtGui.QLinearGradient(0, arriba + alto, 0, arriba)
        for i in range(0, lut.shape[0], 8):
            t = i / float(lut.shape[0] - 1)
            gradiente.setColorAt(t, QtGui.QColor(*[int(v) for v in lut[i]]))
        gradiente.setColorAt(1.0, QtGui.QColor(*[int(v) for v in lut[-1]]))

        caja = QtCore.QRectF(izquierda, arriba, ancho, alto)
        p.setPen(QtGui.QPen(COLOR_ARISTA, 1))
        p.setBrush(QtGui.QBrush(gradiente))
        p.drawRect(caja)
        p.setBrush(SIN_PINCEL)

        fuente = p.font()
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 1.5))
        p.setFont(fuente)
        p.setPen(COLOR_TEXTO)
        izq = enum(Qt, "AlignmentFlag", "AlignLeft")
        vcentro = enum(Qt, "AlignmentFlag", "AlignVCenter")
        for t, valor in ((0.0, hi), (0.5, (lo + hi) / 2.0), (1.0, lo)):
            y = arriba + t * alto
            p.drawLine(QtCore.QPointF(izquierda + ancho, y),
                       QtCore.QPointF(izquierda + ancho + 3, y))
            # El ancho se mide hasta el borde real del widget: calculado
            # desde ANCHO_BARRA se pasaba un pixel y cortaba el ultimo digito.
            p.drawText(QtCore.QRectF(
                izquierda + ancho + 5, y - 7,
                max(10.0, self.width() - (izquierda + ancho + 5) - 4), 14),
                izq | vcentro, _corto(valor))
        # El rotulo va girado, a la izquierda de la barra. Horizontal no
        # entra: la franja mide sesenta pixeles y ahi ya estan los numeros,
        # asi que "reflectancia" quedaba en "refle...". De lado hay todo el
        # alto de la barra para escribirlo entero.
        p.save()
        p.translate(izquierda - 4, arriba + alto / 2.0)
        p.rotate(-90)
        p.drawText(QtCore.QRectF(-alto / 2.0, -14, alto, 14),
                   enum(Qt, "AlignmentFlag", "AlignCenter"),
                   self.unidad or "valor")
        p.restore()

    def _pintar_seleccion(self, p, A, ancho, alto):
        """Los pixeles sueltos ya elegidos, en modo multiple."""
        if not self.seleccion:
            return
        vx0, vy0, vx1, vy1 = self.ventana()
        cols, filas = self.ancho_visible(), self.alto_visible()
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 170), 3))
        p.setBrush(COLOR_SELECCION)
        for x, y in self.seleccion:
            if not (vx0 <= x <= vx1 and vy0 <= y <= vy1):
                continue
            px = A.x() + (x - vx0 + 0.5) / cols * ancho
            py = A.y() + (y - vy0 + 0.5) / filas * alto
            p.drawEllipse(QtCore.QPointF(px, py), 3.2, 3.2)
        p.setBrush(SIN_PINCEL)

    def _pintar_rectangulos(self, p):
        """El area o el zoom que se estan arrastrando ahora."""
        for rect, color, punteado in ((self._area, COLOR_AREA, False),
                                      (self._zoom, COLOR_ZOOM, True)):
            if rect is None:
                continue
            p.setPen(QtGui.QPen(color, 1.4,
                                LINEA_PUNTEADA if punteado else
                                enum(Qt, "PenStyle", "SolidLine")))
            relleno = QtGui.QColor(color)
            relleno.setAlpha(40)
            p.setBrush(relleno)
            p.drawRect(self._rect_pantalla(rect))
        p.setBrush(SIN_PINCEL)

    def _rect_pantalla(self, rect):
        """Un rectangulo en pixeles de escena, llevado a la pantalla."""
        geometria = self._geometria()
        if geometria is None:
            return QtCore.QRectF()
        A, ancho, alto, _ = geometria
        vx0, vy0, _, _ = self.ventana()
        cols, filas = self.ancho_visible(), self.alto_visible()
        x0, y0, x1, y1 = rect
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        izq = A.x() + (x0 - vx0) / float(cols) * ancho
        der = A.x() + (x1 - vx0 + 1) / float(cols) * ancho
        sup = A.y() + (y0 - vy0) / float(filas) * alto
        inf = A.y() + (y1 - vy0 + 1) / float(filas) * alto
        return QtCore.QRectF(izq, sup, max(1.0, der - izq),
                             max(1.0, inf - sup))

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
        vx0, vy0, _, _ = self.ventana()
        cols, filas = self.ancho_visible(), self.alto_visible()
        px = A.x() + (self.x - vx0 + 0.5) / cols * ancho
        py = A.y() + (self.y - vy0 + 0.5) / filas * alto

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

    def _pixel_en(self, punto):
        """Punto de pantalla -> (x, y) de la escena, o None si cae fuera."""
        geometria = self._geometria()
        if geometria is None or not self._en_cara("frontal", punto):
            return None
        A, ancho, alto, _ = geometria
        vx0, vy0, vx1, vy1 = self.ventana()
        x = vx0 + int((punto.x() - A.x()) / ancho * self.ancho_visible())
        y = vy0 + int((punto.y() - A.y()) / alto * self.alto_visible())
        return (int(np.clip(x, vx0, vx1)), int(np.clip(y, vy0, vy1)))

    def mousePressEvent(self, evento):
        if not self._utilizable():
            return
        punto = self._posicion(evento)
        boton = evento.button()

        # El boton central desplaza siempre, sin importar la herramienta. Es
        # el gesto que ya tiene todo el mundo en la mano; la herramienta Pan
        # existe para los trackpads que no tienen boton central.
        if boton == BOTON_CENTRAL or (boton == BOTON_IZQUIERDO
                                      and self.modo == MODO_PAN):
            self._pan_desde = punto
            self.setCursor(QtGui.QCursor(CURSOR_AGARRE))
            return

        if boton == BOTON_DERECHO:
            # Alejar del todo. Es el unico gesto del boton derecho: antes
            # arrastraba un rectangulo de zoom y se sentia raro, porque el
            # boton derecho no arrastra en ninguna otra parte de QGIS.
            self.set_vista(None)
            return
        if boton != BOTON_IZQUIERDO:
            return

        pixel = self._pixel_en(punto)
        if pixel is not None:
            if self.modo == MODO_ZOOM:
                self._zoom = pixel + pixel
                self._zoom_desde = pixel
                return
            self._empezar_gesto(pixel)
            return
        for nombre in ("superior", "derecha"):
            if self._en_cara(nombre, punto):
                self._elegir_longitud(nombre, punto)
                return

    def _empezar_gesto(self, pixel):
        x, y = pixel
        if self.modo == MODO_MULTI:
            # Cada clic suma un pixel. Un solo espectro dice poco de una
            # cubierta: lo que hace falta para conocer su variabilidad es un
            # conjunto.
            self.seleccion.append((x, y))
            self.pixelesElegidos.emit(list(self.seleccion))
            self.update()
            return
        if self.modo == MODO_AREA:
            self._area = (x, y, x, y)
            self._arrastrando = True
            self.update()
            return
        self._arrastrando = True
        self._mover_a_pixel(x, y)

    def mouseMoveEvent(self, evento):
        punto = self._posicion(evento)
        if self._pan_desde is not None:
            self.desplazar(punto.x() - self._pan_desde.x(),
                           punto.y() - self._pan_desde.y())
            self._pan_desde = punto
            return
        if self._zoom is not None and self._zoom_desde is not None:
            pixel = self._pixel_en(punto)
            if pixel is not None:
                self._zoom = self._zoom_desde + pixel
                self.update()
            return
        if not self._arrastrando:
            return
        pixel = self._pixel_en(punto)
        if pixel is None:
            return
        if self.modo == MODO_AREA and self._area is not None:
            self._area = self._area[:2] + pixel
            self.update()
            return
        self._mover_a_pixel(*pixel)

    def mouseReleaseEvent(self, evento):
        if self._pan_desde is not None:
            self._pan_desde = None
            self.setCursor(QtGui.QCursor(
                CURSOR_MANO if self.modo == MODO_PAN else CURSOR_CRUZ))
            return
        if self._zoom is not None:
            zona, self._zoom, self._zoom_desde = self._zoom, None, None
            x0, y0, x1, y1 = zona
            if abs(x1 - x0) < 2 and abs(y1 - y0) < 2:
                self.update()          # un clic suelto no acerca a nada
            else:
                self.set_vista(zona)
            return
        if not self._arrastrando:
            return
        self._arrastrando = False
        if self.modo == MODO_AREA and self._area is not None:
            x0, y0, x1, y1 = self._area
            self._area = None
            self.update()
            if abs(x1 - x0) >= 1 or abs(y1 - y0) >= 1:
                self.areaElegida.emit(x0, y0, x1, y1)
            else:
                self.pixelElegido.emit(x0, y0)
            return
        if self.modo in (MODO_X, MODO_Y):
            eje = "x" if self.modo == MODO_X else "y"
            self.transectoPedido.emit(eje, self.x if eje == "x" else self.y)
            return
        if self.modo not in MODOS_NAVEGACION:
            self.pixelElegido.emit(self.x, self.y)

    def wheelEvent(self, evento):
        """Rueda: acerca y aleja alrededor del cursor."""
        if not self._utilizable():
            return
        pixel = self._pixel_en(self._posicion(evento))
        pasos = evento.angleDelta().y() / 120.0
        if not pasos:
            return
        self.acercar(0.8 ** pasos, pixel)

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
        pixel = self._pixel_en(punto)
        if pixel is not None:
            self._mover_a_pixel(*pixel)

    def _mover_a_pixel(self, x, y):
        """Mueve la cruz respetando el modo.

        En "linea X" solo cambia la columna y en "linea Y" solo la fila. Es
        lo que hace visible la diferencia entre los modos: en X se mueve la
        vertical y cambia la cara derecha; en Y, la horizontal y la superior.
        Con los dos ejes moviendose a la vez los cuatro modos se sienten
        iguales.
        """
        if self.modo == MODO_X:
            y = self.y
        elif self.modo == MODO_Y:
            x = self.x
        antes = (self.x, self.y)
        self.set_posicion(x, y)
        if (self.x, self.y) == antes:
            return
        if self.modo == MODO_X:
            self.transectoPedido.emit("x", self.x)
        elif self.modo == MODO_Y:
            self.transectoPedido.emit("y", self.y)
        else:
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
