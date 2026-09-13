#!/bin/bash
# Reconstruye binary.hybrid.iso desde binary/, corrigiendo dos bugs de
# esta versión de live-build que el build normal (lb_binary_syslinux +
# lb_binary_iso) deja rotos — encontrados arrancando la ISO de verdad
# en QEMU, no durante el build en sí (que termina "bien" sin avisar):
#
#   1. binary/live -> casper (symlink, necesario para que el `mv` de
#      lb_binary_syslinux funcione durante el build — ver el comentario
#      en auto/build) se hornea como un ARCHIVO VACÍO de 0 bytes al
#      armar el .iso — genisoimage no maneja bien un symlink de
#      directorio apuntando a un hermano que también está escaneando,
#      combinado con -cache-inodes. Con /live/vmlinuz apuntando a la
#      nada, ISOLINUX no puede cargar el kernel — arranque en loop, sin
#      ni un mensaje de log. Se probó primero parchear el .iso ya armado
#      con xorriso (-map/-rm_r) en vez de reconstruirlo — funciona a
#      nivel de xorriso, pero es un update incremental/multi-sesión
#      sobre el archivo, y el driver iso9660 normal de Linux (mount -o
#      loop) sigue viendo la sesión vieja rota. Reconstruir el .iso
#      entero de cero, con binary/live como directorio real (copias, no
#      symlink), evita el problema de raíz.
#
#   2. -allow-limited-size (necesario porque nuestro squashfs, con kal +
#      el modelo horneado, supera los 4GiB-1 del límite clásico de
#      ISO-9660 para un solo archivo) deja el tamaño de ese archivo mal
#      representado en el árbol ISO9660/Joliet/RockRidge puro — el
#      propio genisoimage avisa esto en el build ("This size can only be
#      represented in the UDF filesystem"), advertencia que la primera
#      vez se subestimó como "no fatal" sin más. El kernel, leyendo vía
#      ISO9660 puro, ve un tamaño truncado del squashfs y el mount
#      falla con "Invalid argument" — confirmado arrancando de verdad
#      (mount: mounting /dev/loop0 on /filesystem.squashfs failed:
#      Invalid argument). "-udf" agrega el árbol UDF, que sí representa
#      bien archivos >4GiB — Linux prefiere UDF sobre ISO9660 puro al
#      montar un disco híbrido, así que alcanza con sumarlo.
#
# Corre DESPUÉS de que `lb build` (auto/build) ya terminó su propio
# `lb_binary_iso` (roto en los dos sentidos de arriba) — usa el
# contenido de binary/ que esa corrida ya dejó listo, no repite nada
# del resto del build.
set -euo pipefail
cd "$(dirname "${0}")/.."  # iso/

if [ ! -d binary/casper ]; then
    echo "binary/casper no existe — corré primero auto/build" >&2
    exit 1
fi

echo "==> Reconstruyendo binary.hybrid.iso con binary/live real (no symlink) + UDF"

# -rf, no -f: binary/live puede ser el symlink original (ln -sfn en
# auto/build) o ya un directorio real de una corrida anterior de este
# mismo script — rm -f solo falla contra un directorio.
rm -rf binary/live
mkdir -p binary/live
cp binary/casper/vmlinuz binary/live/vmlinuz
cp binary/casper/initrd.img binary/live/initrd.img

rm -rf chroot/binary  # por si quedó algo varado de un intento previo
mv binary chroot/binary
chroot chroot genisoimage \
    -J -l -cache-inodes -allow-multidot \
    -A "Ubuntu Live" \
    -p "live-build 3.0~a57-1; http://packages.qa.debian.org/live-build" \
    -publisher "Debian Live project; http://live.debian.net/; debian-live@lists.debian.org" \
    -V "Ubuntu resolute 20260912-16:14" \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -r -b isolinux/isolinux.bin -c isolinux/boot.cat \
    -allow-limited-size -udf \
    -o /binary.hybrid.iso /binary
chroot chroot isohybrid /binary.hybrid.iso
mv chroot/binary.hybrid.iso ./binary.hybrid.iso
mv chroot/binary ./binary
rm -f chroot/binary.hybrid.iso

echo "==> Listo: binary.hybrid.iso reconstruida"
