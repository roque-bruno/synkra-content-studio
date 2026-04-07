# Arquitetura — Módulo WhatsApp Business

**Story:** 15.1 — Epic 15 (Novos Canais + CRM)
**Autor:** @architect (Aria)
**Data:** 2026-04-07
**Status:** Arquitetura definida — implementação pendente (15.2)

---

## 1. Overview

O WhatsApp foi validado pela IC como **canal #1** para conversão B2B healthcare (Score 95/100). O módulo integra WhatsApp Business API ao Content Studio para nurturing direto, catálogo de produtos e sequências automatizadas por fase da jornada de compra.

### Princípios

- **Nurturing > Broadcasting** — sequências personalizadas por persona e fase, não spam
- **Conteúdo técnico** — engenheiro clínico recebe specs, compras recebe TCO
- **Compliance** — CONAR (sem citar concorrentes), LGPD (opt-in obrigatório), Meta policies
- **Rastreabilidade** — toda mensagem gera UTM para tracking no CRM

---

## 2. Fluxos de Nurturing por Jornada

### 7 Fases × 4 Personas = 28 Fluxos Base

| Fase | Persona: Eng. Clínica | Compras | Equipe Médica | Admin |
|------|----------------------|---------|---------------|-------|
| 1. Identificação | Specs comparativas | — | — | — |
| 2. Planejamento | Fichas técnicas PDF | TCO inicial | — | Overview portfólio |
| 3. Especificação | Claims detalhados, demos | — | Vídeos demo | — |
| 4. Cotação/Consulta | Docs licitação | Proposta, margem 20% | — | ROI projetado |
| 5. Avaliação | Comparativo "vs mercado" | Cases + social proof | Depoimentos | Cases ROI |
| 6. Decisão | Suporte técnico | Documentação pregão | — | Análise TCO final |
| 7. Pós-compra | Tutoriais, manutenção | — | Guia operação | NPS |

### Exemplo: Sequência Fase 2 (Planejamento) — Eng. Clínica + LEV

```
Dia 0: "Olá {nome}, vi que está especificando focos cirúrgicos. Preparei a ficha técnica do LEV 4."
       → Anexo: PDF ficha técnica LEV
Dia 2: "Sabe por que Ra=99 faz diferença na distinção de tecidos? Assista em 2 min."
       → Link: YouTube Short — Ra=99 explicado
Dia 5: "Comparativo técnico: nosso foco vs média de mercado em 5 specs que importam."
       → Anexo: PDF comparativo (sem citar concorrentes)
Dia 7: "Quer agendar uma demonstração técnica presencial? Nosso consultor pode ir até o hospital."
       → CTA: Responda SIM
```

---

## 3. Templates HSM (Header-Structured Messages)

Templates precisam de aprovação prévia da Meta. Categorias:

### Utilidade (utility)

| Template ID | Nome | Produto | Uso |
|-------------|------|---------|-----|
| UTL-001 | confirmacao_demo | Todos | Confirmação de agendamento de demo |
| UTL-002 | envio_ficha_tecnica | Todos | Envio de ficha técnica solicitada |
| UTL-003 | status_proposta | Todos | Atualização de status de proposta/licitação |
| UTL-004 | pos_venda_checklist | LEV, KRATUS | Checklist pós-instalação |

### Marketing (marketing)

| Template ID | Nome | Produto | Uso |
|-------------|------|---------|-----|
| MKT-001 | nurturing_specs | LEV | Sequência specs (Fase 2-3) |
| MKT-002 | nurturing_tco | KRATUS | Sequência TCO/ROI (Fase 4-6) |
| MKT-003 | nurturing_portfolio | Todos | Portfólio completo CC |
| MKT-004 | evento_hospitalar | Todos | Convite para feira/evento |
| MKT-005 | caso_sucesso | Todos | Case de cliente |
| MKT-006 | newsletter_semanal | Todos | Compilado semanal de conteúdo |

### Autenticação (authentication)

| Template ID | Nome | Uso |
|-------------|------|-----|
| AUTH-001 | opt_in_confirmacao | Confirmação de opt-in LGPD |

### Estrutura de um Template

```yaml
template:
  id: "MKT-001"
  name: "nurturing_specs_lev"
  category: "marketing"
  language: "pt_BR"
  header:
    type: "document"  # text | image | video | document
    example: "ficha-tecnica-lev.pdf"
  body: |
    Olá {{1}}, tudo bem?

    Preparamos a ficha técnica completa do foco cirúrgico LEV com todas as especificações:
    • Ra = 99 (fidelidade de cor máxima)
    • Profundidade de 1.930mm
    • 5 articulações independentes
    • Recarga em 2-4,5h

    {{2}}
  footer: "Salk Medical — Equipamento Médico Nacional"
  buttons:
    - type: "quick_reply"
      text: "Quero agendar demo"
    - type: "quick_reply"
      text: "Enviar para colega"
    - type: "url"
      text: "Ver no site"
      url: "https://salkmedical.com.br/lev?utm_source=whatsapp&utm_medium=social&utm_campaign={{3}}"
```

---

## 4. API Endpoints

### Envio de Mensagens

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/whatsapp/send` | Enviar mensagem individual (template ou session) |
| POST | `/api/whatsapp/broadcast` | Broadcast segmentado para lista de contatos |
| POST | `/api/whatsapp/sequence/start` | Iniciar sequência de nurturing para contato |
| PUT | `/api/whatsapp/sequence/{id}/pause` | Pausar sequência ativa |
| DELETE | `/api/whatsapp/sequence/{id}` | Cancelar sequência |

### Webhooks (recebimento)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/whatsapp/webhook` | Callback da Meta (mensagens, status, leitura) |
| GET | `/api/whatsapp/webhook` | Verificação de webhook (challenge) |

### Status e Métricas

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/whatsapp/messages/{id}/status` | Status de mensagem individual |
| GET | `/api/whatsapp/metrics/sequence/{id}` | Métricas de sequência |
| GET | `/api/whatsapp/metrics/template/{id}` | Métricas de template |
| GET | `/api/whatsapp/metrics/overview` | Dashboard geral |

### Gerenciamento

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/whatsapp/templates` | Listar templates aprovados |
| POST | `/api/whatsapp/templates` | Submeter template para aprovação |
| GET | `/api/whatsapp/contacts` | Listar contatos segmentados |
| POST | `/api/whatsapp/contacts/import` | Importar contatos do CRM |
| GET | `/api/whatsapp/sequences` | Listar sequências configuradas |
| POST | `/api/whatsapp/sequences` | Criar nova sequência |

---

## 5. Modelo de Dados

Ver `whatsapp-data-model.yaml` para estrutura completa.

### Entidades Principais

```
Contact ──┐
           ├── Message (1:N)
Sequence ──┤
           ├── SequenceStep (1:N)
Template ──┘
           └── Metric (1:1 por sequence)
```

---

## 6. Integração com Pipeline de Atomização

```
Master Content (Atlas) 
  → SemanticAtomizer 
    → whatsapp_nurturing format (max 1000 chars, conversacional)
    → whatsapp_catalog format (max 500 chars, specs resumidas)
    → whatsapp_broadcast format (max 1000 chars)
  → WhatsApp Module
    → Template matching (content → template HSM mais adequado)
    → Scheduling (horários ótimos: Seg-Qua 10h)
    → Envio via Meta API
```

### Fluxo de Conteúdo

1. Atlas gera master content com claims do claims-bank.yaml
2. SemanticAtomizer cria versão WhatsApp (tom conversacional, max 1000 chars)
3. WhatsApp Module recebe conteúdo atomizado
4. Match com template HSM aprovado (ou cria session message se dentro da janela 24h)
5. Segmenta por persona e fase da jornada
6. Agenda envio no horário ótimo
7. Registra UTM para tracking no CRM

---

## 7. Restrições e Limites da Meta API

| Limite | Valor | Nota |
|--------|-------|------|
| Janela de sessão | 24 horas | Após resposta do usuário, mensagens grátis por 24h |
| HSM fora da janela | Pago (~R$0.15-0.30) | Requer template aprovado |
| Rate limit (Tier 1) | 1.000 msg/dia | Novo número, sem histórico |
| Rate limit (Tier 2) | 10.000 msg/dia | Após enviar 1.000+ com qualidade |
| Rate limit (Tier 3) | 100.000 msg/dia | Após enviar 10.000+ com qualidade |
| Aprovação de template | 1-48 horas | Meta revisa manualmente |
| Botões por template | Max 3 | Quick reply ou URL |
| Variáveis por template | Max 10 | {{1}} a {{10}} |
| Tamanho documento | Max 100 MB | PDF, DOC, XLS |
| Tamanho imagem | Max 5 MB | JPG, PNG |
| Tamanho vídeo | Max 16 MB | MP4 |

### Qualidade e Penalidades

- **Score de qualidade**: green (OK), yellow (alerta), red (bloqueio)
- **Motivos de penalidade**: alta taxa de bloqueio, denúncias, opt-out
- **Mitigação**: segmentação cuidadosa, opt-in real, conteúdo relevante

---

## 8. Estimativa de Custos

| Tipo | Custo/msg | Volume mensal est. | Custo mensal est. |
|------|-----------|:------------------:|:-----------------:|
| HSM Marketing | ~R$0.30 | 500 | R$150 |
| HSM Utilidade | ~R$0.15 | 200 | R$30 |
| Session (grátis) | R$0.00 | 300 | R$0 |
| **Total estimado** | | **1.000** | **~R$180/mês** |

### Meta Business API

- Conta Business verificada (necessário)
- Número dedicado (não pode ser usado no WhatsApp pessoal simultaneamente)
- Provedor BSP (Business Solution Provider) ou API direta

---

## 9. Segmentação por Persona

| Persona | % Mensagens | Tipo conteúdo principal | Frequência |
|---------|:-----------:|------------------------|:----------:|
| Eng. Clínica | 40% | Specs, fichas, demos, comparativos | 2x/sem |
| Compras | 30% | TCO, propostas, documentação licitação | 1x/sem |
| Equipe Médica | 20% | Vídeos demo, tutoriais | 1x/sem |
| Admin | 10% | ROI, cases, portfólio | Quinzenal |

### Critérios de Segmentação

- **Cargo/função** — definido no contato (CRM ou manual)
- **Fase da jornada** — atualizado por interações (abriu PDF = avançou fase)
- **Produto de interesse** — inferido por conteúdo consumido
- **Região** — para eventos e demos presenciais

---

## 10. Compliance

### CONAR
- NUNCA citar concorrentes por nome em mensagens
- Usar "média de mercado", "típico do segmento"
- Claims com `restriction: "NÃO citar concorrente"` respeitados

### LGPD
- Opt-in explícito obrigatório antes de enviar mensagens marketing
- Template AUTH-001 confirma consentimento
- Opt-out fácil em toda mensagem ("Responda SAIR para cancelar")
- Dados armazenados com propósito documentado

### Meta Policies
- Sem conteúdo enganoso ou spam
- Templates revisados antes de submissão
- Respeitar horário comercial (8h-18h seg-sex)

---

## Pré-requisitos para Implementação (Story 15.2)

1. [ ] Conta Meta Business verificada
2. [ ] Número WhatsApp Business dedicado
3. [ ] BSP contratado ou API direta configurada
4. [ ] Templates HSM submetidos e aprovados pela Meta
5. [ ] Webhook endpoint público (HTTPS) configurado
6. [ ] Integração com CRM Bitrix24 (Story 15.5)

---

*Arquitetura definida por @architect (Aria) — Story 15.1 — Epic 15*
*Fonte: Auditoria IC — WhatsApp Score 95/100, Canal #1 validado*
