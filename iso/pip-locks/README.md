# pip-locks/

Lockfiles con hash (`--generate-hashes`) para las dependencias de
terceros de `vendor/kal` y `vendor/kal-in` que el build hornea vía
`0300-install-kal.chroot`/`0320-install-kal-in.chroot` (ver B-A2,
auditoría de seguridad 2026-09-26). `auto/build` los copia a
`config/includes.chroot/opt/{kal,kal-in}/` en cada corrida; los hooks
instalan con `pip install --require-hashes`, que rechaza cualquier
paquete cuyo hash no matchee.

Generados a partir de **SOLO** `requirements-core.txt` de cada
submódulo — nunca `requirements-dev.txt` (pytest/ruff no hacen falta en
el sistema instalado, ver B-M3) ni `requirements-multimodal.txt` (stack
de ML pesado, fuera de alcance de Etapa 1, ver docs/ROADMAP.md).

No se regeneran automáticamente en cada build — son lockfiles, el punto
es que el build sea reproducible hasta que alguien decida
deliberadamente actualizarlos (mismo criterio que cualquier lockfile
común: `package-lock.json`, `Cargo.lock`, etc.).

## Regenerar (cuando `vendor/kal`/`vendor/kal-in` cambian sus requirements)

```sh
# Desde la raíz del repo, con `uv` instalado (https://docs.astral.sh/uv/):
uv pip compile vendor/kal/requirements-core.txt \
    --generate-hashes --python-version 3.11 \
    -o iso/pip-locks/kal.lock.txt

uv pip compile vendor/kal-in/requirements-core.txt \
    --generate-hashes --python-version 3.11 \
    -o iso/pip-locks/kal-in.lock.txt
```

Después de regenerar, verificar que el resultado instala limpio antes
de commitear (no hace falta root ni un venv real del proyecto):

```sh
python3 -m venv /tmp/lock-verify
/tmp/lock-verify/bin/pip install --upgrade pip -q
/tmp/lock-verify/bin/pip install --require-hashes --dry-run -r iso/pip-locks/kal.lock.txt
/tmp/lock-verify/bin/pip install --require-hashes --dry-run -r iso/pip-locks/kal-in.lock.txt
rm -rf /tmp/lock-verify
```

`broker/requirements-broker.lock.txt` (mismo mecanismo, generado desde
`broker/pyproject.toml`) vive junto al propio Broker, no acá, porque el
Broker es primera parte de este repo, no un submódulo vendorizado.
