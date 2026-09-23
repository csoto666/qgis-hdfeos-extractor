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
"""Donde se tomo cada firma, como geometria de mapa.

El dato ya estaba: ``Signature`` guarda la lista completa de ``(x, y)`` desde
el principio -se guardo para poder volver a extraer la firma del cubo y
comprobarla-. Lo unico que faltaba era pasarla por la geotransformacion y
decidir que forma le corresponde.

Y le corresponde una distinta segun como se tomo, que es justo lo que no hay
que perder:

    un pixel        -> un punto
    un rectangulo   -> el poligono de su borde exterior
    pixeles sueltos -> varios puntos, NO su caja envolvente

Lo ultimo importa. La caja que envuelve tres pixeles dispersos pinta en el
mapa hectareas de terreno que nadie midio, y un mapa que afirma algo que no
se midio es peor que un mapa sin la capa.

Este modulo no importa QGIS ni Qt: la geometria se prueba sola.
"""

import collections

TIPO_PUNTO = "punto"
TIPO_AREA = "area"
TIPO_PIXELES = "pixeles"


class Huella(object):
    """Donde cae una firma en el terreno.

    ``puntos`` son coordenadas de mapa -una para un pixel, varias para
    pixeles sueltos-; ``anillo`` es el borde cerrado cuando la firma cubre un
    rectangulo. Nunca vienen los dos.
    """

    def __init__(self, tipo, puntos=None, anillo=None):
        self.tipo = tipo
        self.puntos = list(puntos or [])
        self.anillo = list(anillo) if anillo else None

    @property
    def es_area(self):
        return self.anillo is not None

    def __repr__(self):
        return ("<Huella %s, %d puntos>"
                % (self.tipo, len(self.anillo or self.puntos)))


def tipo_de_firma(firma):
    """De que clase es una firma, deducido de sus pixeles.

    Se DEDUCE en vez de guardarse en un campo nuevo, y es a proposito: asi
    una biblioteca guardada con una version anterior se puede llevar al mapa
    igual, sin migrar nada ni echar de menos un campo que no existe.
    """
    pixeles = list(getattr(firma, "pixels", None) or [])
    if len(pixeles) == 1:
        return TIPO_PUNTO
    if len(pixeles) > 1 and _es_rectangulo_completo(pixeles):
        return TIPO_AREA
    return TIPO_PIXELES


def _es_rectangulo_completo(pixeles):
    """True si los pixeles llenan entero el rectangulo que los envuelve.

    Un rectangulo arrastrado sobre la escena los llena todos; una seleccion
    de pixeles sueltos casi nunca, y ahi la caja envolvente mentiria.
    """
    xs = [int(p[0]) for p in pixeles]
    ys = [int(p[1]) for p in pixeles]
    ancho = max(xs) - min(xs) + 1
    alto = max(ys) - min(ys) + 1
    return len(set((int(p[0]), int(p[1])) for p in pixeles)) == ancho * alto


def ventana_de(pixeles):
    """La ventana ``(x0, y0, x1, y1)`` que envuelve a esos pixeles."""
    xs = [int(p[0]) for p in pixeles]
    ys = [int(p[1]) for p in pixeles]
    return (min(xs), min(ys), max(xs), max(ys))


def huella_de_firma(firma, geo):
    """La geometria de una firma, o None si no se sabe de donde salio.

    None y no una posicion inventada: una firma leida de un CSV ajeno no
    trae pixeles, y ponerla en cualquier sitio del mapa es afirmar algo
    falso.
    """
    pixeles = list(getattr(firma, "pixels", None) or [])
    if not pixeles:
        return None
    tipo = tipo_de_firma(firma)
    if tipo == TIPO_AREA:
        esquinas = geo.esquinas_de_ventana(ventana_de(pixeles))
        return Huella(tipo, anillo=esquinas + [esquinas[0]])
    return Huella(tipo, puntos=[geo.to_map(int(x), int(y))
                                for x, y in pixeles])


def atributos_de_firma(firma):
    """Los campos que acompanian a la geometria en la capa.

    Ninguno puede ser None: un None se escribe como el texto "None" o hace
    fallar la exportacion, segun el controlador que la escriba.
    """
    longitudes = getattr(firma, "wavelengths", None)
    tiene = longitudes is not None and len(longitudes)
    return collections.OrderedDict((
        ("nombre", firma.name or ""),
        ("tipo", tipo_de_firma(firma)),
        ("pixeles", int(getattr(firma, "count", 0) or 0)),
        ("creada", getattr(firma, "created", "") or ""),
        ("procedencia", getattr(firma, "source", "") or ""),
        ("notas", getattr(firma, "notes", "") or ""),
        ("color", getattr(firma, "color", "") or ""),
        ("bandas", int(len(longitudes)) if tiene else 0),
        ("wl_min", float(longitudes[0]) if tiene else 0.0),
        ("wl_max", float(longitudes[-1]) if tiene else 0.0),
    ))


#: Tipo de cada campo, para quien tenga que declarar el esquema de la capa.
CAMPOS = collections.OrderedDict((
    ("nombre", str), ("tipo", str), ("pixeles", int), ("creada", str),
    ("procedencia", str), ("notas", str), ("color", str), ("bandas", int),
    ("wl_min", float), ("wl_max", float),
))


__all__ = ["Huella", "TIPO_AREA", "TIPO_PIXELES", "TIPO_PUNTO", "CAMPOS",
           "atributos_de_firma", "huella_de_firma", "tipo_de_firma",
           "ventana_de"]
