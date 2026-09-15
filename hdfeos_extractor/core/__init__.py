# -*- coding: utf-8 -*-
"""Nucleo hiperespectral: no importa QGIS ni Qt.

Separarlo del plugin no es prolijidad: es lo que permite que el mismo codigo
se use desde Jupyter, desde un script suelto o desde otra interfaz sin
arrastrar QGIS detras. Todo lo que este paquete necesita es numpy; GDAL y
xarray se usan si estan y no se exigen.
"""

from .colormap import PALETAS, colorear
from .cube import CubeError, HyperspectralCube
from .hdf5 import Hdf5Source, es_hdf5
from .envi import EnviError, EnviHeader, EnviSource
from .geo import GeoError, GeoTransform
from .library import LibraryError, SpectralLibrary
from .rgb import PRESETS, RGBComposer, estirar, limites
from .sources import GdalSource, MemorySource
from .spectral import (Signature, SpectralProfile, signature_from_pixel,
                       signature_from_pixels, signature_from_roi,
                       spectral_angle, statistics)

__all__ = [
    "PALETAS", "colorear",
    "CubeError", "HyperspectralCube",
    "Hdf5Source", "es_hdf5",
    "EnviError", "EnviHeader", "EnviSource",
    "GeoError", "GeoTransform",
    "GdalSource", "MemorySource",
    "PRESETS", "RGBComposer", "estirar", "limites",
    "Signature", "SpectralProfile", "signature_from_pixel",
    "signature_from_pixels", "signature_from_roi", "spectral_angle",
    "statistics",
    "LibraryError", "SpectralLibrary",
]
