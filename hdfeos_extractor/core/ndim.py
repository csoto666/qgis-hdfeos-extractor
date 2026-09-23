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
"""Mirar las firmas en n dimensiones, no en dos.

Un grafico de dispersion de dos bandas es lo que casi todas las herramientas
ofrecen, y casi siempre miente por omision: dos clases que en el espectro
completo estan clarisimamente separadas pueden caer una encima de la otra en
el par de bandas que uno eligio. La separacion existe, pero no en ese plano.

La salida no es mirar mas planos de dos en dos -son cientos de pares- sino
mirar la nube entera y hacerla GIRAR. Una nube de n dimensiones proyectada
sobre un plano que rota va enseniando una sombra distinta a cada instante, y
el ojo humano separa grupos en movimiento muchisimo mejor que en una imagen
quieta. Eso es el n-D Visualizer de ENVI, y esto es lo mismo sobre las firmas
guardadas del complemento.

La pieza matematica son dos vectores ortonormales u y v en R^n: la pantalla
es (x, y) = (dato.u, dato.v). Girar es mover ese par de vectores.

Este modulo no importa Qt ni QGIS, asi que la geometria se prueba sola.
"""

import numpy as np

#: Frecuencias de giro. Son raices de primos a proposito: sus cocientes son
#: irracionales, asi que el recorrido no tiene ciclo y la animacion nunca
#: vuelve a pasar exactamente por la misma vista. Con frecuencias enteras la
#: rotacion se cerraria en pocos segundos y dejaria de mostrar proyecciones
#: nuevas, que es para lo unico que sirve.
PRIMOS = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53)

#: Tope de puntos por clase. Medio millon de puntos no se dibujan a treinta
#: cuadros por segundo, y tampoco se ven: se tapan entre ellos.
MAX_POR_CLASE = 4000


class ClaseND(object):
    """Un grupo de puntos con nombre y color: una firma guardada."""

    def __init__(self, nombre, color, cuenta=0, visible=True):
        self.nombre = nombre
        self.color = color or "#ffffff"
        self.cuenta = int(cuenta)
        self.visible = visible

    def __repr__(self):
        return "<ClaseND %r %s, %d puntos>" % (self.nombre, self.color,
                                               self.cuenta)


class TourND(object):
    """El plano que gira. Proyecta R^n sobre la pantalla.

    La rotacion es un producto de giros de Givens -giros en un plano de dos
    coordenadas- con frecuencias inconmensurables. Cada giro es ortogonal,
    asi que el producto tambien lo es y la base sale ortonormal por
    construccion, sin tener que reortogonalizar y sin deriva numerica.

    Aplicar los giros solo a los dos vectores de la base y no a la matriz
    entera cuesta O(n) por cuadro en vez de O(n^2): con doscientas bandas
    seleccionadas la diferencia es entre animar y no animar.
    """

    def __init__(self, n, velocidad=1.0):
        self.n = int(n)
        self.velocidad = float(velocidad)
        self._mano = [0.0, 0.0]        # giro que agrega el usuario
        self._planos = self._armar_planos()

    def _armar_planos(self):
        """Los planos de giro, con su frecuencia.

        Se gira el plano (k, k+1) para todo k, de modo que ninguna banda se
        queda fuera del recorrido: si alguna no participara, su direccion
        nunca se veria de frente y un grupo separado solo en esa banda
        quedaria escondido para siempre.
        """
        if self.n < 3:
            return []
        return [(k, (k + 1) % self.n,
                 float(np.sqrt(PRIMOS[k % len(PRIMOS)])))
                for k in range(self.n)]

    # -- la base ------------------------------------------------------------
    def base(self, t):
        """Los dos vectores ortonormales que definen la pantalla en el
        instante ``t``."""
        u = np.zeros(self.n, dtype=np.float64)
        v = np.zeros(self.n, dtype=np.float64)
        u[0] = 1.0
        if self.n > 1:
            v[1] = 1.0
        if self.n < 3:
            return u, v
        for i, j, w in self._planos:
            self._girar(u, v, i, j, w * t * self.velocidad)
        # El giro del raton se aplica al final y sobre planos fijos: asi
        # arrastrar mueve la vista de forma predecible, y no depende de por
        # donde ande la animacion.
        self._girar(u, v, 0, 2, self._mano[0])
        self._girar(u, v, 1, 2 % self.n, self._mano[1])
        return u, v

    @staticmethod
    def _girar(u, v, i, j, angulo):
        """Un giro de Givens en el plano (i, j), aplicado a los dos vectores."""
        c, s = np.cos(angulo), np.sin(angulo)
        for x in (u, v):
            xi, xj = x[i], x[j]
            x[i] = c * xi - s * xj
            x[j] = s * xi + c * xj

    def girar_a_mano(self, dx, dy):
        """Suma el arrastre del raton al giro."""
        self._mano[0] += float(dx)
        self._mano[1] += float(dy)

    def reiniciar_mano(self):
        self._mano = [0.0, 0.0]

    # -- proyeccion ---------------------------------------------------------
    def proyectar(self, X, t):
        """Puntos de R^n -> pantalla. ``X`` es (n_puntos, n)."""
        u, v = self.base(t)
        X = np.asarray(X, dtype=np.float64)
        if X.size == 0:
            return np.zeros((0, 2))
        return np.column_stack((X.dot(u), X.dot(v)))

    def ejes(self, t):
        """Los n ejes proyectados: los radios que se dibujan y se etiquetan.

        Un radio que apunta hacia donde se alarga un grupo dice que esa banda
        es la que lo separa. Es lo que convierte la nube de manchas en algo
        que se puede leer.
        """
        u, v = self.base(t)
        return np.column_stack((u, v))


class NubeND(object):
    """La matriz de puntos, sus clases y de que pixel salio cada uno."""

    def __init__(self, X, etiquetas, clases, bandas, pixeles=None):
        X = np.asarray(X, dtype=np.float64)
        etiquetas = np.asarray(etiquetas, dtype=np.int32)
        pixeles = list(pixeles or [])
        if X.size:
            # Un punto con algun NaN no se puede proyectar, y colarlo dejaria
            # la coordenada en NaN y el punto en cualquier parte.
            buenos = np.isfinite(X).all(axis=1)
            X = X[buenos]
            etiquetas = etiquetas[buenos]
            if pixeles:
                pixeles = [p for p, ok in zip(pixeles, buenos) if ok]
        self.X = X
        self.etiquetas = etiquetas
        self.clases = list(clases)
        self.bandas = list(bandas)
        self.pixeles = pixeles

    @property
    def vacia(self):
        return self.X.shape[0] == 0

    @property
    def n_dimensiones(self):
        return self.X.shape[1] if self.X.size else len(self.bandas)

    def indices_de(self, clase):
        return np.flatnonzero(self.etiquetas == clase)

    def __repr__(self):
        return ("<NubeND %d puntos, %d dimensiones, %d clases>"
                % (self.X.shape[0], self.n_dimensiones, len(self.clases)))


def nube_de_firmas(cubo, firmas, bandas, max_por_clase=MAX_POR_CLASE,
                   escalar=True):
    """Arma la nube con los pixeles de las firmas guardadas.

    Cada firma aporta TODOS sus pixeles, no su media. Esa es la diferencia
    que hace util la vista: una firma de area es un solo espectro en el
    grafico espectral y quinientos puntos aqui, y la media no muestra si el
    area era un grupo o dos.
    """
    bandas = [b for b in bandas]
    clases, filas, etiquetas, pixeles = [], [], [], []
    for numero, firma in enumerate(firmas):
        coords = _muestrear(firma.pixels, max_por_clase)
        clases.append(ClaseND(firma.name, firma.color, len(coords),
                              getattr(firma, "visible", True)))
        if not coords:
            continue
        espectros = cubo.get_pixels(coords)
        filas.append(espectros)
        etiquetas.extend([numero] * len(coords))
        pixeles.extend(coords)

    if not filas:
        return NubeND(np.zeros((0, max(1, len(bandas)))), [], clases, bandas)

    datos = np.vstack(filas)
    # Una banda mala llega como NaN en todas las filas. Colarla dejaria la
    # nube entera sin dato y la pantalla vacia, sin ninguna explicacion.
    utiles = [b for b in bandas
              if b < datos.shape[1] and np.isfinite(datos[:, b]).any()]
    X = datos[:, utiles] if utiles else np.zeros((datos.shape[0], 0))
    if escalar:
        X = _escalar(X)
    return NubeND(X, etiquetas, clases, utiles, pixeles)


def _muestrear(coords, tope):
    """Submuestrea de forma pareja, no cortando por el principio.

    Cortar los primeros ``tope`` dejaria fuera media escena -los pixeles de
    un area vienen ordenados por fila- y el usuario veria un grupo que no
    existe.
    """
    coords = [tuple(int(v) for v in p) for p in coords]
    if tope is None or len(coords) <= tope:
        return coords
    indices = np.linspace(0, len(coords) - 1, tope).round().astype(int)
    return [coords[i] for i in np.unique(indices)]


def _escalar(X):
    """Centra la nube y la mete en el cubo unidad.

    Se centra y se divide por UN solo numero -el maximo global- en vez de
    normalizar banda por banda. Normalizar cada banda por separado le daria
    a una banda de puro ruido el mismo peso que a una que separa las clases,
    y el ruido se comeria la estructura que se venia a ver.
    """
    if X.size == 0:
        return X
    centro = np.nanmean(X, axis=0)
    Y = X - centro
    escala = float(np.nanmax(np.abs(Y))) if np.isfinite(Y).any() else 0.0
    return Y / escala if escala > 0 else Y


def puntos_en_poligono(puntos, poligono):
    """Que puntos caen dentro del lazo. Devuelve un vector de booleanos.

    Algoritmo del numero de cruces, vectorizado sobre todos los puntos a la
    vez: con veinte mil puntos, hacerlo punto por punto se nota al soltar el
    raton. Sirve con lazos concavos, que es lo que sale de dibujar a mano
    alzada.
    """
    puntos = np.asarray(puntos, dtype=np.float64)
    if puntos.size == 0 or len(poligono) < 3:
        return np.zeros(len(puntos), dtype=bool)
    px, py = puntos[:, 0], puntos[:, 1]
    dentro = np.zeros(len(puntos), dtype=bool)
    vertices = np.asarray(poligono, dtype=np.float64)
    x1, y1 = vertices[:, 0], vertices[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    for a, b, c, d in zip(x1, y1, x2, y2):
        if b == d:
            continue
        cruza = (b > py) != (d > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            corte = a + (py - b) * (c - a) / (d - b)
        dentro ^= cruza & (px < corte)
    return dentro


__all__ = ["ClaseND", "NubeND", "TourND", "nube_de_firmas",
           "puntos_en_poligono", "MAX_POR_CLASE"]
