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
"""De donde salen las coordenadas de la escena, y en que sistema estan.

Este modulo existe porque la georreferencia se estaba deduciendo de la capa
de QGIS -su extension dividida por su tamano en pixeles- y eso solo acierta
cuando la escena esta al norte y sin rotacion. Una escena hiperespectral rara
vez lo esta: sale del sensor inclinada, y la extension que QGIS reporta es la
caja que envuelve ese rombo, no la escena. Dividirla da un tamano de pixel
equivocado y un origen equivocado, y la capa aterriza corrida.

Hay tres formas de saber donde esta una escena, y no son intercambiables:

``afin``
    Una geotransformacion de seis numeros. Es lo que trae un ENVI con
    ``map info`` o cualquier cosa que GDAL abra georreferenciada. Puede
    incluir rotacion, y entonces hay que conservarla entera.

``gcp``
    Una rejilla de puntos de control, uno por cada tanto pixel, sacada de
    las capas de latitud y longitud que el HDF-EOS5 trae al lado del cubo.
    Es el caso de la geometria de sensor: la relacion pixel-terreno no es
    afin -hay balanceo, terreno y curvatura- y ninguna geotransformacion la
    describe. Para llevar esto a un mapa hay que remuestrear, no basta con
    declarar coordenadas.

``ninguna``
    No se sabe. Se dice, y no se inventa un sistema de referencia: una capa
    con un SRC falso es peor que una sin SRC, porque QGIS la reproyecta con
    confianza hacia el lugar equivocado.

El SRC se guarda como WKT cuando el archivo lo trae textual y como codigo
EPSG cuando hay que deducirlo del ``map info``. No se construye WKT aca
-eso necesitaria GDAL u OSR, y este paquete no depende de ninguno-: quien
escriba el archivo resuelve el codigo, que es un paso trivial tanto en GDAL
como en QGIS.
"""

import re

import numpy as np

from .geo import GeoError, GeoTransform

#: Codigos EPSG que se deducen sin ambiguedad del ``map info`` de ENVI.
EPSG_WGS84 = 4326
EPSG_UTM_NORTE = 32600      # + zona
EPSG_UTM_SUR = 32700        # + zona

#: Datums que se pueden mapear a EPSG con confianza. Cualquier otro deja el
#: SRC sin resolver: un datum equivocado desplaza cientos de metros y no se
#: nota mirando la pantalla.
DATUMS_WGS84 = ("wgs-84", "wgs84", "wgs 84", "world geodetic system 1984")

#: Codigos de proyeccion de HDF-EOS (GCTP) que se saben traducir. Los demas
#: se leen igual -la afin es valida- pero se quedan sin SRC y se dice.
GCTP_GEO = "GEO"
GCTP_UTM = "UTM"

#: Codigos de esferoide de GCTP que son WGS84. El 12 es el habitual; -1
#: significa "usa los parametros de proyeccion", y en un producto moderno eso
#: es WGS84 en la practica.
ESFERAS_WGS84 = (12, -1)

#: Cuantos puntos de control por lado se toman de la rejilla de lat/lon.
#: 21x21 = 441 puntos: suficiente para que una transformacion de placa
#: delgada siga el balanceo del sensor, y poco para que el remuestreo no se
#: vuelva lento.
GCP_POR_LADO = 21


class Georreferencia(object):
    """Donde esta la escena y en que sistema, o la confesion de que no se sabe.

    Nunca se falsea: ``origen`` dice de donde salio el dato para que la
    interfaz pueda advertirlo, y ``describir()`` lo cuenta en una linea.
    """

    def __init__(self, gt=None, gcps=None, wkt=None, epsg=None,
                 origen="ninguna", nota=""):
        self.gt = tuple(float(v) for v in gt) if gt is not None else None
        self.gcps = list(gcps) if gcps else None
        self.wkt = wkt or None
        self.epsg = int(epsg) if epsg else None
        self.origen = origen
        self.nota = nota

    # -- interrogacion ------------------------------------------------------
    @property
    def es_afin(self):
        return self.gt is not None

    @property
    def es_gcp(self):
        return self.gt is None and bool(self.gcps)

    @property
    def tiene_mapa(self):
        """True si la escena sabe donde esta, de la forma que sea."""
        return self.es_afin or self.es_gcp

    @property
    def tiene_src(self):
        return self.wkt is not None or self.epsg is not None

    @property
    def necesita_remuestreo(self):
        """True si para ponerla en un mapa hay que reproyectar los pixeles.

        Solo el caso GCP. Una afin se escribe tal cual y GDAL la respeta,
        rotacion incluida.
        """
        return self.es_gcp

    # -- uso ----------------------------------------------------------------
    @property
    def transformacion(self):
        """Una ``GeoTransform`` utilizable para convertir clic <-> pixel.

        Con una afin es exacta. Con GCPs es un ajuste por minimos cuadrados,
        es decir una aproximacion: sirve para dibujar la marca del pixel en
        el mapa, no para medir. Sin nada, es el indice de pixel.
        """
        if self.gt is not None:
            try:
                return GeoTransform(self.gt)
            except GeoError:
                pass
        if self.gcps:
            ajustada = afin_por_minimos_cuadrados(self.gcps)
            if ajustada is not None:
                try:
                    return GeoTransform(ajustada)
                except GeoError:
                    pass
        return GeoTransform.identidad()

    def recortada(self, col0, fila0, paso=1):
        """La misma georreferencia referida a un recorte submuestreado.

        ``col0``/``fila0`` son la esquina del recorte en pixeles del cubo
        entero y ``paso`` el salto de submuestreo. Olvidar cualquiera de los
        dos deja la capa corrida o con la escala equivocada, que es
        exactamente el error que no se ve hasta compararla con otra capa.
        """
        col0, fila0, paso = int(col0), int(fila0), max(1, int(paso))
        gt = None
        if self.gt is not None:
            g = self.gt
            gt = (g[0] + col0 * g[1] + fila0 * g[2],
                  g[1] * paso, g[2] * paso,
                  g[3] + col0 * g[4] + fila0 * g[5],
                  g[4] * paso, g[5] * paso)
        gcps = None
        if self.gcps:
            gcps = [((c - col0) / float(paso), (f - fila0) / float(paso), x, y)
                    for c, f, x, y in self.gcps]
        return Georreferencia(gt=gt, gcps=gcps, wkt=self.wkt, epsg=self.epsg,
                              origen=self.origen, nota=self.nota)

    def recortar_gcps(self, ancho, alto, margen=0.0):
        """Deja solo los puntos de control que caen dentro de la imagen.

        Tras recortar la vista, la mayoria de la rejilla queda fuera. Los
        puntos de fuera no son invalidos -la transformacion los usa igual-
        pero extrapolan, y con placa delgada extrapolar deforma el borde. Se
        quedan los de dentro mas un margen, y si quedan muy pocos se
        devuelven todos: peor que extrapolar es no tener con que ajustar.
        """
        if not self.gcps:
            return self
        dentro = [g for g in self.gcps
                  if -margen <= g[0] <= ancho + margen
                  and -margen <= g[1] <= alto + margen]
        if len(dentro) < 3:
            return self
        return Georreferencia(gt=self.gt, gcps=dentro, wkt=self.wkt,
                              epsg=self.epsg, origen=self.origen,
                              nota=self.nota)

    def describir(self):
        """Una linea para la barra de estado."""
        if self.es_afin:
            g = self.gt
            rot = ("" if (g[2] == 0.0 and g[4] == 0.0) else ", rotada")
            cuerpo = ("georreferencia afin (%s), pixel %.6g%s"
                      % (self.origen, abs(g[1]), rot))
        elif self.es_gcp:
            cuerpo = ("geometria de sensor (%s), %d puntos de control"
                      % (self.origen, len(self.gcps)))
        else:
            cuerpo = "sin georreferencia"
        return cuerpo + ", " + (self.nombre_src or "sin SRC")

    @property
    def nombre_src(self):
        if self.epsg:
            return "EPSG:%d" % self.epsg
        if self.wkt:
            m = re.search(r'^\s*\w+\s*\[\s*"([^"]+)"', self.wkt)
            return m.group(1) if m else "SRC propio"
        return None

    def __repr__(self):
        return "<Georreferencia %s>" % self.describir()

    # -- constructores ------------------------------------------------------
    @classmethod
    def ninguna(cls, nota=""):
        return cls(origen="ninguna", nota=nota)

    @classmethod
    def de_gdal(cls, ds):
        """Lee la georreferencia de un dataset de GDAL ya abierto.

        Se pide la geotransformacion con ``can_return_null`` porque sin eso
        GDAL devuelve la identidad cuando el archivo no tiene ninguna, y la
        identidad es indistinguible de una georreferencia real en pixeles.
        Confundirlas es como termina una escena en el golfo de Guinea.
        """
        if ds is None:
            return cls.ninguna()
        wkt = None
        for obtener in ("GetProjectionRef", "GetProjection"):
            metodo = getattr(ds, obtener, None)
            if metodo is not None:
                wkt = metodo() or None
                if wkt:
                    break
        try:
            gt = ds.GetGeoTransform(can_return_null=True)
        except TypeError:                  # pragma: no cover - GDAL viejo
            gt = ds.GetGeoTransform()
            if tuple(gt) == (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
                gt = None
        if gt is not None and wkt:
            return cls(gt=gt, wkt=wkt, origen="archivo")

        gcps = ds.GetGCPs() if hasattr(ds, "GetGCPs") else []
        if gcps:
            wkt_gcp = (ds.GetGCPProjection() or None
                       if hasattr(ds, "GetGCPProjection") else None)
            return cls(gcps=[(g.GCPPixel, g.GCPLine, g.GCPX, g.GCPY)
                             for g in gcps],
                       wkt=wkt_gcp or wkt, origen="archivo")
        if gt is not None:
            return cls(gt=gt, wkt=wkt, origen="archivo",
                       nota="el archivo trae coordenadas pero no dice en que "
                            "sistema")
        return cls.ninguna()

    @classmethod
    def de_envi(cls, campos):
        """Lee ``map info`` y ``coordinate system string`` de una cabecera.

        El WKT textual tiene prioridad sobre el nombre de proyeccion: es
        exacto y no hay que reconstruir nada. El ``map info`` se sigue
        leyendo igual porque es el unico que trae el origen y el tamano de
        pixel.
        """
        info = parsear_map_info(campos.get("map info"))
        wkt = (campos.get("coordinate system string") or "").strip() or None
        if wkt:
            # El bloque viene entre llaves y read_hdr ya las quito, pero
            # algunos productores dejan comas de separacion entre lineas.
            wkt = wkt.replace("\n", "").strip()
        if info is None:
            return cls.ninguna() if not wkt else cls(wkt=wkt, origen="archivo",
                                                     nota="la cabecera dice el "
                                                          "sistema pero no "
                                                          "donde esta la "
                                                          "escena")
        gt, epsg, nota = info
        return cls(gt=gt, wkt=wkt, epsg=None if wkt else epsg,
                   origen="archivo", nota=nota)

    @classmethod
    def de_estructura(cls, texto, lineas=None, muestras=None):
        """Georreferencia desde el ``StructMetadata`` de un HDF-EOS.

        Es el caso del producto ortorectificado. Un GRID de HDF-EOS no trae
        capas de latitud y longitud -no las necesita, le basta una afin- y
        esa afin esta aqui y en ningun otro sitio del archivo. Buscarle
        lat/lon a un grid no encuentra nada, y el resultado era una escena
        sin georreferencia aunque el producto viniera perfectamente ubicado.
        """
        rejilla = parsear_struct_metadata(texto)
        if rejilla is None:
            return cls.ninguna(
                nota="el contenedor no describe ningun grid georreferenciado")
        ulx, uly, lrx, lry, nx, ny, epsg, nota = rejilla
        # Se prefiere el tamano que declara el cubo: el grid y el cubo tienen
        # que coincidir, y si no coinciden manda el dato.
        nx = int(muestras or nx)
        ny = int(lineas or ny)
        if not nx or not ny:
            return cls.ninguna(nota="el grid no declara su tamano")
        gt = (ulx, (lrx - ulx) / float(nx), 0.0,
              uly, 0.0, (lry - uly) / float(ny))
        return cls(gt=gt, epsg=epsg, origen="grid del producto", nota=nota)

    @classmethod
    def de_rejilla(cls, lon, lat, por_lado=GCP_POR_LADO, epsg=EPSG_WGS84,
                   lineas=None, muestras=None):
        """Puntos de control desde las capas de longitud y latitud.

        Es la georreferencia verdadera de un producto en geometria de sensor.
        Se toma una rejilla y no todos los pixeles: con un punto por pixel el
        remuestreo tarda minutos y no gana precision, porque entre dos puntos
        vecinos la deformacion es despreciable.
        """
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        if lon.shape != lat.shape or lon.ndim != 2 or min(lon.shape) < 2:
            return cls.ninguna(nota="las capas de lat/lon no tienen la forma "
                                    "de la escena")
        alto, ancho = lon.shape
        # La geolocalizacion no siempre viene pixel a pixel: hay productos que
        # la guardan en una rejilla mas gruesa. El punto (f, c) de esa rejilla
        # no es entonces el pixel (f, c) del cubo, y tomarlo como si lo fuera
        # deja la escena del tamano de la rejilla -un error de escala que se
        # ve enorme y no dice por que-.
        escala_f = (float(lineas) / alto) if lineas else 1.0
        escala_c = (float(muestras) / ancho) if muestras else 1.0
        filas = np.unique(np.linspace(0, alto - 1, min(por_lado, alto))
                          .astype(int))
        cols = np.unique(np.linspace(0, ancho - 1, min(por_lado, ancho))
                         .astype(int))
        gcps = []
        for f in filas:
            for c in cols:
                x, y = lon[f, c], lat[f, c]
                if not (np.isfinite(x) and np.isfinite(y)):
                    continue
                # Las capas de geolocalizacion usan el relleno del producto,
                # que suele ser -9999: fuera del planeta y facil de descartar.
                if abs(x) > 180.0 or abs(y) > 90.0:
                    continue
                gcps.append(((float(c) + 0.5) * escala_c,
                             (float(f) + 0.5) * escala_f,
                             float(x), float(y)))
        if len(gcps) < 3:
            return cls.ninguna(nota="las capas de lat/lon no traen valores "
                                    "validos")
        return cls(gcps=gcps, epsg=epsg, origen="lat/lon del producto")

    @classmethod
    def de_capa(cls, layer):
        """Ultimo recurso: la extension de una capa de QGIS.

        Vale solo para capas al norte y sin rotacion, que es justamente el
        caso que esta clase existe para dejar de suponer. Se usa cuando el
        archivo no dice nada y el usuario abrio la escena como capa: es mejor
        que nada, pero se marca como deducida.
        """
        try:
            gt = GeoTransform.from_layer(layer).gt
        except (GeoError, AttributeError):
            return cls.ninguna()
        wkt = None
        try:
            crs = layer.crs()
            if crs is not None and crs.isValid():
                wkt = crs.toWkt()
        except AttributeError:             # pragma: no cover
            wkt = None
        return cls(gt=gt, wkt=wkt, origen="capa de QGIS",
                   nota="deducida de la extension de la capa: si la escena "
                        "esta rotada, no es exacta")


def parsear_map_info(texto):
    """``map info`` de ENVI -> (geotransformacion, epsg, nota), o None.

    El campo trae, en orden: nombre de proyeccion, pixel de referencia en x
    e y -en base 1-, sus coordenadas de mapa, el tamano de pixel en x e y,
    y despues, segun la proyeccion, zona y hemisferio, el datum y los pares
    ``clave=valor``. La rotacion viene como ``rotation=`` al final y es la
    parte que todo el mundo olvida.
    """
    if not texto:
        return None
    partes = [t.strip() for t in texto.replace("\n", " ").split(",")]
    partes = [p for p in partes if p != ""]
    if len(partes) < 7:
        return None
    nombre = partes[0]
    try:
        px, py = float(partes[1]), float(partes[2])
        mx, my = float(partes[3]), float(partes[4])
        tx, ty = float(partes[5]), float(partes[6])
    except ValueError:
        return None
    if tx == 0.0 or ty == 0.0:
        return None

    claves = {}
    for p in partes[7:]:
        if "=" in p:
            k, _, v = p.partition("=")
            claves[k.strip().lower()] = v.strip()
    sueltos = [p for p in partes[7:] if "=" not in p]

    rotacion = 0.0
    if "rotation" in claves:
        try:
            rotacion = float(claves["rotation"])
        except ValueError:
            rotacion = 0.0

    gt = geotransformacion_de_referencia(px, py, mx, my, tx, ty, rotacion)
    epsg, nota = _epsg_de_map_info(nombre, sueltos, claves)
    return gt, epsg, nota


def geotransformacion_de_referencia(px, py, mx, my, tx, ty, rotacion=0.0):
    """Arma la geotransformacion a partir del pixel de referencia de ENVI.

    ENVI numera el pixel de referencia desde 1 y da la coordenada de su
    esquina superior izquierda, no la de su centro. La rotacion esta en
    grados antihorarios y gira los ejes de fila y columna; con rotacion cero
    los terminos cruzados se anulan y queda la geotransformacion de siempre.
    """
    a = np.radians(float(rotacion))
    cos, sen = float(np.cos(a)), float(np.sin(a))
    gt1, gt2 = tx * cos, ty * sen
    gt4, gt5 = tx * sen, -ty * cos
    col0, fila0 = float(px) - 1.0, float(py) - 1.0
    return (float(mx) - col0 * gt1 - fila0 * gt2, gt1, gt2,
            float(my) - col0 * gt4 - fila0 * gt5, gt4, gt5)


def _epsg_de_map_info(nombre, sueltos, claves):
    """Deduce el EPSG del nombre de proyeccion. Devuelve (epsg, nota)."""
    n = (nombre or "").strip().lower()
    datum = " ".join(sueltos).lower()
    es_wgs84 = any(d in datum for d in DATUMS_WGS84)

    if n.startswith("geographic"):
        if es_wgs84 or not sueltos:
            return EPSG_WGS84, ""
        return None, ("la cabecera usa el datum '%s', que no se traduce a un "
                      "codigo EPSG sin ambiguedad" % " ".join(sueltos))
    if n.startswith("utm"):
        zona, hemisferio = None, "north"
        for s in sueltos:
            s2 = s.strip().lower()
            if s2 in ("north", "south", "n", "s"):
                hemisferio = "south" if s2.startswith("s") else "north"
            elif re.fullmatch(r"\d{1,2}", s2):
                zona = int(s2)
        if zona and 1 <= zona <= 60 and es_wgs84:
            base = EPSG_UTM_NORTE if hemisferio == "north" else EPSG_UTM_SUR
            return base + zona, ""
        return None, ("la cabecera declara UTM pero no se pudo deducir el "
                      "codigo EPSG (zona o datum)")
    if "units" in claves and not n:
        return None, ""
    return None, ("la proyeccion '%s' de la cabecera no se traduce a un "
                  "codigo EPSG: la capa saldra sin SRC" % nombre)


def afin_por_minimos_cuadrados(gcps):
    """Mejor geotransformacion afin que pasa por los puntos de control.

    No reemplaza al remuestreo -si una afin bastara, el producto no vendria
    con rejilla de lat/lon-, pero sirve para lo que la interfaz necesita:
    saber mas o menos donde cae un pixel para dibujar su marca en el mapa.
    """
    if not gcps or len(gcps) < 3:
        return None
    datos = np.asarray(gcps, dtype=np.float64)
    a = np.column_stack([datos[:, 0], datos[:, 1], np.ones(len(datos))])
    try:
        coef, _res, rango, _s = np.linalg.lstsq(a, datos[:, 2:4], rcond=None)
    except np.linalg.LinAlgError:          # pragma: no cover
        return None
    if rango < 3:
        return None
    (gt1, gt4), (gt2, gt5), (gt0, gt3) = coef
    return (float(gt0), float(gt1), float(gt2),
            float(gt3), float(gt4), float(gt5))


def parsear_struct_metadata(texto):
    """``StructMetadata`` -> (ulx, uly, lrx, lry, nx, ny, epsg, nota), o None.

    HDF-EOS describe sus grids en un bloque de texto con forma de arbol. Lo
    que hace falta son seis numeros y la proyeccion:

        GROUP=GridStructure
            GROUP=GRID_1
                XDim=1200
                YDim=1200
                UpperLeftPointMtrs=(499980.000000,4600020.000000)
                LowerRightMtrs=(609780.000000,4490220.000000)
                Projection=HE5_GCTP_UTM
                ZoneCode=18
                SphereCode=12

    Se lee el primer grid que este completo. Un producto hiperespectral trae
    uno solo; cuando trae varios son el cubo y sus mascaras, con la misma
    rejilla, asi que el primero sirve igual.
    """
    if not texto:
        return None
    if isinstance(texto, bytes):
        texto = texto.decode("utf-8", "replace")
    if "GridStructure" not in texto:
        return None

    for bloque in re.split(r"\bGROUP\s*=\s*GRID_\d+", texto)[1:]:
        campos = _campos_de_bloque(bloque)
        ul = _par(campos.get("upperleftpointmtrs"))
        lr = _par(campos.get("lowerrightmtrs"))
        if ul is None or lr is None:
            continue
        nx = _entero(campos.get("xdim"))
        ny = _entero(campos.get("ydim"))
        epsg, nota, escala = _epsg_de_estructura(campos)
        ulx, uly = ul[0] * escala, ul[1] * escala
        lrx, lry = lr[0] * escala, lr[1] * escala
        if ulx == lrx or uly == lry:
            continue                       # un grid degenerado no ubica nada
        return (ulx, uly, lrx, lry, nx, ny, epsg, nota)
    return None


def _campos_de_bloque(bloque):
    """``clave=valor`` de un bloque, hasta donde empiece el siguiente grid."""
    campos = {}
    for linea in bloque.splitlines():
        if "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip().lower()
        if clave in ("group", "end_group", "object", "end_object"):
            continue
        campos.setdefault(clave, valor.strip().strip('"'))
    return campos


def _par(valor):
    """``(x,y)`` -> tupla de dos floats, o None."""
    if not valor:
        return None
    numeros = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", valor)
    if len(numeros) < 2:
        return None
    try:
        return (float(numeros[0]), float(numeros[1]))
    except ValueError:
        return None


def _entero(valor):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _epsg_de_estructura(campos):
    """(epsg, nota, escala) para las coordenadas de un grid de HDF-EOS.

    La escala existe por las proyecciones geograficas: GCTP las guarda en
    microgrados -grados por un millon- y tomarlas como grados manda la escena
    a una longitud imposible. Se detecta por magnitud y no por el codigo de
    proyeccion, porque hay productores que ya escriben grados.
    """
    proyeccion = (campos.get("projection") or "").upper()
    esfera = _entero(campos.get("spherecode"))
    if esfera is None:
        esfera = _entero(campos.get("datum"))
    es_wgs84 = esfera is None or esfera in ESFERAS_WGS84

    if GCTP_GEO in proyeccion:
        ul = _par(campos.get("upperleftpointmtrs")) or (0.0, 0.0)
        escala = 1e-6 if max(abs(ul[0]), abs(ul[1])) > 360.0 else 1.0
        return EPSG_WGS84, "", escala
    if GCTP_UTM in proyeccion:
        zona = _entero(campos.get("zonecode"))
        if zona and 1 <= abs(zona) <= 60 and es_wgs84:
            # El signo de la zona es el hemisferio: negativa es sur.
            base = EPSG_UTM_NORTE if zona > 0 else EPSG_UTM_SUR
            return base + abs(zona), "", 1.0
        return None, ("el grid declara UTM pero no se pudo deducir el codigo "
                      "EPSG (zona %s, esferoide %s)" % (zona, esfera)), 1.0
    return None, ("la proyeccion '%s' del grid no se traduce a un codigo "
                  "EPSG: la capa sale con coordenadas pero sin SRC, y hay "
                  "que asignarselo a mano" % (proyeccion or "sin nombre")), 1.0
