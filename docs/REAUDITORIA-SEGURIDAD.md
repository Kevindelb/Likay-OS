# Re-auditoría de seguridad — Likay-OS (post-remediación)

> **Estado de remediación (actualizado 2026-09-26):** todos los
> hallazgos de esta re-auditoría verificados contra el código real
> antes de aceptarlos -- R-1, R-3, R-4, R-5 y R-6 cerrados (ver la
> rama `audit/fixes-2026-09-26`, commit `96a5d0f` y los que le
> preceden). R-1 (Alta) era el más serio: `op_generate_unit()` nunca
> conectaba la aprobación/denegación real del usuario con el sandbox
> generado -- denegar una capacidad era cosmético. R-2 (K-1…K-6, kernel
> vendorizado) sigue sin tocar a propósito: es `kal`/`kal-in`, no este
> repo. R-7/R-8 quedan como verificación pendiente en QEMU/hardware
> real (no como bugs confirmados) -- ver los commits para el detalle
> de por qué. R-9 (residuos menores: `source` de model.conf, CI sin
> hashes, `PolicyStore.get_grant` ante una clave faltante, fairness de
> conexiones) sigue abierto, no bloqueante.

**Fecha:** 2026-09-26
**Alcance:** los 6 commits de remediación sobre la rama
`audit/fixes-2026-09-26` (`4a026df`, `2aa6357`, `0113e38`, `a2e90f2`,
`f5776af`, `57e594c`, `0b56de1`), re-verificación adversarial de los
fixes propios (I-1, I-4…I-10) y estado de los hallazgos del kernel
vendorizado (K-1…K-6).
**Método:** lectura de código completa de cada commit, PoC ejecutadas,
verificación por red de los pins de integridad, y `pytest` (138
passed).

Marcas: **[V]** verificado con evidencia y/o PoC · **[R]** riesgo
razonado, no reproducible en este entorno · **[OK]** verificado y
correcto.

---

## 1. Estado de remediación

| Hallazgo original | Estado real | Evidencia |
|---|---|---|
| I-1 symlinks en el bundle | **[OK]** cerrado | `_reject_unsafe_bundle_entries` + `symlinks=True`; sigo sin encontrar bypass (los hardlinks no cruzan filesystem, y un TOCTOU sobre el contenido del USB queda contenido porque ambas copias preservan symlinks) |
| I-2 colisión de `short_id` | **Parcial** | ya no es el último componente, pero el hash es de **40 bits** (ver R-4) |
| I-3 aprobación gobierna el sandbox | **NO cerrado** | ver R-1 |
| I-4 `/opt/likay-broker` root-owned | **[OK]** | `chown -R root:root` + `go-w`, `likay-broker` solo home/estado/log |
| I-5 auditoría verificable | **[OK]** | `verify-audit` + timer + `0640` + `UMask=0027` |
| I-6 tope de conexiones | **[OK]** | semáforo + `TasksMax`/`MemoryMax` |
| I-7 Quadlet | **Parcial, honesto** | solo `LockPersonality`/`RestrictSUIDSGID`; la doc lo llama "cerrado parcialmente a propósito" (correcto) — ver R-7 |
| I-8 `nosuid,nodev` | **[OK]** | |
| I-9 symlink en `parse_manifest_file` | **[OK]** | |
| I-10 `--port None` | **[OK]** | |
| B-C1 Ollama | **Parcial** | script pineado y verificado (sha256 correcto contra upstream); el **tarball** no se verifica — ver R-6 |
| B-A1 cage | **[OK]** | commit pin `f9626f79…` verificado contra el tag v0.2.1 real |
| B-A2 pip hashes | **Parcial** | locks correctos y sin índices alternativos; **`pip` mismo sigue sin pinear** — ver R-5 |
| B-M1..B-M4, B-B1, B-B3 | **[OK]/[R]** | `cp -a` sin inodos compartidos, dev-deps fuera, `minLength: 12` (probé el `sed` del hook 0490: funciona), `printf %q`, cota de puerto |
| V-1 CI por SHA | **[OK]** | ambos SHAs verificados contra GitHub (`checkout v4.4.0`, `setup-python v5.6.0`) |
| K-1…K-6 kernel vendorizado | **NO cerrado** | ver R-2 |

Los pins nuevos son **correctos**: los verifiqué contra la fuente real
(sha256 de `ollama.com/install.sh` y los tres SHAs de GitHub coinciden
exactamente con lo pineado). Eso es poco común y está bien hecho.

---

## 2. Hallazgos pendientes

### R-1 (Alta) [V] — I-3 sigue abierto: la aprobación/denegación de capacidades no gobierna el sandbox

**Evidencia**
- `agent-install-helper:1080` — `op_generate_unit()` **no recibe** la
  lista aprobada; llama a `_systemd_unit_text(manifest, linux_user)`
  (`:776`), que deriva todo de `manifest.sandbox`.
- `agent-install-launcher:340` — `approved = approve_capabilities(...)`;
  `:383` — `run_helper("generate_unit")` (sin argumentos);
  `:387` — `register_policy(..., capabilities=approved)` (API de
  cortesía, no enforcement).
- `agent-install-launcher:168` — la propia UI dice
  `"[n] denegar (el agente sigue instalándose sin ella)"`.

**PoC ejecutada.** Manifiesto con `capabilities: [network.egress,
camera]`, `sandbox.network: host-egress`, `device_allow: ["/dev/sda
rwm","/dev/video0 rw"]`; el usuario **deniega todo** (`approved = []`):

```
Unidad systemd realmente generada:
   User=agent-helper
   ProtectSystem=strict
   PrivateDevices=no
   DeviceAllow=/dev/sda rwm
   DeviceAllow=/dev/video0 rw

¿obtiene red del host pese a que el usuario la denegó?: True
¿obtiene /dev/sda igual?: True
```

**Por qué el fix no alcanza.** Los dos cambios de `2aa6357` son
(a) una validación de coherencia entre lo que el manifiesto *declara* en
`sandbox:` y en `capabilities:`, y (b) una pantalla que *muestra* el
sandbox. Ninguno de los dos conecta la **decisión** del usuario con la
unidad generada: la denegación sigue siendo cosmética. La coherencia
incluso garantiza que la capacidad estará declarada (así el usuario la
ve), pero no que su "no" se respete.

**Hallazgos secundarios del mismo diseño**
- El mapeo capacidad→dispositivo es genérico: `capabilities: [camera]`
  habilita `device_allow: ["/dev/sda rwm","/dev/mem rw"]`
  (`_DEVICE_RELATED_CAPABILITIES`, `manifest.py:159`).
- `sandbox.filesystem: restricted` **no** exige `filesystem.data_dir`;
  la coherencia solo cubre red y dispositivos.

**Fix recomendado.** Que la lista aprobada sea la entrada de
`generate_unit` (p. ej. `generate_unit` recibe por stdin los ids
aprobados, revalidados en el helper) y derivar el sandbox de ahí:
`network: host-egress` solo si `network.egress` fue aprobada,
`DeviceAllow` solo para dispositivos cubiertos por una capacidad
aprobada, `ReadWritePaths` solo si `filesystem.data_dir` fue aprobada.
Alternativa mínima: si el usuario deniega una capacidad de la que el
sandbox depende, abortar la instalación en vez de continuar.

---

### R-2 (Alta) [V] — Los hallazgos del kernel vendorizado (K-1…K-6) siguen intactos

Los submódulos no se tocaron y `iso/config/includes.chroot/opt/kal*` no
aparece en el diff de la rama. Siguen exactamente igual:

| ID | Evidencia actual |
|---|---|
| K-1 path traversal → escritura host desde una skill | `opt/kal-in/kernel/registry/sandboxed_skill.py:119` (`artifact_dir = root / manifest.name`) y `:244` (`final_path.write_bytes`) |
| K-2 symlink en la recolección de salida | `opt/kal-in/kernel/lifecycle/docker_runner.py:241` (`p.read_bytes()` sobre `rglob("*")`) |
| K-3 firma con clave autodeclarada | `opt/kal/kernel/registry/skill_signing.py:193` (`from_public_bytes(data["author_public_key"])`) |
| K-4 red concedida por el manifiesto de la skill | `opt/kal-in/kernel/registry/sandboxed_skill.py:134` |
| K-5 TOCTOU firma/ejecución | `opt/kal-in/kernel/registry/skills.py:209` vs `sandboxed_skill.py:189` |
| K-6 traversal en versionado de herramientas dinámicas | `opt/kal/kernel/registry/versioning.py:26-29,59-60` |

Recordatorio del matiz ya informado: en la ISO actual, la escritura
final de K-1 está bloqueada **por accidente** (ClamAV no está instalado
y `scan_bytes` es fail-closed), pero el `mkdir` con traversal ya ocurre
y el ataque se activa en cuanto se instale ClamAV, que es requisito de
facto para que cualquier skill produzca artefactos. K-2, K-3, K-4, K-5 y
K-6 no dependen de ClamAV.

**Es el hallazgo más grave del proyecto y el único grupo que quedó
enteramente sin abordar.** El fix correcto va en los repos
`carlosbv99-bit/kal` y `carlosbv99-bit/kal-in` (o actualizando el pin del
submódulo a una versión que lo corrija).

---

### R-3 (Media) [V] — La validación de coherencia nueva rechaza manifiestos OCI válidos del propio repo (regresión)

**Evidencia.** `_validate_sandbox_capability_coherence`
(`broker/likay_broker/manifest.py:186-192`) exige `network.egress`
declarada cuando `sandbox.network: host-egress`. Dos fixtures del propio
repositorio declaran `host-egress` con solo
`capabilities: [filesystem.data_dir]`:

```
RECHAZA  tests/fixtures/oci-nonroot/agent.yaml
RECHAZA  tests/fixtures/secret-leak/agent.yaml
  -> "sandbox.network: host-egress ... capabilities no incluye network.egress"
```

**Por qué la suite no lo detecta:** ningún test parsea esos fixtures
(son para verificación manual en QEMU, fases B/C de OCI). La suite da
138/138 verde con la regresión adentro.

**Impacto.** Cualquier bundle OCI —incluidos los dos flujos de
verificación documentados del proyecto— que declare `host-egress` sin
`network.egress` deja de instalar. Es un **cambio de contrato no
documentado como breaking** en `docs/AGENT_INTERFACE.md` (la sección de
coherencia no menciona que invalida manifiestos antes válidos).

**Fix.** Actualizar los dos fixtures (y cualquier bundle de ejemplo) para
declarar `network.egress`, o marcar la regla como cambio incompatible en
la doc, y agregar un test que parsee **todos** los fixtures del repo
para que una regla nueva no vuelva a invalidarlos en silencio.

---

### R-4 (Media) [V] — `short_id`: el hash de 40 bits es brute-forceable

**Evidencia.** `broker/likay_broker/manifest.py:77-80`:
`sha256(agent_id)[:10]` = 10 nibbles hex = **40 bits**. El prefijo
legible debe coincidir, pero el atacante lo elige libremente (mismo
último componente), así que la búsqueda de segunda preimagen es de
~2^40 ≈ 1,1·10¹² evaluaciones de SHA-256 — minutos en una GPU de gama
alta. Con eso obtiene un `agent_id` distinto con el **mismo** `short_id`
→ mismo usuario Linux, misma unidad, mismo storage y mismo grant:
la suplantación de I-2 vuelve a ser alcanzable, solo que con cómputo.

`docs/AGENT_INTERFACE.md:150` lo describe como *"colisión-resistente por
diseño"*, que es exacto frente a colisiones accidentales pero
sobrevendido frente a un adversario.

**Fix.** Subir a ≥16 hex (64 bits). Ojo con el límite de 32 caracteres
del nombre de usuario Linux: `agent-` (6) + prefijo + `-` + hex ≤ 32,
así que con 16 hex el prefijo legible debe bajar a ≤9 caracteres
(p. ej. `agent-kal-in-a1b2c3d4e5f60718` = 29). Alternativa: nombre de
usuario = `agent-` + hex(16) y dejar el prefijo legible solo en la
unidad systemd.

---

### R-5 (Media) [V] — `pip install --upgrade pip` sigue sin pin ni hash

**Evidencia**
- `iso/config/hooks/0300-install-kal.chroot:22`
- `iso/config/hooks/0320-install-kal-in.chroot:32`
- `iso/config/hooks/0330-install-broker.chroot:17`

Los tres hacen `pip install --no-cache-dir --upgrade pip`: descarga pip
desde PyPI **sin hash ni versión fija**, como root, en el build. Es la
misma clase de hallazgo que B-A2 (que se trató como Alto) y además deja
un detalle incómodo: el `pip` que después ejecuta los
`--require-hashes` es precisamente el binario recién bajado sin
verificar.

**Fix.** Fijar pip con hash en el propio lock (o crear el venv con
`--without-pip` y usar el pip del sistema, root-owned), y eliminar el
`--upgrade pip` sin verificar.

---

### R-6 (Media) [V] — Ollama: el script está pineado, el binario no

Verifiqué que el pin es correcto: el sha256 de
`https://ollama.com/install.sh` hoy coincide exactamente con
`25f64b81…c9f` (`0100-install-ollama.chroot:25`). Pero el propio script,
que sigue ejecutándose como root, **no verifica el tarball** que
descarga:

```
(sin verificacion de integridad del binario)
148:            zstd -d | $SUDO tar -xf - -C "${dest_dir}"
```

Es decir: la integridad del binario de Ollama horneado en la ISO sigue
dependiendo solo de TLS. El pin del script + `OLLAMA_VERSION=0.34.4`
reduce mucho la ventana (ya no es "lo último de ese día"), pero no la
cierra.

Además, el script pineado puede **agregar el repositorio apt de NVIDIA y
ejecutar `apt-get install cuda-drivers` como root** según detección de
GPU (`oll.sh:324-361`), sin verificación de esa keyring. En un build
ejecutado en una máquina con GPU NVIDIA real y `/sys` bind-mounteado en
el chroot, eso agrega un repo de terceros al sistema horneado.

**Fix.** Descargar el tarball de la versión fija y verificar su sha256
antes de extraerlo (o vendorizarlo), y forzar que el script no toque apt
(p. ej. `OLLAMA_SKIP_...`/`--no-...` si existe, o hacer el install a
mano con el tarball verificado).

---

### R-7 (Baja) [R] — Quadlet OCI: `RestrictSUIDSGID=yes` puede romper la extracción de capas

`agent-install-helper:1045` agrega `RestrictSUIDSGID=yes` al `[Service]`
del Quadlet. La doc explica bien por qué **no** se pone
`NoNewPrivileges` (rompe `newuidmap`, setuid) ni `ProtectControlGroups`
(choca con `Delegate=yes`) ni `SystemCallFilter`. Pero
`RestrictSUIDSGID` impide **crear** archivos setuid/setgid, y las
imágenes reales suelen traer binarios setuid (`/usr/bin/passwd`,
`/bin/su`, …): al extraer esas capas, Podman podría recibir `EPERM` en
el `chmod`. No es verificable sin hardware; queda como riesgo de
regresión a confirmar con un `podman load`/`run` real antes de dar I-7
por cerrado.

---

### R-8 (Baja) [R] — Hardening del kiosco sin verificar

`likay-kiosk.service` ahora lleva `NoNewPrivileges`,
`ProtectKernelTunables/Modules`, `ProtectControlGroups`,
`LockPersonality`, `RestrictSUIDSGID`. La exclusión de
`ProtectHome`/`PrivateDevices` está bien razonada, pero el resto no se
pudo reprobar en QEMU/hardware: `ProtectControlGroups` +
`PAMName=login`/logind y `NoNewPrivileges` sobre cage/WebKit son
exactamente el tipo de combinación que en este proyecto ya rompió el
arranque dos veces por motivos no obvios. Verificar en QEMU antes de
considerarlo cerrado.

---

### R-9 (Baja) — residuos menores

- **`source /etc/likay-os/model.conf` como root** (`0200-pull-ollama-model.chroot:19`)
  sigue ejecutando shell de un archivo; el `printf %q` arregló la
  interpolación posterior, no el `source`. Contenido del repo → riesgo
  bajo, pero lo correcto es parsear el valor (p. ej. `grep`/`cut`) en vez
  de `source`.
- **CI**: `pip install -e ".[dev]"` sin hashes
  (`.github/workflows/broker-tests.yml`). El job no produce artefactos
  horneados, así que el impacto es bajo; aun así los actions sí están
  pineados y el pip no.
- **`PolicyStore.load_all`** (`policy_store.py:68-72`): filtrar claves
  extra evita el `TypeError` por claves de más, pero **una clave
  requerida faltante sigue lanzando** `TypeError` y tumbando la conexión
  (`get_grant` no está envuelto). Fallar con un error de dominio, o
  ignorar entradas inválidas, sería más robusto.
- **Tope de conexiones sin fairness por UID** (`socket_server.py`): un
  usuario local puede ocupar los 128 cupos con conexiones ociosas
  (liberadas a los 30 s) y privar de servicio a la TUI. Aceptable y
  acotado; mencionado por completitud.

---

## 3. Verificaciones que dieron bien (independientes)

- **Pins de integridad correctos**: sha256 de `ollama.com/install.sh`
  = `25f64b81…c9f` (coincide); cage v0.2.1 → commit
  `f9626f79519f8ee22d7bb0c3880a66791d82f923` (coincide, tras dereferenciar
  el tag anotado); `actions/checkout@v4.4.0` →
  `11d5960a326750d5838078e36cf38b85af677262` (coincide);
  `actions/setup-python@v5.6.0` → `a26af69be951a213d495a4c3e4e4022e16d87065`
  (coincide).
- **Lockfiles**: sin `--index-url`/`--extra-index-url`/`--find-links`,
  con 850/2596/199 hashes sha256, incluyen `fastapi`/`uvicorn` y
  excluyen `pytest`/`ruff` (B-M3 bien hecho). `auto/build` los copia al
  includes.chroot, y el Broker instala deps hasheadas y luego su propio
  paquete con `--no-deps` (correcto para `-e`).
- **Hook 0490**: probé el `sed` con el texto real del vendorizado
  (`minLength: 6  # …`) → produce `minLength: 12  # …` y el `grep` de
  verificación pasa; si el formato cambia, aborta el build (fail-closed).
- **B-M2**: `cp -a` en el sembrado y en el retorno del caché de modelos;
  ya no hay inodos compartidos host↔chroot.
- **Mis propios fixes (I-1, I-4, I-5, I-6, I-8, I-9, I-10)** siguen en
  pie; no encontré bypass de `_reject_unsafe_bundle_entries` (un TOCTOU
  sobre el contenido del USB no escala porque las dos copias conservan
  symlinks en vez de seguirlos).

---

## 4. Prioridad sugerida

1. **R-1** (conectar la aprobación del usuario con la unidad generada) y
   corregir la afirmación de `docs/AGENT_INTERFACE.md:595`.
2. **R-2** (K-1…K-6) — es el grupo más grave y el único sin tocar;
   requiere parche en los repos `kal`/`kal-in`.
3. **R-3** (fixtures OCI + test que parsee todos los fixtures).
4. **R-4** (subir el hash a ≥64 bits) y **R-5**/**R-6** (pip y tarball
   de Ollama).
5. **R-7**/**R-8**: reprobar en QEMU/hardware antes de dar I-7/B-M1 por
   cerrados.
