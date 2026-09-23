# -*- coding: utf-8 -*-
"""Pruebas de la huella espacial de una firma.

Donde se tomo una firma es un dato que el complemento ya tenia -la lista de
pixeles- y que no estaba usando. Aca se convierte en geometria de mapa.
"""

import numpy as np

from hdfeos_extractor.core.geo import GeoTransform
from hdfeos_extractor.core.huella import (TIPO_AREA, TIPO_PIXELES,
                                          TIPO_PUNTO, atributos_de_firma,
                                          huella_de_firma, tipo_de_firma)
from hdfeos_extractor.core.spectral import Signature

#: 10 m de pixel, esquina en un UTM cualquiera, norte arriba.
GT = GeoTransform((500000.0, 10.0, 0.0, 4000000.0, 0.0, -10.0))
#: La misma escena girada 30 grados, que es como llega una franja de sensor.
ANG = np.radians(30.0)
GIRADA = GeoTransform((500000.0, 10 * np.cos(ANG), -10 * np.sin(ANG),
                       4000000.0, -10 * np.sin(ANG), -10 * np.cos(ANG)))

WL = np.array([450.0, 550.0, 650.0, 850.0])


def firma(pixeles, nombre="una", color="#ff0000", notas=""):
    return Signature(nombre, WL, np.ones(WL.size), pixels=pixeles,
                     color=color, notes=notas, count=len(pixeles),
                     source="escena.h5")


# -- de que tipo es ----------------------------------------------------------
def test_un_solo_pixel_es_un_punto():
    assert tipo_de_firma(firma([(3, 4)])) == TIPO_PUNTO


def test_un_rectangulo_completo_es_un_area():
    """Lo que deja arrastrar un rectangulo sobre la escena."""
    pixeles = [(x, y) for y in (2, 3, 4) for x in (5, 6)]
    assert tipo_de_firma(firma(pixeles)) == TIPO_AREA


def test_pixeles_sueltos_no_son_un_area():
    """El modo Pixeles junta puntos dispersos, y su caja envolvente no es
    donde se tomo la firma: seria pintar en el mapa terreno que nadie midio.
    """
    assert tipo_de_firma(firma([(0, 0), (9, 9), (4, 2)])) == TIPO_PIXELES


def test_a_un_rectangulo_al_que_le_falta_un_pixel_tampoco():
    pixeles = [(x, y) for y in (2, 3) for x in (5, 6)]
    pixeles.remove((6, 3))
    assert tipo_de_firma(firma(pixeles)) == TIPO_PIXELES


def test_el_tipo_se_deduce_y_no_hace_falta_guardarlo():
    """Asi las bibliotecas guardadas con versiones anteriores tambien se
    pueden llevar al mapa: no hay campo nuevo que les falte."""
    from hdfeos_extractor.core.spectral import Signature as S
    vieja = S.from_dict(firma([(1, 1), (2, 1)]).to_dict())
    assert tipo_de_firma(vieja) == TIPO_AREA


# -- donde cae ---------------------------------------------------------------
def test_el_punto_cae_en_el_centro_del_pixel():
    """En el centro y no en la esquina: la esquina lo deja corrido medio
    pixel arriba y a la izquierda de lo que el usuario pincho."""
    h = huella_de_firma(firma([(3, 4)]), GT)
    assert h.tipo == TIPO_PUNTO
    assert h.puntos == [(500035.0, 3999955.0)]
    assert h.anillo is None


def test_el_area_es_el_borde_de_fuera_de_sus_pixeles():
    """Del borde exterior, no del centro de los pixeles del borde: si no, el
    poligono deja fuera media fila y media columna de lo que se midio."""
    pixeles = [(x, y) for y in (2, 3) for x in (5, 6)]
    h = huella_de_firma(firma(pixeles), GT)
    assert h.tipo == TIPO_AREA
    assert h.anillo[0] == h.anillo[-1]          # el anillo se cierra
    xs = [p[0] for p in h.anillo]
    ys = [p[1] for p in h.anillo]
    assert min(xs) == 500050.0 and max(xs) == 500070.0
    assert min(ys) == 3999960.0 and max(ys) == 3999980.0


def test_con_una_escena_girada_el_area_sale_girada():
    """Una franja sin ortorectificar llega inclinada: su rectangulo de
    pixeles es un rombo en el terreno. Una caja alineada con los ejes
    pintaria en el mapa terreno que la firma nunca toco.
    """
    pixeles = [(x, y) for y in (0, 1) for x in (0, 1)]
    h = huella_de_firma(firma(pixeles), GIRADA)
    esquinas = h.anillo[:4]
    lados = [np.hypot(b[0] - a[0], b[1] - a[1])
             for a, b in zip(esquinas, esquinas[1:] + esquinas[:1])]
    assert all(np.isclose(lado, 20.0) for lado in lados)   # sigue cuadrado
    # Comparacion absoluta: con coordenadas de siete cifras, la tolerancia
    # RELATIVA de isclose vale 40 m y daria por iguales dos esquinas que se
    # llevan 10.
    assert abs(esquinas[0][1] - esquinas[1][1]) > 1.0      # no esta recto


def test_los_pixeles_sueltos_son_varios_puntos():
    h = huella_de_firma(firma([(0, 0), (2, 1)]), GT)
    assert h.tipo == TIPO_PIXELES
    assert h.puntos == [(500005.0, 3999995.0), (500025.0, 3999985.0)]
    assert h.anillo is None


def test_una_firma_sin_pixeles_no_tiene_donde_ponerse():
    """Una firma leida de un CSV ajeno no trae pixeles. Inventarle una
    posicion seria peor que no ponerla."""
    assert huella_de_firma(firma([]), GT) is None


def test_sin_georreferencia_la_huella_sigue_saliendo_en_pixeles():
    """Con la transformacion identidad las coordenadas son el indice de
    pixel. Sirve igual para ver la forma; lo que no sirve es para ubicarla,
    y de eso avisa el panel."""
    h = huella_de_firma(firma([(3, 4)]), GeoTransform.identidad())
    assert h.puntos == [(3.5, -4.5)]


# -- que se lleva a la tabla -------------------------------------------------
def test_los_atributos_dicen_quien_es_y_de_donde_salio():
    f = firma([(1, 1), (2, 1)], nombre="agua turbia", color="#3388ff",
              notas="orilla norte")
    a = atributos_de_firma(f)
    assert a["nombre"] == "agua turbia"
    assert a["tipo"] == TIPO_AREA
    assert a["pixeles"] == 2
    assert a["color"] == "#3388ff"
    assert a["notas"] == "orilla norte"
    assert a["procedencia"] == "escena.h5"
    assert a["bandas"] == 4
    assert a["wl_min"] == 450.0 and a["wl_max"] == 850.0
    assert a["creada"]


def test_los_atributos_no_traen_ningun_None():
    """Un None en un campo de una capa se escribe como texto 'None' o
    revienta al exportar, segun el driver."""
    f = Signature("pelada", WL, np.ones(WL.size), pixels=[(0, 0)])
    assert all(v is not None for v in atributos_de_firma(f).values())


# -- la ventana de pixeles a poligono ---------------------------------------
def test_la_ventana_da_las_cuatro_esquinas_y_no_una_caja():
    esquinas = GIRADA.esquinas_de_ventana((0, 0, 1, 1))
    assert len(esquinas) == 4
    caja = GIRADA.bbox_de_ventana((0, 0, 1, 1))
    assert caja == (min(p[0] for p in esquinas), min(p[1] for p in esquinas),
                    max(p[0] for p in esquinas), max(p[1] for p in esquinas))
