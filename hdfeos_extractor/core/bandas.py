# -*- coding: utf-8 -*-
#
# HDF-EOS Extractor - plugin de QGIS para extraer cubos hiperespectrales
# HDF-EOS5 al formato nativo de ENVI
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
"""Bandas malas: las que hay que sacar del analisis, no solo del grafico.

Un cubo hiperespectral siempre tiene bandas que no sirven. Las ventanas donde
el vapor de agua atmosferico absorbe casi todo -1340-1460 y 1790-1960 nm- no
traen senal del terreno: traen ruido amplificado por la division entre una
radiancia casi nula. Los extremos del rango tienen poca relacion senal-ruido
porque ahi el sensor ya no responde bien. Y a veces el productor marca
ademas bandas concretas por defectos del detector.

Arrastrarlas cuesta dos cosas distintas. La visible es que el grafico se
llena de picos que tapan la forma de la firma. La cara es que entran en la
media, en la desviacion y en el angulo espectral como si fueran medidas, y
ahi ya no se ven: solo corren los numeros.

Este modulo decide que banda entra y cual no, combinando cuatro criterios que
se pueden encender por separado. La banda descartada sale como NaN, y de ahi
en adelante todo el resto del nucleo ya la ignora solo: el grafico corta la
curva, nanmean la saltea y el angulo espectral la excluye.
"""

import re

import numpy as np

from ..lector import LIMITE_ESPECTRAL, VENTANAS_ABSORCION


class MascaraBandas(object):
    """Que bandas entran en el analisis y por que.

    Los cuatro criterios se combinan por AND: una banda sobrevive solo si
    ninguno la descarta. Es lo prudente -en la duda, fuera- y ademas es lo que
    hace el extractor al escribir la bbl, asi que el explorador y el ENVI
    extraido coinciden.
    """

    def __init__(self, wavelengths, bbl=None, usar_bbl=True,
                 usar_absorcion=True, usar_extremos=True, rangos=()):
        self.wavelengths = np.asarray(wavelengths, dtype=np.float64)
        n = self.wavelengths.size
        if bbl is not None:
            bbl = np.asarray(bbl).astype(bool)
            if bbl.size != n:
                bbl = None          # no es de este cubo; mejor ignorarla
        #: La lista que traia el archivo, tal cual. None si no habia.
        self.bbl = bbl
        self.usar_bbl = bool(usar_bbl)
        self.usar_absorcion = bool(usar_absorcion)
        self.usar_extremos = bool(usar_extremos)
        self.rangos = [tuple(sorted((float(a), float(b)))) for a, b in rangos]

    # -- estado -------------------------------------------------------------
    @property
    def hay_bbl(self):
        """True si el archivo traia su propia lista de bandas buenas."""
        return self.bbl is not None

    @property
    def buenas(self):
        """Vector booleano: True en las bandas que entran al analisis."""
        wl = self.wavelengths
        buenas = np.ones(wl.size, dtype=bool)
        if self.usar_bbl and self.bbl is not None:
            buenas &= self.bbl
        if self.usar_absorcion:
            for lo, hi in VENTANAS_ABSORCION:
                buenas &= ~((wl >= lo) & (wl <= hi))
        if self.usar_extremos:
            lo, hi = LIMITE_ESPECTRAL
            buenas &= (wl >= lo) & (wl <= hi)
        for lo, hi in self.rangos:
            buenas &= ~((wl >= lo) & (wl <= hi))
        return buenas

    @property
    def malas(self):
        return ~self.buenas

    @property
    def n_malas(self):
        return int(self.malas.sum())

    @property
    def activa(self):
        """False cuando no descarta nada: permite saltarse el trabajo."""
        return self.n_malas > 0

    # -- uso ----------------------------------------------------------------
    def aplicar(self, valores, eje=-1):
        """Pone NaN en las bandas descartadas. Devuelve float32.

        ``eje`` dice cual de los ejes es el espectral, porque las lecturas del
        cubo tienen formas distintas: un espectro es (banda,), un transecto
        (posicion, banda) y una ventana (y, x, banda). En los tres el eje
        espectral es el ultimo, que es el valor por defecto.
        """
        datos = np.asarray(valores, dtype=np.float32)
        if not self.activa:
            return datos
        if datos.shape[eje] != self.wavelengths.size:
            raise ValueError(
                "El eje %d mide %d y la mascara es de %d bandas"
                % (eje, datos.shape[eje], self.wavelengths.size))
        # La forma de broadcasting se arma a mano para no depender de que el
        # eje espectral sea el ultimo.
        forma = [1] * datos.ndim
        forma[eje] = self.wavelengths.size
        malas = self.malas.reshape(forma)
        return np.where(malas, np.float32(np.nan), datos)

    def indice_bueno_mas_cercano(self, longitud):
        """Indice de la banda buena mas cercana a ``longitud``.

        Sirve para que un preset RGB no caiga dentro de una ventana de
        absorcion: pedir 1400 nm ahi devolveria una banda de puro ruido y la
        imagen saldria con textura que no existe en el terreno. Si no queda
        ninguna banda buena se devuelve la mas cercana a secas, porque
        negarse a componer una imagen es peor que componerla mal.
        """
        buenas = self.buenas
        if not buenas.any():
            return int(np.argmin(np.abs(self.wavelengths - float(longitud))))
        indices = np.flatnonzero(buenas)
        cerca = np.argmin(np.abs(self.wavelengths[indices] - float(longitud)))
        return int(indices[cerca])

    # -- presentacion -------------------------------------------------------
    def describir(self):
        """Texto corto para la interfaz: cuantas y por que."""
        total = self.wavelengths.size
        malas = self.n_malas
        if malas == 0:
            return "%d bandas, ninguna descartada" % total
        motivos = []
        if self.usar_bbl and self.bbl is not None:
            motivos.append("lista del archivo")
        if self.usar_absorcion:
            motivos.append("vapor de agua")
        if self.usar_extremos:
            motivos.append("extremos")
        if self.rangos:
            motivos.append("%d rango%s propio%s"
                           % (len(self.rangos),
                              "s" if len(self.rangos) > 1 else "",
                              "s" if len(self.rangos) > 1 else ""))
        return "%d de %d bandas descartadas (%s)" % (
            malas, total, ", ".join(motivos) if motivos else "sin motivo")

    def tramos_malos(self):
        """Los grupos contiguos de bandas descartadas, en longitud de onda.

        Devuelve [(desde, hasta), ...]. Sirve para sombrearlos en el grafico:
        se ve donde falta el dato en vez de solo ver un hueco.
        """
        malas = self.malas
        if not malas.any():
            return []
        bordes = np.flatnonzero(np.diff(malas.astype(np.int8)))
        inicios = np.concatenate(([0], bordes + 1))
        finales = np.concatenate((bordes + 1, [malas.size]))
        wl = self.wavelengths
        return [(float(wl[i]), float(wl[f - 1]))
                for i, f in zip(inicios, finales) if malas[i]]

    def copia(self, **cambios):
        """Una mascara igual con algo cambiado. La interfaz la usa asi."""
        opciones = dict(bbl=self.bbl, usar_bbl=self.usar_bbl,
                        usar_absorcion=self.usar_absorcion,
                        usar_extremos=self.usar_extremos,
                        rangos=list(self.rangos))
        opciones.update(cambios)
        return MascaraBandas(self.wavelengths, **opciones)

    def __repr__(self):
        return "<MascaraBandas %s>" % self.describir()


def parsear_rangos(texto):
    """Lee rangos escritos a mano: "1340-1460, 1790-1960" o "900".

    Acepta guion, dos puntos o la palabra "a" como separador, y un valor
    suelto para descartar una sola banda. Lo que no se entiende se ignora en
    silencio: el campo se escribe mientras se mira el grafico, y detener al
    usuario con un error a media palabra es peor que no aplicar todavia el
    rango que aun no termino de escribir.
    """
    rangos = []
    for trozo in re.split(r"[,;]", texto or ""):
        trozo = trozo.strip()
        if not trozo:
            continue
        # Sin signo a proposito. Con "[-+]?" el guion separador se lee como
        # signo del segundo numero y "1340-1460" da (-1460, 1340): un rango
        # al reves que no descarta nada y que nadie mira. Una longitud de
        # onda negativa no existe, asi que el signo no hace falta.
        numeros = re.findall(r"\d+(?:[.,]\d+)?", trozo)
        try:
            valores = [float(n.replace(",", ".")) for n in numeros]
        except ValueError:
            continue
        if len(valores) >= 2:
            rangos.append((min(valores[0], valores[1]),
                           max(valores[0], valores[1])))
        elif len(valores) == 1:
            rangos.append((valores[0], valores[0]))
    return rangos


def formatear_rangos(rangos):
    """El reves de parsear_rangos, para volver a poner el texto en la caja."""
    partes = []
    for lo, hi in rangos:
        if lo == hi:
            partes.append("%g" % lo)
        else:
            partes.append("%g-%g" % (lo, hi))
    return ", ".join(partes)
