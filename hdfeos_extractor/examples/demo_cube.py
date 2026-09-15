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
"""Demostracion del nucleo sin QGIS: python3 examples/demo_cube.py

Genera una escena sintetica con tres cubiertas de firma conocida -vegetacion,
suelo y agua-, la escribe como ENVI y despues la explora con la misma API que
usa el plugin. Sirve para dos cosas:

1. Comprobar que el nucleo funciona en una instalacion cualquiera, sin QGIS
   y sin conseguir un cubo de verdad de 500 MB.
2. Ver, en el ultimo paso, que el angulo espectral reconoce cada cubierta.
   Si eso sale, la cadena entera -lectura, escala, extraccion, comparacion-
   esta bien encadenada.

Lo unico que hace falta es numpy.
"""

import os
import sys
import tempfile

import numpy as np

# La ruta se arregla antes de importar el paquete, para que el ejemplo corra
# desde una copia del repositorio sin instalar nada.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from hdfeos_extractor.core import (  # noqa: E402
    HyperspectralCube, RGBComposer, SpectralLibrary, signature_from_pixel,
    signature_from_roi, spectral_angle)

LINEAS, MUESTRAS, BANDAS = 120, 160, 120
LONGITUDES = np.linspace(400.0, 2450.0, BANDAS)


# -----------------------------------------------------------------------------
#  Escena sintetica
# -----------------------------------------------------------------------------
def firma_vegetacion(wl):
    """Verde bajo, borde rojo hacia 700 nm, meseta NIR y caidas de agua."""
    curva = np.full_like(wl, 0.03)
    curva += 0.06 * np.exp(-((wl - 550.0) / 40.0) ** 2)       # pico verde
    curva += 0.42 / (1.0 + np.exp(-(wl - 720.0) / 18.0))      # borde rojo
    curva -= 0.12 / (1.0 + np.exp(-(wl - 1400.0) / 90.0))     # agua foliar
    curva -= 0.10 / (1.0 + np.exp(-(wl - 1900.0) / 90.0))
    return np.clip(curva, 0.01, None)


def firma_suelo(wl):
    """Ascenso suave y monotono, con las dos absorciones de arcilla."""
    curva = 0.10 + 0.22 * (wl - wl[0]) / (wl[-1] - wl[0])
    curva -= 0.05 * np.exp(-((wl - 2200.0) / 45.0) ** 2)
    curva -= 0.03 * np.exp(-((wl - 1400.0) / 35.0) ** 2)
    return curva


def firma_agua(wl):
    """Alta en el azul y practicamente cero pasado el NIR."""
    return np.clip(0.07 * np.exp(-((wl - 450.0) / 180.0) ** 2) + 0.004,
                   0.001, None)


def escena_sintetica():
    """Devuelve (cubo, clases): un rio en diagonal y un parche de suelo."""
    y, x = np.mgrid[0:LINEAS, 0:MUESTRAS]
    clases = np.zeros((LINEAS, MUESTRAS), dtype=np.uint8)      # 0 vegetacion
    clases[np.abs(y - 0.6 * x - 10) < 7] = 2                   # 2 agua
    clases[(y > 80) & (x > 100)] = 1                           # 1 suelo

    puras = np.vstack([firma_vegetacion(LONGITUDES),
                       firma_suelo(LONGITUDES),
                       firma_agua(LONGITUDES)]).astype(np.float32)
    cubo = puras[clases]

    # Ruido y un gradiente de iluminacion. El gradiente importa: es lo que
    # hace que comparar por magnitud falle y comparar por angulo funcione.
    rng = np.random.default_rng(42)
    cubo = cubo * (0.85 + 0.3 * (x / MUESTRAS))[:, :, None]
    cubo = cubo + rng.normal(0.0, 0.004, cubo.shape)
    return np.clip(cubo, 0.0, None).astype(np.float32), clases


def escribir_envi(carpeta, cubo):
    """Escribe el cubo como ENVI BIL con su eje espectral en la cabecera."""
    ruta = os.path.join(carpeta, "demo.dat")
    # BIL: (lineas, bandas, muestras)
    cubo.transpose(0, 2, 1).astype("<f4").tofile(ruta)
    txt = ["%.3f" % v for v in LONGITUDES]
    filas = [", ".join(txt[i:i + 8]) for i in range(0, len(txt), 8)]
    with open(os.path.join(carpeta, "demo.hdr"), "w", encoding="utf-8") as f:
        f.write("\n".join([
            "ENVI",
            "description = {escena sintetica de demostracion}",
            "samples = %d" % MUESTRAS,
            "lines = %d" % LINEAS,
            "bands = %d" % BANDAS,
            "header offset = 0",
            "file type = ENVI Standard",
            "data type = 4",
            "interleave = bil",
            "byte order = 0",
            "wavelength units = Nanometers",
            "wavelength = {\n " + ",\n ".join(filas) + "}",
        ]) + "\n")
    return ruta


# -----------------------------------------------------------------------------
#  Recorrido
# -----------------------------------------------------------------------------
def titulo(texto):
    print("\n" + texto)
    print("-" * len(texto))


def main():
    carpeta = tempfile.mkdtemp(prefix="hyperexplorer-demo-")
    datos, clases = escena_sintetica()
    ruta = escribir_envi(carpeta, datos)
    print("Escena sintetica escrita en %s" % ruta)

    with HyperspectralCube.load(ruta) as cubo:
        titulo("1. Cubo abierto")
        print(cubo)
        print("  forma (lineas, muestras, bandas) = (%d, %d, %d)"
              % (cubo.lines, cubo.samples, cubo.bands))
        print("  eje espectral  = %.1f .. %.1f %s"
              % (cubo.wavelengths[0], cubo.wavelengths[-1],
                 cubo.unidad_espectral))

        titulo("2. Composicion RGB")
        for nombre in RGBComposer.presets_aplicables(cubo):
            comp = RGBComposer()
            comp.set_preset(nombre)
            r, g, b = comp.wavelengths_of(cubo)
            print("  %-20s R=%7.1f  G=%7.1f  B=%7.1f nm"
                  % (nombre, r, g, b))
        comp = RGBComposer(842.0, 665.0, 560.0)    # el ejemplo del diseno
        rgb = comp.create_composite(cubo)
        print("  imagen compuesta: %s, %s" % (rgb.shape, rgb.dtype))
        previa, paso = cubo.preview_band(wavelength=842.0, max_lado=64)
        print("  vista previa: %s (submuestreo 1/%d) - el analisis sigue "
              "sobre el dato original" % (previa.shape, paso))

        titulo("3. Un pixel es un espectro")
        muestras = {"vegetacion": (20, 100), "suelo": (140, 100),
                    "agua": (40, 35)}
        for nombre, (x, y) in muestras.items():
            esp = cubo.get_spectrum(x, y)
            print("  %-11s (%3d,%3d)  550nm=%.3f  842nm=%.3f  2200nm=%.3f"
                  % (nombre, x, y,
                     esp[cubo.band_index(550)], esp[cubo.band_index(842)],
                     esp[cubo.band_index(2200)]))

        titulo("4. Navegacion X/Y")
        tx = cubo.get_transect("x", 80)
        ty = cubo.get_transect("y", 60)
        print("  columna x=80  ->  %s  (fila, banda)" % (tx.shape,))
        print("  fila    y=60  ->  %s  (columna, banda)" % (ty.shape,))
        nir = cubo.band_index(842)
        perfil = ty[:, nir]
        print("  NIR a lo largo de y=60: min=%.3f  max=%.3f" %
              (np.nanmin(perfil), np.nanmax(perfil)))
        cruce = np.flatnonzero(np.diff(clases[60, :] == 2) != 0)
        print("  el rio cruza esa fila en las columnas %s"
              % ([int(v) for v in cruce] or "ninguna"))

        titulo("5. Area y variabilidad")
        area = signature_from_roi(cubo, 130, 90, 155, 115, name="Suelo (area)")
        print("  %s sobre %d pixeles" % (area.name, area.count))
        print("  desviacion media entre bandas = %.4f"
              % float(np.nanmean(area.std)))

        titulo("6. Biblioteca espectral")
        biblioteca = SpectralLibrary()
        for nombre, (x, y) in muestras.items():
            biblioteca.add(signature_from_pixel(
                cubo, x, y, name=nombre.capitalize(),
                notes="muestreado en la demo"))
        destino = os.path.join(carpeta, "biblioteca.json")
        biblioteca.save(destino)
        forma = biblioteca.to_csv(os.path.join(carpeta, "biblioteca.csv"))
        print("  %d firmas -> %s" % (len(biblioteca), destino))
        print("  CSV exportado en forma %s" % forma)
        vuelta = SpectralLibrary.load(destino)
        print("  releida: %s" % ", ".join(vuelta.names()))

        titulo("7. Comprobacion: el angulo espectral reconoce la cubierta")
        print("  La escena tiene un gradiente de iluminacion de lado a lado,")
        print("  asi que los pixeles de prueba son mas brillantes que las")
        print("  firmas guardadas. El angulo compara forma, no magnitud.\n")
        pruebas = {"vegetacion": (150, 20), "suelo": (150, 110),
                   "agua": (80, 55)}
        aciertos = 0
        for esperado, (x, y) in pruebas.items():
            candidato = signature_from_pixel(cubo, x, y, name="?")
            nombre, angulo = vuelta.match(candidato)
            ok = nombre.lower() == esperado
            aciertos += ok
            print("  pixel (%3d,%3d) esperado %-11s -> %-11s %5.2f deg  %s"
                  % (x, y, esperado, nombre, angulo, "ok" if ok else "FALLA"))

        peor = max(spectral_angle(vuelta.get(a), vuelta.get(b))
                   for a in vuelta.names() for b in vuelta.names() if a != b)
        print("\n  %d de %d cubiertas reconocidas" % (aciertos, len(pruebas)))
        print("  separacion maxima entre firmas guardadas: %.1f deg" % peor)

    print("\nSalidas en %s" % carpeta)
    return 0 if aciertos == len(pruebas) else 1


if __name__ == "__main__":
    sys.exit(main())
