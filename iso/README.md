# iso/ — build de la ISO live-boot

Esta carpeta arma la ISO de Etapa 1 del [roadmap](../docs/ROADMAP.md):
un USB booteable (sin instalar nada, sin tocar el disco del host) que
arranca directo a un kiosco de pantalla completa, con el kernel
[kal](https://github.com/carlosbv99-bit/kal) montado y el agente de
referencia [kal-in](https://github.com/carlosbv99-bit/kal-in) corriendo
arriba (ver "Estado actual" más abajo).

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

## Estado actual

Confirmado arrancando de punta a punta, en QEMU y en hardware real
(USB grabado con `dd`): kernel → `qwen2.5:3b` (LLM propio de Likay-OS,
vía Ollama) → `kal-in` (agente de referencia, ver más abajo) → kiosco.

- **LLM propio horneado:** `config/likay/model.conf` define
  `qwen2.5:3b` — clasificación de intención + orientación al usuario
  (ver `docs/ROADMAP.md`, Etapa 1), no el modelo de trabajo del agente.
  El límite de 4GiB-1 de ISO9660 para un archivo único (que en su
  momento obligó a probar sin modelo) está resuelto de raíz — ver
  `0550-fix-casper-udf-detection.chroot` en "Cosas raras" más abajo.
- **Agente montado — prototipo de validación, issue [#2](https://github.com/Kevindelb/Likay-OS/issues/2), Fase 1:**
  `vendor/kal-in` (el agente de referencia, sobre el kernel `vendor/kal`)
  vendorizado y conectado a mano vía `kal-in-backend.service`, solo para
  probar kernel→LLM→agente→kiosco de punta a punta. En el diseño final
  ningún agente va horneado en la ISO — el usuario lo monta en su
  propia partición del disco, con Likay-OS ya instalado (ver
  `docs/ROADMAP.md`, decisión del 2026-09-14, Etapa 2). `kal-in` sigue
  trayendo su propio `kernel/`/`agent_core`/`frontend` completos (la
  separación de código *adentro* de kal-in es trabajo futuro de ese
  repo) — corre standalone, no depende de `vendor/kal` todavía.
- **Limitación conocida:** `kal-in` solo usa `qwen2.5:3b` para su
  clasificador de intención (`conversation_engine`, ver
  `vendor/kal-in/config/config.yaml`) — el modelo de trabajo real
  (`llm.default_model`, por default `qwen3.5:4b-q4_K_M`) NO está
  horneado. Pedirle a kal-in una tarea real que necesite ese modelo va
  a fallar sin red. Para hornear también ese modelo, agregar su tag a
  `model-cache/` (mismo mecanismo de hardlinks que ya usa `qwen2.5:3b`)
  o resolverlo como su propio paso — no es parte de esta etapa todavía.
- **Instalador de Etapa 2 — trabajo en curso, pendiente de re-probar en
  QEMU:** una segunda entrada de arranque ("Instalar Likay-OS",
  `config/bootloaders/isolinux/install.cfg.in`) agrega
  `likay.mode=installer` a la línea de kernel, lo único que decide si
  el arranque sigue por `likay-kiosk.service` (Wayland/cage) o por
  `likay-installer.service` (Xorg mínimo + Calamares) — nunca ambos.
  Confirmado en QEMU: la elección de modo funciona bien (kernel
  command line correcto, `likay-kiosk.service` se saltea solo en modo
  instalador). Calamares corre como el usuario de sistema estático
  `likay-installer`, autorizado a escalar a root vía una regla de
  PolicyKit propia (`etc/polkit-1/rules.d/60-likay-installer.rules`)
  — reemplaza el `auth_admin` por defecto de Calamares porque el medio
  live no tiene ninguna cuenta administrativa humana. Vendorizado
  desde `calamares-settings-debian` (config oficial del Debian Live
  Team).
  - **Bug real encontrado y corregido (2026-09-14):** la primera
    versión usaba `DynamicUser=yes` para el usuario `likay-installer`
    — la documentación de systemd dice explícito que eso fuerza
    `NoNewPrivileges=yes` de forma no desactivable, lo que cuelga
    `pkexec calamares` en silencio para siempre (confirmado en QEMU:
    el arranque llegaba a "Started likay-installer.service" y no
    avanzaba nunca más, sin ningún error visible). Corregido con un
    usuario de sistema estático (`useradd -r`, hook
    `0420-setup-installer.chroot`), mismo patrón que `kiosk`/`kal`/
    `kal-in` — todavía sin re-confirmar en QEMU que el arreglo
    funciona de punta a punta.
  - **Corregido en el mismo hallazgo:** `kal-in-backend.service` y
    `ollama.service` (este último vía un drop-in, ya que su unidad la
    instala el script de Ollama, no es nuestra) arrancaban igual en
    modo instalador — no era un camino hacia root, pero sí superficie
    innecesaria mientras hay acceso privilegiado al disco de por
    medio. Ahora tienen la misma `ConditionKernelCommandLine` que
    `likay-kiosk.service`.
  - Todavía sin conectar: particionado real (dual-boot, LUKS,
    partición para el agente), Secure Boot/TPM. Ver
    `docs/ROADMAP.md`, Etapa 2.

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
