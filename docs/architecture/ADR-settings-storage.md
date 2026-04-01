# ADR: Armazenamento Seguro de API Keys via UI

**Data:** 2026-03-31
**Status:** Aceito
**Story:** 7.1

---

## Contexto

O Content Studio precisa permitir que a gestora de marketing configure API keys diretamente pela interface web, sem depender do squad de infraestrutura. Atualmente as credenciais ficam apenas no `.env` do servidor.

## Decisao

**Opcao escolhida: JSON criptografado em volume Docker**

Arquivo `settings.json` armazenado em `/app/settings/settings.json` (volume `studio-settings`), com as seguintes caracteristicas:

### Armazenamento
- Arquivo JSON com chaves armazenadas em **plaintext** no volume Docker (acesso restrito ao container)
- Volume ja mapeado em `docker-compose.production.yml` como `studio-settings → /opt/content-studio/settings`
- Persistencia garantida entre restarts do container

### Hierarquia de Prioridade
```
UI settings (settings.json) > .env (variaveis de ambiente)
```
- Se uma key existe no `settings.json`, ela tem prioridade
- Se nao, fallback para `os.environ` / `.env`
- Keys do `.env` continuam funcionando sem alteracao (migracao zero)

### Mascaramento
- API retorna keys no formato `****{last4}` (ex: `****abc1`)
- Key completa NUNCA retornada ao frontend em nenhum endpoint
- Frontend envia key completa no PUT, backend armazena

### API Design
```
GET    /api/settings/integrations          → lista integracoes com keys mascaradas
PUT    /api/settings/integrations/{plat}   → salva/atualiza credenciais
DELETE /api/settings/integrations/{plat}   → remove credenciais
```

## Alternativas Descartadas

| Opcao | Razao |
|-------|-------|
| SQLite encrypted | Overengineering — poucas keys, nao justifica DB |
| .env.local gerado | Requer restart do container para aplicar |
| Docker secrets | Requer Docker Swarm, nao compativel com compose standalone |
| Vault/KMS | Complexidade excessiva para single-server |

## Riscos Aceitos

- Plaintext no disco: mitigado por acesso restrito ao volume Docker e auth obrigatoria no endpoint
- Sem criptografia at-rest: aceitavel para MVP single-server com VPS dedicado

---

*@architect (Aria) — 2026-03-31*
