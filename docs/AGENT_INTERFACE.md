# Interfaz de agentes de Likay-OS — v1

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

## 0. Arquitectura: tres capas separadas

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
son dos capas distintas a propósito ("Policy ≠ Sandbox"). En v1, el
Sandbox (unidades systemd generadas en el momento de instalar) es el
único backstop real — ver sección 4 y las invariantes de seguridad.

## Invariantes de seguridad (no negociables en v1)

1. `kiosk` nunca se convierte en root, bajo ningún flujo.
2. El código de un agente nunca es confiable — el límite lo impone el
   sistema desde afuera, nunca el propio agente.
3. El manifiesto es datos, nunca política ejecutable — parsearlo no
   ejecuta nada, ninguno de sus campos se interpola en un shell.
4. El ALLOW del Broker no es enforcement de sistema operativo en v1 —
   es una API de cortesía; el sandbox de systemd es el backstop real.
5. Solo la identidad dedicada `likay-agent-install` puede mutar la
   política del Broker (`register_policy`) — nunca un agente, nunca
   root genérico, nunca algo derivado de un campo JSON.
6. `register_policy` se autoriza por **credencial Unix del peer del
   socket** (`SO_PEERCRED`), nunca por un `agent_id` que venga en el
   cuerpo de la solicitud.
7. El helper de instalación no expone ninguna primitiva de ejecución
   arbitraria como root (nada de `exec(cmd)`/`run_as_root(cmd)`) — su
   API son operaciones nombradas, fijas, de propósito único.
8. Todo agente instalado corre bajo su propia identidad Unix dedicada.
9. Todo agente instalado recibe un sandbox de systemd generado
   externamente — nunca uno que el propio agente pueda declarar o
   ampliar.
10. v1 nunca otorga `filesystem: full` — solo `{restricted, none}`.
11. `network: host-egress` es acceso normal a la red del host, **no**
    una ACL de destino — no confundir con "solo salientes controladas
    hacia ciertos dominios".
12. Agente #0 (el instalador de Calamares, ver sección 7) queda
    intacto — sin cambios de código, solo documentado como precedente.
13. Instalar un agente equivale a ejecutar software de terceros
    (`pip install` incluido) dentro del sandbox — se trata como cadena
    de suministro no confiable, nunca como "solo configuración".

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
TUI de instalación (ver sección 5), una sola vez.

| Grupo | Capacidades |
|---|---|
| Disco/sistema (solo clase instalador, ver Agente #0) | `disk.read`, `disk.write`, `partition.manage`, `bootloader.install` |
| Filesystem | `filesystem.data_dir` (su propio directorio, RW), `filesystem.read_external` (futuro — deny-by-default, no implementado en v1) |
| Red | `network.egress` (v1 solo distingue ninguna/con acceso — ver sección 4) |
| Cómputo/modelo | `llm.local` (Ollama/`qwen2.5:3b` propio de Likay-OS), `gpu.compute` |
| Periféricos | `audio.microphone`, `audio.speaker`, `camera`, `clipboard` |
| Ejecución | `docker.sandbox` |

Basada en `permissions.trust_tier_caps` que ya existe en
`vendor/kal-in/config/config.yaml`, extendida con las 4 capacidades
específicas del instalador.

## 3. Lifecycle

Solo aplica a agentes de tipo servicio (kal-in, futuros agentes de
terceros) — Agente #0 no tiene sección `lifecycle`, no es un servicio
de larga duración.

```yaml
lifecycle:
  runtime: python-venv                 # futuro: docker | binary
  entry_point: "agent_core.orchestrator:app"
  command: "uvicorn"
  requirements_file: requirements.txt  # UN solo archivo -- ver abajo
  port: 8000
  health_check_path: /
  env:
    AGENT_ENV: production
```

**`requirements_file` es singular, no una lista.** Un solo archivo,
obligatoriamente dentro de `src/` en el propio bundle — el helper de
instalación rechaza rutas absolutas, `..`, o symlinks que escapen del
bundle. No se acepta `requirements-dev.txt` ni archivos equivalentes:
esos tienen sentido para el desarrollo de un agente dentro de su
propio repo, no para lo que se declara para correr en un sistema ya
instalado. `pip install -r` sigue siendo, en sí misma, una operación
de cadena de suministro (invariante 13) — v1 la acepta pero la trata
como ejecutar código no confiable, nunca como "solo configuración".

**`bind_host` NO es un campo de este manifiesto, a propósito.** Se
consideró incluirlo (`bind_host: 127.0.0.1`) pero un agente podría
declarar `0.0.0.0` y depender de que el generador lo "corrija" — la
política de seguridad debe ganar por construcción, no por convención
del autor del manifiesto. El `ExecStart=` generado siempre fuerza
`--host 127.0.0.1`, sin excepción, sin que el manifiesto tenga ninguna
autoridad sobre ese valor.

## 4. Sandbox

```yaml
sandbox:
  filesystem: restricted   # {restricted, none} -- "full" no es legal en v1
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
secas sugeriría una ACL de destino que v1 no tiene — una allowlist
real de dominios necesitaría eBPF (hay un prototipo sin usar en
`vendor/kal/kernel/lifecycle/ebpf/`) o un proxy por agente, ninguno de
los dos en v1.

**Mapeo campo del manifiesto → directivas systemd concretas:**

| Campo | Directivas |
|---|---|
| `filesystem: restricted` | `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `ReadWritePaths=/mnt/likay-agent/<id>/data` |
| `filesystem: none` | igual, sin `ReadWritePaths` |
| `network: none` | `PrivateNetwork=yes` (AF_UNIX sigue funcionando — el socket del Broker sigue alcanzable) |
| `network: host-egress` | sin `PrivateNetwork`; loopback-only forzado por construcción en el `ExecStart=` generado, nunca por el manifiesto |
| `devices: none` | `PrivateDevices=yes` |
| `devices: explicit` | `PrivateDevices=no`, `DevicePolicy=closed`, `DeviceAllow=<lista>` |
| siempre, todo agente | `NoNewPrivileges=yes`, `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `RestrictSUIDSGID=yes`, `LockPersonality=yes`, `SystemCallFilter=@system-service`, `MemoryMax=`/`CPUQuota=`/`TasksMax=` del manifiesto |

## 5. IPC (Broker)

El Broker (`broker/`, `likay-agent-broker.service`) expone
`/run/likay-agent-broker/broker.sock` (directorio creado por systemd
vía `RuntimeDirectory=`, con el dueño correcto — el Broker corre como
un usuario Linux dedicado sin privilegios, `likay-broker`, nunca como
root) — JSONL sobre `AF_UNIX`, mismo formato
de trama que `vendor/kal/kernel/api/socket_server.py`.

Dos métodos, con fronteras de autorización **distintas**, decididas
por credencial Unix del socket (`SO_PEERCRED`), nunca por un campo
dentro del JSON:

- **`check_capability(capability)`** — cualquier agente puede
  llamarlo, pero el Broker resuelve la identidad de quien pregunta vía
  `SO_PEERCRED` → UID → usuario Linux dedicado de ese agente. Un
  agente solo puede consultar sus propias capacidades otorgadas, nunca
  las de otro proceso.
- **`register_policy(agent_id, capabilities)`** — el Broker acepta
  esta llamada ÚNICAMENTE si `SO_PEERCRED` del peer resuelve a la UID
  del usuario estático `likay-agent-install` (hardcodeado en el
  Broker). Ningún agente instalado puede llamarlo con éxito, sea cual
  sea su UID.

En v1, la política es "lo que un humano aprobó una vez, en el momento
de instalar, en el TUI" — sin flujo de escalación en runtime. Nada
OBLIGA a un agente a consultar este socket antes de actuar: el
backstop real es el sandbox de systemd (sección 4), no la consulta al
Broker. El `check_capability` es hoy una API de cortesía (útil p.ej.
para cuotas de `llm.local`), no una pared.

## 6. Auditoría

```yaml
audit:
  event_prefix: agent_kal-in
```

Toda decisión del Broker (ALLOW o DENY, para cualquiera de los dos
métodos) se loguea siempre, sin excepción, a
`/var/log/likay-agent-broker/audit.log` (JSONL: `timestamp, agent_id,
method, decision`).

## 7. Agente #0 — el instalador, como ejemplo ya resuelto

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
schema_version: 1
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
hardware real, queda intacto.

## 8. Ejemplo completo: kal-in

```yaml
schema_version: 1

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

lifecycle:
  runtime: python-venv
  entry_point: "agent_core.orchestrator:app"
  command: "uvicorn"
  requirements_file: requirements.txt
  port: 8000
  health_check_path: /
  env:
    AGENT_ENV: production

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

## 9. Fuera de alcance de v1 (deliberado, no un olvido)

- Mediación real de kernel vía import de `vendor/kal` como librería —
  `AccessManager`/`socket_server.py` de `kal` quedan intactos, scoped
  a skills.
- Migrar kal-in para depender de `vendor/kal` (deuda técnica
  preexistente de kal-in, deliberadamente desacoplada de este diseño).
- Renegociación/escalación de capacidades en runtime en el Broker.
- ACLs de red finas — solo el split binario `none`/`host-egress`.
- Múltiples agentes activos simultáneamente (un solo kiosco, una sola
  partición `likay-agent`, un solo puerto orientado al kiosco).
- Transporte remoto/autenticado del bundle de instalación — v1 usa
  solo un USB local, explícitamente no confiable como frontera de
  seguridad (la seguridad viene de la validación del manifiesto + la
  aprobación explícita de capacidades + el sandbox, nunca del
  transporte). El formato del bundle se versiona (`schema_version`)
  para poder sumar transportes autenticados más adelante sin romper
  v1.
