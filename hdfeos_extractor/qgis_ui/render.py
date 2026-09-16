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
"""Aplica la composicion RGB a la capa raster de QGIS.

La imagen NO se compone en numpy para despues meterla en el mapa. Se le dice
a QGIS que bandas usar y entre que valores realzarlas, y QGIS la dibuja con
su propio motor. Es mejor por tres razones: no duplica el cubo en disco ni en
memoria, el zoom y el desplazamiento siguen siendo los de QGIS, y cambiar una
banda es instantaneo porque no hay nada que recalcular.

``RGBComposer`` sigue mandando: decide que banda corresponde a cada longitud
de onda y con que criterio se realza. Lo unico que cambia es quien pinta.
"""

from qgis.core import (QgsContrastEnhancement, QgsMultiBandColorRenderer,
                       QgsRasterLayer)

from ..compat import enum
from ..core.rgb import limites


def _a_crudo(cube, valor):
    """Devuelve el valor en las unidades que QGIS ve en el archivo.

    El cubo entrega reflectancia -ya dividida por el factor de escala- y QGIS
    lee el entero crudo. Pasarle a QGIS un maximo de 0.45 sobre un archivo que
    guarda 4500 deja la imagen entera saturada en blanco, sin ningun error.
    Esta es la unica conversion que hace falta en toda la capa de dibujo, y es
    exactamente la que es facil de olvidar.
    """
    if cube.aplicar_escala and cube.scale:
        return valor * cube.scale
    return valor


def limites_de_banda(cube, indice, composer):
    """(minimo, maximo) de una banda, en unidades del archivo."""
    banda = cube.get_band(index=indice)
    lo, hi = limites(banda, composer.modo, composer.percentiles)
    if hi <= lo:
        hi = lo + 1.0
    return _a_crudo(cube, lo), _a_crudo(cube, hi)


def aplicar_composicion(layer, cube, composer):
    """Pone la capa en color multibanda con las bandas del compositor.

    Devuelve los indices de banda usados, empezando en cero, o None si la capa
    no sirve. QGIS numera las bandas desde 1 y el cubo desde 0: el ``+ 1`` de
    aca abajo es toda la diferencia entre ver la imagen correcta y verla
    corrida una banda.
    """
    if layer is None or not isinstance(layer, QgsRasterLayer):
        return None
    proveedor = layer.dataProvider()
    if proveedor is None or proveedor.bandCount() < 3:
        return None

    r, g, b = composer.bands_of(cube)
    renderizador = QgsMultiBandColorRenderer(proveedor, r + 1, g + 1, b + 1)
    asignar = (renderizador.setRedContrastEnhancement,
               renderizador.setGreenContrastEnhancement,
               renderizador.setBlueContrastEnhancement)
    for indice, poner in zip((r, g, b), asignar):
        lo, hi = limites_de_banda(cube, indice, composer)
        realce = QgsContrastEnhancement(proveedor.dataType(indice + 1))
        realce.setContrastEnhancementAlgorithm(
            enum(QgsContrastEnhancement,
                 "ContrastEnhancementAlgorithm",
                 "StretchToMinimumMaximum"), False)
        realce.setMinimumValue(lo)
        realce.setMaximumValue(hi)
        poner(realce)

    layer.setRenderer(renderizador)
    layer.triggerRepaint()
    return (r, g, b)
