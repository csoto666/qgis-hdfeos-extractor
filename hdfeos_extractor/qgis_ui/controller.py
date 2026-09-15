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
"""El controlador que enlaza las vistas. El hito mas importante del diseno.

Toda interaccion pasa por aca y sale como senal: clic en un pixel, linea
movida en X o en Y, bandas RGB cambiadas, firma elegida de la biblioteca. Las
vistas no se hablan entre ellas -el mapa no conoce el grafico y el grafico no
conoce la lista de firmas-; hablan con el controlador, y el controlador avisa.

Sin esto, enlazar cinco vistas son veinte conexiones y cada vista nueva las
multiplica. Con esto son cinco.

Importa Qt, para las senales, pero NO importa QGIS. Es deliberado: asi la
logica de enlace se puede probar sin abrir QGIS, que es donde de verdad se
esconden los errores de este archivo. Lo especifico de QGIS -herramientas de
mapa, renderizador de la capa- vive en los otros modulos de este paquete.
"""

import numpy as np

from ..core.geo import GeoTransform
from ..core.library import SpectralLibrary
from ..core.rgb import RGBComposer
from ..core.spectral import (SpectralProfile, signature_from_pixel,
                             signature_from_pixels, signature_from_roi,
                             statistics)
from ..vista.qt import QtCore, pyqtSignal
from ..vista.spectral_plot import COLOR_ACTUAL, Curva, color_de

#: Modos de navegacion espacial.
MODO_PIXEL, MODO_X, MODO_Y, MODO_AREA = "pixel", "x", "y", "area"

#: Cuantos espectros se resumen al recorrer un transecto. La media sola
#: esconde justamente lo que el usuario esta buscando -como cambia la
#: respuesta a lo largo de la linea-, asi que se dibujan tambien los extremos.
COLOR_TRANSECTO = "#6a51a3"


class SpatialSpectralController(QtCore.QObject):
    """Une imagen, posicion y espectro."""

    cuboCambiado = pyqtSignal(object)          # HyperspectralCube o None
    pixelCambiado = pyqtSignal(int, int)
    transectoCambiado = pyqtSignal(str, int)   # eje, posicion
    composicionCambiada = pyqtSignal(object)   # RGBComposer
    curvasCambiadas = pyqtSignal(list)         # [Curva, ...]
    bibliotecaCambiada = pyqtSignal()
    mascaraCambiada = pyqtSignal(object)       # MascaraBandas
    mensaje = pyqtSignal(str)

    def __init__(self, parent=None):
        super(SpatialSpectralController, self).__init__(parent)
        self.cube = None
        self.layer = None
        self.geo = GeoTransform.identidad()
        self.composer = RGBComposer()
        self.profile = SpectralProfile()
        self.library = SpectralLibrary()
        self.modo = MODO_PIXEL
        self.pixel = None                      # (x, y) del ultimo clic
        self.transecto = None                  # (eje, posicion)
        self._firma_actual = None
        self._resumen_transecto = None

    # -- cubo ---------------------------------------------------------------
    def set_cube(self, cube, layer=None, geo=None):
        """Cambia el cubo activo y reinicia lo que dependia del anterior.

        Las firmas en pantalla se borran y las de la biblioteca no. Es la
        distincion que separa las dos colecciones: el grafico muestra lo que
        se esta mirando ahora, la biblioteca guarda lo que el usuario decidio
        conservar, que es justamente lo que sirve para comparar entre escenas.

        El cubo anterior se cierra. Sin eso su memoria mapeada queda viva
        mientras el usuario abra escenas, y en Windows el archivo sigue
        bloqueado: no se puede mover ni reescribir desde QGIS.
        """
        if self.cube is not None and self.cube is not cube:
            self.cube.close()
        self.cube = cube
        self.layer = layer
        self.geo = geo or GeoTransform.identidad()
        self.profile = SpectralProfile(cube)
        self.pixel = None
        self.transecto = None
        self._firma_actual = None
        self._resumen_transecto = None
        if cube is not None:
            self._ajustar_composicion(cube)
        self.cuboCambiado.emit(cube)
        if cube is not None:
            self.mascaraCambiada.emit(cube.mask)
        self.composicionCambiada.emit(self.composer)
        self._emitir_curvas()

    def _ajustar_composicion(self, cube):
        """Elige un preset que el sensor alcance.

        Abrir un cubo VNIR con el compositor puesto en un preset SWIR da una
        imagen gris: las tres bandas se resuelven a la ultima. Mejor moverlo
        de entrada que hacer que el usuario lo descubra.
        """
        aplicables = RGBComposer.presets_aplicables(cube)
        actuales = (self.composer.red, self.composer.green, self.composer.blue)
        lo, hi = float(np.nanmin(cube.wavelengths)), \
            float(np.nanmax(cube.wavelengths))
        if all(lo - 60.0 <= w <= hi + 60.0 for w in actuales):
            return
        if aplicables:
            self.composer.set_preset(aplicables[0])
        else:
            # Ningun preset sirve -un cubo sin longitudes de onda, por
            # ejemplo-. Se reparten tres bandas a lo largo del rango.
            wl = cube.wavelengths
            self.composer.set_bands(wl[-1], wl[len(wl) // 2], wl[0])

    def close_cube(self):
        if self.cube is not None:
            self.cube.close()
        self.set_cube(None)

    # -- interaccion espacial -----------------------------------------------
    def on_pixel_changed(self, x, y):
        """Un pixel fue elegido en el mapa. La operacion central del plugin."""
        if self.cube is None:
            return None
        try:
            firma = signature_from_pixel(self.cube, x, y)
        except Exception as exc:
            self.mensaje.emit(str(exc))
            return None
        self.pixel = (int(x), int(y))
        self.modo = MODO_PIXEL
        self._firma_actual = firma
        self._resumen_transecto = None
        self.pixelCambiado.emit(int(x), int(y))
        self._emitir_curvas()
        return firma

    def on_x_changed(self, x):
        """La linea vertical se movio a la columna ``x``."""
        return self._transecto("x", x)

    def on_y_changed(self, y):
        """La linea horizontal se movio a la fila ``y``."""
        return self._transecto("y", y)

    def _transecto(self, eje, posicion):
        if self.cube is None:
            return None
        try:
            plano = self.cube.get_transect(eje, posicion)
        except Exception as exc:
            self.mensaje.emit(str(exc))
            return None
        self.modo = MODO_X if eje == "x" else MODO_Y
        self.transecto = (eje, int(posicion))
        self._resumen_transecto = statistics(plano)
        self._firma_actual = None
        self.transectoCambiado.emit(eje, int(posicion))
        self._emitir_curvas()
        return self._resumen_transecto

    def on_area_selected(self, x0, y0, x1, y1):
        """Se dibujo un rectangulo sobre la imagen."""
        if self.cube is None:
            return None
        try:
            firma = signature_from_roi(self.cube, x0, y0, x1, y1)
        except Exception as exc:
            self.mensaje.emit(str(exc))
            return None
        self.modo = MODO_AREA
        self.pixel = None
        self._firma_actual = firma
        self._resumen_transecto = None
        self._emitir_curvas()
        return firma

    def on_pixels_selected(self, coords):
        """Varios pixeles sueltos, elegidos uno por uno."""
        if self.cube is None or not coords:
            return None
        try:
            firma = signature_from_pixels(self.cube, coords)
        except Exception as exc:
            self.mensaje.emit(str(exc))
            return None
        self.modo = MODO_AREA
        self._firma_actual = firma
        self._resumen_transecto = None
        self._emitir_curvas()
        return firma

    # -- composicion --------------------------------------------------------
    def on_rgb_changed(self, red=None, green=None, blue=None):
        self.composer.set_bands(red, green, blue)
        self.composicionCambiada.emit(self.composer)
        self._emitir_curvas()          # los marcadores del grafico se mueven
        return self.composer

    def on_preset_selected(self, nombre):
        try:
            self.composer.set_preset(nombre)
        except KeyError:
            self.mensaje.emit("No existe el preset '%s'" % nombre)
            return None
        self.composicionCambiada.emit(self.composer)
        self._emitir_curvas()
        return self.composer

    def on_stretch_changed(self, modo):
        self.composer.modo = modo
        self.composicionCambiada.emit(self.composer)
        return self.composer

    def marcadores_rgb(self):
        """Las tres longitudes de onda reales que alimentan la imagen."""
        if self.cube is None:
            return []
        return list(self.composer.wavelengths_of(self.cube))

    # -- bandas malas -------------------------------------------------------
    @property
    def mask(self):
        return None if self.cube is None else self.cube.mask

    def on_mask_changed(self, **cambios):
        """Cambia que bandas entran al analisis y rehace todo lo que depende.

        Rehacer es barato y olvidarse no: si la firma en pantalla se
        recalculara y el cubo no, las caras del cubo mostrarian bandas que el
        grafico ya descarto, y la imagen y la curva dirian cosas distintas.
        """
        if self.cube is None:
            return None
        mascara = self.cube.set_mask(self.cube.mask.copia(**cambios))
        # La firma que estaba en pantalla salio con la mascara anterior.
        if self._firma_actual is not None and self.pixel is not None:
            self.on_pixel_changed(*self.pixel)
        elif self.transecto is not None:
            self._transecto(*self.transecto)
        self.mascaraCambiada.emit(mascara)
        # Un preset pudo quedar sobre una banda que ahora esta descartada.
        self.composicionCambiada.emit(self.composer)
        self._emitir_curvas()
        return mascara

    def tramos_descartados(self):
        """Los tramos descartados, para sombrearlos en el grafico."""
        return [] if self.cube is None else self.cube.mask.tramos_malos()

    # -- biblioteca ---------------------------------------------------------
    def save_current(self, nombre=None, notas=""):
        """Guarda en la biblioteca la firma que se esta viendo."""
        if self._firma_actual is None:
            self.mensaje.emit("No hay ninguna firma seleccionada para guardar")
            return None
        firma = self._firma_actual
        if nombre:
            firma.name = nombre
        if notas:
            firma.notes = notas
        firma.color = color_de(len(self.library))
        self.library.add(firma)
        # La firma guardada deja de ser "la actual": si siguiera siendolo, el
        # proximo clic la modificaria dentro de la biblioteca.
        self._firma_actual = None
        self.bibliotecaCambiada.emit()
        self._emitir_curvas()
        return firma

    def on_signature_selected(self, nombre):
        """Marca una firma como unica visible. Devuelve la firma."""
        try:
            firma = self.library.get(nombre)
        except KeyError:
            return None
        for f in self.library:
            f.visible = f is firma
        self.bibliotecaCambiada.emit()
        self._emitir_curvas()
        return firma

    def set_signature_visible(self, nombre, visible):
        try:
            self.library.set_visible(nombre, visible)
        except KeyError:
            return
        self.bibliotecaCambiada.emit()
        self._emitir_curvas()

    def remove_signature(self, nombre):
        if self.library.remove(nombre):
            self.bibliotecaCambiada.emit()
            self._emitir_curvas()
            return True
        return False

    def rename_signature(self, viejo, nuevo):
        try:
            firma = self.library.rename(viejo, nuevo)
        except Exception as exc:
            self.mensaje.emit(str(exc))
            return None
        self.bibliotecaCambiada.emit()
        self._emitir_curvas()
        return firma

    def compare_current(self):
        """Contra que firma guardada se parece lo que se esta viendo."""
        if self._firma_actual is None or not len(self.library):
            return None
        return self.library.match(self._firma_actual)

    # -- lo que el grafico dibuja -------------------------------------------
    @property
    def firma_actual(self):
        return self._firma_actual

    def curvas(self):
        """Arma la lista de curvas a dibujar, en orden de importancia.

        Primero lo guardado y visible, despues el resumen del transecto, y al
        final la firma actual en negro y por encima de todo: es la que el
        usuario acaba de pedir y tiene que poder distinguirla de un vistazo.
        """
        salida = []
        for i, f in enumerate(self.library):
            if not f.visible:
                continue
            salida.append(Curva(f.name, f.wavelengths, f.values,
                                f.color or color_de(i), ancho=2,
                                banda=f.std))
        if self._resumen_transecto is not None and self.cube is not None:
            e = self._resumen_transecto
            eje, pos = self.transecto
            salida.append(Curva(
                "media %s=%d (%d px)" % (eje, pos, e["n"]),
                self.cube.wavelengths, e["mean"], COLOR_TRANSECTO,
                ancho=2, banda=e["std"]))
            # Los extremos son lo que el usuario esta buscando al mover la
            # linea: la media sola esconde justamente la variacion.
            salida.append(Curva("minimo", self.cube.wavelengths, e["min"],
                                COLOR_TRANSECTO, ancho=1, punteada=True))
            salida.append(Curva("maximo", self.cube.wavelengths, e["max"],
                                COLOR_TRANSECTO, ancho=1, punteada=True))
        if self._firma_actual is not None:
            f = self._firma_actual
            salida.append(Curva(f.name, f.wavelengths, f.values, COLOR_ACTUAL,
                                ancho=2, banda=f.std))
        return salida

    def _emitir_curvas(self):
        self.curvasCambiadas.emit(self.curvas())
