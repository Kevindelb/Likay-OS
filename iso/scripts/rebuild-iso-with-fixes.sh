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

# Lee la variante decidida por auto/build (único punto de decisión, ver
# el comentario ahí) en vez de aceptar LIKAY_BARE_KAL_IN de nuevo acá —
# este script corre como un comando SEPARADO (ver el comentario grande
# al final de auto/build), y si dependiera de que el usuario repita la
# misma variable a mano en las dos invocaciones, un olvido dejaría el
# .iso final con el nombre de la variante equivocada sin ningún aviso.
if [ -f .likay-build-variant ]; then
    LIKAY_BUILD_VARIANT="$(cat .likay-build-variant)"
else
    LIKAY_BUILD_VARIANT="default"
fi
echo "=================================================================="
echo "Likay-OS build"
if [ "${LIKAY_BUILD_VARIANT}" = "bare" ]; then
    echo "Variant: bare (no kal-in)"
    ISO_ARTIFACT_NAME="likay-os-amd64-bare.iso"
else
    echo "Variant: default (kal-in baked)"
    ISO_ARTIFACT_NAME="likay-os-amd64.iso"
fi
echo "=================================================================="

# Bug real, encontrado en hardware real (2026-09-15): el menú de arranque
# solo mostraba las dos entradas "Live", nunca "Instalar Likay-OS" —
# nunca se había probado el menú REAL, solo el modo instalador en sí
# (arrancado saltando el menú del todo, inyectando likay.mode=installer
# directo en el -append de QEMU, ver "Probar el modo instalador" en
# README.md). lb_binary_syslinux (ver /usr/lib/live/build/lb_binary_syslinux
# línea 211) solo sabe renderizar "live.cfg.in" -> "live.cfg" -- el nombre
# está hardcodeado, no es un loop genérico sobre *.cfg.in. Nuestro propio
# install.cfg.in (con @KERNEL@/@INITRD@/@LB_BOOTAPPEND_LIVE@ sin
# sustituir) queda tal cual, nunca se genera install.cfg -- y el "include
# install.cfg" de menu.cfg apunta a un archivo que no existe. syslinux no
# tira ningún error por un include faltante, así que esto pasó
# desapercibido hasta arrancar en hardware real y mirar el menú con
# atención. Lo resolvemos acá (no parcheando live-build) con el mismo
# criterio que el resto de este script: reconstruimos binary.hybrid.iso
# desde binary/ de todos modos, así que alcanza con renderizar
# install.cfg.in a mano, con el mismo sed que usa lb_binary_syslinux,
# antes de ese paso -- leyendo KERNEL/INITRD/LB_BOOTAPPEND_LIVE del propio
# live.cfg ya renderizado en vez de re-derivar el entorno de live-build,
# para garantizar que ambas entradas usen exactamente el mismo kernel/
# initrd/bootappend salvo por likay.mode=installer.
# Extracción SIEMPRE (no solo si install.cfg.in existe todavía): el
# bloque de arranque UEFI más abajo también necesita estos tres
# valores, y en una corrida repetida de este script sobre el mismo
# binary/ (p.ej. solo para reagregar UEFI) install.cfg.in ya no existe
# -- se borra abajo la primera vez que se renderiza. Bug real
# encontrado así (2026-09-17): con install.cfg.in ya ausente, todo este
# bloque se saltaba antes y el bloque de UEFI fallaba con "KERNEL_PATH:
# variable sin asignar" (set -u).
#
# Solo el primer stanza de live.cfg (el "live-" normal, no el
# "-failsafe") -- awk corta en la primera línea en blanco, que es
# justo donde termina ese primer bloque (ver live.cfg.in: cada label
# separado por una línea vacía). Nunca usar grep -oP con \K.* acá:
# cuando LB_BOOTAPPEND_LIVE está vacío (nuestro caso, sin
# --bootappend-live en auto/config) el "match" queda de largo cero al
# final de la línea, y grep -oP directamente NO emite esa línea (se
# confirmó en vivo: con head -1 terminaba agarrando el append del
# stanza equivocado, el failsafe, que sí tiene contenido después del
# mismo prefijo) -- silencioso, sin ningún error. El "${var#prefijo}"
# de bash no tiene ese problema con sufijos vacíos.
FIRST_STANZA="$(awk '/^$/{exit} {print}' binary/isolinux/live.cfg)"
KERNEL_PATH="$(echo "${FIRST_STANZA}" | grep -m1 'kernel' | awk '{print $2}')"
APPEND_LINE="$(echo "${FIRST_STANZA}" | grep -m1 'append')"
INITRD_PATH="${APPEND_LINE#*initrd=}"
INITRD_PATH="${INITRD_PATH%% *}"
BOOTAPPEND_LIVE="${APPEND_LINE#*console=ttyS0,115200n8 }"

if [ -f binary/isolinux/install.cfg.in ]; then
    echo "==> Renderizando install.cfg.in -> install.cfg (lb_binary_syslinux no lo procesa solo)"
    sed -e "s|@KERNEL@|${KERNEL_PATH}|g" \
        -e "s|@INITRD@|${INITRD_PATH}|g" \
        -e "s|@LB_BOOTAPPEND_LIVE@|${BOOTAPPEND_LIVE}|g" \
        binary/isolinux/install.cfg.in > binary/isolinux/install.cfg
    rm -f binary/isolinux/install.cfg.in
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

# Arranque UEFI -- issue #6. Esta versión de live-build (ver el
# comentario grande en auto/config) solo sabe generar UN catálogo El
# Torito (BIOS, vía isohybrid) -- no tiene ningún camino para producir
# una ISO híbrida BIOS+UEFI nativamente, sin importar qué
# --bootloader se elija (confirmado leyendo /usr/lib/live/build/
# lb_binary_iso: un solo -b/-c por invocación de genisoimage). En vez
# de parchear live-build, injertamos el arranque UEFI a mano sobre la
# binary.hybrid.iso YA armada, con xorriso -- mismo criterio que el
# resto de este script (post-procesar en vez de tocar el paquete).
#
# Alcance: esto cierra "arranca en firmware UEFI", NO "arranca con
# Secure Boot activo" -- BOOTX64.EFI sale de grub-mkstandalone sin
# firmar, y un firmware con Secure Boot habilitado (default en la
# mayoría de laptops UEFI reales) lo va a rechazar. Habilitar Secure
# Boot está fuera de alcance del roadmap (ver docs/ROADMAP.md) -- para
# arrancar esta ISO en un equipo real con Secure Boot activo hay que
# desactivarlo primero en la configuración del firmware.
#
# Bug real encontrado prototipando esto (ver commit): `xorriso -indev
# X -outdev Y` (Y un archivo NUEVO, distinto de X) TRUNCA cualquier
# archivo que dependa del puente UDF para representar su tamaño real
# (nuestro caso: filesystem.squashfs, que supera 4GiB-1 -- ver
# -allow-limited-size/-udf más arriba en este mismo script). Confirmado
# con un archivo sintético de prueba de 4.4GB con marcadores en
# offsets conocidos: con -outdev a un archivo nuevo, el archivo
# resultante quedaba en ~100MB (la interpretación ISO9660/RockRidge del
# tamaño, que -allow-limited-size sabe que es incorrecta -- xorriso lee
# esa en vez del valor correcto del árbol UDF al recopiar todo de cero
# a un image nuevo). La fix: usar `-dev` (mismo archivo de entrada Y
# salida) en vez de `-indev`/`-outdev` separados -- xorriso trata esto
# como una sesión NUEVA agregada al final del archivo existente (multi-
# session, como grabar un CD-R de a partes), nunca necesita re-leer ni
# re-copiar los bytes de la sesión anterior -- los marcadores del
# archivo de prueba sobrevivieron bit a bit, en el offset exacto, con
# este enfoque. Confirmado también de punta a punta en QEMU (BIOS Y
# UEFI/OVMF) contra binary.hybrid.iso real, sin este bug (real, no
# sintético) porque el squashfs de la variante bare usada para probar
# no llegaba a superar 4GiB -- la prueba del archivo sintético es la
# que efectivamente cubre ese caso.
if command -v grub-mkstandalone >/dev/null && command -v xorriso >/dev/null && command -v mformat >/dev/null; then
    echo "==> Agregando arranque UEFI (grub-mkstandalone + ESP FAT + xorriso, ver comentario arriba)"

    UEFI_WORK="$(mktemp -d)"
    trap 'rm -rf "${UEFI_WORK}"' EXIT

    # Mismos KERNEL_PATH/INITRD_PATH/BOOTAPPEND_LIVE ya extraídos de
    # live.cfg más arriba para renderizar install.cfg.in -- una sola
    # fuente de verdad para los tres bootloaders (isolinux BIOS, GRUB
    # UEFI, y el install.cfg.in ya renderizado), nunca tres lugares
    # separados que puedan desincronizarse.
    cat > "${UEFI_WORK}/grub.cfg" <<EOF
insmod part_msdos
insmod part_gpt
insmod fat
insmod iso9660
insmod search
insmod search_fs_file
insmod all_video

search --no-floppy --set=root --file ${KERNEL_PATH}

set timeout=5
set default=0

menuentry "Live" {
    linux ${KERNEL_PATH} boot=casper config console=tty0 console=ttyS0,115200n8 ${BOOTAPPEND_LIVE}
    initrd ${INITRD_PATH}
}

menuentry "Instalar Likay-OS" {
    linux ${KERNEL_PATH} boot=casper config console=tty0 console=ttyS0,115200n8 likay.mode=installer likay.privileged ${BOOTAPPEND_LIVE}
    initrd ${INITRD_PATH}
}
EOF

    grub-mkstandalone -O x86_64-efi -o "${UEFI_WORK}/BOOTX64.EFI" \
        --modules="part_msdos part_gpt fat iso9660 search search_fs_file all_video normal linux" \
        --fonts="" --themes="" --locales="" \
        "boot/grub/grub.cfg=${UEFI_WORK}/grub.cfg"

    # 16MiB alcanza de sobra para un solo BOOTX64.EFI (~4.3MB armado
    # arriba) -- ESP real, no simbólico, es lo que xorriso injerta como
    # segunda partición (ver -append_partition abajo).
    dd if=/dev/zero of="${UEFI_WORK}/esp.img" bs=1M count=16 status=none
    mkfs.vfat -n LIKAY_ESP "${UEFI_WORK}/esp.img" >/dev/null
    mmd -i "${UEFI_WORK}/esp.img" ::/EFI
    mmd -i "${UEFI_WORK}/esp.img" ::/EFI/BOOT
    mcopy -i "${UEFI_WORK}/esp.img" "${UEFI_WORK}/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI

    # -dev, NO -indev/-outdev (ver el comentario grande de arriba) --
    # agrega el catálogo El Torito UEFI (para arranque óptico/QEMU
    # -cdrom) Y una partición MBR tipo 0xef con el mismo contenido
    # (para arranque desde USB grabado con dd, donde el firmware lee
    # la tabla de particiones en vez de un catálogo El Torito).
    xorriso -dev binary.hybrid.iso \
        -boot_image any replay \
        -append_partition 2 0xef "${UEFI_WORK}/esp.img" \
        -boot_image any next \
        -boot_image any efi_path=--interval:appended_partition_2:all:: \
        -boot_image any platform_id=0xef \
        -boot_image any emul_type=no_emulation \
        -commit

    rm -rf "${UEFI_WORK}"
    trap - EXIT
    echo "==> Arranque UEFI agregado (BIOS intacto -- la ISO ahora arranca en ambos)"
else
    echo "==> AVISO: falta grub-mkstandalone/xorriso/mformat en el host -- la ISO queda solo BIOS/legacy (ver 'Requisitos (host)' en iso/README.md)" >&2
fi

# Copia con nombre distinguible por variante -- pedido explícito del
# usuario (2026-09-16): "no dejaría que ambas ISOs terminen con nombres
# indistinguibles". binary.hybrid.iso sigue siendo el artefacto de
# trabajo (lo referencian el resto de los scripts/docs de prueba en
# QEMU) -- esta copia es específicamente la que se flashea a un USB
# real, para no confundir accidentalmente qué variante se está grabando.
cp -f binary.hybrid.iso "${ISO_ARTIFACT_NAME}"
echo "==> Artefacto para flashear: ${ISO_ARTIFACT_NAME}"
