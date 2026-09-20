# Interfaz de agentes de Likay-OS — v2

> "Nunca confiar en el código interno de un agente — solo en el límite
> que el sistema le impone desde afuera. Incluso cuando el límite de
> seguridad choca con lo que ese agente 'quiere' hacer."
> — `docs/ROADMAP.md`

Este documento define el contrato entre Likay-OS y cualquier agente
(de referencia o de terceros) que un usuario monte sobre un sistema ya
instalado. Restringe a tres partes independientes que no deben
desalinearse: autores de agentes, el Broker que evalúa capacidades, y
el generador de unidades systemd que arma el sandbox real. El schema
que realmente se aplica vive en
[`broker/schema/agent-manifest.schema.json`](../broker/schema/agent-manifest.schema.json)
— este documento es prosa y razones, no la fuente de verdad del
formato exacto.

**v2 es runtime-neutral.** v1 asumía implícitamente que todo agente es
un venv de Python (`lifecycle.requirements_file` como concepto
central). Esa asunción se rompió evaluando agentes reales de terceros
del mercado (Node.js, con su propio Gateway/estado persistente,
distribuidos como imagen OCI) — v2 separa "qué necesita el agente"
(`runtime.type`) de "cómo se materializa" (el instalador lo decide),
sin tocar nada de lo que ya funciona para agentes Python. Ver
"Migración desde schema v1" al final.

## 0. Arquitectura

```
   Agente                Broker                  Sandbox de SO
(proceso externo)   (Access Manager)          (systemd/namespaces)
       │                    │                          │
       │  request(cap)      │                          │
       ├───────────────────>│                          │
       │                    │  ALLOW / DENY            │
       │<───────────────────┤  (política, no fuerza)   │
       │                                                │
       │  el agente sigue limitado por esto,            │
       │  pase lo que pase con el Broker                │
       └───────────────────────────────────────────────>│
                                                    enforcement real
```

**Un agente no obtiene privilegio por estar instalado.** El Broker
decide política (ALLOW/DENY); el Sandbox de sistema operativo hace
cumplir un límite, independiente de lo que el Broker haya decidido —
son dos capas distintas a propósito ("Policy ≠ Sandbox"). El Sandbox
(unidades systemd generadas en el momento de instalar) es el único
backstop real — ver sección 5 y las invariantes de seguridad.

Entre el manifiesto y el sandbox hay una capa intermedia, el
**Runtime Adapter**, que decide cómo materializar lo que el manifiesto
declaró (venv de Python, imagen OCI, ...) sin que el manifiesto mismo
tenga que saber nada de mecánica de instalación:

```
                   agent.yaml
                       │
                 validate + approve
                       │
                       ▼
              ┌─────────────────┐
              │ Runtime Adapter │   -- "cómo materializar runtime.type"
              └────────┬────────┘
          ┌────────────┼────────────┐
          ▼                         ▼
       Python                      OCI    (otros, futuro -- ver sección 9)
    (implementado)            (contrato definido,
                                Sandbox Adapter en Fase C)
                       │
                       ▼
              ┌─────────────────┐
              │ Sandbox Adapter │   -- "cómo aislar el proceso resultante"
              └────────┬────────┘
                       ▼
                systemd (.service / .container vía Quadlet)
```

Solo el adapter Python está implementado hoy en
`agent-install-helper` — un manifiesto con `runtime.type: oci` valida
correctamente contra el schema (útil para diseñar/probar el contrato
por adelantado) pero el helper lo rechaza explícito en tiempo de
instalación (`_require_implemented_runtime`) en vez de intentar algo a
medias.

## Invariantes de seguridad (no negociables)

1. `kiosk` nunca se convierte en root, bajo ningún flujo.
2. El código de un agente nunca es confiable — el límite lo impone el
   sistema desde afuera, nunca el propio agente.
3. El manifiesto es datos, nunca política ejecutable — parsearlo no
   ejecuta nada, ninguno de sus campos se interpola en un shell.
4. El ALLOW del Broker no es enforcement de sistema operativo — es una
   API de cortesía; el sandbox de systemd es el backstop real.
5. Solo la identidad dedicada `likay-agent-install` puede mutar la
   política del Broker (`register_policy`/`unregister_policy`) — nunca
   un agente, nunca root genérico, nunca algo derivado de un campo
   JSON.
6. `register_policy`/`unregister_policy` se autorizan por **credencial
   Unix del peer del socket** (`SO_PEERCRED`), nunca por un `agent_id`
   o `linux_user` que venga en el cuerpo de la solicitud.
7. El helper de instalación no expone ninguna primitiva de ejecución
   arbitraria como root (nada de `exec(cmd)`/`run_as_root(cmd)`) — su
   API son operaciones nombradas, fijas, de propósito único. Esto
   sigue valiendo igual para el Runtime Adapter OCI cuando se
   implemente (Fase C): "necesito Node 26"/"necesito la imagen X" se
   traduce a operaciones fijas del helper, nunca a ejecutar un
   `install.sh` que el propio agente/marketplace provea.
8. Todo agente instalado corre bajo su propia identidad Unix dedicada.
9. Todo agente instalado recibe un sandbox generado externamente —
   nunca uno que el propio agente pueda declarar o ampliar. Para
   runtime Python, una unidad `.service`; para runtime OCI (Fase C),
   una unidad generada vía Quadlet — mismo principio, mecanismo
   distinto.
10. Nunca se otorga `filesystem: full` — solo `{restricted, none}`.
11. `network: host-egress` es acceso normal a la red del host, **no**
    una ACL de destino — no confundir con "solo salientes controladas
    hacia ciertos dominios".
12. Agente #0 (el instalador de Calamares, ver sección 8) queda
    intacto — sin cambios de código, solo documentado como precedente.
13. Instalar un agente equivale a ejecutar software de terceros dentro
    del sandbox — se trata como cadena de suministro no confiable,
    nunca como "solo configuración". Esto vale igual para `pip install`
    (runtime Python) y para una imagen OCI (runtime OCI): por eso
    `runtime.oci.image.digest` es obligatorio, nunca un tag mutable
    como `:latest` — ver sección 3.
14. La conectividad de red de `agent-install` es una capacidad
    **temporal del instalador**, nunca una propiedad de los agentes
    instalados ni del sistema live normal. El modo normal (kiosco)
    permanece sin red por defecto. Tras resolver las dependencias del
    bundle, la red del instalador se apaga antes de continuar con el
    resto de la instalación — ver `_enable_installer_network`/
    `_disable_installer_network` en `agent-install-helper`. Ningún
    agente obtiene red por haber tenido el instalador conectividad
    para bajar sus dependencias: `sandbox.network` sigue viniendo
    únicamente del manifiesto.
15. El transporte del artefacto (`artifact.transport`) nunca implica
    red durante la instalación, en ningún runtime. `local-bundle`
    (Python) y `local-oci-archive` (OCI, Fase B) son ambos medios
    locales verificados — un registry remoto/autenticado queda
    deliberadamente fuera de v2 (ver sección 4 y sección 9).

## 1. Identidad

Cada agente se identifica con un `id` único, estilo reverse-DNS
(`com.vendor.nombre`). El instalador deriva de acá el nombre del
usuario Unix dedicado (`agent-<id-corto>`), el nombre de la unidad
systemd (`likay-agent-<id-corto>.service`), y el prefijo de auditoría.

```yaml
agent:
  id: com.likay.kal-in
  name: "kal-in"
  version: "0.1.0"
  vendor: "Likay-OS project"
```

## 2. Capacidades

Una capacidad es una declaración de intención del agente — no una
concesión automática. El usuario aprueba cada una explícitamente en el
TUI de instalación (ver sección 6), una sola vez.

| Grupo | Capacidades |
|---|---|
| Disco/sistema (solo clase instalador, ver Agente #0) | `disk.read`, `disk.write`, `partition.manage`, `bootloader.install` |
| Filesystem | `filesystem.data_dir` (su propio directorio, RW), `filesystem.read_external` (futuro — deny-by-default, no implementado) |
| Red | `network.egress` (v2 solo distingue ninguna/con acceso — ver sección 5) |
| Cómputo/modelo | `llm.local` (Ollama/`qwen2.5:3b` propio de Likay-OS), `gpu.compute` |
| Periféricos | `audio.microphone`, `audio.speaker`, `camera`, `clipboard` |
| Ejecución | `docker.sandbox` |

Basada en `permissions.trust_tier_caps` que ya existe en
`vendor/kal-in/config/config.yaml`, extendida con las 4 capacidades
específicas del instalador. Sin cambios respecto a v1 — el rediseño de
v2 es sobre `runtime`, no sobre `capabilities`.

## 3. Runtime

Reemplaza a `lifecycle:` de schema v1. Describe **qué necesita el
agente para correr**, no cómo instalarlo — esa decisión la toma el
Runtime Adapter del instalador (sección 0), nunca el propio manifiesto.

```yaml
runtime:
  type: python              # | oci -- ningún otro valor es legal en v2
  port: 8000
  health_check_path: /
  env:
    AGENT_ENV: production
  python:                   # obligatorio si type: python
    entry_point: "agent_core.orchestrator:app"
    command: "uvicorn"
    requirements_file: requirements.txt
```

`port`, `health_check_path`, y `env` son comunes a cualquier runtime
(cualquier agente de tipo servicio necesita un puerto que healthchequear
y puede necesitar variables de entorno) — el sub-objeto específico del
tipo (`python:`/`oci:`) solo trae lo que ESE mecanismo de instalación
necesita.

**Por qué solo `python`/`oci` en v2, no `node`/`native` todavía:**
decisión deliberada, no un olvido. Diseñar una abstracción de runtime a
partir de un solo caso real (Python, ya construido) más un caso
imaginado hubiera acoplado mal las costuras. Con Python (referencia,
ya probado contra un agente malicioso real) y OCI (el runtime que
fuerza a resolver imagen/storage/secrets/red/lifecycle con un caso
externo de verdad — ver Fase C) construidos y probados, un tercer tipo
se generaliza desde dos ejemplos reales, no desde una lista de
posibilidades. Ver sección 9.

### 3.1 `runtime.python`

```yaml
python:
  entry_point: "agent_core.orchestrator:app"
  command: "uvicorn"
  requirements_file: requirements.txt
```

**`requirements_file` es singular, no una lista.** Un solo archivo,
obligatoriamente dentro de `src/` en el propio bundle — el helper de
instalación rechaza rutas absolutas, `..`, o symlinks que escapen del
bundle. No se acepta `requirements-dev.txt` ni archivos equivalentes:
esos tienen sentido para el desarrollo de un agente dentro de su
propio repo, no para lo que se declara para correr en un sistema ya
instalado. `pip install -r` sigue siendo, en sí misma, una operación
de cadena de suministro (invariante 13) — se acepta pero se trata como
ejecutar código no confiable, nunca como "solo configuración".

**`bind_host` NO es un campo de este manifiesto, a propósito.** Se
consideró incluirlo (`bind_host: 127.0.0.1`) pero un agente podría
declarar `0.0.0.0` y depender de que el generador lo "corrija" — la
política de seguridad debe ganar por construcción, no por convención
del autor del manifiesto. El `ExecStart=` generado siempre fuerza
`--host 127.0.0.1`, sin excepción, sin que el manifiesto tenga ninguna
autoridad sobre ese valor.

**`command`/`entry_point`/`env` están restringidos en el schema, no
solo por convención** (hallazgo de una revisión de seguridad,
2026-09-17): `command` no admite `/` (no puede escapar de
`<venv>/bin/`); `entry_point` no admite espacios (no puede inyectar
flags extra después del `--host 127.0.0.1` forzado); las claves de
`env` deben matchear `^[A-Z_][A-Z0-9_]*$` y sus valores no pueden
contener CR/LF (sin esto, `_systemd_unit_text` interpola
`Environment={k}={v}` crudo, y un valor con `\n` embebido podía
inyectar una directiva propia como `User=root` — última asignación
gana, escalando el servicio a root pese a `sandbox:` declarar lo
contrario). `parse_manifest_file` revalida el schema en cada lectura
del manifiesto, así que estas restricciones se aplican en todos los
puntos de entrada del helper.

**`pip install`/la creación del venv corren como el usuario Unix del
agente, no como root** — aunque el helper entero corre como root (vía
`pkexec`). `create_agent` crea ese usuario antes de que `install_bundle`
lo necesite; ambos subprocesos bajan explícitamente a su UID/GID (sin
grupos suplementarios) antes de ejecutar. El código de terceros de
cualquier paquete (`setup.py`, build backends) sigue siendo no
confiable (invariante 13) — esto acota el blast radius de ese código a
un usuario recién creado y sandboxeado después, no a compromiso total
del sistema.

### 3.2 `runtime.oci` (implementado, Fase C — Sandbox Adapter OCI)

```yaml
oci:
  image:
    reference: ghcr.io/openclaw/openclaw
    digest: "sha256:<64 hex chars>"
```

**`digest` es obligatorio, `reference` nunca lleva tag.** Un tag
(`:latest`, `:v1`) es mutable — puede apuntar a contenido distinto
entre el momento en que el usuario aprueba capacidades en el TUI y el
momento en que el helper efectivamente instala. El digest fija la
imagen exacta (invariante 13), coherente con por qué `env`/
`device_allow` se restringen: la seguridad de v2 nunca depende de que
un campo mutable siga significando lo mismo dos veces.

**Por qué OCI y no un adapter nativo por lenguaje (Node, Ruby, Go...):**
OCI cubre "cualquier runtime que alguien empaquete como imagen" con un
solo Sandbox Adapter, en vez de necesitar uno nuevo por cada lenguaje
que un agente de terceros use. El caso que forzó a definir esto
(OpenClaw, un agente Node.js con Gateway persistente) ya distribuye una
imagen Docker oficial pensada para correr como usuario no-root — el
mecanismo que v2 necesita coincide con lo que ese ecosistema ya provee,
no hace falta inventar un empaquetado propio.

**Implementado (Fase C, 2026-09-20) — Sandbox Adapter completo vía
Quadlet (`podman-systemd.unit(5)`).** `create_agent` asigna, además del
usuario Linux dedicado (`useradd -r`), un rango subuid/subgid fijo
(`usermod --add-subuids/--add-subgids`) — un usuario de sistema no lo
recibe automáticamente, a diferencia de un usuario normal.
`generate_unit` despacha por `runtime.type`: `python` sigue escribiendo
un `.service` a mano (sección 3.1); `oci` escribe un Quadlet
`.container` en `/etc/containers/systemd/`, que el generador de Podman
convierte en una unidad real (`likay-agent-<short_id>.service`) al
hacer `daemon-reload`/boot — mismo nombre resultante que el caso
Python, así que `activate_agent` no necesita saber cuál de los dos lo
generó. `[Container] User=` nunca se usa (fijaría el usuario DENTRO de
la imagen, que no controlamos); la identidad de host se fija con
`[Service] User=`/`Group=`, igual que en el caso Python.

**Hallazgo real, el más costoso de Fase C (2026-09-20): un simple
`setuid()`/`setgid()` no alcanza para que Podman rootless funcione.**
`load_oci_image` corre un segundo `podman load` como el usuario
dedicado del agente (ver sección 4) para dejar la imagen en SU storage
rootless, no la de root. Con un `subprocess.run(user=..., group=...)`
directo (equivalente a un `setuid`/`setgid` plano), esto fallaba de
forma reproducible con `potentially insufficient UIDs or GIDs
available in user namespace ... lchown /etc/shadow: invalid argument`
al descomprimir cualquier capa con un layer de SO real (`/etc/shadow`,
etc.) — con `/etc/subuid`/`/etc/subgid` ya correctos (confirmado con
`getsubids`) y storage completamente limpia (se descartó la hipótesis
de estado corrupto por reintentos repitiendo el intento contra una
storage recién borrada). El diagnóstico real, aislado a mano con
`newuidmap` fuera de Podman: fallaba con `write to uid_map failed:
Operation not permitted` — un `setuid` plano deja al proceso corriendo
bajo el cgroup de la sesión de quien invocó `sudo`/`pkexec` (root), sin
la delegación de cgroup que el kernel exige para permitir
`CLONE_NEWUSER` con un mapeo subordinado no trivial ahí. La corrección:
envolver ese `podman load` en `systemd-run --uid=... --gid=...
--property=Delegate=yes`, que crea una unidad transitoria con su propio
cgroup delegado desde cero — confirmado que basta, sin ninguna otra
advertencia de Podman. Por el mismo motivo, el Quadlet generado
(`_quadlet_unit_text`) lleva `Delegate=yes` en su propio `[Service]`
explícito: el contenedor, cuando arranca de verdad vía systemd
(`activate_agent`), necesita exactamente la misma delegación.

`activate_agent` también despacha por `runtime_type`: una unidad
generada por Quadlet no puede `systemctl enable`arse (falla con "Unit
... is transient or generated") — se activa con `systemctl start`
únicamente, y se desactiva (al reemplazar un agente OCI anterior)
borrando su archivo `.container` fuente + `systemctl stop`, nunca
`systemctl disable --now` (falla igual de explícito).

Verificado en QEMU de punta a punta, en un solo intento limpio tras
corregir el hallazgo de `Delegate=yes`: `mount_bundle` →
`validate_manifest` → `create_agent` → `load_oci_image` →
`generate_unit` → `activate_agent` contra un fixture propio
(`likay-test-fixture`, una imagen mínima basada en
`python:3.12-alpine` sirviendo `python3 -m http.server 8000`, nunca
tocada por quien construyó el Broker) — `systemctl status` mostró el
proceso real del contenedor corriendo dentro del cgroup de la unidad, y
`curl http://127.0.0.1:8000/` devolvió `200 OK`.

## 4. Artifact — transporte y procedencia

Nuevo en v2, separado a propósito de `runtime` (sección 3). `runtime`
describe QUÉ ejecutar; `artifact` describe CÓMO llegó al sistema —
mantenerlos separados es lo que evita que "instalar una imagen OCI"
termine acoplado a "necesita red durante la instalación".

```yaml
artifact:
  transport: local-bundle          # runtime.type: python
  # o
  transport: local-oci-archive     # runtime.type: oci
```

Ninguno de los dos valores legales en v2 implica red durante la
instalación (invariante 15):

- **`local-bundle`** — el bundle USB de siempre: `agent.yaml` + `src/`
  copiados a un staging root-owned por `mount_bundle`, el mismo
  mecanismo que ya cierra el TOCTOU del manifiesto (ver sección 7).
- **`local-oci-archive`** — un archivo de imagen ya exportado
  (`podman save`/equivalente), transportado en la raíz del bundle
  (`<bundle>/image.tar`, junto a `agent.yaml`, en vez de `src/`) y
  cargado con `podman load` — nunca `pull` durante la instalación.
  **Implementado (Fase B, 2026-09-19)**: `mount_bundle` transporta
  `image.tar` al mismo staging root-owned que ya usa para `src/`
  (mismo mecanismo TOCTOU, sección 7); la nueva operación
  `load_oci_image` del helper corre `podman load`, captura la
  referencia real que cargó (`"Loaded image: ..."` en su stdout — no
  se asume que coincide con `runtime.oci.image.reference`), y compara
  el digest real (`podman inspect --format '{{.Digest}}'`) contra
  `runtime.oci.image.digest` — si no coincide, borra la imagen del
  store (`podman rmi -f`) y falla, nunca deja una imagen sin verificar
  ahí ni un instante más de lo necesario. Separada a propósito de
  `create_agent`/`install_bundle`/`generate_unit` (que siguen
  rechazando `runtime.type: oci`, sección 3.2): Fase B resuelve
  transporte + integridad de forma aislada, antes de que exista el
  Sandbox Adapter completo. La primera carga corre a la storage de
  Podman de *root*, únicamente para verificar el digest antes de
  exponerle nada al usuario del agente — `load_oci_image` (Fase C, ver
  sección 3.2) copia la MISMA imagen ya verificada a la storage
  rootless del usuario dedicado, que es donde el Quadlet generado
  espera encontrarla al arrancar el contenedor de verdad.

  **Gotcha real, confirmado en QEMU (2026-09-19): el digest que hay que
  poner en `runtime.oci.image.digest` es el que reporta Podman DESPUÉS
  de cargar el archivo, no el `RepoDigest` que mostraba el registry
  antes de exportarlo.** Probado con `docker pull hello-world` +
  `docker save` (RepoDigest `sha256:5e23...`) — tras `podman load` del
  mismo archivo, `podman inspect --format '{{.Digest}}'` reportó un
  digest DISTINTO (`sha256:d1a8...`). El roundtrip `save`/`load` no
  preserva el digest original del manifiesto del registry (formatos de
  archivo/reempaquetado distintos entre herramientas). Consecuencia
  práctica para quien prepare un bundle OCI: calcular el digest a poner
  en el manifiesto corriendo `podman load` + `podman inspect` sobre el
  MISMO archivo que va a viajar en el bundle — nunca copiar el digest
  que mostraba `docker inspect`/el registry antes de exportar.

**Explícitamente fuera de v2**: un registry remoto/autenticado como
transporte (`docker pull` en el momento de instalar). Documentado en
OpenClaw mismo un escenario de transferencia de imagen offline —
coherente con este diseño, no una excepción a él. Ver sección 9.

## 5. Storage

Nuevo en v2 — reemplaza el `data/` único de v1. Reveló la falta
evaluar un agente con estado/configuración propios más allá de "un
directorio de trabajo" (ej. `~/.openclaw/openclaw.json` + `workspace/`
de OpenClaw).

```yaml
storage:
  config: persistent
  state: persistent
  workspace: persistent
  secrets: private
```

**Puramente declarativo — el instalador crea estos cuatro directorios
para TODO agente de tipo servicio, sin importar lo que `storage:`
declare o no declare.** No es una opción que el agente pueda activar o
desactivar; es documentación de intención más que configuración real
en v2 (`_agent_paths()` en `agent-install-helper` ya los genera
siempre). El campo existe para que un manifiesto sea legible sin leer
el código del instalador, y para dejar espacio a valores no
`persistent` en el futuro (p.ej. `workspace: ephemeral`) sin romper el
schema.

| Directorio | Variable de entorno | Contenido |
|---|---|---|
| `config/` | `AGENT_CONFIG_DIR` | Configuración persistente del agente (no secretos) |
| `state/` | `AGENT_STATE_DIR` | Estado propio del agente entre reinicios |
| `workspace/` | `AGENT_WORKSPACE_DIR` | Área de trabajo del agente (archivos que genera/consume) |
| `secrets/` | `AGENT_SECRETS_DIR` | Credenciales — `0700`, nunca comparte permisos con el resto (ver sección 6) |

Los cuatro quedan dentro de `ReadWritePaths=` cuando
`sandbox.filesystem: restricted` (sección 7) — `ProtectSystem=strict`
sigue bloqueando todo lo demás.

## 6. Secrets

Nuevo en v2. Para un agente real (OpenClaw incluido) instalar el
binario no significa que esté configurado para hablar con un proveedor
de IA — necesita una API key/credencial que nunca debe vivir en
`agent.yaml`, en un argumento de proceso, ni en un log.

```yaml
secrets:
  - id: OPENAI_API_KEY
    required: true
  - id: TELEGRAM_BOT_TOKEN
    required: false
```

Solo **declaración** en v2 — `id` (nombre lógico) y `required`, nunca
un valor. El flujo real (pedirle el valor al usuario en el TUI,
inyectarlo al proceso sin que quede en texto plano en la unidad
systemd generada) es trabajo de Fase C, cuando exista un agente real
que lo necesite (OpenClaw) contra el cual validarlo — construir un
Secret Manager completo (rotación, auditoría) antes de tener ese caso
real sería exactamente el tipo de sobre-ingeniería que este documento
evita en otros lados.

Diseño ya decidido para cuando se implemente, para que quede escrito
antes de programarlo: el valor se escribe a un archivo dentro de
`secrets/` (sección 5, `0700`, dueño el usuario del agente), y se
estudia `LoadCredential=`/`EnvironmentFile=` de systemd (mantiene el
secreto fuera del contenido visible de la unidad vía `systemctl cat`)
antes de comprometerse a uno de los dos — nunca un valor interpolado
directo en `Environment=` como los demás campos de `runtime.env`.

## 7. Sandbox

```yaml
sandbox:
  filesystem: restricted   # {restricted, none} -- "full" no es legal
  network: host-egress     # {none, host-egress}
  devices: none             # {none, explicit}
  memory_max: "4G"
  cpu_quota: "200%"
  tasks_max: 512
```

**Por qué `host-egress` y no `egress`:** systemd solo da un split
binario para red vía `PrivateNetwork=` — `host-egress` significa "el
proceso conserva acceso normal a la red del host", **no** "solo
salientes permitidas hacia destinos controlados". Llamarlo `egress` a
secas sugeriría una ACL de destino que v2 no tiene — una allowlist
real de dominios necesitaría eBPF (hay un prototipo sin usar en
`vendor/kal/kernel/lifecycle/ebpf/`) o un proxy por agente, ninguno de
los dos implementado.

**Mapeo campo del manifiesto → directivas systemd concretas (runtime
Python; runtime OCI vía Quadlet mapea igual conceptualmente, Fase C):**

| Campo | Directivas |
|---|---|
| `filesystem: restricted` | `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `ReadWritePaths=` para `config/`, `state/`, `workspace/`, `secrets/` (sección 5) |
| `filesystem: none` | igual, sin `ReadWritePaths` |
| `network: none` | `PrivateNetwork=yes` (AF_UNIX sigue funcionando — el socket del Broker sigue alcanzable) |
| `network: host-egress` | sin `PrivateNetwork`; loopback-only forzado por construcción en el `ExecStart=` generado, nunca por el manifiesto |
| `devices: none` | `PrivateDevices=yes` |
| `devices: explicit` | `PrivateDevices=no`, `DevicePolicy=closed`, `DeviceAllow=<lista>` |
| siempre, todo agente | `NoNewPrivileges=yes`, `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `RestrictSUIDSGID=yes`, `LockPersonality=yes`, `SystemCallFilter=@system-service`, `MemoryMax=`/`CPUQuota=`/`TasksMax=` del manifiesto |

**`device_allow` está restringido igual que `env`** (mismo hallazgo
2026-09-17): `_systemd_unit_text` interpola `DeviceAllow={entry}` crudo
también, así que un valor con `\n` embebido era el mismo vector de
inyección que `env`, solo que más silencioso — la TUI nunca muestra el
`sandbox:` del manifiesto al usuario, solo `id`/puerto/cantidad de
capacidades. El schema prohíbe CR/LF pero permite el espacio interno
que la sintaxis real de `DeviceAllow=` necesita (`<device> <permisos>`,
p.ej. `/dev/sda5 rwm`).

## 8. Lifecycle operativo

No es una sección del manifiesto — no hay nada que un autor de agente
declare acá. `start`/`stop`/`restart`/`status`/`logs` los expone
`systemd` para cualquier agente instalado, sin código nuevo: son
`systemctl {start,stop,restart,status} likay-agent-<id-corto>.service`
y `journalctl -u likay-agent-<id-corto>.service` sobre la unidad ya
generada (sección 7). Documentado acá explícitamente para que quede
claro que es intencional, no un olvido: no había que construir nada
para tenerlo.

**Explícitamente fuera de v2**: `update`/`rollback` — necesitan
versionar instalaciones, swap atómico, health-check post-swap, y
revert ante fallo, mecanismo genuinamente nuevo (no algo que systemd
ya dé gratis como lo de arriba). Deferred a una fase posterior, no
bloqueante para instalar/correr un primer agente OCI real.

## 9. IPC (Broker)

El Broker (`broker/`, `likay-agent-broker.service`) expone
`/run/likay-agent-broker/broker.sock` (directorio creado por systemd
vía `RuntimeDirectory=`, con el dueño correcto — el Broker corre como
un usuario Linux dedicado sin privilegios, `likay-broker`, nunca como
root) — JSONL sobre `AF_UNIX`, mismo formato
de trama que `vendor/kal/kernel/api/socket_server.py`.

Tres métodos, con fronteras de autorización **distintas**, decididas
por credencial Unix del socket (`SO_PEERCRED`), nunca por un campo
dentro del JSON:

- **`check_capability(capability)`** — cualquier agente puede
  llamarlo, pero el Broker resuelve la identidad de quien pregunta vía
  `SO_PEERCRED` → UID → usuario Linux dedicado de ese agente. Un
  agente solo puede consultar sus propias capacidades otorgadas, nunca
  las de otro proceso.
- **`register_policy(agent_id, linux_user, capabilities)`** — el
  Broker acepta esta llamada ÚNICAMENTE si `SO_PEERCRED` del peer
  resuelve a la UID del usuario estático `likay-agent-install`
  (hardcodeado en el Broker). Ningún agente instalado puede llamarlo
  con éxito, sea cual sea su UID.
- **`unregister_policy(linux_user)`** — misma frontera exacta que
  `register_policy`. Limpieza de lifecycle: v2 sigue soportando un
  agente activo a la vez (sección 10) — cuando `activate_agent`
  (helper) desactiva y da de baja el usuario Linux de un agente
  anterior, la TUI llama a esto para que su grant en `policy.json` no
  quede huérfano para siempre. `removed: false` en la respuesta es el
  caso normal (no había ningún agente anterior que limpiar), no un
  error.

En v2, la política sigue siendo "lo que un humano aprobó una vez, en
el momento de instalar, en el TUI" — sin flujo de escalación en
runtime. Nada OBLIGA a un agente a consultar este socket antes de
actuar: el backstop real es el sandbox de systemd (sección 7), no la
consulta al Broker. El `check_capability` es hoy una API de cortesía
(útil p.ej. para cuotas de `llm.local`), no una pared.

## 10. Auditoría

```yaml
audit:
  event_prefix: agent_kal-in
```

Toda decisión del Broker (ALLOW o DENY, para cualquiera de los tres
métodos) se loguea siempre, sin excepción, a
`/var/log/likay-agent-broker/audit.log` (JSONL: `timestamp, peer_user,
method, decision, detail`).

**Cadena hash-linked** (portado de `vendor/kal/audit/audit_log.py`,
2026-09-17): cada línea incluye `prev_hash`/`event_hash` (SHA-256 sobre
el resto de sus propios campos), así que una edición retroactiva del
archivo (un agente con acceso de escritura local intentando borrar su
propio rastro) rompe la cadena de forma detectable —
`AuditLog.diagnose_chain()` distingue manipulación de contenido real
(`hash_ok=False`) de una condición de carrera entre escritores
concurrentes (`hash_ok=True, chain_ok=False`, ya cubierta por el
`fcntl.flock` que envuelve todo el ciclo leer-último-hash + escribir).
No es criptográficamente inviolable — para eso haría falta firma
externa o almacenamiento WORM real — pero hace la manipulación
evidente en vez de silenciosa.

## 11. Agente #0 — el instalador, como ejemplo ya resuelto

`likay-installer.service` + `pkexec` + PolicyKit (usuario dedicado
`likay-installer`), construido y validado en QEMU y hardware real
antes de que existiera esta interfaz, es en retrospectiva una primera
instancia real de exactamente este patrón:

```
kiosk (nunca se involucra)
   │
   ▼ (elegido en el menú de arranque, nunca desde una sesión corriendo)
Xorg + installer-launcher (usuario likay-installer, sin privilegios)
   │  pkexec, acción com.github.calamares.calamares.pkexec.run
   ▼
PolicyKit (regla scoped a subject.user == "likay-installer")
   │
   ▼
Calamares (privilegiado)
```

```yaml
schema_version: 2
agent:
  id: com.likay.installer
capabilities: [disk.read, disk.write, partition.manage, bootloader.install]
sandbox:
  user: likay-installer
  filesystem: restricted
  network: none
  devices: explicit
```

Este manifiesto es solo documentación — Agente #0 no se reimplementa
contra esta interfaz (invariante 12): su código, ya probado en
hardware real, queda intacto. No tiene `runtime:` — no es un agente de
tipo servicio.

## 12. Ejemplos completos

### 12.1 kal-in (runtime Python, implementado)

```yaml
schema_version: 2

agent:
  id: com.likay.kal-in
  name: "kal-in"
  version: "0.1.0"
  vendor: "Likay-OS project"

capabilities:
  - network.egress
  - filesystem.data_dir
  - llm.local
  - gpu.compute
  - audio.microphone
  - docker.sandbox

runtime:
  type: python
  port: 8000
  health_check_path: /
  env:
    AGENT_ENV: production
  python:
    entry_point: "agent_core.orchestrator:app"
    command: "uvicorn"
    requirements_file: requirements.txt

artifact:
  transport: local-bundle

storage:
  config: persistent
  state: persistent
  workspace: persistent
  secrets: private

sandbox:
  filesystem: restricted
  network: host-egress
  devices: none
  memory_max: "4G"
  cpu_quota: "200%"
  tasks_max: 512

audit:
  event_prefix: agent_kal-in
```

### 12.2 OpenClaw (runtime OCI, probado contra la imagen real publicada)

**Probado en QEMU (2026-09-20) contra `ghcr.io/openclaw/openclaw:slim`
real** — no un fixture propio, la imagen oficial publicada por el
proyecto, sin tocar. `mount_bundle` → `validate_manifest` →
`create_agent` → `load_oci_image` → `generate_unit` → `activate_agent`
corrieron de punta a punta contra ella; el contenedor real (~2.8GB
descomprimido) arrancó bajo el sandbox completo (rootless, digest
fijado, `NoNewPrivileges`, `DropCapability=ALL`, raíz de solo lectura)
y ejecutó el binario real de OpenClaw. Esto encontró y corrigió DOS
bugs reales en el propio Sandbox Adapter, ninguno específico de
OpenClaw — exactamente el valor de probar contra un agente de terceros
real, no solo un fixture escrito a medida:

- **`Image=` sin digest dejaba que Quadlet intentara un `pull` de
  red.** `_quadlet_unit_text()` construía `Image=` a partir de
  `runtime.oci.image.reference` solo, sin el digest — si esa
  referencia exacta (sin tag) no estaba en la storage local, Quadlet le
  agregaba `:latest` por su cuenta e intentaba bajarla de `ghcr.io`. El
  fixture de Fase C nunca lo expuso porque, por coincidencia, se había
  cargado bajo el tag `:latest` también; la imagen real de OpenClaw se
  probó bajo `:slim`, un tag distinto, y el intento de pull real violó
  directamente `artifact.transport: local-oci-archive` (invariante
  15). Corregido fijando SIEMPRE `Image={reference}@{digest}` — coincide
  además con la invariante 13 (nunca confiar en un tag mutable en el
  momento de arrancar).
- **`systemctl list-units` sin `--plain` rompía la desactivación de un
  agente anterior en estado `failed`.** `op_activate_agent()` parsea la
  salida de `list-units` para encontrar y desactivar cualquier otro
  `likay-agent-*.service` activo — sin `--plain`, systemd antepone un
  glifo "●" como primera columna para cualquier unidad en estado
  `failed`, y `line.split()[0]` agarraba ese glifo en vez del nombre
  real de la unidad, rompiendo con "Invalid unit name". No es
  específico de Quadlet/OCI — cualquier `likay-agent-*` que haya
  fallado antes de ser reemplazado dispara el mismo bug.

**Prueba de humo completa, lograda (2026-09-20): `curl /healthz` real
devolvió `{"ok":true,"status":"live"}`, HTTP 200, con los 13 plugins de
OpenClaw cargados y el heartbeat corriendo.** El primer intento salió
con `"Missing config. Run \`openclaw setup\` or set gateway.mode=local
(or pass --allow-unconfigured)."` — el propio gate de onboarding de
OpenClaw, no un bug del Sandbox Adapter. Se corrigió UN error de
investigación propio en el camino (ver más abajo) y se llegó a 200
combinando, a mano (fuera del pipeline declarativo — ver los dos
vacíos reales que quedan, al final), lo siguiente:

- **`OPENCLAW_STATE_DIR`** apuntado al volumen persistente montado
  (`runtime.env`, ya soportado sin cambios).
- **`HOME`** apuntado al MISMO volumen — OpenClaw usa `$HOME/.cache`
  para un directorio temporal de respaldo, separado de
  `OPENCLAW_STATE_DIR`; sin esto fallaba igual con
  `EACCES`/`ENOENT` al intentar crearlo.
- **El montaje necesita el flag `:U` de Podman, no solo `:Z`** — sin
  él, el volumen aparece dentro del contenedor con el dueño que resulta
  de la identidad de host (UID 0 del contenedor), nunca el usuario
  no-root que la imagen declara correr (`node`, UID 1000 interno) — ese
  usuario no podía escribir en su propio volumen. **Corregido en
  `_quadlet_unit_text()` (ya no es específico de esta prueba) — genérico
  para cualquier imagen de terceros bien comportada que corra como
  no-root**, no una rareza de OpenClaw.
- **`OPENCLAW_GATEWAY_TOKEN`** — un secret real (Gateway se niega a
  escuchar en `0.0.0.0` sin autenticación configurada, una guarda de
  seguridad correcta de su parte).

**Error de investigación propio, corregido en público**: la primera
versión de este smoke test asumió (sin verificarlo contra el código
fuente) que no existía forma de relocalizar el estado de OpenClaw fuera
de su `docker-compose.yml`, y se filó un feature request
([openclaw/openclaw#153623](https://github.com/openclaw/openclaw/issues/153623))
pidiéndolo. Es falso — `OPENCLAW_STATE_DIR`/`OPENCLAW_CONFIG_PATH`/
`OPENCLAW_HOME` ya existen, están implementados
(`src/config/paths.ts`) y documentados para otros objetivos de
despliegue no-compose (`docs/install/fly.md`, `docs/install/nix.md`) —
simplemente no en la página específica que se había revisado
(`docs/install/docker.md`). El issue se corrigió con un comentario
público y se cerró. Lección operativa: verificar contra el código
fuente real (`gh search code`), no solo contra una página de docs vía
resumen automático, antes de publicar un reporte a un proyecto externo.

**Dos vacíos reales, todavía sin resolver, por los que esta prueba se
hizo a mano y no a través del pipeline declarativo real**:

1. **Sin mecanismo de inyección de secrets** (`OPENCLAW_GATEWAY_TOKEN`)
   — ya documentado en la sección 6, `secrets:` sigue siendo solo
   declaración en v2.
2. **Sin forma de declarar argumentos extra del comando del
   contenedor** (`--allow-unconfigured`) — el schema no tiene ningún
   campo para esto hoy; `ExecStart`/`Cmd` del Quadlet generado siempre
   usa el `Cmd` por defecto de la imagen. Sumar esto ensancharía lo que
   un manifiesto puede hacer arrancar (sigue siendo datos
   estructurados, nunca shell libre, pero es una decisión de diseño
   real, no solo una corrección) — evaluada y diferida, no
   implementada todavía.

```yaml
schema_version: 2

agent:
  id: com.openclaw.gateway
  name: "OpenClaw"
  version: "slim"
  vendor: "OpenClaw project"

capabilities:
  - network.egress
  - filesystem.data_dir

runtime:
  type: oci
  port: 18789
  health_check_path: /healthz
  env:
    OPENCLAW_STATE_DIR: /var/lib/likay-agent/state
    HOME: /var/lib/likay-agent/state
  oci:
    image:
      reference: ghcr.io/openclaw/openclaw
      digest: "sha256:988320c1dc7b146b1e4feca5aa825f668f7cca385cb00aeb5682720bab69b63c"

artifact:
  transport: local-oci-archive

storage:
  config: persistent
  state: persistent
  workspace: persistent
  secrets: private

secrets:
  - id: OPENCLAW_GATEWAY_TOKEN
    required: true
  - id: OPENAI_API_KEY
    required: false

sandbox:
  filesystem: restricted
  network: host-egress
  devices: none
  memory_max: "1G"
  cpu_quota: "150%"
  tasks_max: 256
```

## 13. Fuera de alcance de v2 (deliberado, no un olvido)

- Mediación real de kernel vía import de `vendor/kal` como librería —
  `AccessManager`/`socket_server.py` de `kal` quedan intactos, scoped
  a skills.
- Migrar kal-in para depender de `vendor/kal` (deuda técnica
  preexistente de kal-in, deliberadamente desacoplada de este diseño).
- Renegociación/escalación de capacidades en runtime en el Broker.
- ACLs de red finas — solo el split binario `none`/`host-egress`.
- Múltiples agentes activos simultáneamente (un solo kiosco, una sola
  partición `likay-agent`, un solo puerto orientado al kiosco).
- `runtime.type: node`/`runtime.type: native` — deliberadamente sin
  declarar hasta que un caso real (no imaginado) demuestre que OCI no
  alcanza. OpenClaw, el caso que motivó todo este rediseño, ya cubre
  su propio runtime Node.js vía su imagen OCI oficial — no hizo falta
  un adapter nativo de Node para el primer agente de terceros real.
- Transporte remoto/autenticado de ningún artefacto — ni un `pull` de
  registry para OCI, ni un transporte de red para el bundle Python.
  `artifact.transport` solo acepta medios locales verificados en v2
  (sección 4). El formato se versiona (`schema_version`) para poder
  sumar transportes autenticados más adelante sin romper v2.
- `update`/`rollback` de un agente ya instalado (sección 8).
- Firma criptográfica de bundles/imágenes más allá del digest OCI ya
  obligatorio (sección 3.2).
- Un Secret Manager completo (rotación, auditoría propia) — v2 solo
  define la declaración (sección 6).
- Un marketplace/catálogo de agentes — lo que sí queda de este
  documento es el FORMATO de artefacto que un marketplace futuro
  podría producir, no el marketplace en sí.

## Migración desde schema v1

Cambio incompatible, no aditivo — `schema_version: 1` y
`schema_version: 2` no son intercambiables, `jsonschema.validate`
rechaza un manifiesto v1 contra el schema v2 (y viceversa) por el
`const` de `schema_version`. No hay soporte dual: todo manifiesto real
de este repo (kal-in, dummy-agent, malicious-agent) se migró a v2 en
el mismo cambio que introdujo este schema — no hay ningún v1 en
producción que necesite convivir con v2.

| v1 | v2 |
|---|---|
| `lifecycle.runtime: python-venv` | `runtime.type: python` |
| `lifecycle.entry_point`/`command`/`requirements_file` | `runtime.python.entry_point`/`command`/`requirements_file` |
| `lifecycle.port`/`health_check_path`/`env` | `runtime.port`/`health_check_path`/`env` (sin cambios de forma, solo de ubicación) |
| (no existía) | `artifact.transport` |
| (no existía, un solo `data/` implícito) | `storage:` + los cuatro directorios de la sección 5 |
| (no existía) | `secrets:` |
| `Environment=AGENT_DATA_DIR=...` (generado) | `Environment=AGENT_STATE_DIR=...` + `AGENT_CONFIG_DIR`/`AGENT_WORKSPACE_DIR`/`AGENT_SECRETS_DIR` |

**Hallazgo de seguridad heredado de v1, sin cambios en v2 (TOCTOU del
manifiesto, 2026-09-17):** `mount_bundle` es la ÚNICA operación que
toca el medio físico (USB para `local-bundle`) — copia
`agent.yaml`+`src/` a un staging root-owned
(`/var/lib/likay-agent-install/bundle-staging/`, `0700`) una sola vez
y desmonta el medio ahí mismo. Toda operación posterior lee de ese
staging, nunca vuelve a tocar el medio original. `activate_agent`
borra el staging al terminar.
