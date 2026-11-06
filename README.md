# expense-report

Un reporte de gastos por línea de comandos, sobre un CSV. Solo Python, sin dependencias: el repo más fácil para empezar.
Es uno de los repos del taller "Software factories with Claude Code".

## Cómo funciona

La fábrica toma un ticket (un issue de este repo) y lo convierte en un pull request, sola: cuatro sesiones
de Claude que no se conocen entre sí (plan, build, check, review), más tus revisiones automáticas (los gates).
**Una vez que arranca, no te pregunta nada:** siempre termina en un PR, aprobado o `[REJECTED]` con el motivo.

## 1. Copia el repo (antes del taller)

Necesitas una cuenta de Claude con Claude Code, `gh` con sesión iniciada (`gh auth login`, luego
`gh auth setup-git`) y Python 3.10 o más nuevo (`python3 --version`).

```zsh
gh repo fork sgomezahumada/expense-report --clone && cd expense-report
python3 -m report data/sample.csv   # debería imprimir un resumen
./doctor.sh      # repítelo hasta que diga "doctor: all green"
```

Es un fork, no solo un clone: así tienes tu propia copia en GitHub, la fábrica puede subir tu rama y abrir
el PR de vuelta a este repo, donde lo vemos todos.

## 2. Antes de arrancar, cambia lo que quieras

| Archivo | Qué controla |
|---|---|
| `AGENTS.md` | el contexto y las reglas que leen los agentes |
| `gates/` | tus revisiones automáticas (lee [`gates/README.md`](gates/README.md)) |
| `prompts/` | lo que se le dice a cada fase |
| `factory.conf` (avanzado) | qué rutas pueden cambiar los agentes (`SCOPE`), qué comandos pueden correr, el modelo |

No toques `factory.sh`, `lib/` ni `doctor.sh`: son el motor. Después, haz commit en `main`:

```zsh
git add -A && git commit -m "mi fábrica"
```

## 3. Arranca

El día del taller, primero pega en la terminal las tres líneas `export …` que mostramos en pantalla (son
para el tablero de la sala). Luego:

```zsh
./factory.sh 1   # el número del ticket
```

Desde aquí corre sola, unos 2 minutos. No toques el repo mientras corre. Mira la terminal: cada fase muestra lo que hace.

## 4. Lee el PR, cambia una cosa, repite

Tu PR aparece en https://github.com/sgomezahumada/expense-report/pulls. Nada se mergea: los PRs sirven para comparar
el tuyo con el de los demás para el mismo ticket. Al terminar vuelves a `main`: haz tu siguiente cambio ahí
y vuelve a correr.

## Los tickets

- #1 y #2: totales por moneda y por mes.
- #3 pide leer cualquier formato de archivo. Este repo trae `gates/diff-size.sh`, que detiene cambios de más de 200 líneas.
