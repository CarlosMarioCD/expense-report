# Tus gates

Un gate es un script en esta carpeta. Corre después de la fase 3 (tests y revisión de seguridad) y antes
de la revisión final. Si sale con `0`, la corrida sigue; si sale con cualquier otro código, la corrida se
detiene, la revisión no corre, y lo que imprimió tu gate es el motivo del PR `[REJECTED]`.

## Las reglas

- Corren todos los archivos de `gates/` en orden por nombre (menos este README y los que empiezan con `.`).
  El primero que falla detiene la corrida. Ponle número al nombre si quieres un orden: `10-tests.sh`.
- Tiene que ser ejecutable y con finales de línea Unix: `chmod +x gates/mi-gate.sh`. La fábrica lo revisa
  antes de gastar una sola fase y te dice cómo arreglarlo.
- Recibe tres variables:
  - `FACTORY_BASE`: el commit de tu `main` donde empezó la corrida (lo que había antes de los agentes).
  - `FACTORY_CHANGED`: los archivos que cambiaron los agentes, uno por línea.
  - `FACTORY_ROOT`: la carpeta del repo (el gate ya corre ahí).
- Tiene 60 segundos (`GATE_TIMEOUT` en `factory.conf`).
- Los agentes no pueden editar `gates/`: tus reglas son tuyas.
- Haz commit en `main` antes de correr `./factory.sh`.

## Para copiar y adaptar

**Que no toquen ciertos archivos**

```bash
#!/usr/bin/env bash
# Nadie cambia la configuración del proyecto sin un humano.
if grep -qE '^(package\.json|requirements\.txt|pyproject\.toml)$' <<<"$FACTORY_CHANGED"; then
  echo "Los agentes cambiaron un archivo de dependencias. Eso lo decide una persona."
  exit 1
fi
```

**Cambios chicos**

```bash
#!/usr/bin/env bash
# Máximo 120 líneas agregadas + borradas.
total="$(git diff --numstat "$FACTORY_BASE" -- . | awk '{ if ($1 != "-") n += $1 + $2 } END { print n + 0 }')"
if [ "$total" -gt 120 ]; then echo "El cambio tiene $total líneas; el máximo es 120."; exit 1; fi
```

**Un patrón prohibido**

```bash
#!/usr/bin/env bash
# Nada de prints sueltos (cámbialo por console.log, TODO, una URL, lo que quieras prohibir).
bad="$(git diff "$FACTORY_BASE" -- . | grep -E '^\+' | grep -E 'print\(' || true)"
if [ -n "$bad" ]; then echo "Encontré print() en el cambio:"; echo "$bad"; exit 1; fi
```

**Que pase otra revisión**

```bash
#!/usr/bin/env bash
# Corre una revisión más que la de factory.conf, por ejemplo un formateador o un type checker.
# Ojo: solo cuenta lo que ya está instalado en tu laptop.
python3 -m compileall -q . >/dev/null || { echo "Hay archivos de Python que no compilan."; exit 1; }
```

Pruébalo antes de la corrida, a mano:
`FACTORY_BASE=HEAD FACTORY_CHANGED="$(git diff --name-only HEAD)" ./gates/mi-gate.sh; echo $?`
