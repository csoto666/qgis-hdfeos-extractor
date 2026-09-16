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
"""Un enum de Qt o de QGIS, encontrado en la version que sea.

Qt6 metio los enums dentro de su propia clase -``Qt.Orientation.Horizontal``-
mientras que en Qt5 cuelgan del espacio de nombres -``Qt.Horizontal``-. QGIS
hizo lo mismo con los suyos a partir de la 3.30. Un plugin que quiera correr
en las dos no puede elegir una forma: tiene que preguntar.

Esto vive en un modulo propio, sin importar nada, por dos razones. Una es que
lo necesitan tanto la capa de Qt como el algoritmo de Processing, que no
importa Qt y no deberia empezar a hacerlo por esto. La otra es que la regla
-calificado primero, plano despues- tiene que estar escrita una sola vez: es
exactamente el tipo de cosa que se escribe de dos maneras distintas en dos
archivos y se desincroniza al primer cambio.
"""


def enum(raiz, grupo, nombre):
    """Resuelve ``raiz.grupo.nombre``, o ``raiz.nombre`` donde no exista.

    El orden importa: primero la forma calificada, que es la unica que existe
    en Qt6. La plana queda de respaldo para las versiones anteriores.

    No basta con mirar si el grupo existe. Hay versiones intermedias de las
    vinculaciones en que la clase del enum esta expuesta pero no lleva sus
    miembros -son atributos de la clase de fuera y de ningun otro sitio-, y
    un ``getattr`` encadenado a ciegas revienta justo ahi. Por eso se
    comprueba el miembro y no el grupo.
    """
    contenedor = getattr(raiz, grupo, None)
    if contenedor is not None:
        valor = getattr(contenedor, nombre, None)
        if valor is not None:
            return valor
    return getattr(raiz, nombre)


__all__ = ["enum"]
