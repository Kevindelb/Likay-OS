# Auditoría de seguridad — Likay-OS

> **Estado de remediación (actualizado 2026-09-26):** Parte A (I-1 a
> I-10) y Parte C, en lo que corresponde a este repositorio (B-C1,
> B-A1, B-A2, B-M1 a B-M4, B-B1, B-B3), y los ítems de V-1 propios de
> este repo (CI por SHA, `PolicyStore` tolera claves extra, `podman
> secret create` idempotente) están cerrados — ver la rama
> `audit/fixes-2026-09-26` (10 commits, 138/138 tests) y las
> referencias cruzadas agregadas a `docs/AGENT_INTERFACE.md`.
> Deliberadamente sin cerrar, con motivo documentado en los commits:
> B-B2, B-B4, B-B7 (riesgo real bajo o no corregible vía código sin
> volver a probar en QEMU/hardware). Parte B (K-1 a K-11) es el
> kernel vendorizado `kal`/`kal-in` — se resuelve en esos repos, no en
> este. Este documento queda tal cual se recibió, como registro del
> estado ANTES de la remediación — no se edita retroactivamente el
> cuerpo del informe.

**Fecha:** 2026-09-26
**Alcance:** repositorio completo. Código de primera parte (Broker,
instalador de agentes, integración ISO/systemd/polkit/Calamares, hooks
de build, `auto/build`, scripts), y código vendorizado que la ISO
hornea y/o ejecuta (`iso/config/includes.chroot/opt/kal`,
`opt/kal-in`, `vendor/`).
**Método:** lectura completa de archivos, análisis de fronteras de
privilegio, prueba de concepto ejecutada para cada hallazgo confirmado,
y ejecución de la suite existente (`python3 -m pytest -q` → **108
passed**).
**Énfasis:** vulnerabilidades explotables y rupturas de las invariantes
declaradas en `docs/AGENT_INTERFACE.md` y `docs/ROADMAP.md`.

**Marcas de verificación usadas en todo el informe:**

| Marca | Significado |
|---|---|
| **[V]** | Verificado por el auditor, con evidencia en código y PoC ejecutada cuando aplica. |
| **[C]** | Reportado por una revisión delegada y **verificado en código** por el auditor (líneas citadas leídas). |
| **[R]** | Reportado por una revisión delegada, razonable y con evidencia citada, **no reproducido** por el auditor. Se indica como tal. |

> Honestidad metodológica: donde un control existente mitiga un
> hallazgo, se dice explícitamente y la severidad se ajusta a la baja.
> Donde algo no pudo verificarse (permisos reales dentro del artefacto
> de build, comportamiento en hardware), también se dice.

---

## 1. Resumen ejecutivo

### 1.1 Tabla unificada

| ID | Sev. | Hallazgo | Dónde | Marca |
|---|---|---|---|---|
| **K-1** | **Crítica (latente)** | Path traversal en `manifest.name` de una skill → escritura de archivos arbitrarios en el host como el usuario del agente (RCE diferido vía `.pth`/autostart) | `kal-in/kernel/registry/sandboxed_skill.py:119,244` | [V] |
| **B-C1** | **Crítica (build)** | `curl … \| sh` como root, sin pin ni checksum, para instalar Ollama | `0100-install-ollama.chroot:8` | [C] |
| **I-1** | **Alta** | Un bundle USB no confiable hace que el helper (root) copie archivos arbitrarios al `src/` del agente y agote el disco, siguiendo symlinks | `agent-install-helper:310,559` | [V] |
| **I-2** | **Alta** | Colisión de `short_id`: dos `agent.id` distintos → mismo usuario Linux, unidad, storage y grant → suplantación, herencia de secretos y capacidades | `manifest.py:50`, `agent-install-helper:392,1014`, `policy_store.py:62` | [V] |
| **K-2** | **Alta** | La recolección de salida del contenedor sigue symlinks → lectura arbitraria de archivos del host por el proceso agente | `kal-in/kernel/lifecycle/docker_runner.py:239-243` | [V] |
| **K-3** | **Alta** | Firma de skills con la clave pública **autodeclarada** en el propio `skill.sig` → `verified` no prueba autoría | `kal/kernel/registry/skill_signing.py:191-205` | [V] |
| **K-4** | **Alta** | La red de una skill la concede su propio manifiesto; `PermissionCascade` no se invoca dentro del kernel | `kal-in/kernel/registry/sandboxed_skill.py:134` | [V] |
| **K-5** | **Alta** | TOCTOU: firma verificada al cargar, código releído de disco en cada ejecución | `skills.py:209`, `sandboxed_skill.py:189` | [V] |
| **B-A1** | **Alta (build)** | `git clone` de un tag mutable + compilación + `install` como root (cage) | `0350-build-cage-noxwayland.chroot:60-69` | [C] |
| **B-A2** | **Alta (build)** | `pip install` de dependencias remotas sin hashes ni versiones fijas, como root, en los tres venvs horneados | `0300:18-21`, `0320:31-34`, `0330:17-18` | [C] |
| **I-3** | **Media-Alta** | La aprobación explícita de capacidades **no gobierna el sandbox**: `network: host-egress` y `device_allow` no se muestran al usuario | `agent-install-launcher:305`, `agent-install-helper:740-755` | [V] |
| **I-4** | **Media** | Código y venv del Broker son de `likay-broker` pero se ejecutan como root (shebang del helper) y como `likay-agent-install` (pkexec sin contraseña) | `0330-install-broker.chroot:29`, `agent-install-helper:1` | [V] |
| **I-5** | **Media** | La cadena de auditoría del Broker nunca se verifica; log legible por todos y sin rotación | `broker/…/audit.py:134,154,157` | [V] |
| **I-6** | **Media** | DoS local trivial del Broker: hilos sin tope, sin `TasksMax`/`MemoryMax` | `socket_server.py:116`, `likay-agent-broker.service` | [V] |
| **K-6** | **Media** | Traversal en el nombre de herramientas dinámicas (nombre elegido por el LLM) → escritura fuera del store | `kal/kernel/registry/versioning.py:26-29,59-60` | [V] |
| **K-7** | **Media** | Cadena de auditoría de kal sin ancla externa y frágil ante una línea truncada | `kal/audit/audit_log.py:157-163,202-251` | [C] |
| **B-M1** | **Media** | Sandbox de WebKit desactivado en el kiosco horneado | `likay-kiosk.service:60` | [V] |
| **B-M2** | **Media** | Caché de modelos por hardlinks host↔chroot + `chown` por nombre → confusión de uid e integridad del modelo | `auto/build:154,163`, `0100:16-17` | [C] |
| **B-M3** | **Media** | Dependencias de desarrollo y `build-essential` horneados en la imagen | `0300:19-21`, `0320:32-34`, package-list:49 | [C] |
| **B-M4** | **Media** | Política de contraseña del sistema instalado: mínimo 6 caracteres, usuario en `sudo` | `users.conf:6,21` | [V] |
| **I-7** | **Baja** | El Quadlet OCI no recibe el hardening base que sí recibe el runtime Python | `agent-install-helper:947` | [V] |
| **I-8** | **Baja** | La partición de agentes se monta sin `nosuid,nodev` | `mnt-likay\x2dagent.mount:40` | [V] |
| **I-9** | **Baja** | `parse_manifest_file` no implementa la protección anti-symlink que documenta | `manifest.py:120-132` | [V] |
| **I-10** | **Baja** | `port` opcional y `health_check_path` muerto → unidades con `--port None` | `schema:59-60`, `agent-install-helper:771` | [V] |
| **K-8** | **Baja** | `/execute` del `sandbox_runner` sin autenticación (no live en la ISO actual) | `kal/kernel/api/sandbox_api.py:29-38` | [V] |
| **K-9** | **Baja** | `install_from_market`: inyección de argumentos en `git clone` y traversal en `skill_name` | `kal/kernel/registry/skill_market.py:36-38,71` | [C] |
| **K-10** | **Baja** | Config cargada desde ruta relativa al CWD | `kal/utils/config.py:522-530` | [C] |
| **B-B1** | **Baja** | `MODEL_TAG` interpolado en `sh -c` + `source` de archivo de datos como root | `0200-pull-ollama-model.chroot:18,54` | [V] |
| **B-B2** | **Baja** | Interpolación sin escapar en `sed`/heredoc del reconstruido de ISO | `rebuild-iso-with-fixes.sh:120-122,206-229` | [C] |
| **B-B3** | **Baja** | TOCTOU de puerto + `fuser -k` sobre el host de build | `0200:26-42` | [C] |
| **B-B4** | **Baja** | `xhost +si:localuser:root` en el instalador | `installer-launcher:51` | [V] |
| **B-B5** | **Baja** | `kal-in-backend.service` sin hardening (inconsistente con el Broker) | `kal-in-backend.service:30-51` | [V] |
| **B-B6** | **Baja** | `app.py` del smoke-test: `Content-Length` sin validar y `read()` sin tope | `smoke-test/app.py:88-90` | [V] |
| **B-B7** | **Baja** | Scripts de build *group-writable* que corren como root | `iso/auto/build`, `hooks/*.chroot` | [C] |
| **K-11** | **Informativa** | Docstring dice `enabled: false` por defecto; las 6 skills horneadas están en `true` | `kal-in/kernel/registry/skills.py:17-20` | [V] |
| **V-1** | **Informativa** | CI: actions por tag, `pip install` sin lock; imágenes `:latest` en el compose de kal-in; `PolicyStore` revienta con claves extra; `podman secret create` falla al reinstalar | varios | [V] |

Ningún hallazgo **Alta** es explotable de forma remota: la etapa actual
no expone servicios fuera de loopback (`kal-in` en `127.0.0.1:8000`,
Ollama en loopback, Broker en socket Unix local). Los vectores reales
son el **bundle/transporte no confiable** (invariante 13), el **usuario
local sin privilegios** y el **código vendorizado de skills**, que es
exactamente el modelo de amenaza que el proyecto declara.

### 1.2 Las tres cosas que hay que arreglar primero

1. **K-1 + K-2**: el kernel vendorizado usado por el agente que corre
   (`opt/kal-in`) confía en strings que controla la skill (`name`) y en
   symlinks que crea dentro de la carpeta compartida. Es la ruptura más
   directa de *"el límite lo impone el sistema desde afuera"*.
2. **I-1 + I-2**: el instalador de bundles hace, como root, una copia
   que sigue symlinks, y deriva toda la identidad de sistema del
   *último componente* del `agent.id`.
3. **I-3**: la aprobación por capacidades que el usuario ve en la TUI no
   es la que gobierna el sandbox real.

---

## 2. Parte A — Instalador de agentes y Broker (código de primera parte)

### I-1 (Alta) [V] — `copytree(symlinks=False)` como root: lectura arbitraria de archivos y agotamiento de disco

**Evidencia**
- `iso/config/includes.chroot/usr/lib/likay/agent-install-helper:310`
  `shutil.copytree(usb_src_dir, BUNDLE_SRC_DIR, symlinks=False)`
- `:559` — misma llamada al copiar el staging al storage del agente.
- `:291` — comentario que revela la suposición errada: *"install_bundle
  solo copia bytes vía shutil.copytree, nunca ejecuta nada de acá"*.

**Por qué es explotable.** `mount_bundle` corre **como root** vía
`pkexec`. Con `symlinks=False`, `shutil.copytree` **sigue** los
symlinks: copia el contenido del destino y, si apunta a un directorio,
recursiona dentro. El USB se monta `ro,nosuid,nodev,noexec`, pero nada
de eso impide que el kernel resuelva un symlink al copiar. `mount_bundle`
corre **antes** de cualquier aprobación; `install_bundle` después copia
ese `src/` al storage del agente y lo `chown`ea al usuario del agente.

**PoC ejecutada (comportamiento del stdlib confirmado):**

```python
ln -s /etc/shadow   usb/src/leak.txt
ln -s /etc/hostname usb/src/leak2.txt
ln -s /dev/zero     usb/src/unbounded
ln -s /etc          usb/src/etcdir
shutil.copytree('/tmp/usb/src', '/tmp/dst', symlinks=False)
# real: dst/leak.txt  = contenido de /etc/shadow (archivo regular)
#       dst/etcdir    = recursión dentro de /etc
#       dst/unbounded = copia de /dev/zero sin límite hasta el corte
```

**Impacto**
1. **Confidencialidad:** root materializa cualquier archivo del sistema
   dentro del `src/` del agente no confiable, que su propio código lee en
   runtime → **se saltea por completo el sandbox** (`ProtectSystem=strict`,
   `ProtectHome=yes`). Rompe invariantes 2 y 13.
2. **Disponibilidad:** symlink a `/dev/zero` o `/dev/sda` llena el disco
   en una operación que corre como root.

**Mitigación existente verificada:** `validate_requirements_path`
(`manifest.py:135`) sí bloquea symlinks que escapan, **pero solo para
`requirements_file`**. El test `test_rejects_symlink_escaping_bundle`
cubre únicamente ese campo; ningún test cubre symlinks dentro de `src/`.

**Fix:** `symlinks=True` en ambos call sites (el symlink queda inerte
dentro del sandbox), rechazar explícitamente symlinks/archivos
especiales y cualquier resolución fuera de `usb_src_dir` antes de
copiar, y poner cuota de tamaño total.

---

### I-2 (Alta) [V] — Colisión de `short_id`: suplantación de agente y herencia de secretos y grants

**Evidencia**
- `broker/likay_broker/manifest.py:50-52` — `short_id` = último
  componente del `agent.id`.
- `agent-install-helper:392,471,547,644,997` —
  `linux_user = f"agent-{manifest.short_id}"`.
- `agent-install-helper:1014,1038` — el nombre de unidad se compara
  contra el `short_id`, no contra el `agent_id` completo.
- `broker/likay_broker/policy_store.py:62-65` — `get_grant` devuelve la
  **primera** entrada que matchea `linux_user` (y `upsert_grant` solo
  deduplica por `agent_id`).

**PoC ejecutada**

```
com.likay.kal-in -> short_id kal-in -> linux_user agent-kal-in
com.evil.kal-in  -> short_id kal-in -> linux_user agent-kal-in
Mismo usuario Linux: True    Misma unidad systemd: True

policy.json con dos grants que comparten linux_user:
get_grant('agent-kal-in') -> com.likay.kal-in ['llm.local','gpu.compute','docker.sandbox']
El agente B (evil) hereda las capacidades de A: True
```

**Consecuencias (todas bajo control del autor del bundle):**
1. **Suplantación total:** declarar el mismo `agent.id` que un agente ya
   instalado hace que `create_agent` **reuse** el usuario (no lo crea),
   `activate_agent` **no** detecte "otro agente" y `generate_unit`
   sobrescriba la unidad legítima. La TUI muestra el mismo `agent_id`:
   el usuario no puede notar la diferencia.
2. **Herencia de secretos y estado:** `chown -R … paths["base"]`
   incluye `secrets/`, `config/`, `state/`, `workspace/`.
3. **Herencia de capacidades en el Broker:** gana el grant más viejo.

**Fix:** derivar el identificador de sistema del `agent_id` completo
(p. ej. `com-likay-kal-in`) o persistir y comparar el `agent_id`
completo, rechazando si ya existe otro id con el mismo `short_id`; y
hacer que `PolicyStore` no admita dos grants para el mismo `linux_user`.

---

### I-3 (Media-Alta) [V] — La aprobación de capacidades no gobierna el sandbox

**Evidencia**
- `agent-install-launcher:129-152` (aprobación una por una), `:305`.
- `agent-install-launcher:296-303` — la pantalla de manifiesto validado
  muestra **solo** `id`, `puerto` y cantidad de capacidades.
- `agent-install-helper:721-762` — el sandbox sale exclusivamente de
  `manifest.sandbox`, nunca de `capabilities`.
- `docs/AGENT_INTERFACE.md:544-550` lo admite: *"la TUI nunca muestra el
  `sandbox:` del manifiesto al usuario (`id`/puerto/cantidad de
  capacidades)"*, e incluso da `/dev/sda5 rwm` como ejemplo.

**Qué permite.** El usuario puede **denegar** `network.egress` y el
agente igual obtiene red del host con `sandbox.network: host-egress`;
puede declarar `capabilities: []` y `devices: explicit` + `device_allow`
para acceder a dispositivos que las capacidades dicen gatear.

**PoC ejecutada.** Un manifiesto con `capabilities: []` y
`device_allow: ["/dev/sda rwm","/dev/mem rw"]` **pasa el schema** y
genera:

```
User=agent-helper
ExecStart=/mnt/likay-agent/helper/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
ProtectSystem=strict
PrivateDevices=no
DevicePolicy=closed
DeviceAllow=/dev/sda rwm
DeviceAllow=/dev/mem rw
```

Matiz honesto: para `/dev/sda` el permiso Unix del nodo (`0660
root:disk`) sigue aplicando, así que no siempre alcanza para leer el
disco; pero `network: host-egress` sin `network.egress` aprobada es una
anulación directa y sin matices, y `device_allow` sí otorga GPU/cámara/
micrófono/KVM sin pasar por la aprobación.

**Fix:** mostrar y aprobar el `sandbox` completo, y/o derivarlo de las
capacidades aprobadas, y/o validar coherencia (`host-egress` exige
`network.egress`, `device_allow` no vacío exige la capacidad asociada).

---

### I-4 (Media) [V] — Código y venv del Broker, de `likay-broker`, ejecutados como root

**Evidencia**
- `iso/config/hooks/0330-install-broker.chroot:29`
  `chown -R likay-broker:likay-broker /opt/likay-broker …`
- `agent-install-helper:1` — shebang `#!/opt/likay-broker/.venv/bin/python3`.
- `agent-install-launcher:1` — mismo shebang; la TUI corre como
  `likay-agent-install`, que tiene pkexec sin contraseña al helper.
- `agent-install-helper:37` — `from likay_broker.manifest import …`.

`likay-broker` es dueño recursivo de su código **y de su intérprete**
(el symlink `.venv/bin/python3` es reemplazable). Cualquier escritura
lograda como ese usuario se convierte en **ejecución como root** en la
siguiente invocación del helper.

**Mitigación existente (importante):** `likay-agent-broker.service`
corre con `ProtectSystem=strict` + `ReadWritePaths=/var/lib/… /var/log/…`
(`:36,47`), así que **el proceso del Broker no puede escribir en
`/opt/likay-broker`**. Eso es lo que hoy bloquea la explotación directa;
el hallazgo queda como violación de mínimo privilegio y defensa en
profundidad. Nada ejecutado por root debería ser escribible por un
usuario sin privilegios.

**Fix:** instalar venv y paquete como `root:root` y hacer `chown` a
`likay-broker` solo de `/var/lib/likay-agent-broker`,
`/var/log/likay-agent-broker` y `/opt/likay-broker-home`.

---

### I-5 (Media) [V] — Cadena de auditoría sin verificación, log legible por todos, sin rotación

**Evidencia**
- `broker/likay_broker/audit.py:134` — `open(self.path, "a+", …)` sin
  `chmod` explícito (a diferencia de `policy_store.py:91`, que sí hace
  `0o640`). La unit no define `UMask=`.
- `audit.py:154,157` — `verify_chain()` / `diagnose_chain()`.

**Qué pasa**
1. **Nunca se verifica:** no hay servicio, timer, CLI ni chequeo al
   arrancar que las llame. Los únicos callers están en `broker/tests/`.
   La "manipulación evidente" que promete `AGENT_INTERFACE.md` sección
   10 y el README **no se ejerce en el sistema instalado**.
2. **Legible por cualquier usuario:** PoC ejecutada — con el umask por
   defecto de systemd (0022) el archivo queda `0664` y el directorio
   `0755`. Cualquier usuario local (incluido un agente) lee qué
   capacidades consultó cada agente y cuándo.
3. **Sin rotación:** crecimiento indefinido, y `_read_last_hash` relee
   el archivo entero en cada evento (O(n) por evento).

**Fix:** `os.chmod(self.path, 0o640)` + `UMask=0027`, rotación por
timer/logrotate, y exponer la verificación (CLI + timer que falle
ruidosamente ante ruptura).

---

### I-6 (Media) [V] — DoS local trivial del Broker

`socket_server.py:109` (socket `0666`, deliberado), `:116`
(`threading.Thread` por conexión, sin tope). La unit no define
`TasksMax=`/`MemoryMax=`. Cualquier UID local — incluido un agente
instalado — puede abrir conexiones sin límite; cada una ocupa un hilo y
hasta ~1 MiB hasta el timeout de 30 s (que se reinicia con cada byte).
Los hilos nacen en el cgroup del **Broker**, así que el `TasksMax` del
agente no ayuda. **Fix:** límites en la unit + tope de conexiones
concurrentes.

---

### I-7 a I-10, B-B1 a B-B7 — endurecimiento y correcciones menores

- **I-7 [V]** `_quadlet_unit_text` (`agent-install-helper:816-976`) no
  aplica `_SANDBOX_BASE_DIRECTIVES` (`:701-709`) en el `[Service]` del
  Quadlet OCI: sin `NoNewPrivileges`, `ProtectSystem`, `PrivateTmp`,
  `SystemCallFilter`, etc. Asimetría de defensa en profundidad respecto
  del runtime Python.
- **I-8 [V]** `mnt-likay\x2dagent.mount:40` → `Options=defaults,nofail`
  sobre una partición donde escriben agentes. El USB sí se monta
  `ro,nosuid,nodev,noexec` (`agent-install-helper:293`). Agregar
  `nosuid,nodev`.
- **I-9 [V]** `parse_manifest_file` (`manifest.py:120-132`) documenta
  *"No sigue el archivo si es un symlink que escapa"* pero usa
  `path.resolve()` (que sigue symlinks) y solo chequea `is_file()`.
  Mismo error conceptual que I-1.
- **I-10 [V]** `port` opcional (`schema:59`) → `ExecStart … --port None`
  (`agent-install-helper:771`); `health_check_path` está en el schema y
  en los ejemplos pero **no se usa en ninguna parte** (0 ocurrencias).
- **B-B1 [V]** `0200-pull-ollama-model.chroot:18` hace
  `source /etc/likay-os/model.conf` como root y `:54` interpola
  `'${MODEL_TAG}'` dentro de un `sh -c`; una comilla simple rompe el
  quoting. Fuente repo-controlled (impacto bajo). Validar con regex y
  pasar por entorno.
- **B-B2 [C]** `rebuild-iso-with-fixes.sh:120-122` y `:206-229`
  interpolan rutas extraídas de `live.cfg` en `sed`/heredoc sin escapar.
- **B-B3 [C]** `0200:26-42`: puerto elegido por escaneo con `ss` y
  liberado con `fuser -k <puerto>` sobre un chroot que comparte red con
  el host; el `while` no tiene cota.
- **B-B4 [V]** `installer-launcher:51` → `xhost +si:localuser:root`
  (acotado a root, `-nolisten tcp`); preferible cookie `xauth`.
- **B-B5 [V]** `kal-in-backend.service:30-51` sin el hardening que sí
  tiene el Broker (`:35-47`).
- **B-B6 [V]** `smoke-test/app.py:88-90`: `int(self.headers.get(
  "Content-Length", 0))` fuera del `try` y `read(length)` sin tope
  (loopback-only, componente descartable).
- **B-B7 [C]** `iso/auto/build`, `iso/config/hooks/*.chroot` y
  `rebuild-iso-with-fixes.sh` son `-rwxrwxr-x`; corren con `sudo`. Hoy
  el grupo solo contiene al usuario de desarrollo.

---

## 3. Parte B — Kernel vendorizado `kal` / `kal-in`

**Contexto de alcance [V]:** `vendor/kal` es byte-idéntico a
`iso/config/includes.chroot/opt/kal` salvo `tests/` y `.git`; y el
kernel de `opt/kal-in` es el mismo código con un único cambio de import
(`from tool_integration.malware_scan` en lugar de
`from kernel.security.malware_scan`). **Ningún servicio systemd ejecuta
`/opt/kal`**; el que corre es `kal-in-backend.service`
(`ExecStart=/opt/kal-in/.venv/bin/uvicorn agent_core.orchestrator:app`,
`WorkingDirectory=/opt/kal-in`). Por lo tanto los hallazgos de esta
sección son relevantes en la medida en que existan en
`opt/kal-in/kernel`, que es donde los verifiqué.

### K-1 (Crítica, latente) [V] — Path traversal en `manifest.name` de una skill

**Evidencia (`opt/kal-in` y `opt/kal`, idéntico)**
```python
# kal-in/kernel/registry/sandboxed_skill.py:59
_DEFAULT_ARTIFACTS_ROOT = Path("data") / "artifacts" / "skills"

# :119-120  (en tiempo de CARGA de la skill)
self.artifact_dir = (artifacts_root or _DEFAULT_ARTIFACTS_ROOT) / manifest.name
self.artifact_dir.mkdir(parents=True, exist_ok=True)

# :244-245  (en tiempo de EJECUCIÓN)
final_path = self.artifact_dir / f"{uuid.uuid4()}{Path(uri).suffix}"
final_path.write_bytes(data)
```
`manifest.name` sale sin validar de `raw["name"]`
(`kernel/registry/skills.py:138-150`). La raíz es **relativa al CWD**
(`/opt/kal-in` en la ISO).

**PoC ejecutada (semántica de `pathlib`):**
```
'/opt/kal-in/.venv/lib/python3.11/site-packages' -> /opt/kal-in/.venv/lib/python3.11/site-packages | absoluto: True
'../../../../etc/cron.d' -> data/artifacts/skills/../../../../etc/cron.d
```

**Cadena de explotación:** una skill de terceros con
`name: "/opt/kal-in/.venv/lib/python3.11/site-packages"` produce que el
proceso **host** (el agente) escriba
`site-packages/<uuid>.<sufijo>` con bytes que la skill eligió →
en el siguiente arranque del intérprete, Python ejecuta las líneas
`import` de todo `.pth` → **ejecución de código como `kal-in`**, con
acceso a `data/keys/*` (claves de firma), `admin_token` y `.env`. La
variante `.desktop` en `~/.config/autostart` es equivalente.

**Estado real hoy (importante, sin exagerar):**
- El `mkdir(parents=True, exist_ok=True)` de `:120` **ya ocurre** (crea
  directorios arbitrarios dentro de lo que permitan los permisos de
  `kal-in`).
- La **escritura** del archivo pasa por `scan_bytes` (`:236-243`), que es
  *fail-closed*: si ClamAV no está, lanza. Verifiqué que la ISO **no
  instala ClamAV** (no hay `clamscan` en el chroot, no aparece en
  package-lists ni en los `.packages`), así que hoy la escritura está
  bloqueada **por accidente**.
- Se activa en cuanto se instale ClamAV, que es requisito de facto para
  que cualquier skill produzca artefactos: la seguridad no puede
  depender de que falte una dependencia.

**Fix:** validar `name` con `^[a-z0-9][a-z0-9_-]{0,63}$` en
`parse_manifest`, y verificar
`artifact_dir.resolve().is_relative_to(root.resolve())` antes de crear y
de escribir; allowlist del sufijo (`Path(uri).suffix`).

### K-2 (Alta) [V] — Escape por symlink en la recolección de salida

**Evidencia** `kal-in/kernel/lifecycle/docker_runner.py:239-243`:
```python
if output_path is not None and output_path.exists():
    result.output_files = {
        str(p.relative_to(output_path)): p.read_bytes()
        for p in output_path.rglob("*") if p.is_file()
    }
```
Sin `lstat`, sin `follow_symlinks=False`, sin comprobar que el
`resolve()` quede dentro de `output_path`. La skill (código no
confiable, dentro del contenedor) puede crear symlinks en el bind mount
`rw` de salida; el **proceso host** los sigue y carga el contenido en
memoria. `SandboxExecutor` (`executor.py:29,76`) usa
`DockerSandboxRunner` por defecto, y `SandboxedSkillTool` se registra en
`kernel/registry/skills.py:269-272`, así que el camino está vivo.

**Impacto:** lectura arbitraria de archivos del host por parte del
proceso agente (`/proc/self/environ`, claves de firma, `admin_token`),
más DoS por tamaño (K relacionado: lectura sin tope, también
`container.logs()` completo).

**Fix:** descartar entradas que no sean archivos regulares
(`os.lstat`), o copiar con `follow_symlinks=False`, o exigir
containment resuelto; y poner tope de tamaño.

### K-3 (Alta) [V] — La firma usa la clave pública que viene en el propio paquete

**Evidencia** `kal/kernel/registry/skill_signing.py:191-205`:
```python
data = json.loads(sig_path.read_text(encoding="utf-8"))
public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(data["author_public_key"]))
signature = bytes.fromhex(data["signature"])
...
public_key.verify(signature, current_manifest)
```
No hay trust store ni pinning. Cualquiera que pueda modificar el
paquete —exactamente el atacante del modelo de marketplace— regenera su
keypair, re-firma y obtiene `verified`. La firma solo detecta
alteraciones *sin re-firma*, y `install_from_market` la usa como único
control técnico. El docstring del módulo es honesto (dice que cubre
integridad, no autoridad), pero la UI/flujo inducen a leer "verificada"
como validación de autor. **Fix:** pinning de claves de autor (por
fingerprint o por nombre de skill) o firma contra un registro.

### K-4 (Alta) [V] — La red de la skill la concede su propio manifiesto

**Evidencia** `kal-in/kernel/registry/sandboxed_skill.py:134`:
```python
network_mode = "bridge" if Permission.NETWORK in self.manifest.permissions else None
```
`manifest.permissions` es autodeclarado en `skill.yaml`. El techo por
tier (`config/config.yaml:344-345`, `skill: [filesystem_read]`) solo lo
aplica `PermissionCascade`, que **no se invoca en ninguna parte del
kernel** (grep: solo definición y comentarios dentro de
`opt/kal`/`opt/kal-in/kernel`).

**Mitigación real (verificada fuera del kernel, en el código horneado):**
`kal-in/agent_core/llm/agent_loop.py:771` sí llama a
`permission_cascade.missing_permissions(tool.permissions, tool.trust_tier, …)`
antes de ejecutar, así que **el agente de referencia** bloquea la red no
autorizada. El problema es de frontera: la garantía vive en el
llamador, no en el kernel — cualquier otro consumidor de
`SandboxedSkillTool.execute()` no la hereda. **Fix:** consultar la
cascada dentro de `SandboxedSkillTool`/`DynamicSandboxedTool` antes de
derivar `network_mode`, y soportar allowlist de dominios en vez de
`bridge` abierto.

### K-5 (Alta) [V] — TOCTOU entre la firma y la ejecución

`kernel/registry/skills.py:209-223` verifica la firma **una vez al
cargar**; `sandboxed_skill.py:189` (`_collect_skill_files`) **relee el
código del disco en cada ejecución** (`path.read_text`). Quien pueda
escribir en `skills/<x>/` entre la carga y una ejecución posterior
ejecuta código no firmado, y la auditoría sigue reportando
`signature_status: verified` (se auditó al cargar). **Fix:** hashear el
contenido en el momento de ejecutar contra el manifiesto firmado, o
ejecutar un snapshot en memoria verificado al cargar.

### K-6 (Media) [V] — Traversal en el nombre de herramientas dinámicas

`kal/kernel/registry/versioning.py:26-29` y `:59-60` usan `name` sin
sanitizar (`_tool_dir` hace `mkdir(parents=True, exist_ok=True)` y
`(tool_dir / f"{name}_v{version}.py").write_text(...)`).
`registry.py:247-251` lo llama con `manifest.name`, elegido por el LLM
en `propose_dynamic_tool`. El sufijo `_vN.py` acota el impacto (no se
puede pisar `authorized_keys`/`sitecustomize.py`), pero es escritura
fuera del store e inyección de versiones de otras herramientas — y la
firma se recalcula sobre lo escrito, así que "verifica". **Fix:**
charset estricto + containment resuelto; `re.escape(name)` en el glob.

### K-7 (Media) [C] — Auditoría de kal sin ancla y frágil ante corrupción

`kal/audit/audit_log.py:157-163` lee el archivo completo y hace
`json.loads` de la última línea; una última línea truncada (crash a
mitad de escritura) hace fallar **todo `record()` posterior**, y
`record()` se llama sin `try` en varios caminos. `verify_chain()`
(`:202-251`) no tiene firma/HMAC ni ancla externa: quien tenga escritura
en el log puede reescribir la cadena completa y `verify_chain()`
devolverá `True`. Positivo verificado: el `flock` + lectura del último
hash desde disco cierra la carrera entre escritores. **Fix:** firmar
entradas (o periódicamente), publicar el último hash fuera de banda, y
tolerar/descartar una última línea inválida.

### K-8 (Baja) [V] — `/execute` del sandbox_runner sin autenticación

`kal/kernel/api/sandbox_api.py:29-38` expone `POST /execute` que corre
`executor.execute(req.source_code, …)` sin token ni identidad; el
`Dockerfile:32` bindea `0.0.0.0:9000`. No usa `utils/admin_token.py`.
**No está live en la ISO actual**: `/opt/kal` no lo ejecuta ningún
servicio y, en el compose de kal-in, `sandbox_runner` no publica puertos
y vive en la red interna. Se reporta porque es una primitiva de
ejecución de código sin auth en el árbol vendorizado.

### K-9 a K-11 — menores

- **K-9 [C]** `skill_market.py:36-38` (`git clone … market_url`) sin
  `--` permite *argument injection* (`--upload-pack=…`); `:71` y
  `scripts/install_from_market.py:75` permiten traversal en
  `skill_name`. Entrada de CLI (impacto bajo).
- **K-10 [C]** `utils/config.py:522-530` carga `config/config.yaml`
  relativo al CWD; en la ISO el CWD es `/opt/kal-in` (no escribible por
  terceros) → riesgo bajo.
- **K-11 [V]** El docstring de `skills.py:17-20` afirma *"cada
  `skill.yaml` trae `enabled: false`"*, pero **las 6 skills horneadas
  traen `enabled: true`**. Discrepancia documentación/artefacto.

---

## 4. Parte C — Build e integración de la ISO

### B-C1 (Crítica, build) [C] — Script remoto ejecutado como root sin pin ni integridad

`iso/config/hooks/0100-install-ollama.chroot:8` →
`curl -fsSL https://ollama.com/install.sh | sh`. El script upstream
(verificado contra la rama `main`) no valida checksum ni firma, baja la
**última** release (este repo no define `OLLAMA_VERSION`), crea el
usuario `ollama` y escribe su unit systemd. Además puede agregar el repo
apt de NVIDIA e instalar drivers como root. Un compromiso/MITM del
endpoint produce RCE root en la máquina de build y un backdoor horneado
en el squashfs. Mitigación existente: `-fsSL`, TLS y
`set -euo pipefail`; **no hay verificación de integridad**. **Fix:**
versión fija + `sha256` pineado en el repo (o vendorizar el binario).

### B-A1 (Alta, build) [C] — `git clone` de un tag mutable + compilación como root

`0350-build-cage-noxwayland.chroot:60-69`: `git clone --branch v0.2.1
--depth 1 https://github.com/cage-kiosk/cage.git`, `meson`/`ninja`,
`install -m 0755 build/cage /usr/bin/cage`. El pin es un **tag**
(mutable), sin `git verify-tag` ni SHA. Un tag movido o una cuenta
comprometida entrega fuentes que `meson`/`ninja` compilan como root.
Mitigación existente: `--depth 1`, tag explícito, `grep -qx` que
verifica que el parche se aplicó (fail-closed), purga de deps de build.
**Fix:** pinear el SHA completo o verificar la firma del tag; compilar
sin privilegios.

### B-A2 (Alta, build) [C] — `pip install` sin hashes ni versiones fijas

`0300-install-kal.chroot:18-21`, `0320-install-kal-in.chroot:31-34`,
`0330-install-broker.chroot:17-18`. `requirements-core.txt` usa `>=` sin
techo; no hay `--require-hashes` ni lockfile. Una release maliciosa de
cualquiera de las dependencias transitivas queda horneada y se importa
en runtime. **Fix:** lock con hashes (`pip-compile --generate-hashes` /
`uv lock`) + `--require-hashes`; fijar también `pip`.

### B-M1 (Media) [V] — Sandbox de WebKit desactivado en el kiosco

`likay-kiosk.service:60` →
`Environment=WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1`. Un RCE del
renderizador WebKit corre directamente como el usuario `kiosk` (grupos
`video,input,render`), sin bubblewrap. El kiosco renderiza salida del
modelo local. Mitigación: solo navega a `AGENT_URL` (loopback) y no es
root. **Fix:** hacer funcionar userns/bubblewrap en la imagen o endurecer
el servicio (grupos mínimos, `ProtectSystem=strict`, `PrivateDevices`).

### B-M2 (Media) [C] — Hardlinks host↔chroot + `chown` por nombre

`auto/build:154` siembra el caché de modelos con `cp -al` (hardlinks) y
`:163-164` lo devuelve igual al repo. `0100:16-17` hace
`chown -R ollama:ollama /usr/share/ollama/.ollama` **dentro del chroot**,
pero los inodos de los blobs son **los mismos** que los de
`iso/model-cache/` en el host. Verifiqué inodos compartidos
(`stat -c '%i %h'`: mismo inodo, `links=2`) y la divergencia de
`/etc/passwd`: en el chroot `ollama=999`, `kal=997`; en el host `999` es
`dnsmasq` y `997` es `ollama`. En un build como root real, ese `chown`
re-owneriza archivos **del repositorio del host** a una cuenta de
servicio distinta, que podría reescribir los blobs horneados en la
próxima build. No pude determinar si el `65534` observado proviene de un
build previo en user namespace o del `chown` (lo digo explícitamente).
Efecto runtime confirmado: los blobs quedan como `nobody`, no `ollama`.
**Fix:** no compartir inodos host/chroot (`cp -a`/`rsync`), usar uid/gid
numéricos en el `chown`, y verificar el ownership en el squashfs final.

### B-M3 (Media) [C] — Dependencias de desarrollo horneadas

`0300:19-21` y `0320:32-34` instalan `requirements-dev.txt` (que el
propio archivo declara "nunca hace falta en una instalación de uso
normal"), y la package-list incluye `build-essential:49`. Superficie y
tamaño innecesarios en el sistema instalado.

### B-M4 (Media) [V] — Política de contraseña del sistema instalado

`users.conf:6` incluye `sudo` en `defaultGroups`, `:17`
`setRootPassword: false` (correcto), `:21` `minLength: 6` sin requisitos
de complejidad. Es config vendorizada de Calamares, pero queda horneada.
**Fix:** mínimo ≥ 12 + calidad, y revisar si el usuario debe ser sudoer
por defecto.

---

## 5. Controles correctos observados

Es justo decirlo: buena parte del diseño resiste un análisis adversarial
serio, y varios hallazgos solo existen porque el resto está bien hecho.

**Primera parte**
- Identidad por `SO_PEERCRED` (`socket_server.py:44-54`): la UID viene
  del kernel, nunca del JSON. La frontera de `register_policy`/
  `unregister_policy` está bien implementada.
- `user`/`group`/`extra_groups` explícitos en `_run`
  (`agent-install-helper:196-229`): pip/venv corren como el usuario del
  agente, no como root, con `setgroups(0, NULL)`.
- Defensa contra inyección en units systemd: los patrones del schema
  (`env` `^[^\r\n]*$`, `device_allow` `^[^\r\n]+$`, `command`
  `^[A-Za-z0-9_.-]+$`, `entry_point` sin `\s`, `image.reference`/
  `digest`, enums de `sandbox`) cierran el vector `\nUser=root` que el
  propio proyecto documenta como hallazgo previo.
- `--host 127.0.0.1` forzado por construcción y `bind_host` ausente del
  schema; `runtime.oci.image.digest` obligatorio e `Image=ref@digest` en
  el Quadlet (evita el pull implícito de `:latest`).
- Staging root-owned + `umount` inmediato del USB cierra el TOCTOU del
  manifiesto de forma estructural.
- Auditoría del Broker con `flock` y lectura del último hash desde disco
  (no cacheado en memoria): el bug clásico está correctamente evitado.
- Secretos: valor por stdin (nunca argv), `secrets/` `0700`, archivo
  `0600`; en OCI no pasa por `Image=`/`Environment=` ni queda en
  `podman inspect`.
- Aislamiento de usuarios: cada agente con usuario de sistema sin shell
  ni contraseña; kiosk, instalador y agente separados; `pkexec` acotado
  por acción Polkit y `exec.path`.
- `set -euo pipefail` consistente; sin `shell=True`/`eval` en el helper.

**Build/ISO**
- `set -euo pipefail` en todos los hooks y **live-build aborta** ante
  hook con exit != 0 (`lb_chroot_hooks`).
- Hooks idempotentes y *fail-closed*: 0430/0440/0450/0460/0480/0550
  verifican marcadores y fallan si el vendorizado cambió; `0350:65`
  verifica que el parche se aplicó.
- `mktemp -d` en todos los casos (sin nombres predecibles en `/tmp`),
  con traps de limpieza.
- Sin `chmod 777/666`, sin setuid/setgid, sin tocar sudoers, sin
  `NOPASSWD`; `chown -R` acotados.
- `archives/`, `packages.chroot/`, `preseed/` **vacíos**: no se agregan
  repos ni claves apt de terceros; apt solo usa el archivo firmado de
  Ubuntu.
- Sin secretos hardcodeados ni en URLs; `admin_token` generado con
  `secrets.token_urlsafe(32)` y `0600`.
- No se instala `openssh-server` (no hay `sshd` que endurecer).

**Kernel vendorizado**
- Sandbox Docker bien endurecido (`docker_runner.py:208-230`): sin
  `privileged`, `cap_drop=["ALL"]`, `no-new-privileges`, `read_only`,
  `tmpfs` con `noexec,nosuid`, `network_mode` por defecto `none`,
  límites de memoria/swap/CPU/PIDs, contenedor efímero.
- Sin `shell=True`, sin `eval/exec/pickle/marshal`, `yaml.safe_load` en
  todo el árbol; subprocess con listas y `timeout`.
- Escaneo de malware *fail-closed* antes de escribir artefactos (lo que
  hoy bloquea accidentalmente K-1).
- Rechazo de permisos sin motor real de enforcement, validación AST
  previa a código no confiable, allowlist de métodos del bus con rechazo
  auditado y límite de 1 MiB por línea.
- Claves privadas `0600`; Ed25519; allowlists de red *fail-closed* con
  matching de sufijo correcto (`network_safety.py:49-52`).

---

## 6. Cobertura y limitaciones

- **Revisado completo:** `broker/`, `iso/config/includes.chroot/usr/**`
  (helper, launchers, kiosco, Calamares helpers), systemd units, reglas
  y acción Polkit, módulos Calamares, `.mount`, `grub.d`, los 18 hooks
  `*.chroot`, `auto/{build,config,clean}`,
  `scripts/rebuild-iso-with-fixes.sh`, package-lists, frontends y el
  kernel vendorizado de `opt/kal` y `opt/kal-in`.
- **No verificado empíricamente:** comportamiento en hardware real
  (arranque, DRM, LUKS, Podman rootless); no se ejecutó el build de la
  ISO ni QEMU. No fue posible leer `iso/chroot/etc/shadow` (denegado por
  el sandbox) ni determinar el ownership real dentro del artefacto de
  build (las UID aparecen mapeadas a `nobody`); en esos casos me apoyé
  en el código de los hooks, que es la fuente autoritativa.
- **Vendorizado:** `kal`, `kal-in` y `calamares-settings-debian` son
  submódulos de otros repositorios. Esta auditoría cubre sus caminos
  relevantes para la seguridad de Likay-OS; merecen su propia auditoría
  en origen (varios hallazgos de la Parte B son de ese código).
- **B-M2** tiene una parte no determinada (origen del uid `65534`) que
  se explicita en su sección.
- **Estado del árbol de trabajo al momento de la auditoría:** `git
  status` reporta cambios **preexistentes** que esta auditoría **no**
  introdujo (verificado por mtime): `iso/config/hooks/0200-pull-ollama-model.chroot`
  modificado el 2026-09-21 (reemplaza `kill "$OLLAMA_PID"` por
  `fuser -k` — es la versión sobre la que se reporta B-B3) y los
  punteros de submódulo `vendor/kal` / `vendor/kal-in` por delante del
  commit registrado en el índice (checkout del 2026-09-19). El único
  archivo agregado por esta auditoría es este documento.

## 7. Plan de remediación priorizado

1. **K-1, K-2** — sanitizar `manifest.name` y no seguir symlinks al
   recolectar salida del contenedor. Coordinar con el repo `kal`.
2. **I-1, I-2** — `symlinks=True`/rechazo de symlinks en el bundle, y
   identificador de sistema derivado del `agent.id` completo.
3. **I-3** — mostrar/aprobar el `sandbox` completo o derivarlo de las
   capacidades aprobadas.
4. **B-C1, B-A1, B-A2** — pin + verificación de integridad en el build
   (Ollama, cage, pip con hashes).
5. **K-3, K-4, K-5** — trust store de autores, cascada de permisos
   dentro del kernel, y verificación de integridad en el momento de
   ejecutar.
6. **I-4, I-5, I-6, K-6, K-7, B-M1** — higiene de privilegios,
   auditoría verificable, límites de recursos y sandbox del kiosco.
7. **Resto (Baja/Informativa)** — endurecimiento y correcciones menores.

## 8. Reproducibilidad

Los PoC de este informe se ejecutaron en el workspace **sin modificar el
repositorio** (solo se agregó este documento):
`shutil.copytree(symlinks=False)` sobre symlinks a archivo, directorio y
`/dev/zero`; `parse_manifest_text` + `_systemd_unit_text` con
`device_allow: ["/dev/sda rwm"]`; colisión de `short_id` y `get_grant`
sobre `PolicyStore` en directorio temporal; modo de archivo de
`AuditLog.record()`; semántica de `pathlib` para rutas absolutas;
verificación de inodos compartidos y de `/etc/passwd` del chroot; y
`python3 -m pytest -q` → **108 passed**.
