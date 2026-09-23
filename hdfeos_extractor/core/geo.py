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
"""Conversion entre coordenadas de mapa y coordenadas de pixel.

Esto vive en el nucleo y no en la capa de QGIS a proposito. Es la parte del
frontend que mas facil se equivoca -el eje Y va al reves, el origen esta en
la esquina y no en el centro del pixel, y con rotacion la division simple
deja de servir- y a la vez la unica que se puede probar sin abrir QGIS.
Aislarla aca la vuelve comprobable.

Se usa la convencion de geotransformacion de GDAL, que es la que devuelven
tanto GDAL como ``QgsRasterLayer``:

    X = gt0 + col * gt1 + fila * gt2
    Y = gt3 + col * gt4 + fila * gt5

donde (gt0, gt3) es la esquina superior izquierda del pixel (0, 0) -su
esquina, no su centro- y gt5 es normalmente negativo porque Y crece hacia
el norte mientras las filas crecen hacia el sur.
"""

import numpy as np


class GeoError(Exception):
    """La geotransformacion no es invertible o no hay ninguna."""


class GeoTransform(object):
    """Una geotransformacion afin, con su inversa ya resuelta.

    Soporta rotacion -gt2 y gt4 distintos de cero- porque las escenas
    hiperespectrales sin ortorectificar la traen a menudo. Con rotacion no
    alcanza con dividir por el tamano de pixel: hay que invertir la matriz.
    """

    def __init__(self, gt):
        gt = tuple(float(v) for v in gt)
        if len(gt) != 6:
            raise GeoError("Una geotransformacion tiene 6 numeros, no %d"
                           % len(gt))
        self.gt = gt
        # [[gt1, gt2], [gt4, gt5]] lleva (col, fila) a (X, Y).
        matriz = np.array([[gt[1], gt[2]], [gt[4], gt[5]]], dtype=np.float64)
        determinante = float(np.linalg.det(matriz))
        if abs(determinante) < 1e-15:
            raise GeoError(
                "La geotransformacion es degenerada (determinante %g): no se "
                "puede pasar de mapa a pixel" % determinante)
        self._inversa = np.linalg.inv(matriz)

    @classmethod
    def from_layer(cls, layer):
        """Construye la transformacion desde un ``QgsRasterLayer``.

        QGIS no expone la geotransformacion como tal: hay que armarla con la
        extension y el tamano en pixeles. Eso solo vale para capas sin
        rotacion, que es lo que QGIS puede dibujar de todos modos.
        """
        ext = layer.extent()
        ancho, alto = layer.width(), layer.height()
        if not ancho or not alto:
            raise GeoError("La capa no declara tamano en pixeles")
        return cls((ext.xMinimum(), ext.width() / ancho, 0.0,
                    ext.yMaximum(), 0.0, -ext.height() / alto))

    @classmethod
    def identidad(cls, lines=None, samples=None):
        """Transformacion para un cubo sin georreferencia.

        Un cubo en geometria de sensor no tiene coordenadas de mapa. En vez de
        negarse a trabajar, se usa el propio indice de pixel como sistema de
        coordenadas: la fila crece hacia abajo, igual que en la imagen.
        """
        return cls((0.0, 1.0, 0.0, 0.0, 0.0, -1.0))

    # -- conversion ---------------------------------------------------------
    def to_pixel(self, x, y, redondear=True):
        """Coordenada de mapa -> (columna, fila).

        Con ``redondear`` devuelve el pixel que contiene el punto, usando
        ``floor`` y no ``round``: el pixel 0 va de 0.0 a 1.0, asi que un punto
        en 0.9 esta en el pixel 0. Redondear pondria medio pixel de cada lado
        en el vecino y el usuario veria el espectro del pixel de al lado
        cuando hace clic cerca del borde.
        """
        gt = self.gt
        d = np.array([float(x) - gt[0], float(y) - gt[3]], dtype=np.float64)
        col, fila = self._inversa.dot(d)
        if redondear:
            return int(np.floor(col)), int(np.floor(fila))
        return float(col), float(fila)

    def to_map(self, col, fila, centro=True):
        """(columna, fila) -> coordenada de mapa.

        Con ``centro`` devuelve el centro del pixel y no su esquina. Es lo que
        se quiere casi siempre: para dibujar la marca del pixel seleccionado,
        la esquina la deja corrida medio pixel arriba y a la izquierda.
        """
        gt = self.gt
        c = float(col) + (0.5 if centro else 0.0)
        f = float(fila) + (0.5 if centro else 0.0)
        return (gt[0] + c * gt[1] + f * gt[2],
                gt[3] + c * gt[4] + f * gt[5])

    def pixel_bbox(self, col, fila):
        """Las cuatro esquinas de un pixel, en coordenadas de mapa.

        En orden, cerrando el anillo, para dibujarlo directo como poligono.
        Se calculan las cuatro y no dos opuestas porque con rotacion el pixel
        no es un rectangulo alineado con los ejes.
        """
        esquinas = [(col, fila), (col + 1, fila),
                    (col + 1, fila + 1), (col, fila + 1)]
        return [self.to_map(c, f, centro=False) for c, f in esquinas]

    @property
    def tamano_pixel(self):
        """(ancho, alto) del pixel en unidades de mapa, siempre positivos."""
        gt = self.gt
        return (float(np.hypot(gt[1], gt[4])), float(np.hypot(gt[2], gt[5])))

    @property
    def tiene_rotacion(self):
        return self.gt[2] != 0.0 or self.gt[4] != 0.0

    def contiene(self, col, fila, samples, lines):
        return 0 <= col < samples and 0 <= fila < lines

    # -- ventanas -----------------------------------------------------------
    def bbox_de_ventana(self, ventana):
        """Ventana de pixeles -> caja envolvente en coordenadas de mapa.

        La ventana llega con los extremos DENTRO -el pixel x1 se ve-, asi que
        el borde derecho del recorte es la esquina de x1+1. Restar ese uno
        deja fuera la ultima columna y la ultima fila, que es justo el error
        que al vincular vistas se acumula zoom tras zoom.

        Se calculan las cuatro esquinas y no dos opuestas porque con rotacion
        el rectangulo de pixeles es un rombo en el terreno: su caja
        envolvente necesita las cuatro.
        """
        esquinas = self.esquinas_de_ventana(ventana)
        xs = [p[0] for p in esquinas]
        ys = [p[1] for p in esquinas]
        return (min(xs), min(ys), max(xs), max(ys))

    def esquinas_de_ventana(self, ventana):
        """Ventana de pixeles -> sus cuatro esquinas en el terreno.

        Las cuatro y en orden, no dos opuestas: con rotacion el rectangulo
        de pixeles es un ROMBO en el terreno, y su caja envolvente pinta
        terreno que la ventana nunca toco. Para dibujar la huella de una
        firma en el mapa hace falta el rombo, no la caja.

        Los extremos van DENTRO -el pixel x1 se ve-, asi que el borde
        derecho es la esquina de x1+1.
        """
        x0, y0, x1, y1 = [int(v) for v in ventana]
        return [self.to_map(c, f, centro=False)
                for c, f in ((x0, y0), (x1 + 1, y0),
                             (x1 + 1, y1 + 1), (x0, y1 + 1))]

    def ventana_de_bbox(self, bbox, samples, lines):
        """Caja en coordenadas de mapa -> ventana de pixeles, recortada.

        Devuelve None cuando la caja no toca la escena: es lo que hay que
        distinguir de "la escena entera" para no saltar al verlo todo cuando
        el usuario se va con el mapa a otro continente.
        """
        xmin, ymin, xmax, ymax = bbox
        esquinas = [self.to_pixel(x, y, redondear=False)
                    for x, y in ((xmin, ymin), (xmax, ymin),
                                 (xmax, ymax), (xmin, ymax))]
        cols = [p[0] for p in esquinas]
        filas = [p[1] for p in esquinas]
        x0, x1 = int(np.floor(min(cols))), int(np.ceil(max(cols))) - 1
        y0, y1 = int(np.floor(min(filas))), int(np.ceil(max(filas))) - 1
        if x1 < 0 or y1 < 0 or x0 > samples - 1 or y0 > lines - 1:
            return None
        return (max(0, x0), max(0, y0),
                min(samples - 1, x1), min(lines - 1, y1))

    def __repr__(self):
        return ("<GeoTransform origen=(%.4f, %.4f) pixel=%.4gx%.4g%s>"
                % (self.gt[0], self.gt[3], self.tamano_pixel[0],
                   self.tamano_pixel[1],
                   " rotada" if self.tiene_rotacion else ""))
