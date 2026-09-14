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

### Probar el modo instalador (`likay.mode=installer`)

El menú de arranque tiene 5 segundos de timeout, muy poco para
interactuar a mano de forma confiable en pruebas automatizadas —
mejor arrancar directo con el kernel/initrd extraídos del propio
`.iso` (sin mount, sin root):

```bash
xorriso -osirrox on -indev binary.hybrid.iso \
  -extract /live/vmlinuz /tmp/vmlinuz \
  -extract /live/initrd.img /tmp/initrd.img

qemu-system-x86_64 \
  -enable-kvm -cpu host -smp 4 -m 4096 \
  -device virtio-rng-pci -usb -device usb-tablet \
  -cdrom binary.hybrid.iso \
  -drive file=/tmp/disco-de-prueba.qcow2,if=virtio,format=qcow2 \
  -kernel /tmp/vmlinuz -initrd /tmp/initrd.img \
  -append "boot=casper config console=tty0 console=ttyS0,115200n8 likay.mode=installer" \
  -vnc :5
```

(`qemu-img create -f qcow2 /tmp/disco-de-prueba.qcow2 40G` para el
disco descartable — nunca toca el disco real del host.)

Para clickear la UI de Calamares sin cabeza: `-vnc :N` en vez de
`-display none` — `mouse_move`/`mouse_button` del monitor HMP
**no funcionan de forma confiable** con `-display none` aunque
`info mice` muestre el puntero activo (probado, descartado). Con VNC
sí funciona, vía [`vncdotool`](https://pypi.org/project/vncdotool/)
(`pip install vncdotool` en un venv descartable, no hace falta sudo):

```bash
vncdotool -s localhost:5 move 1007 672 click 1   # mover Y clickear
                                                   # en la MISMA llamada
vncdotool -s localhost:5 capture screenshot.png
```

Ojo: cada invocación de `vncdotool` es una conexión nueva, el cursor
arranca en el origen — siempre encadenar `move` justo antes de
`click` en la misma llamada, no asumir que la posición persiste entre
llamadas separadas.

**Importante:** `/tmp` puede ser `tmpfs` (RAM, no disco) en algunas
máquinas — confirmado en la máquina de desarrollo de este proyecto,
con solo ~7.5G de capacidad. Un archivo de prueba de varios GB ahí
puede agotar la RAM y colgar el equipo entero (pasó de verdad
armando el disco de prueba dual-boot de abajo). Usá `/var/tmp`
(respaldado por disco) para cualquier imagen de disco o archivo
grande de prueba.

Para simular un disco con Windows/NTFS ya instalado (probar
dual-boot) sin root ni loop devices:

```bash
qemu-img create -f raw /var/tmp/disco.img 40G   # RAW, no qcow2 --
                                                  # parted necesita
                                                  # operar el archivo
                                                  # directo
parted --script /var/tmp/disco.img mklabel msdos
parted --script /var/tmp/disco.img mkpart primary ntfs 1MiB 35GiB
parted --script /var/tmp/disco.img unit s print   # confirmar el
                                                   # sector de inicio
                                                   # real (típicamente
                                                   # 2048s = 1MiB)

# formatear un archivo aparte, del tamaño exacto de la partición
qemu-img create -f raw /var/tmp/ntfs-part.img <tamaño-en-bytes>
mkfs.ntfs -f -F -L "Windows" /var/tmp/ntfs-part.img

# insertarlo en el disco completo, en el offset correcto
dd if=/var/tmp/ntfs-part.img of=/var/tmp/disco.img \
   bs=1M seek=1 conv=notrunc,sparse   # seek=1 si la partición
                                       # arranca en 1MiB
```

`conv=sparse` mantiene el archivo destino disperso (sparse) — el uso
real de disco queda en decenas de MB, no en los 40G nominales
(confirmar con `du -sh`, no con `ls -la`).

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
- **Instalador de Etapa 2 — mecanismo gráfico/de privilegios
  confirmado en QEMU (2026-09-14):** una segunda entrada de arranque
  ("Instalar Likay-OS", `config/bootloaders/isolinux/install.cfg.in`)
  agrega `likay.mode=installer` a la línea de kernel, lo único que
  decide si el arranque sigue por `likay-kiosk.service` (Wayland/cage)
  o por `likay-installer.service` (Xorg mínimo + Calamares) — nunca
  ambos. Confirmado de punta a punta: Xorg arranca bajo el usuario de
  sistema estático `likay-installer`, `pkexec calamares` escala a root
  **sin pedir contraseña** (regla de PolicyKit propia scoped a ese
  usuario, `etc/polkit-1/rules.d/60-likay-installer.rules` — reemplaza
  el `auth_admin` por defecto porque el medio live no tiene ninguna
  cuenta administrativa humana), y la UI real de Calamares se ve
  ("Welcome to the Calamares installer for Debian 14"). Vendorizado
  desde `calamares-settings-debian` (config oficial del Debian Live
  Team).
  - **Cuatro bugs reales encontrados y corregidos en el camino**
    (cada uno confirmado en QEMU antes de pasar al siguiente): (1)
    `DynamicUser=yes` para `likay-installer` fuerza
    `NoNewPrivileges=yes` de forma no desactivable (documentación de
    systemd) — colgaba `pkexec` en silencio para siempre; corregido
    con un usuario de sistema estático (`useradd -r`, hook
    `0420-setup-installer.chroot`), mismo patrón que
    `kiosk`/`kal`/`kal-in`. (2) `Xorg.wrap` rechazaba el arranque
    ("Only console users are allowed to run the X server") porque un
    job de shell en segundo plano sin `stdin` explícito se redirige
    solo a `/dev/null` por regla POSIX — corregido con `</dev/tty1`
    explícito en `installer-launcher` (el cambio de VT2→VT1 de un
    commit anterior no era la causa real, solo coincidencia de
    mensaje). (3) `pkexec` es un paquete separado de `polkitd` —
    faltaba listarlo. (4) `settings.conf` vendorizado referencia seis
    módulos custom de Debian ("process", scripts de shell — no
    binarios compilados como se asumió al principio) que no venían
    instalados.
  - **Corregido de paso:** `kal-in-backend.service` y
    `ollama.service` (este último vía un drop-in, ya que su unidad la
    instala el script de Ollama, no es nuestra) arrancaban igual en
    modo instalador — no era un camino hacia root, pero sí superficie
    innecesaria mientras hay acceso privilegiado al disco de por
    medio. Ahora tienen la misma `ConditionKernelCommandLine` que
    `likay-kiosk.service`.
- **Particionado — primer esquema, confirmado visualmente de punta a
  punta en QEMU con un disco virtual real conectado (2026-09-14):**
  `root` (/, ext4, tamaño fijo 20G) + `likay-agent` (ext4, `size: 100%`
  — "lo que quede" — + `minSize: 10G`, sin `mountPoint` a propósito —
  Calamares la crea pero no la toca más, es donde el usuario instala su
  propio agente después, issue #2 Fase 2, mecanismo de montaje todavía
  sin diseñar). Ambas LUKS2, misma passphrase compartida vía crypttab
  — el roadmap ya exige LUKS en esta etapa justo por los
  tokens/credenciales que un agente puede guardar ahí. Sin ESP —
  Calamares lo antepone solo si hace falta UEFI, y seguimos BIOS/
  legacy (issue #6). Tamaños son placeholder, ajustables. Configurado
  vía hook `0440-configure-calamares-partitioning.chroot`.
  - **Bug real en el camino:** la primera versión usaba `size: 70%` +
    `size: 30%` (en teoría sumando el 100% del disco) — en un disco de
    prueba de 40G, Calamares terminó proponiendo root=21G,
    likay-agent=10G y **9G de "Free Space" sin asignar**. El propio
    ejemplo de `partitionLayout` en `partition.conf` usa `size: 100%`
    solo en la ÚLTIMA entrada de la lista (osea "lo que quede", no
    porcentajes independientes) — se seguió ese patrón documentado en
    vez de inventar uno propio: root pasó a tamaño fijo, likay-agent a
    `100%`.
  - **Confirmado visualmente después del fix:** con el disco de 40G,
    "Erase disk" ahora propone root=20GiB + likay-agent=20GiB, sin
    nada de "Free Space" sobrante. Tildar "Encrypt system" y escribir
    una passphrase cambia la etiqueta de ambas particiones de "ext4" a
    **"LUKS2"**, con el check verde de confirmación — el diseño de
    "una sola passphrase para las dos particiones" funciona tal cual
    en la UI real, no solo en el YAML. No se completó una instalación
    real (no hacía falta para esta validación).
  - **De los seis módulos de Debian que no venían instalados, tres se
    restauraron de verdad** (`dpkg-unsafe-io(-undo)` tal cual, y
    `bootloader-config` con una versión propia que hornea
    `grub-pc`/`cryptsetup`/`cryptsetup-initramfs`/`keyutils` en el
    medio live en vez de instalarlos en vivo por red durante el
    install). **Los otros tres quedan afuera de la secuencia
    permanentemente, no como pendiente** (`sources-media(-unmount)`,
    `sources-final`, hook `0430-trim-calamares-sequence.chroot`):
    verificado a mano montando el squashfs horneado, `/etc/apt/
    sources.list` ya tiene las fuentes reales de Ubuntu resolute sin
    que nuestro pipeline las toque — `sources-final` (que Debian usa
    para reescribir esto) no tendría nada útil que hacer. Y
    `packages.conf` (ver abajo) solo remueve paquetes, nunca instala,
    así que tampoco necesita `sources-media` (que le daría a apt un
    origen local). No es que sean incompatibles y haya que
    reescribirlos — genuinamente no hacen falta en nuestro caso.
  - **`packages.conf` corregido** (hook
    `0450-configure-calamares-packages.chroot`): la lista `remove:`
    vendorizada nombra paquetes de Debian (`live-boot`, `live-config`)
    que nunca instalamos (usamos `casper`) — inofensivo pero inútil,
    `apt remove` sobre algo no instalado no hace nada. Reemplazada por
    `remove: [casper]`, que sí es basura real solo-para-live en un
    sistema ya instalado. Deliberadamente sin tocar el resto del stack
    de kiosco (`cage`/`epiphany-browser`/`xdg-desktop-portal*`) — si
    el Likay-OS instalado sigue siendo kiosco o se vuelve un sistema
    "normal" es una pregunta de diseño todavía sin resolver (issue
    #1), no algo para decidir de paso acá.
  - **Dual-boot — probado parcialmente, bloqueado por un crash real de
    Calamares (2026-09-14):** con un disco de prueba armado a mano con
    una partición NTFS real (`parted` + `mkfs.ntfs` directo sobre un
    archivo, sin loop device ni root — ver nota al final de "Probar en
    QEMU"), Calamares detecta bien la partición (`vda1: 35.00 GiB
    NTFS` + `Free Space: 5.00 GiB`) y ofrece una opción nueva,
    "Replace a partition", que no aparece con disco vacío. "Alongside"
    nunca apareció — probablemente porque una NTFS vacía (sin archivos
    reales de Windows) no la detecta `os-prober` como sistema
    operativo real, haría falta simular una instalación de Windows más
    elaborada para probar ese camino específico. **Bug real de
    Calamares, diagnosticado con `gdb` en vivo dentro de la VM:**
    clickear el checkbox/barra de selección de partición dentro del
    flujo "Replace a partition" cuelga toda la sesión Xorg/Calamares
    con `Segmentation fault` — reproducido tres veces (un doble-click,
    un click simple sobre el checkbox, y una vez más ya corriendo bajo
    `gdb`). El backtrace del thread que crashea es 100% interno de Qt,
    sin ningún símbolo de Calamares:
    `QListView::currentChanged` → `QAbstractItemView::currentChanged`
    → `QStandardItemModel::flags()` → `QStandardItem::child()` —
    sugiere un `QModelIndex` inválido/desactualizado en el modelo que
    arma esa lista. No es nuestro — reporte preparado con el backtrace
    completo para subir a
    [Codeberg.org/Calamares/calamares/issues](https://codeberg.org/Calamares/calamares/issues)
    (Codeberg, no GitHub — el proyecto movió ahí su tracker; texto
    completo del reporte en `/var/tmp/likay-dualboot/
    calamares-bug-report.md`, todavía sin publicar al escribir esto —
    actualizar este link con el número real una vez publicado). El
    scaffolding de `gdb` usado para esto
    (paquete + acción de PolicyKit propia + wrapper) fue temporal,
    revertido (`c2374e5`, `d89ca6e`) — no queda en el build normal.
  - Todavía sin conectar: Secure Boot/TPM (bloqueado por UEFI, issue
    #6, fuera de alcance por ahora). Ver `docs/ROADMAP.md`, Etapa 2.

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
