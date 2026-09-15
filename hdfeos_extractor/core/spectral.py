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
"""Firmas espectrales: extraccion, estadisticas y el conjunto que se dibuja.

Una *firma* es un espectro con procedencia. El vector de reflectancia solo no
sirve para nada seis meses despues: hay que saber de que escena salio, de que
pixel, cuando, y que creia el usuario que estaba muestreando. Por eso
``Signature`` guarda todo eso junto y es lo que viaja a la biblioteca, al CSV
y al grafico.
"""

import contextlib
import datetime
import warnings

import numpy as np


@contextlib.contextmanager
def sin_avisos_de_rebanada_vacia():
    """Calla los avisos de numpy al promediar una banda entera de NaN.

    Con la mascara de bandas malas puesta, una banda descartada es NaN en
    todos los pixeles, y nanmean y nanstd avisan "Mean of empty slice" y
    "Degrees of freedom <= 0". Ahora eso es lo normal y no una anomalia: sin
    esto, cada firma de area llena el registro de QGIS de avisos que no
    significan nada y que tapan los que si.

    errstate no alcanza: estos son avisos de Python, no estados de punto
    flotante.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", r"Mean of empty slice",
                                RuntimeWarning)
        warnings.filterwarnings("ignore", r"Degrees of freedom <= 0",
                                RuntimeWarning)
        warnings.filterwarnings("ignore", r"All-NaN slice encountered",
                                RuntimeWarning)
        with np.errstate(invalid="ignore"):
            yield


def _ahora():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


class Signature(object):
    """Un espectro con su procedencia.

    ``pixels`` es una lista de ``(x, y)``: un solo par para una firma de
    pixel, varios para una firma de area. Se guarda la lista completa y no
    solo el centroide porque es lo unico que permite volver a extraer la
    firma del cubo original y comprobarla.
    """

    def __init__(self, name, wavelengths, values, pixels=None, source=None,
                 notes="", color=None, visible=True, created=None,
                 std=None, count=1):
        self.name = name
        self.wavelengths = np.asarray(wavelengths, dtype=np.float64)
        self.values = np.asarray(values, dtype=np.float32)
        if self.wavelengths.size != self.values.size:
            raise ValueError(
                "La firma '%s' tiene %d longitudes de onda y %d valores"
                % (name, self.wavelengths.size, self.values.size))
        self.pixels = [tuple(int(v) for v in p) for p in (pixels or [])]
        self.source = source or ""
        self.notes = notes
        self.color = color
        self.visible = visible
        self.created = created or _ahora()
        # Desviacion por banda: solo existe cuando la firma es de un area.
        self.std = None if std is None else np.asarray(std, dtype=np.float32)
        self.count = int(count)

    @property
    def is_area(self):
        return self.count > 1

    def to_dict(self):
        """Forma serializable. Los NaN salen como None: JSON no tiene NaN."""
        return {
            "name": self.name,
            "notes": self.notes,
            "source": self.source,
            "created": self.created,
            "color": self.color,
            "visible": self.visible,
            "count": self.count,
            "pixels": [list(p) for p in self.pixels],
            "wavelengths": [float(v) for v in self.wavelengths],
            "values": _sin_nan(self.values),
            "std": None if self.std is None else _sin_nan(self.std),
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"],
            wavelengths=d["wavelengths"],
            values=[np.nan if v is None else v for v in d["values"]],
            pixels=d.get("pixels") or [],
            source=d.get("source", ""),
            notes=d.get("notes", ""),
            color=d.get("color"),
            visible=d.get("visible", True),
            created=d.get("created"),
            std=(None if d.get("std") is None
                 else [np.nan if v is None else v for v in d["std"]]),
            count=d.get("count", 1))

    def __repr__(self):
        clase = "area de %d px" % self.count if self.is_area else "pixel"
        return "<Signature %r (%s), %d bandas>" % (
            self.name, clase, self.values.size)


def _sin_nan(vector):
    return [None if not np.isfinite(v) else float(v) for v in vector]


# -----------------------------------------------------------------------------
#  Extraccion
# -----------------------------------------------------------------------------
def signature_from_pixel(cube, x, y, name=None, notes=""):
    """Firma de un solo pixel."""
    valores = cube.get_spectrum(x, y)
    return Signature(
        name=name or "px %d,%d" % (int(x), int(y)),
        wavelengths=cube.wavelengths, values=valores,
        pixels=[(x, y)], source=cube.name, notes=notes)


def signature_from_pixels(cube, coords, name=None, notes=""):
    """Firma media de varios pixeles sueltos, con su desviacion por banda."""
    espectros = cube.get_pixels(coords)
    return _promediar(cube, espectros, coords,
                      name or "seleccion de %d px" % len(coords), notes)


def signature_from_roi(cube, x0, y0, x1, y1, name=None, notes=""):
    """Firma media de un rectangulo.

    Los pixeles enteramente de relleno se descartan antes de promediar. Si no
    se hiciera, un area que toca el borde de una escena en geometria de
    sensor arrastraria el NaN a todas las bandas y la firma saldria vacia.
    """
    roi = cube.get_roi(x0, y0, x1, y1)
    alto, ancho, bandas = roi.shape
    plano = roi.reshape(alto * ancho, bandas)
    utiles = np.isfinite(plano).any(axis=1)
    plano = plano[utiles]
    if plano.size == 0:
        raise ValueError("El area seleccionada es toda relleno")
    x0, x1 = sorted((int(x0), int(x1)))
    y0, y1 = sorted((int(y0), int(y1)))
    coords = [(x0 + j, y0 + i) for i in range(alto) for j in range(ancho)]
    coords = [c for c, u in zip(coords, utiles) if u]
    return _promediar(cube, plano, coords,
                      name or "area %d,%d-%d,%d" % (x0, y0, x1, y1), notes)


def _promediar(cube, espectros, coords, name, notes):
    """Construye una firma de area a partir de una matriz (n_pixeles, banda).

    ``nanmean`` y ``nanstd`` y no ``mean``/``std``: una sola banda invalida en
    un solo pixel del area bastaria para anular esa banda en la media de todo
    el poligono.
    """
    with sin_avisos_de_rebanada_vacia():
        media = np.nanmean(espectros, axis=0)
        desv = np.nanstd(espectros, axis=0)
    return Signature(name=name, wavelengths=cube.wavelengths, values=media,
                     pixels=coords, source=cube.name, notes=notes,
                     std=desv, count=espectros.shape[0])


# -----------------------------------------------------------------------------
#  Estadisticas y comparacion
# -----------------------------------------------------------------------------
def statistics(espectros):
    """Media, minimo, maximo y desviacion por banda de una matriz de espectros.

    Devuelve un diccionario, no una tupla: quien lo consume pide por nombre y
    no tiene que recordar el orden.
    """
    datos = np.atleast_2d(np.asarray(espectros, dtype=np.float32))
    with sin_avisos_de_rebanada_vacia():
        return {
            "n": int(datos.shape[0]),
            "mean": np.nanmean(datos, axis=0),
            "min": np.nanmin(datos, axis=0),
            "max": np.nanmax(datos, axis=0),
            "std": np.nanstd(datos, axis=0),
        }


def spectral_angle(a, b, en_grados=True):
    """Angulo espectral entre dos firmas (SAM).

    Es la medida de parecido correcta entre espectros porque compara la forma
    y no la magnitud: la misma cubierta en sombra y al sol da curvas a alturas
    distintas y con el mismo angulo. Las bandas que son NaN en cualquiera de
    las dos se excluyen del calculo.
    """
    va = np.asarray(_valores(a), dtype=np.float64)
    vb = np.asarray(_valores(b), dtype=np.float64)
    if va.size != vb.size:
        raise ValueError(
            "No se pueden comparar firmas de %d y %d bandas. "
            "Hay que remuestrearlas al mismo eje espectral primero."
            % (va.size, vb.size))
    util = np.isfinite(va) & np.isfinite(vb)
    if util.sum() < 2:
        raise ValueError("Las dos firmas no comparten bandas validas")
    va, vb = va[util], vb[util]
    norma = np.linalg.norm(va) * np.linalg.norm(vb)
    if norma == 0:
        raise ValueError("Una de las firmas es toda ceros")
    # El clip evita que el error de redondeo saque el coseno de [-1, 1] y
    # arccos devuelva NaN para dos firmas identicas.
    coseno = float(np.clip(np.dot(va, vb) / norma, -1.0, 1.0))
    angulo = np.arccos(coseno)
    return float(np.degrees(angulo)) if en_grados else float(angulo)


def _valores(firma):
    return firma.values if isinstance(firma, Signature) else firma


class SpectralProfile(object):
    """El conjunto de firmas que el grafico esta mostrando ahora.

    Distinto de ``SpectralLibrary``: esto es lo que se ve, aquello es lo que
    se guarda. Una firma puede estar aca sin haberse guardado nunca -el
    espectro que aparece al pasar el raton- y puede estar en la biblioteca
    sin estar visible.
    """

    def __init__(self, cube=None):
        self.cube = cube
        self._firmas = []

    def __len__(self):
        return len(self._firmas)

    def __iter__(self):
        return iter(self._firmas)

    @property
    def signatures(self):
        return list(self._firmas)

    @property
    def visible(self):
        return [f for f in self._firmas if f.visible]

    def get_signature(self, x, y, name=None):
        """Extrae la firma de un pixel del cubo asociado, sin agregarla."""
        if self.cube is None:
            raise ValueError("Este perfil no tiene cubo asociado")
        return signature_from_pixel(self.cube, x, y, name=name)

    def add_signature(self, firma):
        """Agrega una firma. Si el nombre ya existe se le pone un sufijo.

        Renombrar en vez de reemplazar: el usuario que hace clic dos veces en
        dos pixeles de vegetacion quiere las dos curvas para compararlas, no
        que la segunda borre a la primera.
        """
        usados = {f.name for f in self._firmas}
        if firma.name in usados:
            base, n = firma.name, 2
            while "%s (%d)" % (base, n) in usados:
                n += 1
            firma.name = "%s (%d)" % (base, n)
        self._firmas.append(firma)
        return firma

    def remove_signature(self, nombre_o_firma):
        """Quita una firma por nombre o por referencia. True si estaba."""
        antes = len(self._firmas)
        if isinstance(nombre_o_firma, Signature):
            self._firmas = [f for f in self._firmas if f is not nombre_o_firma]
        else:
            self._firmas = [f for f in self._firmas
                            if f.name != nombre_o_firma]
        return len(self._firmas) != antes

    def clear(self):
        self._firmas = []

    def statistics(self, solo_visibles=True):
        """Estadisticas por banda sobre las firmas del conjunto.

        Devuelve None cuando no hay ninguna, o cuando no todas comparten el
        largo del eje espectral: promediar firmas de sensores distintos sin
        remuestrear da un numero, pero no significa nada.
        """
        firmas = self.visible if solo_visibles else self._firmas
        if not firmas:
            return None
        largos = {f.values.size for f in firmas}
        if len(largos) > 1:
            return None
        return statistics(np.vstack([f.values for f in firmas]))
