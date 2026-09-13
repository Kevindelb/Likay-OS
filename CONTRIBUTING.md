# Contribuir a Likay-OS

Gracias por el interés. Esto es joven — Etapa 1 del [roadmap](docs/ROADMAP.md)
recién arranca de punta a punta en VM — así que la forma más útil de
ayudar hoy es probando en hardware real, revisando el análisis de
seguridad de cada etapa, y picando de a partes chicas y verificables.

## Antes de nada: la regla de seguridad que no se negocia

> Nunca confiar en el código interno de un agente — solo en el límite
> que el sistema le impone desde afuera.

Esto no es un lema — es el criterio con el que se evalúa cada cambio.
Si tu contribución toca cómo Likay-OS media el acceso de un agente a
filesystem, red, o cualquier otro recurso, el PR tiene que explicar qué
superficie nueva introduce y qué la mitiga (mismo formato que ya usa
`docs/ROADMAP.md` para cada etapa).

## Setup

```bash
git clone --recurse-submodules https://github.com/Kevindelb/Likay-OS.git
cd Likay-OS
```

Si ya clonaste sin `--recurse-submodules`:

```bash
git submodule update --init
```

`vendor/kal` es un submódulo — apunta a un commit específico de
[kal](https://github.com/carlosbv99-bit/kal), no a su rama principal.
Actualizarlo a un commit más nuevo es un cambio deliberado (ver `git
log -- vendor/kal` para el criterio: qué trae cada bump y por qué),
no algo que se haga de paso en un PR que no es sobre eso.

Para trabajar en la ISO live-boot específicamente, ver
[`iso/README.md`](iso/README.md) — tiene los requisitos, cómo buildear,
y cómo probar en QEMU.

## Estructura del repo

```
docs/ROADMAP.md    # las etapas del proyecto, en orden, con el análisis de seguridad de cada una
iso/                 # build de la ISO live-boot de Etapa 1 (live-build + hooks propios)
vendor/kal/            # submódulo — el kernel agéntico que Likay-OS empaqueta
```

## Cómo trabajar

- **Cambios chicos y verificables** en vez de PRs enormes. Si tocás el
  build de la ISO, probalo de verdad en QEMU antes de abrir el PR — no
  alcanza con que `lb build` termine sin error (varios bugs reales de
  esta versión de live-build hacen que el build "termine bien" con un
  `.iso` que no arranca; ver la sección "Cosas raras" en
  [`iso/README.md`](iso/README.md)).
- **Comentarios que expliquen el PORQUÉ, no el qué.** El código ya dice
  qué hace. Un comentario vale la pena cuando documenta una restricción
  no obvia, un bug de una herramienta de terceros, o por qué la
  alternativa "obvia" no funciona — el estilo que ya vas a ver en todo
  `iso/`.
- **Root cause, no parche encima.** Si algo falla, preferimos entender
  por qué antes de agregar un workaround. Cuando el workaround es
  inevitable (bug real de una herramienta de terceros que no vamos a
  parchear nosotros), documentarlo como tal.
- Los mensajes de commit de este repo están en español — seguí esa
  convención salvo que tengas una buena razón para no hacerlo.

## Reportar bugs / proponer cambios

Abrí un issue. Para bugs del build de la ISO, incluí:

- El comando exacto que corriste (`auto/build`, la línea de QEMU).
- El log relevante — `iso/build.log` para errores de build, o lo que
  se vea en la consola serie de QEMU para algo que falla ya arrancado.
- Si el problema es específico de una versión de Ubuntu/live-build,
  decilo — esta ISO depende bastante de particularidades de la versión
  actual (`3.0~a57-1ubuntu54` sobre Ubuntu 26.04).

## Licencia

Apache License 2.0 (ver [`LICENSE`](LICENSE)) — la misma que usa kal.
Al contribuir, aceptás que tu contribución se licencie bajo los mismos
términos (Sección 5 de la licencia).
