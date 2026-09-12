# Roadmap de Likay-OS

Este documento recoge el plan acordado durante el diseño inicial del proyecto
(entonces llamado "Kal OS"). Cada etapa suma sobre la anterior — no se
avanza a la siguiente hasta validar la actual en hardware real.

## Principio que ata todo el roadmap

Nada de esto es una arquitectura nueva por etapa — es el **mismo motor de
seguridad que kal ya tiene y ya probó** (Access Manager: permisos
explícitos, sandbox, auditoría con cadena verificable) ganando más
"adaptadores" (tipos de recurso a mediar) y más "inquilinos" (kal mismo,
o un agente de terceros migrado por el usuario). El criterio no cambia
entre etapas: **nunca confiar en el código interno de un agente — solo en
el límite que el sistema le impone desde afuera.** Eso ya es cierto hoy
para las Skills de terceros en kal, y sigue siendo cierto para un agente
completo alojado en Likay-OS.

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
real de la máquina — kal (backend + Ollama) arriba, interfaz en modo
kiosk (pantalla completa, sin escritorio ni barra de tareas alrededor).

- **Base:** Debian/Ubuntu mínimo — a propósito, no Alpine. El stack de
  kal (PyTorch/diffusers en particular) ya está probado sobre esa
  familia; Alpine usa musl en vez de glibc y suele dar problemas reales
  de compatibilidad con ese stack.
- **Fortaleza de seguridad:** cero riesgo de por sí — completamente
  reversible (sacar el USB devuelve la máquina a su estado original),
  base mínima reduce superficie (menos paquetes instalados, menos CVEs
  potenciales) frente a un escritorio completo.
- **A vigilar:** kal y Ollama arrancan como servicios de red desde el
  boot mismo, sin que el usuario los "abra" a mano — hay que confirmar
  que el binding a loopback (127.0.0.1) y el token administrativo que
  kal ya tiene se preserven exactos en este contexto nuevo, nunca
  asumir que se heredan solos.

## Etapa 2 — Instalador real para dual-boot

**Entrega:** instalación persistente, conviviendo con el Windows/Linux
que el usuario ya tenga en la máquina.

- **Riesgo nuevo, el más serio de todo el roadmap:** es la primera vez
  que se escribe sobre el disco real — una partición mal hecha o un
  bootloader mal configurado puede inutilizar el sistema operativo
  existente del usuario. No es un riesgo teórico, es pérdida de datos
  real si se hace mal.
- **Mitigación:** backup completo obligatorio antes de tocar nada; usar
  un instalador ya probado en el mundo real (p.ej. Calamares) en vez de
  escribir uno propio desde cero; modo de simulación (dry-run) antes de
  escribir de verdad.
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
  mitigado en kal para `pip install`).
- **Mitigación:** fuentes confiables por defecto (repositorios oficiales
  de Debian/Ubuntu, Flathub verificado), deny-by-default para cualquier
  otra fuente — mismo criterio que ya usa kal para dominios permitidos
  en su herramienta de navegación/descarga.
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
  gran mayoría ya se resuelve con lo que kal tiene hoy — herramientas
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

Ninguna etapa está implementada todavía — este documento es el plan
acordado antes de escribir la primera línea de código de Likay-OS.
