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
"""Composicion RGB a partir de tres bandas cualesquiera del cubo.

Una regla, y no es negociable: el compositor es una capa de visualizacion.
Nunca escribe en el cubo. Cambiar el realce cambia lo que se ve, jamas lo que
se mide; el espectro que sale de ``get_spectrum`` es el mismo antes y despues
de tocar cualquier control de esta pantalla.

Los presets estan en longitud de onda y no en numero de banda, que es lo que
los vuelve portables: "rojo = 665 nm" significa lo mismo en Tanager, en
PRISMA y en EMIT; "rojo = banda 29" no significa nada fuera del sensor donde
se escribio.
"""

import collections

import numpy as np

#: Presets de composicion, en nanometros. El orden es (R, G, B).
PRESETS = collections.OrderedDict([
    ("Color natural", (660.0, 550.0, 470.0)),
    ("Falso color IR", (840.0, 660.0, 550.0)),
    ("Agricultura", (1610.0, 840.0, 660.0)),
    ("Vegetacion sana", (840.0, 720.0, 660.0)),
    ("Suelos y geologia", (2200.0, 1610.0, 660.0)),
    ("Agua y humedad", (840.0, 1610.0, 2200.0)),
])

#: Realce por defecto. 2-98 recorta el 2% de cada cola.
PERCENTILES = (2.0, 98.0)

MODOS = ("percentil", "minmax", "reflectancia", "desviacion")


def limites(banda, modo="percentil", percentiles=PERCENTILES, sigmas=2.0):
    """Devuelve el par (lo, hi) con el que ``estirar`` lleva la banda a 0..1.

    Esta separado del estiramiento porque QGIS no necesita la imagen: le basta
    con el minimo y el maximo para configurar su propio realce sobre la capa
    raster. Asi la imagen del mapa y el grafico usan exactamente el mismo
    criterio, en vez de dos realces parecidos que no coinciden.
    """
    datos = np.asarray(banda, dtype=np.float32)
    muestra = datos[np.isfinite(datos)]
    if muestra.size == 0:
        return 0.0, 1.0
    if modo == "minmax":
        return float(muestra.min()), float(muestra.max())
    if modo == "reflectancia":
        return 0.0, 1.0
    if modo == "desviacion":
        media, sigma = float(muestra.mean()), float(muestra.std())
        return media - sigmas * sigma, media + sigmas * sigma
    lo, hi = np.percentile(muestra, percentiles)
    return float(lo), float(hi)


def estirar(banda, modo="percentil", percentiles=PERCENTILES, sigmas=2.0):
    """Lleva una banda a 0..1 para poder dibujarla.

    Los cuatro modos existen porque ninguno sirve siempre:

    ``percentil``    lo razonable por defecto. Recortar las colas evita que
                     un pixel saturado -una nube, un techo metalico- deje el
                     resto de la escena en negro.
    ``minmax``       fiel al rango real. Util para comprobar, malo para ver.
    ``reflectancia`` fija 0..1 sin mirar los datos. Es el unico modo que
                     permite comparar dos escenas entre si, porque el realce
                     no depende del contenido de cada una.
    ``desviacion``   media +- n sigmas. Saca detalle de escenas planas.

    Los NaN -relleno, bordes- no participan del calculo y salen como 0.
    """
    datos = np.asarray(banda, dtype=np.float32)
    validos = np.isfinite(datos)
    if not validos.any():
        return np.zeros(datos.shape, dtype=np.float32)

    lo, hi = limites(datos, modo, percentiles, sigmas)
    if hi <= lo:
        # Banda constante: no hay contraste que estirar. Gris medio es mas
        # honesto que un negro o un blanco que sugieren estructura.
        return np.where(validos, np.float32(0.5), np.float32(0.0))

    salida = (datos - lo) / (hi - lo)
    salida = np.clip(salida, 0.0, 1.0, out=salida)
    return np.where(validos, salida, np.float32(0.0)).astype(np.float32)


class RGBComposer(object):
    """Tres bandas, un realce, y una imagen para mostrar.

    No guarda referencia al cubo: recibe uno en cada llamada. Asi el mismo
    compositor -y el mismo preset elegido por el usuario- se aplica a varias
    escenas sin reconstruirlo.
    """

    def __init__(self, red=660.0, green=550.0, blue=470.0,
                 modo="percentil", percentiles=PERCENTILES):
        self.modo = modo
        self.percentiles = tuple(percentiles)
        self.set_bands(red, green, blue)

    # -- seleccion de bandas ------------------------------------------------
    def set_bands(self, red=None, green=None, blue=None):
        """Fija las longitudes de onda de R, G y B. Los None no se tocan."""
        if red is not None:
            self.red = float(red)
        if green is not None:
            self.green = float(green)
        if blue is not None:
            self.blue = float(blue)
        return self

    def set_preset(self, nombre):
        """Aplica un preset por nombre. Lanza KeyError si no existe."""
        r, g, b = PRESETS[nombre]
        return self.set_bands(r, g, b)

    @staticmethod
    def presets():
        """Nombres de preset disponibles, en orden de presentacion."""
        return list(PRESETS.keys())

    @staticmethod
    def presets_aplicables(cube, margen=60.0):
        """Presets cuyas tres bandas caen dentro del rango del sensor.

        Un preset SWIR sobre un cubo que llega a 900 nm no falla: ``get_band``
        devuelve la banda mas cercana, es decir la ultima, tres veces, y el
        usuario ve una imagen gris sin entender por que. Filtrar de antemano
        es mas claro que explicarlo despues.
        """
        wl = cube.wavelengths
        lo, hi = float(np.nanmin(wl)), float(np.nanmax(wl))
        return [n for n, bandas in PRESETS.items()
                if all(lo - margen <= b <= hi + margen for b in bandas)]

    def bands_of(self, cube):
        """Indices de banda que este compositor usaria sobre ``cube``.

        Se piden solo bandas buenas: un preset que cae dentro de una ventana
        de absorcion devolveria una banda de puro ruido, y la imagen saldria
        con textura que no existe en el terreno -y que el usuario
        interpretaria-.
        """
        return tuple(cube.band_index(w, solo_buenas=True)
                     for w in (self.red, self.green, self.blue))

    def wavelengths_of(self, cube):
        """Longitudes de onda reales que se usarian, ya ajustadas al sensor."""
        return tuple(float(cube.wavelengths[i]) for i in self.bands_of(cube))

    # -- composicion --------------------------------------------------------
    def create_composite(self, cube, as_uint8=True, preview=False,
                         max_lado=1024):
        """Devuelve la imagen RGB como ``(y, x, 3)``.

        Con ``preview=True`` compone sobre bandas submuestreadas: la imagen
        sale en un instante y sirve para navegar. La extraccion de espectros
        no pasa por aca, asi que el analisis sigue sobre el dato original.
        """
        canales = []
        for wl in (self.red, self.green, self.blue):
            if preview:
                banda, _ = cube.preview_band(wavelength=wl, max_lado=max_lado)
            else:
                banda = cube.get_band(wavelength=wl)
            canales.append(estirar(banda, self.modo, self.percentiles))

        rgb = np.dstack(canales)
        if as_uint8:
            return (rgb * 255.0 + 0.5).astype(np.uint8)
        return rgb

    def __repr__(self):
        return ("<RGBComposer R=%.1f G=%.1f B=%.1f modo=%s>"
                % (self.red, self.green, self.blue, self.modo))
