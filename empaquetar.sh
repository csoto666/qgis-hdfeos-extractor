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
# Los modulos van por comodin y no en una lista escrita a mano. La lista
# estuvo, y paso lo que pasa con las listas escritas a mano: se agrego un
# modulo nuevo -compat.py- y nadie la actualizo. El ZIP salio sin el y el
# plugin no cargaba, con un ModuleNotFoundError en casa del usuario y las
# pruebas en verde aqui.
cp "$AQUI/$PAQUETE"/*.py "$TEMP/$PAQUETE/"
# Lo que no es codigo si va enumerado: son cuatro archivos que cambian una
# vez cada nunca, y un comodin aqui se llevaria cualquier cosa que quedara
# suelta en la carpeta.
for f in metadata.txt icon.png icon.svg icono_explorador.png \
         icono_explorador.svg; do
    cp "$AQUI/$PAQUETE/$f" "$TEMP/$PAQUETE/"
done
for d in core vista qgis_ui; do
    mkdir "$TEMP/$PAQUETE/$d"
    cp "$AQUI/$PAQUETE/$d"/*.py "$TEMP/$PAQUETE/$d/"
done
cp "$AQUI/LICENSE" "$AQUI/README.md" "$AQUI/NOTAS.md" "$TEMP/$PAQUETE/"

rm -f "$SALIDA"
(cd "$TEMP" && zip -q -r - "$PAQUETE") > "$SALIDA"
rm -rf "$TEMP"

echo "Listo: $SALIDA"
unzip -l "$SALIDA" | tail -n +2
