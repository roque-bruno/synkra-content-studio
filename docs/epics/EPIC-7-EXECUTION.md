# Epico 7 — Configuracao Self-Service

**PRD:** Auditoria Content Studio — gestora precisa configurar integracoes sem depender do squad de infra
**Status:** Em Execucao (5/7 stories Done — aguardando QA 7.6, 7.7)
**Inicio:** Apos Epic 6 (Fase 1 minimo)
**Duracao Estimada:** 1 semana
**Owner:** @pm (Morgan) — gestao / @architect (Aria) — design / @dev (Dex) — execucao

---

## Objetivo

Permitir que a gestora de marketing configure API keys e integracoes diretamente pela interface web, sem precisar do squad de infraestrutura. Validacao real das credenciais antes de salvar.

## Principio

> **Autonomia > Dependencia. Quem usa o sistema deve poder configura-lo.**

---

## Problemas Identificados (Auditoria 2026-03-31)

1. **Settings e read-only** — Pagina mostra status mas nao permite editar nada
2. **Sem validacao real** — Backend verifica `bool(api_key)` mas nunca faz chamada real para validar
3. **Dependencia do squad de infra** — Qualquer mudanca de credencial requer SSH no servidor e editar .env
4. **Sem feedback de erro** — Se uma API key e invalida, ninguem sabe ate tentar publicar
5. **Google API key sem UI** — Obrigatoria para geracao de conteudo IA mas so configuravel via .env

---

## Fases

### Fase 1: Arquitetura & Backend (Stories 7.1-7.2)

**Objetivo:** Definir modelo seguro de armazenamento e criar endpoints.

| Story | Titulo | Executor | Dependencia |
|-------|--------|----------|-------------|
| 7.1 | Arquitetura de armazenamento seguro de API keys | @architect (Aria) | — |
| 7.2 | Endpoints CRUD para configuracoes editaveis | @dev (Dex) | 7.1 |

### Fase 2: Frontend & Validacao (Stories 7.3-7.5)

**Objetivo:** Interface editavel com validacao real.

| Story | Titulo | Executor | Dependencia |
|-------|--------|----------|-------------|
| 7.3 | UI editavel de settings com validacao inline | @dev (Dex) | 7.2 |
| 7.4 | Validacao real de API keys via chamada externa | @dev (Dex) | 7.2 |
| 7.5 | Feedback visual de status de integracao | @dev (Dex) | 7.3, 7.4 |

### Fase 3: QA & Deploy (Stories 7.6-7.7)

**Objetivo:** Validar seguranca e usabilidade.

| Story | Titulo | Executor | Dependencia |
|-------|--------|----------|-------------|
| 7.6 | QA de seguranca — API keys nunca expostas no frontend | @qa (Quinn) | 7.2, 7.3 |
| 7.7 | QA end-to-end — fluxo completo de configuracao | @qa (Quinn) | 7.5, 7.6 |

---

## Plataformas a Configurar

| Plataforma | API/Credencial | Validacao |
|------------|---------------|-----------|
| Google AI (Gemini) | GOOGLE_API_KEY | `POST /v1beta/models?key=X` |
| Instagram | Access Token + Page ID | `GET /me?access_token=X` |
| Facebook | Page Access Token | `GET /me/accounts?access_token=X` |
| LinkedIn | Access Token + Org ID | `GET /v2/me` com Bearer |
| YouTube | OAuth2 + Channel ID | `GET /youtube/v3/channels?mine=true` |

---

## Criterios de Sucesso

- [ ] Gestora consegue configurar Google API key pela UI sem SSH
- [ ] Validacao real retorna OK/ERRO antes de salvar
- [ ] API keys armazenadas com seguranca (nunca retornadas inteiras ao frontend)
- [ ] Status de cada plataforma reflete conexao real validada
- [ ] QA gate PASS em seguranca (keys mascaradas, HTTPS only, auth required)

---

## Riscos

| Risco | Mitigacao |
|-------|----------|
| API keys expostas no frontend | Retornar apenas mascarado (****last4) |
| Credenciais em plaintext no disco | Criptografia at-rest ou variavel de ambiente |
| Token expirado sem aviso | Health check periodico com notificacao |
| Gestora insere key invalida | Validacao sincrona antes de persistir |

---

*Criado por @pm (Morgan) — 2026-03-31*
