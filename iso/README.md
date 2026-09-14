# iso/ — build de la ISO live-boot

Esta carpeta arma la ISO de Etapa 1 del [roadmap](../docs/ROADMAP.md):
un USB booteable (sin instalar nada, sin tocar el disco del host) que
arranca directo a un kiosco de pantalla completa mostrando el chat de
[kal](https://github.com/carlosbv99-bit/kal).

Usa [live-build](https://salsa.debian.org/live-team/live-build) (la
versión empaquetada por Ubuntu, `3.0~a57-1ubuntu54` al momento de
escribir esto) más algunos scripts y hooks propios para tapar varios
bugs reales de esa versión — ver la sección "Cosas raras" más abajo.

## Requisitos (host)

Probado en Ubuntu 26.04. Necesitás:

```bash
sudo apt install live-build qemu-system-x86 python3-pip git rsync
```

`sudo` hace falta para `lb build` (arma un chroot de verdad). El resto
de las herramientas del build (`genisoimage`, `syslinux`, `isolinux`,
etc.) se instalan *adentro* del chroot vía
`config/package-lists/likay.list.chroot` — no hace falta instalarlas
en el host.

## Estructura

```
auto/build              # script principal — correlo con "sudo ./auto/build"
auto/clean               # limpieza — "sudo ./auto/clean --binary" o "--all"
auto/config               # genera config/ vía `lb config` (ya corrido, normalmente no hace falta re-correrlo)
config/package-lists/      # paquetes que se instalan en el chroot
config/hooks/*.chroot       # scripts que corren DENTRO del chroot, en orden numérico
config/includes.chroot/       # archivos que se copian tal cual al filesystem final
config/bootloaders/isolinux/    # override de la plantilla de syslinux (bugs de la plantilla original)
config/likay/model.conf          # qué modelo de Ollama hornear en la ISO
scripts/rebuild-iso-with-fixes.sh # reconstruye el .iso final a mano (bugs de lb_binary_iso)
model-cache/                       # cache de blobs de Ollama entre builds (gitignored, no se versiona)
```

## Build

```bash
cd iso
sudo ./auto/build
sudo ./scripts/rebuild-iso-with-fixes.sh
```

**Dos comandos, no uno** — `scripts/rebuild-iso-with-fixes.sh` arregla
dos bugs reales de `lb_binary_iso` (ver "Cosas raras" más abajo) que
dejan el `.iso` sin arrancar aunque el build "termine bien". Antes
estaba encadenado automáticamente al final de `auto/build`, pero
encadenado así, simplemente no aplicaba su propio arreglo — sin ningún
error visible, confirmado en vivo varias veces con timestamps. Corrido
como comando aparte, en cambio, siempre funcionó. No se encontró la
causa de fondo; se lo dejó como paso manual porque es el que
realmente funciona.

Tarda varios minutos (la mayor parte en `auto/build`). Al final vas a
tener `binary.hybrid.iso` en esta carpeta — booteable tanto por USB
(`dd`) como en una VM.

`chroot/` se conserva entre builds a propósito (así no hay que
reinstalar Python/kal/cage desde cero en cada iteración) — pero
`auto/build` fuerza que las etapas que sí importan (hooks, instalación
de paquetes, `binary/`) corran siempre, así que no hace falta correr
`auto/clean` entre corridas normales. Si algo se ve raro después de
tocar `config/`, `sudo ./auto/clean --binary` (mantiene `chroot/`) o
`--all` (limpia todo, build desde cero) son la salida segura.

## Probar en QEMU

```bash
qemu-system-x86_64 \
  -enable-kvm -cpu host -smp 4 -m 4096 \
  -device virtio-rng-pci \
  -cdrom binary.hybrid.iso
```

Notas sobre estas flags (todas se encontraron necesarias probando en
vivo, no son capricho):

- `-enable-kvm -cpu host`: sin esto, numpy (parte de las dependencias
  de kal) crashea porque el modelo de CPU por default de QEMU no trae
  las instrucciones baseline x86-64-v2 que el wheel de numpy pide.
- `-device virtio-rng-pci`: sin una fuente de entropía, el kernel
  puede tardar minutos en `crng init done`, y el boot parece colgado.
- `-cdrom` (no `-drive ...,if=virtio`): el detector de medio live de
  casper busca específicamente un dispositivo tipo CD-ROM. Un USB real
  se reporta como removible y no debería tener este problema.

Usuario `kiosk` sin contraseña — no hay login de verdad en este modo,
`likay-kiosk.service` arranca solo. Para entrar por consola a mirar
logs en vivo, agregá temporalmente algo como
`Environment=StandardOutput=journal+console` (ya está puesto) y mirá
la consola serie (`-serial file:log.txt` o `-serial stdio`), o
`chpasswd` en un hook temporal como se hizo durante el desarrollo (no
lo dejes en un commit).

## Estado actual: sin modelo horneado

Los hooks `0100-install-ollama.chroot` y `0200-pull-ollama-model.chroot`
están renombrados a `.disabled` — la ISO actual arranca el kiosco y
`kal-backend`, pero sin Ollama instalado (el indicador "LLM" en la UI
sale en rojo). Esto fue una decisión deliberada para aislar el pipeline
de boot del problema de tamaño: un `filesystem.squashfs` con Ollama +
un modelo de 4B pesa más de 4GiB, el límite de un archivo único en
ISO9660 — `genisoimage`/casper no lo manejan bien (ver comentarios en
`scripts/rebuild-iso-with-fixes.sh`).

Para volver a habilitar el modelo:

1. `mv config/hooks/0100-install-ollama.chroot.disabled config/hooks/0100-install-ollama.chroot`
   (mismo para `0200`).
2. Definir qué modelo hornear en `config/likay/model.conf` — candidato
   fuerte: `qwen2.5:3b` en vez de `qwen3.5:4b-q4_K_M` (el modelo chico
   que kal ya usa como clasificador de intención, siempre cargado —
   ver `vendor/kal/agent_core/conversation_engine.py`), mucho más chico
   y evita el problema de tamaño de entrada.
3. Resolver el límite de 4GiB si igual hace falta un modelo más grande
   (squashfs en capas separadas, o UDF real en vez del parche actual).

## Cosas raras de esta versión de live-build (por qué tantos hooks/parches)

Esta versión de live-build es vieja y tiene varios bugs reales que
costó bastante encontrar. Cada uno está documentado en detalle como
comentario en el archivo donde se resuelve — no los repetimos acá,
pero la lista de "dónde mirar" si algo se rompe parecido:

- **Markers de `.build/` que no reflejan el estado real de `config/`
  ni de `chroot/`** (hooks, instalación de paquetes, `binary/` que se
  saltean solos) → `auto/build`, comentario arriba del `rm -f .build/...`.
- **`_SUFFIX` sin definir en `lb_binary_syslinux`** (typo real de
  live-build) → `auto/build`, `export _SUFFIX=...`.
- **Bootloader**: tiene que ser `syslinux`, no `grub`/`grub2` (rompe el
  hybrid ISO) → `auto/config`.
- **`isolinux.bin`/`vesamenu.c32`/`ldlinux.c32` en rutas viejas que ya
  no existen** → `config/hooks/0500-fix-syslinux-paths.chroot`.
- **`start-stop-daemon` desaparece del chroot** después de cierto punto
  del build (bug de `dpkg-divert` en sistemas con `/sbin` fusionado a
  `/usr/sbin`) → por eso `config/package-lists/likay.list.chroot`
  instala TODO lo que la etapa `binary` necesitaría instalar solo.
- **`filesystem.squashfs`/`/live/vmlinuz` rotos en el `.iso` final**
  pese a que el build "termina bien" → `scripts/rebuild-iso-with-fixes.sh`.
- **Ubuntu 26.04 usa `dracut` por default, casper necesita
  `initramfs-tools`** → `config/hooks/0600-regenerate-initramfs.chroot`.
- **`cage` (el compositor Wayland del kiosco) arranca Xwayland aunque
  nunca se use, y crashea al cerrarlo** (bug de wlroots) → recompilado
  sin soporte de Xwayland en
  `config/hooks/0350-build-cage-noxwayland.chroot`.

Si algo de esto vuelve a aparecer (por ejemplo, al actualizar la
versión de Ubuntu base), el patrón general para depurarlo fue: arrancar
en QEMU con `console=ttyS0` puesto (ya está, ver
`config/bootloaders/isolinux/live.cfg.in`) y consola serie redirigida a
un archivo, y si el mensaje de systemd/journal no alcanza, instalar
`gdb` en vivo dentro de la VM (necesita red — agregar
`-netdev user,id=net0 -device virtio-net-pci,netdev=net0` al comando de
QEMU) y atrapar la señal real con `gdb -batch -ex run ...`.
