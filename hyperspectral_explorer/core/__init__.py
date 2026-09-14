# -*- coding: utf-8 -*-
"""Nucleo hiperespectral: no importa QGIS ni Qt.

Separarlo del plugin no es prolijidad: es lo que permite que el mismo codigo
se use desde Jupyter, desde un script suelto o desde otra interfaz sin
arrastrar QGIS detras. Todo lo que este paquete necesita es numpy; GDAL y
xarray se usan si estan y no se exigen.
"""

from .cube import CubeError, HyperspectralCube
from .envi import EnviError, EnviHeader, EnviSource
from .library import LibraryError, SpectralLibrary
from .rgb import PRESETS, RGBComposer, estirar
from .sources import GdalSource, MemorySource
from .spectral import (Signature, SpectralProfile, signature_from_pixel,
                       signature_from_pixels, signature_from_roi,
                       spectral_angle, statistics)

__all__ = [
    "CubeError", "HyperspectralCube",
    "EnviError", "EnviHeader", "EnviSource",
    "GdalSource", "MemorySource",
    "PRESETS", "RGBComposer", "estirar",
    "Signature", "SpectralProfile", "signature_from_pixel",
    "signature_from_pixels", "signature_from_roi", "spectral_angle",
    "statistics",
    "LibraryError", "SpectralLibrary",
]
