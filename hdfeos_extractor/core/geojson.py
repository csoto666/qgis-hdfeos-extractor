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
"""Las huellas de las firmas, escritas como GeoJSON.

Un archivo por geometria -puntos por un lado, areas por otro- y no uno solo
mezclado: GeoJSON admite la mezcla, pero casi ningun programa que lo lee
admite una capa con dos tipos de geometria, asi que un archivo mezclado se
abre a medias o no se abre.

Se escribe en longitud y latitud porque eso es lo que GeoJSON significa. El
RFC 7946 fija WGS84 y quito el miembro ``crs`` que antes permitia otra cosa,
asi que un GeoJSON con metros UTM dentro es un archivo que cada programa
interpreta a su manera -y casi siempre mal, como si fueran grados-. Quien
reproyecta es la capa de QGIS, que es la que sabe; aqui solo se escribe.

Este modulo no importa QGIS ni Qt.
"""

import json

from .huella import TIPO_AREA, TIPO_PUNTO, atributos_de_firma

#: Cifras decimales. Siete son unos 11 mm en el ecuador: de sobra para un
#: pixel de 30 m, y evita archivos llenos de ruido de coma flotante.
DECIMALES = 7


def feature_de(huella, atributos):
    """Un Feature de GeoJSON a partir de una huella y sus campos."""
    if huella is None:
        return None
    return {"type": "Feature",
            "properties": dict(atributos),
            "geometry": _geometria(huella)}


def _geometria(huella):
    if huella.tipo == TIPO_AREA:
        return {"type": "Polygon",
                "coordinates": [[_coord(p) for p in huella.anillo]]}
    if huella.tipo == TIPO_PUNTO:
        return {"type": "Point", "coordinates": _coord(huella.puntos[0])}
    return {"type": "MultiPoint",
            "coordinates": [_coord(p) for p in huella.puntos]}


def _coord(punto):
    return [round(float(punto[0]), DECIMALES),
            round(float(punto[1]), DECIMALES)]


def coleccion(features):
    """Envuelve los features en una FeatureCollection."""
    return {"type": "FeatureCollection",
            "features": [f for f in features if f is not None]}


def colecciones_de_firmas(firmas, huellas):
    """Reparte las firmas en dos colecciones: puntos y areas.

    ``huellas`` llega en paralelo a ``firmas`` -la misma posicion- y puede
    traer None, que es lo que devuelve una firma sin pixeles: no se sabe de
    donde salio y no se le inventa un sitio.
    """
    puntos, areas = [], []
    for firma, huella in zip(firmas, huellas):
        if huella is None:
            continue
        feature = feature_de(huella, atributos_de_firma(firma))
        (areas if huella.es_area else puntos).append(feature)
    return coleccion(puntos), coleccion(areas)


def escribir(ruta, coleccion_geojson):
    """Escribe la coleccion. Devuelve cuantos features quedaron."""
    with open(ruta, "w") as archivo:
        json.dump(coleccion_geojson, archivo, ensure_ascii=False, indent=1)
        archivo.write("\n")
    return len(coleccion_geojson["features"])


__all__ = ["coleccion", "colecciones_de_firmas", "escribir", "feature_de",
           "DECIMALES"]
