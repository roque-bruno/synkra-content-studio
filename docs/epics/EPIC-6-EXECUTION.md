# Epico 6 — Transparencia de Producao

**PRD:** Auditoria Content Studio — dados enganosos na UI
**Status:** Em Execucao (4/5 stories Done — aguardando QA 6.5)
**Inicio:** 2026-03-31
**Duracao Estimada:** 1 semana
**Owner:** @pm (Morgan) — gestao / @dev (Dex) — execucao

---

## Objetivo

Eliminar TODOS os dados falsos, simulados ou enganosos da interface do Content Studio. A gestora de marketing deve conseguir distinguir claramente o que esta funcional do que nao esta, sem risco de tomar decisoes baseadas em informacoes irreais.

## Principio

> **Honestidade > Aparencia. Uma UI que mente e pior que uma UI vazia.**

---

## Problemas Identificados (Auditoria 2026-03-31)

1. **Status de plataformas falso** — Instagram/Facebook/LinkedIn/YouTube mostram "Conectado" sem nenhuma conta real integrada
2. **Modo preview indistinguivel** — Sem API key, o sistema opera em preview mode mas nada indica isso visualmente
3. **Publicacao simulada** — Botao "Publicar" funciona e retorna IDs falsos (preview-xxxx) como se tivesse publicado de verdade
4. **Confirmacao enganosa** — Toast de sucesso "Publicado com sucesso!" aparece mesmo em preview mode
5. **Pagina de settings read-only** — Mostra status mas nao permite configurar nada

---

## Fases

### Fase 1: Sinalizacao Visual (Stories 6.1-6.3)

**Objetivo:** Tornar impossivel confundir preview mode com producao real.

| Story | Titulo | Executor | Dependencia |
|-------|--------|----------|-------------|
| 6.1 | Banner persistente de preview mode | @dev (Dex) | — |
| 6.2 | Status real de conexao das plataformas | @dev (Dex) | — |
| 6.3 | Desabilitar publicacao sem configuracao valida | @dev (Dex) | 6.2 |

### Fase 2: Validacao & QA (Stories 6.4-6.5)

**Objetivo:** Garantir que nenhuma informacao falsa restou na UI.

| Story | Titulo | Executor | Dependencia |
|-------|--------|----------|-------------|
| 6.4 | Teste real de conexao com APIs externas | @dev (Dex) | 6.2 |
| 6.5 | Auditoria QA completa — zero dados falsos | @qa (Quinn) | 6.1, 6.2, 6.3, 6.4 |

---

## Criterios de Sucesso

- [ ] Nenhum status "Conectado" sem conta real integrada
- [ ] Banner de preview mode visivel em todas as paginas quando sem API key
- [ ] Botao de publicar desabilitado/oculto quando plataforma nao configurada
- [ ] Toast de publicacao mostra claramente "Preview" quando em modo simulado
- [ ] QA gate PASS com zero dados enganosos

---

## Riscos

| Risco | Mitigacao |
|-------|----------|
| Gestora confundir novo estado "vazio" com bug | Banner explicativo claro com instrucoes |
| Mudar comportamento de endpoints existentes | Testes de regressao em cada story |

---

*Criado por @pm (Morgan) — 2026-03-31*
