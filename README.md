# Likay-OS

> Un sistema operativo que no le pregunta al agente si puede — se lo
> impone desde afuera.

**[Español](#español) | [English](#english)**

---

## Español

### Qué es

¿Le vas a dar a un agente de IA acceso a tu computadora — tus archivos, tu
red, tu terminal — confiando en que "se porte bien"? Cada vez lo
hacemos más, y cada vez confiamos más en la buena voluntad del código
que corre. Likay-OS parte de la pregunta contraria: ¿y si el sistema
operativo mismo se encargara de que un agente nunca pueda hacer más de
lo que se le permitió, pase lo que pase con su código?

Es un sistema operativo pensado para que un agente de IA viva ahí — no
una app más que corres sobre Windows o Linux, sino el sistema que
arranca directo, listo para trabajar, con la seguridad como la única
prioridad que no se negocia.

Y no es un kernel inventado desde cero — eso sería, de hecho, *menos*
seguro, no más (ver "Por qué existe" abajo). Reusa los 30+ años de
escrutinio de seguridad de Linux y todo el motor de seguridad que
[kal](https://github.com/carlosbv99-bit/kal) ya construyó y probó —
Access Manager, sandboxing, log de auditoría con cadena verificable,
ResourceBroker — para darte, de cara afuera, la experiencia de un
sistema propio dedicado a trabajar con agentes.

### La prueba, no la promesa

Nada de esto vale si no se puede verificar. Así que se construyó, a
propósito, un agente malicioso: uno que al arrancar intenta leer
`/etc/shadow`, escribir en `/etc/`, meterse en dispositivos crudos,
escalar a root, y abrir un puerto privilegiado. Siete formas distintas
de romper las reglas.

Las siete quedaron bloqueadas. **DENIED, las siete** — y no en una VM
optimista: en hardware real, una laptop común. Lo que sostiene esa
garantía no es que el agente "se porte bien" — es el sandbox que
Likay-OS le arma por afuera, sin pedirle permiso. Esa es la regla que
no se negocia en este repo: **el código interno de un agente nunca es
confiable — el límite lo impone el sistema desde afuera, nunca el
propio agente** (ver [`docs/ROADMAP.md`](docs/ROADMAP.md)).

### Estado actual

**Etapa 1** (ISO live-boot, sin persistencia) arranca de punta a punta,
en QEMU y en hardware real, en BIOS y en UEFI: kernel → `qwen2.5:3b`
(modelo propio, horneado en la ISO) → `kal-in` (agente de referencia)
→ kiosco. Detalle completo en
[`iso/README.md`](iso/README.md#estado-actual).

**Etapa 2** (montar cualquier agente sobre un Likay-OS ya instalado, vía
el Agent Broker) también está validada de punta a punta en hardware
real: instalación de un agente externo sin hornear de fábrica, y la
prueba de los siete intentos de escape de arriba. Ver
[`docs/AGENT_INTERFACE.md`](docs/AGENT_INTERFACE.md).

Sin rodeos: es un proyecto joven, en desarrollo activo — pero lo de
arriba tiene hardware real detrás, documentado con fecha y verificable
en `docs/`, no solo una demo optimista. Cuando algo cambia de estado
(un hallazgo nuevo, una regresión, un fix), se documenta ahí mismo con
fecha — la fuente de verdad es esa documentación fechada, no este
resumen.

### Por qué existe

Este proyecto parte de kal, que **no es un agente de IA — es un kernel
agéntico**: la infraestructura de seguridad (permisos explícitos de
filesystem/red, sandboxing con Docker, auditoría verificable,
protección activa contra presión de RAM) que kal ya construyó y probó,
sobre el mismo diseño que valida kal-in, el agente de referencia (hoy
un repo separado — kal-in todavía no importa a `kal` como dependencia
directa, deuda técnica reconocida, ver `docs/ROADMAP.md`), que orquesta
modelos de IA (locales vía Ollama, o en la nube) para resolver tareas.
Corre hoy como una aplicación sobre Windows/Linux. Likay-OS lleva esa
misma base de seguridad un paso más allá: en vez de ser una app que
abres, es el sistema que arranca
directo y ya está listo para trabajar.

La visión de esta etapa es que Likay-OS pueda administrar, además de
sus propios modelos de IA, agentes de terceros que ya uses en tu
trabajo — bajo el mismo principio de seguridad que kal ya validó.

Visión a largo plazo (no el plan inmediato): eventualmente, un kernel
propio e independiente, construido con una comunidad. El camino hasta
ahí pasa primero por sacarle todo el jugo a Linux — ver
[`docs/ROADMAP.md`](docs/ROADMAP.md).

### Documentación

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — las etapas del proyecto, en
  orden, con el análisis de seguridad de cada una (qué superficie
  nueva introduce, qué la mitiga).
- [`docs/AGENT_INTERFACE.md`](docs/AGENT_INTERFACE.md) — el contrato
  entre Likay-OS y cualquier agente que se monte sobre un sistema ya
  instalado (Etapa 2).
- [`docs/AUDITORIA-SEGURIDAD.md`](docs/AUDITORIA-SEGURIDAD.md) /
  [`docs/REAUDITORIA-SEGURIDAD.md`](docs/REAUDITORIA-SEGURIDAD.md) —
  auditorías de seguridad externas del código de primera parte
  (Broker/instalador/build), con estado de remediación de cada
  hallazgo.
- [`iso/README.md`](iso/README.md) — cómo buildear y probar la ISO
  live-boot de Etapa 1.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — cómo contribuir.

### Cómo colaborar

Es un proyecto abierto y todavía joven — hay lugar de verdad para
aportar, y no hace falta ser programador para eso. Sirve código,
sirve revisión de seguridad, sirve probarlo en hardware que aquí no
tenemos, y sirve tanto explicarle esto a la gente como escribir sobre
el tema con criterio.

- Empieza por [`CONTRIBUTING.md`](CONTRIBUTING.md) si quieres
  contribuir al código — tiene el setup, la estructura del repo, y el
  criterio con el que se evalúa cada cambio.
- Abre un [issue](https://github.com/Kevindelb/Likay-OS/issues) para
  proponer algo, reportar un bug, o simplemente decir "quiero ayudar"
  y que te orientemos hacia algo concreto.
- Si quieres escribir o hablar del proyecto, la documentación técnica
  de este repo es la fuente primaria — pensada para ser citable, con
  cada afirmación respaldada por lo que realmente se probó (y dónde:
  QEMU o hardware real, cada vez que la diferencia importa). Ese mismo
  nivel de minuciosidad es el método diario de trabajo: cada cambio se
  revisa y se verifica en coordinación permanente con Claude
  (Anthropic), no solo se documenta después.

### Relación con kal

Este es un repositorio **separado** — el proyecto
[kal](https://github.com/carlosbv99-bit/kal) original sigue su curso
propio, sin cambios, en su propio repositorio. Likay-OS es una
iniciativa aditiva que construye sobre lo que kal ya validó, no un
reemplazo.

### Licencia

[Apache License 2.0](LICENSE).

---

## English

### What it is

Would you give an AI agent access to your computer — your files, your
network, your shell — trusting it to "behave"? We're doing that more
and more, and trusting the good behavior of the code running that
much more too. Likay-OS starts from the opposite question: what if
the operating system itself made sure an agent could never do more
than it was explicitly allowed, no matter what its code tries?

It's an operating system designed for an AI agent to live in — not
another app you run on top of Windows or Linux, but the system that
boots directly, ready to work, with security as the one priority that
never gets negotiated away.

And it's not a from-scratch kernel — that would actually make it
*less* secure, not more (see "Why it exists" below). It reuses
Linux's 30+ years of security scrutiny and the entire security engine
already built and proven by [kal](https://github.com/carlosbv99-bit/kal)
— Access Manager, sandboxing, tamper-evident audit log, ResourceBroker
— to give you, on the surface, the experience of a dedicated operating
system built around working with agents.

### The proof, not the pitch

None of this means anything if it can't be checked. So a deliberately
malicious agent was built on purpose: one that, on startup, tries to
read `/etc/shadow`, write to `/etc/`, get into raw devices, escalate
to root, and open a privileged port. Seven different ways to break the
rules.

All seven got blocked. **DENIED, all seven** — and not in an
optimistic VM: on real hardware, an ordinary laptop. What holds that
guarantee isn't the agent "behaving" — it's the sandbox Likay-OS
builds around it from the outside, without asking its permission.
That's the rule this repo never negotiates on: **an agent's internal
code is never trustworthy — the boundary is enforced by the system
from the outside, never by the agent itself** (see
[`docs/ROADMAP.md`](docs/ROADMAP.md)).

### Current status

**Stage 1** (live-boot ISO, no persistence) boots end to end, in QEMU
and on real hardware, in both BIOS and UEFI: kernel → `qwen2.5:3b`
(Likay-OS's own model, baked into the ISO) → `kal-in` (reference
agent) → kiosk. Full detail in
[`iso/README.md`](iso/README.md#estado-actual).

**Stage 2** (mounting any agent onto an already-installed Likay-OS, via
the Agent Broker) is also validated end to end on real hardware:
installing an external agent that was never baked into the image, and
the seven-escape-attempt test above. See
[`docs/AGENT_INTERFACE.md`](docs/AGENT_INTERFACE.md).

Straight up: this is a young project, under active development — but
the above has real hardware behind it, documented with dates and
verifiable in `docs/`, not just an optimistic demo. When something's
status changes (a new finding, a regression, a fix), it's documented
right there with a date — that dated documentation is the source of
truth, not this summary.

### Why it exists

This project builds on kal, which is **not an AI agent — it's an
agentic kernel**: the security infrastructure (explicit filesystem/
network permissions, Docker sandboxing, verifiable auditing, active
protection against RAM pressure) that kal already built and proved,
under the same design that kal-in, the reference agent, validates
(today a separate repo — kal-in doesn't import `kal` as a direct
dependency yet, acknowledged technical debt, see
`docs/ROADMAP.md`), orchestrating AI models (local via Ollama, or
cloud) to get work done. It runs today as an application on top of
Windows/Linux. Likay-OS takes that same security foundation one step
further:
instead of being an app you open, it's the system that boots directly
and is already ready to work.

The vision for this stage is for Likay-OS to manage, beyond its own AI
models, third-party agents you already rely on in your work — under
the same security principle kal already validated.

Long-term vision (not the immediate plan): eventually, a fully
independent, purpose-built kernel, built with a community. The path
there starts with squeezing everything out of Linux first — see
[`docs/ROADMAP.md`](docs/ROADMAP.md).

### Documentation

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — the project's stages, in
  order, with the security analysis for each one (what new surface it
  introduces, what mitigates it).
- [`docs/AGENT_INTERFACE.md`](docs/AGENT_INTERFACE.md) — the contract
  between Likay-OS and any agent mounted onto an already-installed
  system (Stage 2).
- [`docs/AUDITORIA-SEGURIDAD.md`](docs/AUDITORIA-SEGURIDAD.md) /
  [`docs/REAUDITORIA-SEGURIDAD.md`](docs/REAUDITORIA-SEGURIDAD.md) —
  external security audits of the first-party code
  (Broker/installer/build), with the remediation status of each
  finding.
- [`iso/README.md`](iso/README.md) — how to build and test the Stage 1
  live-boot ISO.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute.

### How to get involved

This is an open, still-young project — there's real room to
contribute, and you don't need to be a programmer for that. Code
helps, security review helps, testing it on hardware we don't have
helps, and so does explaining this to people and writing about it with
real understanding.

- Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) if you want to touch
  the code — it has the setup, the repo structure, and the standard
  every change is judged against.
- Open an [issue](https://github.com/Kevindelb/Likay-OS/issues) to
  propose something, report a bug, or just to say "I want to help" and
  get pointed toward something concrete.
- If you want to write or talk about the project, this repo's
  technical documentation is the primary source — written to be
  citable, with every claim backed by what was actually tested (and
  where: QEMU or real hardware, whenever that difference matters).
  That same level of care is the day-to-day working method: every
  change gets reviewed and verified in ongoing coordination with
  Claude (Anthropic), not just documented after the fact.

### Relationship to kal

This is a **separate** repository — the original
[kal](https://github.com/carlosbv99-bit/kal) project continues on its
own course, unchanged, in its own repository. Likay-OS is an additive
initiative that builds on what kal already validated, not a
replacement for it.

### License

[Apache License 2.0](LICENSE).
