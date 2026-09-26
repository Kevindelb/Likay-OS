# Roadmap de Likay-OS

Este documento recoge el plan acordado durante el diseño inicial del proyecto
(entonces llamado "Kal OS"). Cada etapa suma sobre la anterior — no se
avanza a la siguiente hasta validar la actual en hardware real.

## Principio que ata todo el roadmap

Nada de esto es una arquitectura nueva por etapa — es el **mismo motor de
seguridad que kal ya tiene y ya probó** (Access Manager: permisos
explícitos, sandbox, auditoría con cadena verificable) ganando más
"adaptadores" (tipos de recurso a mediar) y más "inquilinos" (kal-in, el
agente de referencia, o un agente de terceros que el usuario ya use hoy
en el mercado). El criterio no cambia entre etapas: **nunca confiar en
el código interno de un agente — solo en el límite que el sistema le
impone desde afuera.** Eso ya es cierto hoy para las Skills de terceros
en kal, y sigue siendo cierto para un agente completo alojado en
Likay-OS — **incluso cuando el límite de seguridad choca con lo que ese
agente "quiere" hacer.** Ante ese conflicto, gana siempre la seguridad,
nunca la funcionalidad del agente montado — el usuario puede perder una
capacidad puntual de un agente mal comportado; no puede perder la
garantía de que el sistema le impuso un límite real.

Desde septiembre de 2026, kal dejó de ser un solo repositorio híbrido:
se separó en **kal** (el microkernel de seguridad puro — Access
Manager, sandbox, audit log, registry, ResourceBroker, SDK; sin agente,
sin LLM, sin ML — [github.com/carlosbv99-bit/kal](https://github.com/carlosbv99-bit/kal))
y **kal-in** (el antiguo kal, renombrado — el agente de referencia que
corre sobre ese kernel). Likay-OS monta siempre el kernel `kal`; el
agente que corre arriba es intercambiable — kal-in es la opción por
default y mejor probada, no una dependencia obligatoria. Cualquier
agente de terceros que exponga lo que el Access Manager necesita para
mediarlo (permisos explícitos, sin acceso directo sin pasar por el
kernel) tiene que poder montarse igual.

**Ningún agente se hornea dentro de la imagen de Likay-OS.** Likay-OS
se instala solo sobre `kal` — kernel más la capa propia de Likay (LLM
chico, kiosco/anfitrión). El agente (kal-in u otro) es algo que el
usuario monta *después*, con Likay-OS ya instalado y corriendo, en su
propia partición del disco — igual que instalar una aplicación sobre
un sistema operativo ya instalado, no algo que viene precargado de
fábrica. Esto es, por definición, trabajo de persistencia en disco real
(ver Etapa 2 más abajo) — no existe todavía en Etapa 1 (live-boot puro,
sin tocar el disco). El `kal-in` horneado en la ISO actual de Etapa 1
es un prototipo de validación temporal del pipeline de boot, no el
diseño final de cómo se monta un agente.

## Decisión de fondo: por qué no un kernel desde cero (todavía)

Un sistema operativo propio de verdad independiente (bootloader, kernel,
drivers, todo desde cero) es de los proyectos de ingeniería más grandes
que existen — y, contraintuitivamente, **un kernel nuevo arranca con
MENOS garantías de seguridad que Linux, no más**: Linux lleva 30+ años
con miles de investigadores auditándolo, con primitivas maduras
(namespaces, seccomp, cgroups, LSM/eBPF) que kal ya usa hoy como columna
vertebral de su seguridad real. Escribir un kernel propio significaría
tirar esa base madura y empezar de cero con código sin escrutinio.

La visión de un kernel propio e independiente queda como objetivo a
**largo plazo**, a perseguir con la colaboración de una comunidad — no
como punto de partida.

---

## Etapa 1 — ISO live-boot

**Entrega:** Likay-OS arranca directo desde un USB, sin tocar el disco
real de la máquina — el kernel `kal` montado, un LLM propio y chico
(`qwen2.5:3b`) siempre cargado para clasificación de intención y para
orientar al usuario apenas arranca, y un kiosco propio — pantalla
completa, sin escritorio ni barra de tareas alrededor, pensado para dar
una experiencia empática y funcional al usuario, no un panel de chat de
desarrollador. La ISO en sí no trae ningún agente horneado — eso es
trabajo de Etapa 2 (ver más abajo). Para validar el pipeline de boot de
punta a punta, esta etapa incluye `kal-in` horneado a mano como
prototipo temporal (no el diseño final de cómo se monta un agente).

- **Base:** Debian/Ubuntu mínimo — a propósito, no Alpine. El stack de
  kal-in (PyTorch/diffusers en particular) ya está probado sobre esa
  familia; Alpine usa musl en vez de glibc y suele dar problemas reales
  de compatibilidad con ese stack.
- **Fortaleza de seguridad:** cero riesgo de por sí — completamente
  reversible (sacar el USB devuelve la máquina a su estado original),
  base mínima reduce superficie (menos paquetes instalados, menos CVEs
  potenciales) frente a un escritorio completo.
- **El LLM propio de Likay-OS, separado del LLM del agente montado:**
  `qwen2.5:3b` es chico a propósito (clasificar intención y guiar al
  usuario en el arranque no necesita un modelo grande) y es parte del
  *sistema operativo*, no del agente — se hornea en la ISO igual que
  cualquier otro servicio de Likay-OS. Cuando el trabajo real lo pide,
  Likay-OS usa el LLM que el agente montado tenga configurado (el
  propio, o uno en la nube) — nunca fuerza a un agente de terceros a
  pasar por `qwen2.5:3b` para su propio trabajo, ese modelo es
  exclusivamente la capa de Likay-OS.
- **Kernel siempre presente, agente intercambiable:** el Access Manager
  media los recursos del agente que esté montado — sea kal-in o un
  agente de terceros — de la misma forma. Ningún agente monta el
  sistema sin pasar por ese límite; eso es lo único no negociable de
  esta etapa (ver el principio de arriba). El montaje real del agente
  (instalado por el usuario en su propia partición) es trabajo de
  Etapa 2 — acá el requisito es que el kernel esté listo para mediarlo
  cuando exista.
- **A vigilar:** el kernel, el LLM propio, y el agente montado arrancan
  como servicios de red desde el boot mismo, sin que el usuario los
  "abra" a mano — hay que confirmar que el binding a loopback
  (127.0.0.1) y cualquier token administrativo se preserven exactos en
  este contexto nuevo, nunca asumir que se heredan solos. Esto ya se
  verificó para kal-in corriendo solo; falta re-verificar una vez que
  haya más de un servicio de red conviviendo (LLM propio + agente).

## Etapa 2 — Instalador real para dual-boot

**Entrega:** instalación persistente, conviviendo con el Windows/Linux
que el usuario ya tenga en la máquina. Likay-OS se instala solo sobre
`kal` (kernel + capa propia) — sin ningún agente incluido. Recién acá
el usuario monta el agente que quiera (kal-in u otro) en su propia
partición, con Likay-OS ya instalado y corriendo — no algo horneado de
fábrica, igual que instalar una aplicación sobre un sistema operativo
que ya está instalado.

- **Riesgo nuevo, el más serio de todo el roadmap:** es la primera vez
  que se escribe sobre el disco real — una partición mal hecha o un
  bootloader mal configurado puede inutilizar el sistema operativo
  existente del usuario. No es un riesgo teórico, es pérdida de datos
  real si se hace mal.
- **Mitigación:** backup completo obligatorio antes de tocar nada; usar
  un instalador ya probado en el mundo real (p.ej. Calamares) en vez de
  escribir uno propio desde cero; modo de simulación (dry-run) antes de
  escribir de verdad. El Access Manager media el acceso del agente
  recién instalado a esa partición y al resto del sistema desde el
  primer momento — mismo criterio de "nunca confiar en el código interno
  del agente" del principio de arriba, ahora con disco persistente de
  por medio.
- **Fortalezas a sumar en esta etapa, no antes** (recién tienen sentido
  con una instalación persistente):
  - **Secure Boot + arranque medido (TPM)** — protege contra
    manipulación del proceso de arranque con acceso físico a la máquina
    (ataque "evil maid").
  - **Cifrado completo del disco (LUKS)** — Likay-OS va a guardar
    memoria de largo plazo del agente, tokens administrativos,
    credenciales de API en la nube. Sin cifrado, cualquiera con acceso
    físico a una máquina robada o perdida tiene acceso a todo eso. Dado
    que la seguridad es la prioridad declarada del proyecto, esto no es
    opcional en esta etapa.

## Etapa 3 — Filesystem raíz de solo lectura

**Entrega:** endurecimiento estilo Chrome OS / Talos Linux — el sistema
base no se puede modificar en caliente, solo se actualiza de forma
atómica.

- **Fortaleza:** un compromiso del sistema no puede persistir cambios a
  los binarios del sistema — cualquier alteración se pierde en la
  próxima actualización atómica (o reinicio, según el diseño exacto).
- **Riesgo nuevo:** el propio mecanismo de actualización pasa a ser el
  componente de mayor confianza de todo el sistema — si se compromete
  el servidor de actualizaciones o la clave de firma, ese es el nuevo
  blanco de mayor valor para un atacante.
- **Mitigación:** reusar directamente el mecanismo de firma criptográfica
  que kal ya tiene para verificar la integridad de herramientas — no
  hay que diseñar un esquema de firma nuevo desde cero.

## Etapa 4 — Instalación de aplicaciones como tercer adaptador del Access Manager

**Entrega:** cualquier agente (Likay-OS mismo, o un agente de terceros
que el usuario migró) puede pedir instalar una aplicación real —
DaVinci Resolve, GIMP, Office, lo que haga falta según a qué se dedique
el usuario — mediado por el mismo motor que hoy media filesystem y red.

- **Por qué es alcanzable sin inventar nada nuevo:** al ser Linux por
  dentro, Likay-OS ya hereda casi toda la superficie de software que
  tiene Windows o Linux hoy (apt, Flatpak con su propio sandboxing vía
  Bubblewrap, AppImage, y Wine o una VM de Windows para lo que
  genuinamente no tenga versión Linux). No hace falta curar una lista
  de apps soportadas.
- **Riesgo nuevo:** typosquatting de paquetes — un nombre de paquete
  parecido a uno real pero malicioso (mismo patrón de ataque ya visto y
  mitigado en kal-in para `pip install`).
- **Mitigación:** fuentes confiables por defecto (repositorios oficiales
  de Debian/Ubuntu, Flathub verificado), deny-by-default para cualquier
  otra fuente — mismo criterio que ya usa kal-in para dominios
  permitidos en su herramienta de navegación/descarga.
- **Decisión de diseño explícita:** instalar software con privilegios de
  sistema es una acción más poderosa que escribir un archivo dentro de
  un workspace — nunca debería auto-permitirse por defecto (a
  diferencia de `filesystem_write` dentro del workspace, que sí lo hace
  hoy en kal). Siempre aprobación humana explícita, mismo nivel de
  exigencia que una modificación de un módulo núcleo.

## Etapa 5 — Sesión de GUI aislada para agentes de "computer use"

**Entrega:** trabajos de diseño gráfico/edición de video (DaVinci
Resolve, GIMP, Photoshop vía VM de Windows) manejados por un agente de
terceros con capacidad real de "computer use" (ver una pantalla,
controlar mouse/teclado), dentro de un entorno gráfico aislado que
Likay-OS gestiona.

- **Por qué hace falta esta etapa y no antes:** de las categorías de uso
  reales (programación, administración de empresa, diseño/video), la
  gran mayoría ya se resuelve con lo que kal-in tiene hoy — herramientas
  CLI/API para programación, la herramienta de navegación web ya
  construida para SaaS/Office 365/etc. Solo el diseño/video con apps de
  escritorio puras, sin equivalente API o web razonable, necesita esta
  pieza nueva.
- **Riesgo nuevo, el de mayor superficie de todo el roadmap:** una
  sesión de GUI completa (compositor gráfico, portapapeles, toolkit de
  la aplicación) es mucho más compleja de contener que un sandbox de
  código headless, que no tiene ninguna de esas superficies.
- **Mitigación:** mismo principio de contención que ya usa el sandbox de
  código de kal — sin acceso a red por defecto, sin ver el disco real
  fuera de una carpeta de trabajo explícitamente concedida, límites de
  RAM/CPU vía el mismo ResourceBroker que ya existe, y las
  credenciales/token administrativo de Likay-OS **nunca** llegan a esa
  sesión (mismo patrón ya verificado hoy en kal para variables de
  entorno sensibles dentro del sandbox).
- **Riesgo de privacidad a nombrar explícitamente:** la inteligencia de
  "computer use" probablemente dependa de una API en la nube de un
  tercero — eso implica que capturas de pantalla de esa sesión salen de
  la máquina del usuario. Debe ser una función explícitamente opt-in, y
  acotada SOLO a la sesión aislada — nunca a la pantalla física
  completa, de forma que el resto del trabajo del usuario siga siendo
  privado aunque esta función esté activa.

---

## Estado actual

Etapa 1, parcial: el pipeline de arranque en sí (BIOS → casper →
systemd → un backend en 127.0.0.1 → kiosco Wayland en pantalla
completa) ya está probado de punta a punta en QEMU y en hardware real
(ver [`iso/README.md`](../iso/README.md)), con `qwen2.5:3b` horneado
como LLM propio de Likay-OS y `kal-in` horneado a mano como prototipo
de validación (no el diseño final — ver el principio de arriba).
Todavía falta diseñar el kiosco nuevo.

**Decisión de diseño 2026-09-14:** ningún agente se hornea en la ISO de
Likay-OS. El usuario monta su propio agente (kal-in u otro) en su
propia partición del disco, con Likay-OS ya instalado y corriendo —
eso es trabajo de Etapa 2 (instalador real), no de Etapa 1. La
interfaz genérica para montar cualquier agente (issue
[#2](https://github.com/Kevindelb/Likay-OS/issues/2), Fase 2) se
diseña junto con esa etapa, no antes.

**Etapa 2, en progreso — la interfaz genérica (Agent Broker) ya está
implementada y validada en hardware real** (ver
[`docs/AGENT_INTERFACE.md`](AGENT_INTERFACE.md)): instalación de un
agente de terceros que nunca se horneó en la imagen (transporte USB,
manifiesto validado, sandbox systemd/Quadlet OCI generado por agente),
y el fixture `malicious-agent` (7 intentos de escape, los 7 DENIED)
corrido contra ese sandbox en una laptop real, no solo en QEMU. Lo que
sigue abierto de Etapa 2, sin cerrar todavía: Secure Boot/TPM y LUKS
(explícitamente pospuestos a esta etapa, ver más abajo, no
implementados aún), y una auditoría de seguridad propia (2026-09-26,
ver `docs/AUDITORIA-SEGURIDAD.md`/`docs/REAUDITORIA-SEGURIDAD.md`) que
encontró y cerró varios hallazgos reales sobre el Broker/instalador —
tratarla como el estado de referencia actual, no esta sección, para el
detalle hallazgo por hallazgo.
