# Resposta aos Itens Pendentes — Squad Infra

**Data:** 2026-03-31
**Re:** 4 itens levantados pelo squad de infra

---

## Item 1: Imagem Docker — MUDANCA DE ABORDAGEM

**NAO vamos usar registry (GHCR).** Para deploy single-server, a abordagem mais eficiente
e build direto no servidor a partir do codigo-fonte.

**O que muda no servidor:**

Instalar git (se nao tiver):
```bash
apt-get install -y git
```

O deploy agora funciona assim:
```
git clone repo → docker compose build → docker compose up
```

O script `deploy.sh` ja esta no repositorio e faz tudo automaticamente.
Remover a linha `image: ghcr.io/...` do docker-compose.yml — ja foi substituida por `build:`.

**Primeiro deploy manual (executar como deployer ou root):**
```bash
cd /opt/content-studio

# Clonar repositorio (unica vez)
git clone --depth 1 --branch main https://github.com/roque-bruno/salk-content-studio.git repo

# Copiar docker-compose de producao
cp repo/deploy/docker-compose.production.yml docker-compose.yml

# Ajustar o path do build context para o repo local
sed -i 's|context: ../packages/content-pipeline|context: /opt/content-studio/repo/packages/content-pipeline|' docker-compose.yml

# Build e start
docker compose build
docker compose up -d

# Verificar
docker compose ps
curl -s http://127.0.0.1:8000/api/health
```

**Proximos deploys (automaticos via CI/CD ou manuais):**
```bash
bash /opt/content-studio/repo/deploy/deploy.sh
```

---

## Item 2: Credenciais

### STUDIO_PASS
Senha sugerida para producao: `SalkStudio@2026!Prod`
(Pode trocar por outra. O usuario de login sera `gestora`.)

Atualizar no `/opt/content-studio/.env`:
```bash
STUDIO_USER=gestora
STUDIO_PASS=SalkStudio@2026!Prod
```

### STUDIO_JWT_SECRET
Gerar no servidor:
```bash
openssl rand -hex 32
```
Copiar o resultado para o `.env`:
```bash
STUDIO_JWT_SECRET=<resultado_do_comando_acima>
```

### GOOGLE_API_KEY
**Sera fornecida pela equipe de produto.** Por enquanto, deixar em branco ou comentada.
O sistema funciona sem ela (modo preview) — apenas a geracao de conteudo por IA fica desabilitada.

Arquivo `.env` completo:
```bash
STUDIO_USER=gestora
STUDIO_PASS=SalkStudio@2026!Prod
STUDIO_JWT_SECRET=<gerar_com_openssl>
GOOGLE_API_KEY=
```

---

## Item 3: SSH Key para CI/CD

**Recomendacao: Opcao A — gerar no servidor.**

Executar como root:
```bash
# Gerar chave para o deployer
ssh-keygen -t ed25519 -f /home/deployer/.ssh/deploy_key -N "" -C "github-actions-deploy"

# Autorizar a chave
cat /home/deployer/.ssh/deploy_key.pub >> /home/deployer/.ssh/authorized_keys
chmod 600 /home/deployer/.ssh/authorized_keys
chown -R deployer:deployer /home/deployer/.ssh
```

**Depois, enviar a CHAVE PRIVADA para a equipe de dev:**
```bash
cat /home/deployer/.ssh/deploy_key
```

Enviar o conteudo (comeca com `-----BEGIN OPENSSH PRIVATE KEY-----`) de forma segura
(nao por email aberto). A equipe cadastrara como `SSH_PRIVATE_KEY` nos Secrets do GitHub.

**Se preferir nao configurar CI/CD agora:** o primeiro deploy pode ser feito manualmente
com o script acima. O CI/CD pode ser ativado depois.

---

## Item 4: DNS — JA PROPAGADO

Confirmado via Google DNS (8.8.8.8):
```
studio.salkmedical.com → 162.240.13.51 ✅
```

Nameservers sao do proprio VPS (ns1/ns2.salkmedical.com.br), entao a propagacao
foi direta. **Nada mais a fazer neste item.**

---

## Resumo de Acoes

| # | Item | Acao | Responsavel |
|---|------|------|-------------|
| 1 | Docker image | Instalar git, clonar repo, `docker compose build` | Squad Infra |
| 2 | Credenciais | Preencher `.env` conforme acima | Squad Infra |
| 3 | SSH key | Gerar no servidor, enviar privada para equipe dev | Squad Infra → Dev |
| 4 | DNS | Concluido | — |

Apos os itens 1-3, executar o teste de validacao:
```bash
curl -s http://127.0.0.1:8000/api/health        # teste local
curl -s https://studio.salkmedical.com/api/health  # teste externo (apos SSL)
```

---

*Equipe de Desenvolvimento — 2026-03-31*
