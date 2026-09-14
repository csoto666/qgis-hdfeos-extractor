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
"""Biblioteca espectral: las firmas que el usuario decidio conservar.

Formato de disco: un JSON con una lista de firmas. No es el formato de
biblioteca de ENVI -``.sli`` mas cabecera- a proposito: el ``.sli`` guarda
solo nombre y valores, y aca hace falta tambien de que escena y de que pixel
salio cada curva. El JSON se lee con cualquier cosa, se versiona bien en git
y aguanta campos nuevos sin romper los archivos viejos.

La exportacion a CSV existe para sacar las curvas a una hoja de calculo o a
un informe, que es lo que la gente hace de verdad con una biblioteca chica.
"""

import csv
import json
import os

import numpy as np

from .spectral import Signature, spectral_angle

#: Version del formato en disco. Se escribe para que un lector futuro pueda
#: distinguir un archivo viejo de uno nuevo sin adivinar por los campos.
FORMATO = 1


class LibraryError(Exception):
    """El archivo de biblioteca no existe, no se puede leer o no es uno."""


class SpectralLibrary(object):
    """Coleccion con nombre de firmas espectrales, persistible a disco."""

    def __init__(self, path=None, signatures=None):
        self.path = path
        self._firmas = list(signatures or [])

    # -- coleccion ----------------------------------------------------------
    def __len__(self):
        return len(self._firmas)

    def __iter__(self):
        return iter(self._firmas)

    def __contains__(self, nombre):
        return any(f.name == nombre for f in self._firmas)

    @property
    def signatures(self):
        return list(self._firmas)

    def names(self):
        return [f.name for f in self._firmas]

    def get(self, nombre):
        for f in self._firmas:
            if f.name == nombre:
                return f
        raise KeyError(nombre)

    def add(self, firma, reemplazar=False):
        """Guarda una firma. Sin ``reemplazar``, un nombre repetido se numera.

        Numerar en vez de sobrescribir es la opcion segura: el costo de
        equivocarse es una firma de mas, no una firma perdida que el usuario
        tardo diez minutos en muestrear.
        """
        if firma.name in self:
            if reemplazar:
                self.remove(firma.name)
            else:
                base, n = firma.name, 2
                while "%s (%d)" % (base, n) in self:
                    n += 1
                firma.name = "%s (%d)" % (base, n)
        self._firmas.append(firma)
        return firma

    def remove(self, nombre):
        antes = len(self._firmas)
        self._firmas = [f for f in self._firmas if f.name != nombre]
        return len(self._firmas) != antes

    def rename(self, viejo, nuevo):
        """Renombra una firma. Falla si el nombre nuevo ya esta ocupado."""
        nuevo = (nuevo or "").strip()
        if not nuevo:
            raise LibraryError("El nombre no puede quedar vacio")
        if nuevo == viejo:
            return self.get(viejo)
        if nuevo in self:
            raise LibraryError("Ya hay una firma llamada '%s'" % nuevo)
        firma = self.get(viejo)
        firma.name = nuevo
        return firma

    def set_visible(self, nombre, visible):
        self.get(nombre).visible = bool(visible)

    def clear(self):
        self._firmas = []

    # -- comparacion --------------------------------------------------------
    def compare(self, a, b, en_grados=True):
        """Angulo espectral entre dos firmas de la biblioteca, por nombre."""
        return spectral_angle(self.get(a), self.get(b), en_grados)

    def compare_all(self, referencia, en_grados=True):
        """Ordena la biblioteca por parecido a ``referencia``, la mas cercana
        primero.

        ``referencia`` puede ser un nombre de la biblioteca o una ``Signature``
        suelta -tipicamente el pixel que el usuario acaba de tocar-, que es el
        caso util: "a cual de mis firmas se parece esto".

        Las firmas que no se pueden comparar -otro eje espectral, todo NaN- se
        omiten en vez de tumbar la comparacion entera.
        """
        ref = (self.get(referencia) if isinstance(referencia, str)
               else referencia)
        salida = []
        for f in self._firmas:
            if f is ref:
                continue
            try:
                salida.append((f.name, spectral_angle(ref, f, en_grados)))
            except ValueError:
                continue
        return sorted(salida, key=lambda par: par[1])

    def match(self, firma):
        """La firma mas parecida y su angulo, o None si no hay con que comparar."""
        orden = self.compare_all(firma)
        return orden[0] if orden else None

    # -- persistencia -------------------------------------------------------
    def save(self, path=None):
        """Escribe la biblioteca a JSON. Recuerda la ruta para el proximo save.

        Se escribe a un temporal y se renombra al final. Un corte a mitad de
        escritura deja la biblioteca anterior intacta en vez de un archivo
        truncado, que es la unica copia que el usuario tenia de un trabajo de
        campo.
        """
        destino = path or self.path
        if not destino:
            raise LibraryError("No se dijo donde guardar la biblioteca")
        datos = {
            "formato": FORMATO,
            "signatures": [f.to_dict() for f in self._firmas],
        }
        temporal = destino + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        os.replace(temporal, destino)
        self.path = destino
        return destino

    @classmethod
    def load(cls, path):
        """Lee una biblioteca de JSON."""
        if not os.path.isfile(path):
            raise LibraryError("No existe: %s" % path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except ValueError as exc:
            raise LibraryError("No es un JSON valido: %s (%s)" % (path, exc))
        if not isinstance(datos, dict) or "signatures" not in datos:
            raise LibraryError(
                "El archivo no tiene forma de biblioteca espectral: %s" % path)
        firmas = [Signature.from_dict(d) for d in datos["signatures"]]
        return cls(path=path, signatures=firmas)

    # -- exportacion --------------------------------------------------------
    def to_csv(self, path):
        """Exporta a CSV y devuelve la forma usada: "ancho" o "largo".

        Cuando todas las firmas comparten el eje espectral sale la tabla ancha
        -una columna de longitud de onda y una por firma-, que es la que se
        grafica de una en una hoja de calculo. Cuando no lo comparten esa
        tabla no existe, y forzarla alinearia valores de bandas distintas en
        la misma fila; en ese caso se escribe la forma larga.
        """
        if not self._firmas:
            raise LibraryError("La biblioteca esta vacia")

        ejes = {tuple(np.round(f.wavelengths, 4)) for f in self._firmas}
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if len(ejes) == 1:
                w.writerow(["wavelength"] + self.names())
                eje = self._firmas[0].wavelengths
                for i, wl in enumerate(eje):
                    w.writerow([_num(wl)] + [_num(s.values[i])
                                             for s in self._firmas])
                return "ancho"
            w.writerow(["name", "wavelength", "value", "std", "count",
                        "source", "notes"])
            for s in self._firmas:
                for i, wl in enumerate(s.wavelengths):
                    w.writerow([
                        s.name, _num(wl), _num(s.values[i]),
                        "" if s.std is None else _num(s.std[i]),
                        s.count, s.source, s.notes])
            return "largo"


def _num(valor):
    """Formatea un numero para CSV. Los NaN salen como celda vacia."""
    v = float(valor)
    return "" if not np.isfinite(v) else repr(round(v, 6))
