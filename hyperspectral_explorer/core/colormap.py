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
"""Paletas para pintar un plano del cubo como imagen.

Las caras laterales del cubo hiperespectral son matrices ``(posicion, banda)``
-lo que devuelve ``get_transect``-, no imagenes. Pintarlas necesita una
paleta.

Esta en el nucleo y no en la vista porque es numpy puro y porque el mismo
plano coloreado sirve para el panel de QGIS, para un cuaderno y para escribir
un PNG desde un script.

Sobre el arcoiris: perceptualmente es una mala paleta -inventa bordes donde
el dato es continuo y se vuelve ilegible en escala de grises-. Se incluye y
es la predeterminada igual, porque es la que usa ENVI y es la referencia
visual que todo el mundo en hiperespectral ya tiene en la cabeza. ``viridis``
esta al lado para quien quiera leer magnitudes de verdad.
"""

import numpy as np

#: Puntos de control de cada paleta: (posicion, R, G, B) con RGB en 0..255.
#: Entre puntos se interpola linealmente.
PALETAS = {
    # Arcoiris tipo "jet": el aspecto clasico del cubo en ENVI.
    "arcoiris": [
        (0.000, 0, 0, 131), (0.125, 0, 0, 255), (0.375, 0, 255, 255),
        (0.625, 255, 255, 0), (0.875, 255, 0, 0), (1.000, 128, 0, 0),
    ],
    # Perceptualmente uniforme: distancias iguales en el dato se ven como
    # distancias iguales en el color, y sobrevive a la escala de grises.
    "viridis": [
        (0.00, 68, 1, 84), (0.13, 71, 44, 122), (0.25, 59, 81, 139),
        (0.38, 44, 113, 142), (0.50, 33, 144, 141), (0.63, 39, 173, 129),
        (0.75, 92, 200, 99), (0.88, 170, 220, 50), (1.00, 253, 231, 37),
    ],
    "grises": [(0.0, 0, 0, 0), (1.0, 255, 255, 255)],
    # Para reflectancia: oscuro abajo, calido arriba, sin el salto del verde.
    "fuego": [
        (0.00, 0, 0, 0), (0.25, 110, 20, 90), (0.50, 200, 60, 40),
        (0.75, 245, 155, 20), (1.00, 255, 255, 210),
    ],
}

PALETA_POR_DEFECTO = "arcoiris"

#: Color de las muestras sin dato. Negro a proposito: en las caras del cubo
#: las bandas malas quedan como franjas oscuras, que es como se ven en ENVI y
#: como conviene que se vean -un hueco tiene que parecer un hueco-.
COLOR_SIN_DATO = (0, 0, 0)

#: Resolucion de la tabla. 256 alcanza para 8 bits por canal.
NIVELES = 256


def nombres():
    """Nombres de paleta disponibles, con la predeterminada primero."""
    resto = sorted(k for k in PALETAS if k != PALETA_POR_DEFECTO)
    return [PALETA_POR_DEFECTO] + resto


def tabla(nombre=PALETA_POR_DEFECTO, niveles=NIVELES):
    """Construye la tabla de consulta de una paleta: ``(niveles, 3)`` uint8."""
    try:
        puntos = PALETAS[nombre]
    except KeyError:
        raise KeyError("No existe la paleta '%s'. Hay: %s"
                       % (nombre, ", ".join(nombres())))
    posiciones = np.asarray([p[0] for p in puntos], dtype=np.float64)
    canales = np.asarray([p[1:] for p in puntos], dtype=np.float64)
    t = np.linspace(0.0, 1.0, niveles)
    salida = np.empty((niveles, 3), dtype=np.float64)
    for c in range(3):
        salida[:, c] = np.interp(t, posiciones, canales[:, c])
    return np.clip(salida, 0, 255).astype(np.uint8)


def colorear(datos, nombre=PALETA_POR_DEFECTO, lo=None, hi=None,
             sin_dato=COLOR_SIN_DATO):
    """Pinta una matriz 2D y devuelve ``(alto, ancho, 3)`` uint8.

    ``lo`` y ``hi`` fijan el rango; si faltan se toman del propio dato,
    ignorando los NaN. Pasarlos explicitos es lo que permite que dos caras del
    mismo cubo compartan escala: si cada una se normaliza sola, la de arriba y
    la de la derecha dicen cosas distintas con el mismo color y el cubo miente.
    """
    valores = np.asarray(datos, dtype=np.float32)
    if valores.ndim != 2:
        raise ValueError("Se esperaba una matriz 2D, llegaron %d ejes"
                         % valores.ndim)
    validos = np.isfinite(valores)

    if lo is None or hi is None:
        muestra = valores[validos]
        auto_lo = float(muestra.min()) if muestra.size else 0.0
        auto_hi = float(muestra.max()) if muestra.size else 1.0
        lo = auto_lo if lo is None else lo
        hi = auto_hi if hi is None else hi
    if hi <= lo:
        hi = lo + 1.0

    lut = tabla(nombre)
    normal = (valores - lo) / (hi - lo)
    # nan_to_num antes de convertir a entero: sin esto los NaN se vuelven un
    # indice cualquiera y las bandas malas salen de un color vivo al azar.
    indices = np.clip(np.nan_to_num(normal, nan=0.0), 0.0, 1.0)
    indices = (indices * (lut.shape[0] - 1) + 0.5).astype(np.int32)

    salida = lut[indices]
    if not validos.all():
        salida = salida.copy()
        salida[~validos] = np.asarray(sin_dato, dtype=np.uint8)
    return salida
