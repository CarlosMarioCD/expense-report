# expense-report

Un reporte de gastos por línea de comandos, sobre un CSV. Solo Python, sin dependencias: el repo más
fácil para empezar. Es uno de los repos del taller "Software factories with Claude Code".

## Preparar (antes del taller)

Necesitas Python 3.10 o más nuevo (`python3 --version`).

```zsh
gh repo fork sgomezahumada/expense-report --clone && cd expense-report
python3 -m report data/sample.csv   # debería imprimir un resumen
./doctor.sh                          # hasta que diga "doctor: all green"
```

## En el taller

```zsh
./factory.sh 1       # el ticket #1 entra, sale un PR (o un PR [REJECTED])
```

Este repo trae un gate: `gates/diff-size.sh` detiene cambios de más de 200 líneas. El ticket #3 está
pensado para chocar con él.

Lo que tú cambias: `AGENTS.md` (el contexto), `gates/` (tus revisiones), `prompts/` (las fases).
Haz commit en `main` antes de cada corrida. Nada se mergea: los PRs son para comparar.

## Tus gates

Lee [`gates/README.md`](gates/README.md): las reglas y cuatro ejemplos para copiar y adaptar.
