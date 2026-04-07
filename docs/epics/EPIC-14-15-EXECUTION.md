# Epicos 14-15 — Reestruturacao Estrategica (Auditoria IC)

**Origem:** Auditoria Content Studio vs Inteligencia Competitiva (2026-04-07)
**Status:** Em Execucao
**Inicio:** 2026-04-07
**Owner:** Orion (aiox-master) — orquestracao
**Score auditoria:** 62/100 → Meta: 85/100

---

## Contexto

A auditoria do Squad IC identificou que o Content Studio e uma **peca de engenharia solida** (compliance 95/100, arquitetura 90/100) mas com **estrategia desalinhada dos dados reais de mercado** (canais 35/100, jornada 30/100, CRM 10/100, SEO 5/100).

Este documento define 2 epicos com 15 stories para corrigir os 11 issues identificados.

---

## Epic 14 — Recalibracao Estrategica (Dados + Conteudo)

**Objetivo:** Alinhar TODOS os dados estrategicos do sistema com os achados da IC — claims, pilares, canais, jornada, personas, frequencia.

**Principio:** Corrigir a mira antes de disparar. Zero codigo novo — apenas recalibracao de dados YAML e estrategia.

**Duracao:** 1 semana (Sprint 1)
**Executor principal:** @analyst (Alex) + @po (Pax)

### Stories

| Story | Titulo | Executor | Dep. | Prioridade |
|-------|--------|----------|------|:----------:|
| 14.1 | Expandir banco de claims com diferenciais IC | @analyst (Alex) | — | P0 | **DONE** |
| 14.2 | Redesenhar pilares Salk para jornada de compra | @po (Pax) + @analyst | 14.1 | P0 | **DONE** |
| 14.3 | Reprioritizar canais por validacao IC | @po (Pax) + @analyst | — | P0 | **DONE** |
| 14.4 | Integrar battlecards IC como fonte de conteudo | @analyst (Alex) | 14.1 | P1 | **DONE** |
| 14.5 | Recalibrar personas e priorizacao | @po (Pax) | 14.2 | P1 | **DONE** |
| 14.6 | Ajustar frequencia e volume por marca | @pm (Morgan) | 14.3 | P2 | **DONE** |
| 14.7 | Expandir calendario sazonal + conteudo pos-venda | @pm (Morgan) | 14.2 | P3 | **DONE** |

### Pre-Requisitos

- [x] Auditoria IC concluida (AUDITORIA_CONTENT_STUDIO_vs_IC.md)
- [x] Regras de negocio documentadas (REGRAS-DE-NEGOCIO-COMPLETAS.md)
- [x] Sistema 100% editavel pela UI (Motor IA + Marca)
- [ ] Acesso aos documentos IC (battlecards, diferenciais, jornada)

### Success Metrics

| Metrica | Antes | Meta |
|---------|:-----:|:----:|
| Claims no banco | 42 | 65-70 | **83 ✓** |
| Pilares mapeados para jornada | 0/7 fases | 7/7 fases |
| Score canais (auditoria) | 35/100 | 75/100 |
| Score jornada (auditoria) | 30/100 | 80/100 |
| COMMAND % Salk | 15% | 5% |

---

## Epic 15 — Novos Canais + Integracao CRM

**Objetivo:** Implementar os canais prioritarios validados pela IC (WhatsApp, SEO, YouTube avancado) e integrar CRM Bitrix24 para tracking de leads.

**Principio:** Canais que convertem > canais que impressionam. Cada peca deve gerar lead rastreavel.

**Duracao:** 3 semanas (Sprints 2-4)
**Executor principal:** @dev (Dex) + @architect (Aria)

### Stories

| Story | Titulo | Executor | Dep. | Prioridade |
|-------|--------|----------|------|:----------:|
| 15.1 | Arquitetura WhatsApp Business como canal primario | @architect (Aria) | 14.3 | P0 | **DONE** |
| 15.2 | Implementar modulo WhatsApp (sequencias, catalogo, templates) | @dev (Dex) | 15.1 | P0 |
| 15.3 | Arquitetura modulo SEO (blog, landing pages, schema) | @architect (Aria) | 14.2 | P1 | **DONE** |
| 15.4 | Implementar modulo SEO/Blog | @dev (Dex) | 15.3 | P1 |
| 15.5 | Integrar Bitrix24 CRM (leads por UTM, tracking) | @dev (Dex) + @devops (Gage) | 14.3 | P1 |
| 15.6 | Dashboard de metricas por fase da jornada | @dev (Dex) | 14.2, 15.5 | P2 |
| 15.7 | Conteudo pos-venda (tutoriais, manuais, suporte) | @dev (Dex) + @po (Pax) | 14.7 | P2 | **DONE** (dados) |
| 15.8 | Descontinuar Facebook + realocar esforco | @pm (Morgan) | 14.6 | P3 | **DONE** |

### Pre-Requisitos

- [ ] Epic 14 concluido (dados recalibrados)
- [ ] Acesso WhatsApp Business API (Meta Business Suite)
- [ ] Credenciais Bitrix24 API
- [ ] Dominio/hosting para blog SEO (subdominio ou path)

### Success Metrics

| Metrica | Antes | Meta |
|---------|:-----:|:----:|
| Canais com estrategia propria | 4 | 6 (+ WhatsApp, SEO) |
| Score CRM (auditoria) | 10/100 | 70/100 |
| Score SEO (auditoria) | 5/100 | 60/100 |
| Leads rastreavies/mes | 0 | 10+ |
| Score geral auditoria | 62/100 | 85/100 |

---

## Riscos

| Risco | Mitigacao |
|-------|-----------|
| WhatsApp Business API requer aprovacao Meta | Iniciar com WhatsApp Web automation; migrar para API |
| Blog SEO demora para indexar | Comecar com 2 artigos/semana; usar Google Search Console |
| Bitrix24 API limitada | Mapear endpoints disponiveis antes de desenvolver |
| Equipe nao dedicada | Epic 14 e 100% dados — gestora pode executar pela UI |
| Documentos IC incompletos | Validar com @analyst antes de cada story |

---

**Epicos 14-15 — Definidos 2026-04-07 por Orion (aiox-master)**
**Origem: Auditoria IC — Score 62/100 → Meta 85/100**
