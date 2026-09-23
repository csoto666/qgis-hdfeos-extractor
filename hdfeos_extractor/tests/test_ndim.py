# -*- coding: utf-8 -*-
"""Pruebas del visualizador n-dimensional.

Lo que hay que fijar aca no es que se vea bonito sino tres cosas concretas:
que la proyeccion sea de verdad una proyeccion ortogonal -si no, las
distancias que el usuario ve mintieron-, que la rotacion recorra el espacio
sin repetirse, y que la seleccion con lazo devuelva exactamente los puntos
que quedaron dentro.
"""

import numpy as np
import pytest

from hdfeos_extractor.core.ndim import (NubeND, TourND, nube_de_firmas,
                                        puntos_en_poligono)
from hdfeos_extractor.core.cube import HyperspectralCube
from hdfeos_extractor.core.spectral import Signature

from conftest import cubo_patron, longitudes_patron


# -- la rotacion -------------------------------------------------------------
def test_la_base_es_ortonormal_siempre():
    """Si no lo fuera, la nube se veria estirada o cizallada al girar."""
    tour = TourND(7)
    for t in (0.0, 0.3, 1.7, 42.0, 1000.0):
        u, v = tour.base(t)
        assert np.isclose(np.linalg.norm(u), 1.0)
        assert np.isclose(np.linalg.norm(v), 1.0)
        assert abs(float(np.dot(u, v))) < 1e-9


def test_con_dos_bandas_no_gira():
    """Dos dimensiones ya caben en la pantalla: girarlas solo marearia.

    Es lo que hace ENVI, y no es capricho: con dos bandas el grafico de
    dispersion ES el dato, no una proyeccion de el.
    """
    tour = TourND(2)
    u0, v0 = tour.base(0.0)
    u1, v1 = tour.base(9.5)
    assert np.allclose(u0, u1) and np.allclose(v0, v1)
    assert np.allclose(u0, [1.0, 0.0])
    assert np.allclose(v0, [0.0, 1.0])


def test_con_tres_o_mas_bandas_si_gira():
    tour = TourND(5)
    u0, _ = tour.base(0.0)
    u1, _ = tour.base(2.0)
    assert not np.allclose(u0, u1)


def test_la_rotacion_es_reproducible():
    """Dos sesiones con la misma vista tienen que ver lo mismo.

    Sin esto, 'mira este agrupamiento' no se puede compartir con nadie.
    """
    a, b = TourND(6), TourND(6)
    for t in (0.5, 3.25):
        assert np.allclose(a.base(t)[0], b.base(t)[0])


def test_la_rotacion_no_se_repite_enseguida():
    """Frecuencias inconmensurables: el recorrido no tiene ciclo corto.

    Si lo tuviera, la animacion volveria a pasar por las mismas vistas y
    dejaria de mostrar proyecciones nuevas, que es para lo unico que sirve.
    """
    tour = TourND(8)
    base = tour.base(0.0)[0]
    repetidas = [t for t in np.arange(1.0, 200.0, 0.5)
                 if np.allclose(tour.base(t)[0], base, atol=1e-3)]
    assert not repetidas


def test_proyectar_es_una_proyeccion_ortogonal():
    """La sombra nunca puede ser mas larga que el objeto."""
    tour = TourND(9)
    rng = np.random.default_rng(3)
    X = rng.normal(size=(50, 9))
    P = tour.proyectar(X, 1.3)
    assert P.shape == (50, 2)
    sombra = np.linalg.norm(P, axis=1)
    objeto = np.linalg.norm(X, axis=1)
    assert np.all(sombra <= objeto + 1e-9)


def test_los_radios_son_las_bandas_proyectadas():
    """Cada radio es el eje de una banda: por eso se puede leer la nube.

    Un radio que apunta hacia donde se alarga el grupo dice que esa banda es
    la que lo separa. Si no fueran exactamente los ejes proyectados, esa
    lectura -que es para lo que sirven- seria falsa.
    """
    tour = TourND(4)
    radios = tour.ejes(0.77)
    identidad = np.eye(4)
    assert np.allclose(radios, tour.proyectar(identidad, 0.77))


def test_el_giro_manual_cambia_la_vista():
    tour = TourND(5)
    antes = tour.proyectar(np.eye(5), 0.0)
    tour.girar_a_mano(0.4, -0.2)
    assert not np.allclose(antes, tour.proyectar(np.eye(5), 0.0))


# -- la nube -----------------------------------------------------------------
@pytest.fixture
def cubo():
    return HyperspectralCube.from_array(cubo_patron(6, 8, 9),
                                        longitudes_patron(9))


def firma(nombre, pixeles, color, cubo):
    coords = list(pixeles)
    return Signature(nombre, cubo.wavelengths,
                     cubo.get_spectrum(*coords[0]),
                     pixels=coords, color=color, count=len(coords))


def test_cada_pixel_de_cada_firma_es_un_punto(cubo):
    """La firma guardada es la media; lo que se explora aqui es la nube.

    Una firma de area con quinientos pixeles es un solo espectro en el
    grafico espectral y quinientos puntos aqui. Esa es toda la diferencia:
    la media no muestra si el area era un grupo o dos.
    """
    firmas = [firma("agua", [(0, 0), (1, 0), (2, 0)], "#0000ff", cubo),
              firma("suelo", [(3, 3), (4, 3)], "#aa5500", cubo)]
    nube = nube_de_firmas(cubo, firmas, bandas=[0, 2, 4, 6])
    assert nube.X.shape == (5, 4)
    assert list(nube.etiquetas) == [0, 0, 0, 1, 1]
    assert nube.clases[0].nombre == "agua"
    assert nube.clases[1].color == "#aa5500"


def test_los_valores_son_los_del_cubo_en_esas_bandas(cubo):
    firmas = [firma("una", [(2, 1)], "#ff0000", cubo)]
    nube = nube_de_firmas(cubo, firmas, bandas=[1, 5], escalar=False)
    espectro = cubo.get_spectrum(2, 1)
    assert np.allclose(nube.X[0], [espectro[1], espectro[5]])


def test_se_descartan_las_bandas_sin_dato(cubo):
    """Una banda mala llega como NaN y no se puede proyectar.

    Colarla haria que toda la nube fuera NaN y la pantalla quedara vacia sin
    ninguna explicacion.
    """
    from hdfeos_extractor.core.bandas import MascaraBandas
    wl = cubo.wavelengths
    cubo.set_mask(MascaraBandas(wl, rangos=[(wl[3], wl[3])]))
    firmas = [firma("una", [(2, 1), (3, 1)], "#ff0000", cubo)]
    nube = nube_de_firmas(cubo, firmas, bandas=[1, 3, 5])
    assert nube.bandas == [1, 5]
    assert np.isfinite(nube.X).all()


def test_un_pixel_con_todo_NaN_no_entra(cubo):
    firmas = [firma("una", [(0, 0), (1, 1)], "#ff0000", cubo)]
    nube = nube_de_firmas(cubo, firmas, bandas=[0, 1])
    nube_rota = NubeND(np.array([[np.nan, 1.0], [2.0, 3.0]]),
                       np.array([0, 0]), nube.clases, [0, 1])
    assert nube_rota.X.shape[0] == 1


def test_escalar_deja_la_nube_en_un_rango_dibujable(cubo):
    """Sin escalar, una banda con valores mil veces mayores manda sola."""
    firmas = [firma("una", [(x, 0) for x in range(6)], "#ff0000", cubo)]
    nube = nube_de_firmas(cubo, firmas, bandas=[0, 3, 6], escalar=True)
    assert np.abs(nube.X).max() <= 1.0 + 1e-6


def test_se_limita_cuantos_pixeles_entran(cubo):
    """Medio millon de puntos no se dibujan a treinta cuadros por segundo.

    Se submuestrea de forma pareja y no cortando por el principio: cortar
    dejaria fuera media escena y el usuario veria un grupo que no existe.
    """
    todos = [(x, y) for y in range(6) for x in range(8)]
    firmas = [firma("grande", todos, "#00ff00", cubo)]
    nube = nube_de_firmas(cubo, firmas, bandas=[0, 1], max_por_clase=10)
    assert nube.X.shape[0] == 10
    assert len({p for p in nube.pixeles}) == 10


def test_sin_firmas_la_nube_queda_vacia_y_lo_dice(cubo):
    nube = nube_de_firmas(cubo, [], bandas=[0, 1])
    assert nube.vacia
    assert nube.X.shape == (0, 2)


# -- el lazo -----------------------------------------------------------------
def test_el_lazo_devuelve_lo_que_quedo_dentro():
    puntos = np.array([[0.0, 0.0], [5.0, 5.0], [1.0, 1.0], [-3.0, 2.0]])
    cuadrado = [(-1.0, -1.0), (3.0, -1.0), (3.0, 3.0), (-1.0, 3.0)]
    dentro = puntos_en_poligono(puntos, cuadrado)
    assert list(np.flatnonzero(dentro)) == [0, 2]


def test_un_lazo_de_menos_de_tres_puntos_no_selecciona_nada():
    puntos = np.array([[0.0, 0.0]])
    assert not puntos_en_poligono(puntos, [(0.0, 0.0), (1.0, 1.0)]).any()


def test_el_lazo_funciona_con_una_forma_concava():
    """Un lazo a mano alzada casi nunca es convexo."""
    puntos = np.array([[0.5, 0.5], [5.0, 0.5], [2.5, 4.0]])
    ele = [(0.0, 0.0), (6.0, 0.0), (6.0, 1.0), (1.0, 1.0), (1.0, 6.0),
           (0.0, 6.0)]
    dentro = puntos_en_poligono(puntos, ele)
    assert list(np.flatnonzero(dentro)) == [0, 1]
