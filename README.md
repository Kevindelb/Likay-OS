# Likay-OS

*(anteriormente "Kal OS" durante la etapa de diseño)*

**ES:** Likay-OS es un sistema operativo para agentes de IA — pensado para arrancar de forma independiente (sin depender de Windows o Linux como anfitrión visible), con la seguridad como prioridad absoluta en cada decisión de diseño. No es un kernel escrito desde cero: reusa la madurez de Linux (30+ años de escrutinio de seguridad) y todo el kernel de seguridad ya construido en el proyecto [kal](https://github.com/carlosbv99-bit/kal) — Access Manager, sandboxing, log de auditoría con cadena verificable, ResourceBroker — para dar, de cara al usuario, la experiencia de un sistema operativo propio dedicado a trabajar con agentes.

**EN:** Likay-OS is an operating system for AI agents — designed to boot independently (without a visible Windows/Linux host), with security as the top priority in every design decision. It is not a from-scratch kernel: it reuses Linux's maturity (30+ years of security scrutiny) and the entire security kernel already built in the [kal](https://github.com/carlosbv99-bit/kal) project — Access Manager, sandboxing, tamper-evident audit log, ResourceBroker — to give the user, on the surface, the experience of a dedicated operating system built around working with agents.

## Por qué existe (resumen)

Kal, el proyecto del que parte esto, **no es un agente de IA — es un kernel agéntico**: la infraestructura de seguridad (permisos explícitos de filesystem/red, sandboxing con Docker, auditoría verificable, protección activa contra presión de RAM) sobre la que hoy corre un agente de referencia, que orquesta modelos de IA (locales vía Ollama, o en la nube) para resolver tareas. Corre hoy como una aplicación sobre Windows/Linux. Likay-OS lleva esa misma base de seguridad un paso más allá: en vez de ser una app que el usuario abre, es el sistema que arranca directo y ya está listo para trabajar.

La visión de esta nueva etapa — todavía por construir, no algo ya probado hoy — es que Likay-OS pueda administrar, además de modelos de IA, agentes de terceros que el usuario ya use en su trabajo, bajo el mismo principio de seguridad que kal ya validó: **nunca confiar en el código interno de un agente — solo en el límite que el sistema le impone desde afuera.**

Visión a largo plazo (no el plan inmediato): eventualmente, un kernel propio e independiente, construido con la colaboración de una comunidad. El camino hasta ahí pasa primero por aprovechar Linux al máximo — ver `docs/ROADMAP.md`.

## Documentación

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — las etapas del proyecto, en orden, con el análisis de seguridad de cada una (qué superficie nueva introduce, qué la mitiga).

## Relación con kal

Este es un repositorio **separado** — el proyecto kal original sigue su curso propio, sin cambios, en su propio repositorio. Likay-OS es una iniciativa aditiva que construye sobre lo que kal ya validó, no un reemplazo.
