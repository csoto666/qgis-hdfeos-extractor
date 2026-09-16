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
"""Algoritmo de Processing: HDF-EOS5 -> ENVI."""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from .compat import enum
from .lector import Escena, ErrorLectura, LINEAS_BLOQUE

# Enums calificados en QGIS reciente, planos en versiones previas. Se resuelve
# una sola vez aca para no repetir la llamada en cada parametro.
#
# Va por ``enum`` y no por un try/except aunque el try/except funcionaba: el
# verificador de compatibilidad con Qt6 del repositorio de complementos lee el
# codigo sin ejecutarlo, ve el nombre plano de la rama de respaldo y marca el
# archivo, sin manera de saber que esa rama solo corre en QGIS antiguo. Con
# los nombres en cadenas no hay nada plano que ver, y el comportamiento es el
# mismo.
_ARCHIVO = enum(QgsProcessingParameterFile, "Behavior", "File")
_ENTERO = enum(QgsProcessingParameterNumber, "Type", "Integer")
_AVANZADO = enum(QgsProcessingParameterNumber, "Flag",
                 "FlagAdvanced")


class ExtraerHdfEosAlgoritmo(QgsProcessingAlgorithm):
    """Extrae un cubo HDF-EOS5 y sus capas asociadas al formato ENVI."""

    ENTRADA = "ENTRADA"
    CUBO = "CUBO"
    IGM = "IGM"
    MASCARAS = "MASCARAS"
    ATMOSFERA = "ATMOSFERA"
    GEOMETRIA = "GEOMETRIA"
    CARPETA = "CARPETA"
    PREFIJO = "PREFIJO"
    BLOQUE = "BLOQUE"
    PREFERIR_H5PY = "PREFERIR_H5PY"

    # -- identidad -----------------------------------------------------------
    def name(self):
        return "extraer_hdfeos_a_envi"

    def displayName(self):
        return self.tr("HDF-EOS5 to ENVI / HDF-EOS5 a ENVI")

    def group(self):
        return self.tr("Hyperspectral")

    def groupId(self):
        return "hyperspectral"

    def createInstance(self):
        return ExtraerHdfEosAlgoritmo()

    def tr(self, texto):
        return texto

    def shortHelpString(self):
        return self.tr(
            "Extracts a hyperspectral cube stored in an HDF-EOS5 file "
            "(Planet Tanager and similar products) into ENVI's native "
            "format, so it can be opened by software that predates the "
            "product.\n\n"
            "The cube is written as BIL, the interleave ENVI expects for "
            "spectral processing. The header carries the centre wavelengths, "
            "the FWHM, the fill value, and a bad band list (bbl) with the "
            "water vapour absorption windows already flagged, so MNF, PPI "
            "and unmixing do not drag those bands along.\n\n"
            "Unorthorectified (basic) products come in sensor geometry with "
            "per-pixel latitude and longitude. Enabling the geolocation "
            "option writes an IGM file for ENVI's 'Georeference from Input "
            "Geometry'.\n\n"
            "Reads with h5py when available and falls back to GDAL, which "
            "always ships with QGIS.\n\n"
            "ESPANOL: extrae el cubo hiperespectral de un archivo HDF-EOS5 "
            "al formato nativo de ENVI, con longitudes de onda, FWHM y lista "
            "de bandas malas en la cabecera. Opcionalmente escribe el "
            "archivo de geometria de entrada (IGM) y las capas auxiliares "
            "2D: mascaras de nube y cirrus, aerosoles, vapor de agua y "
            "geometria sol-sensor."
        )

    # -- parametros ----------------------------------------------------------
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.ENTRADA,
            self.tr("HDF-EOS5 file / Archivo HDF-EOS5"),
            behavior=_ARCHIVO,
            fileFilter=self.tr("HDF5 (*.h5 *.he5 *.hdf5);; All files (*.*)")))

        self.addParameter(QgsProcessingParameterBoolean(
            self.CUBO,
            self.tr("Hyperspectral cube / Cubo hiperespectral"),
            defaultValue=True))

        self.addParameter(QgsProcessingParameterBoolean(
            self.IGM,
            self.tr("Geolocation IGM / IGM de geolocalizacion"),
            defaultValue=True))

        self.addParameter(QgsProcessingParameterBoolean(
            self.MASCARAS,
            self.tr("Masks: cloud, cirrus, nodata / Mascaras"),
            defaultValue=False))

        self.addParameter(QgsProcessingParameterBoolean(
            self.ATMOSFERA,
            self.tr("Atmosphere: AOD, water vapour / Atmosfera"),
            defaultValue=False))

        self.addParameter(QgsProcessingParameterBoolean(
            self.GEOMETRIA,
            self.tr("Sun-sensor geometry / Geometria sol-sensor"),
            defaultValue=False))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.CARPETA,
            self.tr("Output folder / Carpeta de salida")))

        self.addParameter(QgsProcessingParameterString(
            self.PREFIJO,
            self.tr("Output prefix (blank = input file name) / "
                    "Prefijo (vacio = nombre del archivo)"),
            defaultValue="", optional=True))

        avanzado = QgsProcessingParameterNumber(
            self.BLOQUE,
            self.tr("Lines per block (memory) / Lineas por bloque"),
            type=_ENTERO, defaultValue=LINEAS_BLOQUE, minValue=1,
            maxValue=4096)
        self._avanzado(avanzado)
        self.addParameter(avanzado)

        prefiere = QgsProcessingParameterBoolean(
            self.PREFERIR_H5PY,
            self.tr("Prefer h5py over GDAL / Preferir h5py sobre GDAL"),
            defaultValue=True)
        self._avanzado(prefiere)
        self.addParameter(prefiere)

    @staticmethod
    def _avanzado(parametro):
        """Marca un parametro como avanzado, con enums de cualquier version."""
        parametro.setFlags(parametro.flags() | _AVANZADO)

    # -- ejecucion -----------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        entrada = self.parameterAsFile(parameters, self.ENTRADA, context)
        carpeta = self.parameterAsString(parameters, self.CARPETA, context)
        prefijo = (self.parameterAsString(parameters, self.PREFIJO, context)
                   or "").strip()
        quiere_cubo = self.parameterAsBool(parameters, self.CUBO, context)
        quiere_igm = self.parameterAsBool(parameters, self.IGM, context)
        bloque = self.parameterAsInt(parameters, self.BLOQUE, context)
        preferir = self.parameterAsBool(parameters, self.PREFERIR_H5PY, context)

        categorias = []
        for clave, nombre in ((self.MASCARAS, "mascaras"),
                              (self.ATMOSFERA, "atmosfera"),
                              (self.GEOMETRIA, "geometria")):
            if self.parameterAsBool(parameters, clave, context):
                categorias.append(nombre)

        if not (quiere_cubo or quiere_igm or categorias):
            raise QgsProcessingException(
                self.tr("Nothing selected to extract. / "
                        "No seleccionaste nada para extraer."))

        if not os.path.isdir(carpeta):
            os.makedirs(carpeta, exist_ok=True)
        if not prefijo:
            prefijo = os.path.splitext(os.path.basename(entrada))[0]
        base = os.path.join(carpeta, prefijo)

        try:
            escena = Escena(entrada, preferir_h5py=preferir)
        except ErrorLectura as e:
            raise QgsProcessingException(str(e))

        salidas = {}
        try:
            for linea in escena.resumen().splitlines():
                feedback.pushInfo(linea)
            feedback.pushInfo("")

            if quiere_cubo:
                feedback.pushInfo(self.tr("Writing cube / Escribiendo cubo..."))
                ruta = escena.escribir_cubo(
                    base,
                    avance=feedback.setProgress,
                    cancelado=feedback.isCanceled,
                    lineas_bloque=bloque)
                if ruta is None:
                    feedback.reportError(
                        self.tr("Cancelled; partial cube deleted. / "
                                "Cancelado; se borro el cubo parcial."))
                    return {}
                salidas["CUBO"] = ruta
                feedback.pushInfo("  %s (%.0f MB)"
                                  % (ruta, os.path.getsize(ruta) / 1e6))

            if quiere_igm:
                ruta = escena.escribir_igm(base)
                if ruta:
                    salidas["IGM"] = ruta
                    feedback.pushInfo("  %s" % ruta)
                else:
                    feedback.pushWarning(
                        self.tr("No latitude/longitude in this file; the IGM "
                                "was not written. Ortho products do not need "
                                "it. / Sin lat/lon: no se escribio el IGM."))

            if categorias:
                rutas = escena.capas_2d(categorias)
                ruta = escena.escribir_auxiliares(base, rutas)
                if ruta:
                    salidas["AUXILIARES"] = ruta
                    feedback.pushInfo("  %s (%d bandas)" % (ruta, len(rutas)))
                else:
                    feedback.pushWarning(
                        self.tr("No matching 2D layers found. / "
                                "No hay capas 2D de esas categorias."))
        finally:
            escena.cerrar()

        salidas[self.CARPETA] = carpeta
        return salidas
