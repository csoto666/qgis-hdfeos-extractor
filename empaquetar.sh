#!/bin/sh
# Arma el ZIP instalable en QGIS (Complementos > Instalar desde ZIP).
#
# Por que no sirve el "Download ZIP" de GitHub: ese genera una carpeta raiz
# llamada "qgis-hdfeos-extractor-main", y QGIS usa el nombre de esa carpeta
# como nombre del complemento. Quien lo instale asi termina con el plugin
# registrado bajo un nombre distinto -y si despues lo instala bien, QGIS
# carga las dos copias a la vez-. Este script deja la carpeta raiz con el
# nombre correcto: hdfeos_extractor.
#
# El nombre de la carpeta NO cambia aunque el plugin ahora se llame
# "HDF-EOS Explorer": es la identidad con la que QGIS reconoce una
# actualizacion de una instalacion existente en vez de un plugin nuevo.
set -e

PAQUETE=hdfeos_extractor
AQUI=$(cd "$(dirname "$0")" && pwd)
VERSION=$(sed -n 's/^version=//p' "$AQUI/$PAQUETE/metadata.txt")
SALIDA="$AQUI/$PAQUETE-$VERSION.zip"
TEMP=$(mktemp -d)

mkdir "$TEMP/$PAQUETE"
# Solo lo que el plugin necesita en tiempo de ejecucion, mas LICENSE y README.
# Las pruebas y los ejemplos no van: no los usa QGIS y engordan la descarga.
for f in __init__.py plugin.py proveedor.py algoritmo.py lector.py \
         metadata.txt icon.png icon.svg icono_explorador.png \
         icono_explorador.svg; do
    cp "$AQUI/$PAQUETE/$f" "$TEMP/$PAQUETE/"
done
for d in core vista qgis_ui; do
    mkdir "$TEMP/$PAQUETE/$d"
    cp "$AQUI/$PAQUETE/$d"/*.py "$TEMP/$PAQUETE/$d/"
done
cp "$AQUI/LICENSE" "$AQUI/README.md" "$TEMP/$PAQUETE/"

rm -f "$SALIDA"
(cd "$TEMP" && zip -q -r - "$PAQUETE") > "$SALIDA"
rm -rf "$TEMP"

echo "Listo: $SALIDA"
unzip -l "$SALIDA" | tail -n +2
