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

### Variante bare (sin kal-in horneado)

```bash
cd iso
sudo LIKAY_BARE_KAL_IN=1 ./auto/build
sudo ./scripts/rebuild-iso-with-fixes.sh
```

Por default el build hornea `kal-in` (Fase 1 del issue #2, prototipo de
validación del pipeline de boot — ver docs/ROADMAP.md). La variante
`bare` la saca por completo: nada de `vendor/kal-in` en el chroot,
`kal-in-backend.service` ni instalado ni habilitado. Sirve para probar
el mecanismo genérico de "instalar un agente externo" (TUI +
`agent-install-helper` + Broker + sandbox, ver `docs/AGENT_INTERFACE.md`)
sobre un sistema realmente limpio — si aparece un agente andando después
de instalar esta ISO, se sabe con certeza que vino del flujo de
instalación externa, no de algo horneado de fábrica.

`LIKAY_BARE_KAL_IN` se lee una sola vez, en `auto/build` — es el único
punto de decisión de la variante; todo lo que depende de kal-in
(el propio `vendor/kal-in`, el hook `0320-install-kal-in.chroot`, el
`systemctl enable` de `0400-setup-kiosk.chroot`, la Condition de
`kal-in-backend.service`) lo lee de ahí en cascada, nunca decide por su
cuenta. `sudo ./scripts/rebuild-iso-with-fixes.sh` no necesita que le
repitas la variable — la variante queda persistida en
`.likay-build-variant` (generado por `auto/build`, no versionado) para
que el segundo comando no pueda desincronizarse del primero.

El resultado final es un archivo con nombre distinto por variante
(`likay-os-amd64.iso` / `likay-os-amd64-bare.iso`, junto al
`binary.hybrid.iso` de siempre que siguen usando el resto de los
scripts/docs de prueba en QEMU) — para no arriesgarse a flashear la ISO
equivocada a un USB real.

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
  - **Dual-boot — funciona hoy, vía "Manual partitioning"
    (2026-09-15):** con el mismo disco de prueba (NTFS real +
    5GiB libres), seleccionar "Manual partitioning" en vez de
    "Replace a partition" abre un editor de particiones completo
    (tabla `Name`/`File System`/`Label`/`Mount Point`/`Size`, no el
    `QListView` roto) — seleccionar "Free Space", "Create", elegir
    `ext4` + mount point `/`, confirma sin ningún error: queda
    `/dev/vda1` (NTFS, sin tocar) + `New Partition` (ext4, `/`, 5GiB)
    con bootloader apuntando al MBR de `vda`. Un usuario puede lograr
    dual-boot real hoy mismo por este camino, sin depender de que
    Calamares arregle el bug de abajo — solo el camino AUTOMÁTICO
    ("Replace a partition"/probablemente "Alongside" también, no
    confirmado) está roto.
  - **Bug real de Calamares en el camino automático — probado
    parcialmente, bloqueado (2026-09-14):** con un disco de prueba
    armado a mano con
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
    arma esa lista. No es nuestro — reportado upstream con el
    backtrace completo en
    [Calamares/calamares#2535](https://codeberg.org/Calamares/calamares/issues/2535)
    (Codeberg, no GitHub — el proyecto movió ahí su tracker). El
    scaffolding de `gdb` usado para esto
    (paquete + acción de PolicyKit propia + wrapper) fue temporal,
    revertido (`c2374e5`, `d89ca6e`) — no queda en el build normal.
  - **"Alongside" — la sospecha de arriba (que os-prober no detectaba
    una NTFS vacía) era incorrecta; bug real distinto, encontrado y
    corregido (2026-09-15):** armando un disco de prueba con contenido
    Windows-*ish* de verdad (`bootmgr` + `Boot/BCD` con la cadena
    "Windows 10" codificada en UTF-16LE, igual que un BCD real —
    escrito directo con `ntfscp`/montaje FUSE de `ntfs-3g` en el host,
    sin root, ver nota al final de "Probar en QEMU"), os-prober
    detectó bien "Windows 10" (se vio en la barra de particiones), pero
    "Install alongside" seguía sin aparecer — solo "Replace a
    partition"/"Erase disk"/"Manual partitioning". Leyendo
    `ChoicePage.cpp` de Calamares upstream: el botón de Alongside se
    oculta salvo que `PartUtils::canBeResized()` devuelva true para
    alguna partición, y esa función depende de `candidate->available()`
    — el espacio libre *dentro* del filesystem NTFS existente, que
    KPMcore calcula en runtime llamando a `ntfsresize` (paquete
    `ntfs-3g`). `libkpmcore13` solo lo necesita en runtime, no lo
    declara como `Depends`/`Recommends` de dpkg — nunca se había
    instalado en el medio live (a diferencia del sistema instalado, que
    no lo necesita para nada). Sin él, KPMcore no puede leer cuánto
    lugar libre tiene la partición de Windows y `canBeResized()`
    devuelve false siempre, ocultando Alongside sin importar cuánto
    espacio real hubiera. Agregado `ntfs-3g` al package-list. **Confirmado
    después del fix:** "Install alongside" aparece, seleccionarlo abre
    el slider de resize real ("Select a partition to shrink, then drag
    the bottom bar to resize"), clickear la partición Windows 10 la
    selecciona y calcula automáticamente `/dev/vda1 will be shrunk to
    2968MiB and a new 32870MiB partition will be created for Debian`,
    con "Next" habilitado. No se completó el install real por este
    camino (alcanzaba con confirmar que el slider calcula y habilita
    bien) — el camino "Replace a partition" sigue bloqueado por el bug
    de Qt de arriba (#2535), pero "Alongside" es una vía automática
    alternativa que ya funciona de punta a punta hasta el paso de
    partición.
  - Todavía sin conectar: Secure Boot/TPM (bloqueado por UEFI, issue
    #6, fuera de alcance por ahora). Ver `docs/ROADMAP.md`, Etapa 2.
  - **Instalación completa de punta a punta, confirmada en QEMU
    (2026-09-15):** primera vez que se completa un install real (todos
    los intentos anteriores se habían detenido en la selección de
    partición). Con un disco virtual de 40G en blanco: "Erase disk" →
    LUKS2 en ambas particiones (passphrase compartida) → usuario/
    hostname → resumen → "Install" → progreso real de instalación →
    **"All done. Debian 14 has been installed on your computer."**
    Encontrados y corregidos tres bugs reales en el camino (cada uno
    confirmado con un rebuild+retest en QEMU antes de pasar al
    siguiente):
    1. `unpackfs.conf` vendorizado apuntaba a
       `/run/live/medium/live/filesystem.squashfs` (convención
       live-build/Debian) en vez del path real de casper,
       `/cdrom/casper/filesystem.squashfs` — fallaba con "Bad unpackfs
       configuration". Corregido con el nuevo hook
       `0460-configure-calamares-unpackfs.chroot`.
    2. Con el path corregido, seguía fallando ("Failed to unpack
       image...") — leyendo el código real de `unpackfs/main.py`
       (upstream), el módulo chequea `shutil.which("unsquashfs")`
       antes de montar el squashfs. Faltaba `squashfs-tools` en el
       chroot (nunca había hecho falta para arrancar la ISO en sí, que
       usa el módulo squashfs del kernel directo).
    3. Con `squashfs-tools` puesto, mismo error superficial pero
       distinta causa — el diálogo de error completo de la UI (no solo
       el log truncado) mostraba el detalle real: `"rsync failed with
       error code 127"` (127 = comando no encontrado). El módulo
       `unpackfs` no descomprime con `unsquashfs` — monta el squashfs
       vía el kernel y copia el contenido con `rsync -aHAXSr`. Faltaba
       `rsync` en el chroot (usado todo el tiempo por este mismo
       proyecto en `auto/build`, pero eso corre en el host de build,
       nunca dentro del chroot horneado). Este fue el fix final.
  - **Arranque standalone del disco instalado, confirmado en QEMU
    (2026-09-15):** apagada la VM del instalador, se arrancó una
    segunda VM completamente nueva usando *solo* el disco resultante
    (sin `-cdrom`, sin override de `-kernel`/`-initrd` — SeaBIOS → MBR
    → GRUB reales). Resultado: GRUB pide la passphrase de LUKS de
    `root` → "Attempting to decrypt master key..." → segundo prompt de
    LUKS para `likay-agent` → ambas aceptadas → arranca por systemd →
    llega al mismo frontend de `kal-in` (ventana kiosk de Epiphany,
    logo "kal", indicador de `qwen2.5:3b`) visto hasta ahora solo en el
    medio live — esta vez corriendo desde una instalación real en
    disco. Confirma que nuestro `calamares-bootloader-config` propio
    (GRUB + `os-prober` + soporte de doble LUKS en el initramfs) deja
    un sistema instalado que arranca solo, sin nada del medio live.
  - **Bug real encontrado en hardware real (2026-09-15): el menú de
    arranque nunca mostraba "Instalar Likay-OS".** Todo lo de arriba se
    había probado siempre saltando el menú (inyectando
    `likay.mode=installer` directo en `-append` de QEMU) — la primera
    vez que se arrancó por el menú real de verdad, en hardware físico,
    solo aparecían las dos entradas "Live". Causa: `lb_binary_syslinux`
    (ver `/usr/lib/live/build/lb_binary_syslinux` línea 211) solo sabe
    renderizar `live.cfg.in` → `live.cfg` — el nombre está hardcodeado,
    no es un loop genérico sobre `*.cfg.in`. Nuestro `install.cfg.in`
    quedaba sin procesar, y el `include install.cfg` de `menu.cfg`
    apuntaba a un archivo que nunca se creaba — syslinux no avisa nada
    por un include faltante. `scripts/rebuild-iso-with-fixes.sh` (que
    de todos modos reconstruye la ISO desde `binary/`) ahora renderiza
    `install.cfg.in` a mano con el mismo sed que usa
    `lb_binary_syslinux`, leyendo `KERNEL`/`INITRD`/`LB_BOOTAPPEND_LIVE`
    del propio `live.cfg` ya renderizado. Confirmado después del fix:
    las tres entradas aparecen, "Instalar Likay-OS" arranca Calamares
    correctamente.
  - **Bug real en el camino "Alongside": nunca aparecía pese a que
    os-prober detectaba bien Windows (2026-09-15).** Con un disco de
    prueba con contenido Windows-*ish* más realista (`bootmgr` +
    `Boot/BCD` con "Windows 10" codificado en UTF-16LE, como un BCD
    real), os-prober detectaba bien "Windows 10", pero "Install
    alongside" seguía sin aparecer. Causa, leyendo `ChoicePage.cpp` de
    Calamares upstream: el botón depende de
    `PartUtils::canBeResized()`, que necesita que KPMcore lea el
    espacio libre *dentro* de la partición NTFS existente vía
    `ntfsresize` (paquete `ntfs-3g`) — una dependencia que
    `libkpmcore13` solo usa en runtime, nunca declarada en dpkg, así
    que nunca se había instalado en el medio live. Agregado `ntfs-3g`
    al package-list. Confirmado después del fix: "Install alongside"
    aparece, el slider de resize calcula y habilita bien.
  - **Primera instalación completa en hardware real, dual-boot
    automático con una distro Linux real (2026-09-15):** laptop con
    Zorin OS 18.1 ya instalado (ext4, disco GPT) — "Instalación
    paralela" (Alongside) detectó bien "Zorin OS 18.1 (18)" (código de
    detección de Linux de os-prober, distinto del camino NTFS/Windows
    — funcionó de entrada, sin faltarle ningún paquete, ya que
    `e2fsprogs` es esencial y siempre está presente). Slider calculó un
    split parejo (`/dev/sda3` reducido a 232GB + partición nueva de
    232GB para Debian, con nuestro `partitionLayout` root/likay-agent
    aplicado igual que en "Erase disk"). Install completo, reinicio, y
    el **GRUB resultante mostró ambas entradas** ("Debian GNU/Linux" +
    "Zorin OS 18.1 (18) (on /dev/sda3)", con sus respectivos "Advanced
    options") — confirmado arrancando las dos: Likay-OS llega al kiosco
    de `kal-in` como siempre, y Zorin sigue arrancando bien después del
    shrink de partición. Primera prueba real de dual-boot automático
    fuera de QEMU, con una segunda distro genuina (no un disco NTFS
    sintético).
  - **Rebrand de arranque/apagado/GRUB — "Ubuntu"/"Debian" → "Likay
    OS" (2026-09-15).** Pedido por el usuario tras ver "Ubuntu 26.04"
    en el splash de Plymouth (arranque Y apagado, mismo campo `title`
    en el tema `ubuntu-text`) y "Debian GNU/Linux" en el menú de GRUB
    del mismo sistema recién instalado. Fondo cambiado del morado
    "Aubergine" de Ubuntu al mismo gris carbón que ya usa el kiosco de
    `kal-in` (`#14181c`), para continuidad visual. `/etc/os-release`
    también actualizado (NAME/PRETTY_NAME, sin tocar ID/ID_LIKE —
    esos los usan apt/systemd para decisiones reales, no solo texto).
    El menú de GRUB necesitó **tres vueltas hasta la causa real**:
    hardcodear `GRUB_DISTRIBUTOR` en `calamares-bootloader-config` no
    alcanzó — un módulo propio de Calamares, `grubcfg` (corre después
    en la secuencia), lo reescribe desde `branding.desc`
    (`bootloaderEntryName: Debian`) salvo `keep_distributor: true`
    (documentado en su propio schema para exactamente este caso). Y
    ese archivo de config no puede vivir directo en
    `includes.chroot/etc/calamares/` — `auto/build` rsyncea el vendor
    ahí con `--delete` en cada build y se lo come; tuvo que ir en un
    hook (`0480-configure-calamares-grubcfg.chroot`), igual que
    `0440`/`0450`/`0460` patchean en vez de agregar directo. Confirmado
    con `debugfs` sobre discos de instalaciones de prueba en QEMU (sin
    arrancarlos) antes de gastar otra vuelta en hardware real, y
    finalmente confirmado en hardware real también. Hooks
    `0470-rebrand-boot-branding.chroot` + `0480-...`. Pendiente,
    "más adelante": rebrandear el instalador de Calamares en sí (logo +
    "Debian" en su propia UI, `branding.desc`) — no tocado todavía.
  - **Limitación conocida, no un bug nuestro: sin el prompt de "retirar
    el medio" al reiniciar después de instalar, con Ventoy
    (2026-09-15).** Al terminar el install y reiniciar, no aparece
    ningún mensaje pidiendo sacar el USB — vuelve a arrancar el mismo
    medio de instalación. `casper-stop` (`sbin/casper-stop`, el script
    real de shutdown de casper) SÍ tiene ese prompt normalmente
    ("Please remove the installation medium, then press ENTER"), pero
    se salta todo de entrada si `find_iso=` está en `/proc/cmdline` —
    probablemente lo que Ventoy inyecta al arrancar una ISO por
    loopback en vez de un USB grabado con `dd` (no hay un dispositivo
    "expulsable" cuando el medio es un archivo). No confirmado al 100%
    (no se pudo revisar `/proc/cmdline` en vivo), pero es la explicación
    más concreta encontrada en el código real. Workaround: interceptar
    el arranque manualmente (tecla de boot menu) y elegir el disco real
    en vez del USB.

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
