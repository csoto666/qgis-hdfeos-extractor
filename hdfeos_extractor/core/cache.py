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
"""Un cache de arrays acotado por bytes.

Acotado por BYTES y no por cantidad de piezas, que es la diferencia que
importa con datos pesados: doce bandas de una escena de 200x200 son tres
megabytes y doce bandas de un Tanager son veinticinco. Contar piezas deja el
consumo de memoria a merced del tamano de la escena, que es justo lo que no
se puede permitir aqui.

Lo que se guarda sale de solo lectura. Quien lee una banda recibe el mismo
array que recibieron los demas, y sin esa marca un consumidor distraido
-un ``+=`` en vez de un ``+``- corrompe lo que van a leer todos los que
vengan detras, sin error y sin rastro.
"""

import collections


class CacheLRU(object):
    """Guarda arrays de numpy hasta llenar su presupuesto; luego desaloja.

    Se desaloja lo menos usado recientemente. Es lo que corresponde al uso
    real: el usuario vuelve sobre la banda que estaba mirando y sobre el
    transecto que acaba de dejar, no sobre el primero que abrio.
    """

    def __init__(self, megabytes):
        self.tope = int(megabytes * 1024 * 1024)
        self._piezas = collections.OrderedDict()
        self.bytes_usados = 0
        self.aciertos = 0
        self.fallos = 0

    def obtener(self, clave):
        """El array guardado, o None. Un acierto lo rejuvenece."""
        if clave not in self._piezas:
            self.fallos += 1
            return None
        self.aciertos += 1
        self._piezas.move_to_end(clave)
        return self._piezas[clave]

    def poner(self, clave, array):
        """Guarda el array y devuelve el mismo, ya de solo lectura.

        Devolverlo permite escribir ``return cache.poner(k, leer())`` sin una
        linea mas, que es como se usa en las tres lecturas del cubo.
        """
        array.flags.writeable = False
        cuanto = int(array.nbytes)
        if cuanto > self.tope:
            # Mas grande que todo el presupuesto: no se guarda, y sobre todo
            # no se vacia el cache entero para no guardarlo igual. Pasa con
            # un transecto de una escena enorme, y desalojar todo lo demas
            # para nada seria lo peor de los dos mundos.
            return array
        if clave in self._piezas:
            self.bytes_usados -= int(self._piezas[clave].nbytes)
        self._piezas[clave] = array
        self._piezas.move_to_end(clave)
        self.bytes_usados += cuanto
        while self.bytes_usados > self.tope and len(self._piezas) > 1:
            _, viejo = self._piezas.popitem(last=False)
            self.bytes_usados -= int(viejo.nbytes)
        return array

    def vaciar(self):
        self._piezas.clear()
        self.bytes_usados = 0

    def __len__(self):
        return len(self._piezas)

    def __contains__(self, clave):
        return clave in self._piezas

    def __repr__(self):
        return ("<CacheLRU %d piezas, %.1f de %.0f MB, %d aciertos / %d>"
                % (len(self._piezas), self.bytes_usados / 1048576.0,
                   self.tope / 1048576.0, self.aciertos,
                   self.aciertos + self.fallos))


__all__ = ["CacheLRU"]
