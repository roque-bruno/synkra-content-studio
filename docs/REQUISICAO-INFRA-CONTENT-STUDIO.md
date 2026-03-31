# Requisicao de Infraestrutura — Salk Content Studio

**De:** Equipe de Produto / Desenvolvimento
**Para:** Squad de Infraestrutura (Administracao VPS/WHM)
**Data:** 2026-03-31
**Prioridade:** Alta
**Servidor:** 162.240.13.51 (WHM)

---

## Contexto

Precisamos hospedar o **Salk Content Studio** (sistema web de producao de conteudo) no VPS existente.
A aplicacao roda em container Docker e precisa ser acessivel via `studio.salkmedical.com`.
Hoje o DNS desse subdominio aponta para o Render — sera redirecionado para o proprio VPS.

---

## 1. Docker Engine

### Instalar
- Docker Engine (CE) versao 24+ e Docker Compose v2
- Instrucoes oficiais: https://docs.docker.com/engine/install/

### Verificacao
```bash
docker --version          # >= 24.0
docker compose version    # >= 2.20
docker run hello-world    # teste basico
```

### Configuracao pos-instalacao
```bash
# Habilitar inicio automatico
systemctl enable docker
systemctl start docker
```

---

## 2. Estrutura de Diretorios

Criar a seguinte arvore no servidor:

```bash
mkdir -p /opt/content-studio/{data,uploads,settings,logs}
chmod 755 /opt/content-studio
chmod 777 /opt/content-studio/{data,uploads,settings,logs}
```

| Diretorio | Finalidade | Persistencia |
|-----------|-----------|--------------|
| `/opt/content-studio/` | Raiz da aplicacao | Permanente |
| `/opt/content-studio/data/` | Banco SQLite + dados de producao | Permanente — incluir em backup |
| `/opt/content-studio/uploads/` | Imagens e arquivos enviados pelos usuarios | Permanente — incluir em backup |
| `/opt/content-studio/settings/` | Configuracoes salvas (API keys, preferencias) | Permanente — incluir em backup |
| `/opt/content-studio/logs/` | Logs da aplicacao | Rotacional (pode limpar a cada 30 dias) |

---

## 3. Arquivo Docker Compose

Criar o arquivo `/opt/content-studio/docker-compose.yml` com o conteudo abaixo:

```yaml
version: '3.8'

services:
  content-studio:
    image: ghcr.io/roque-bruno/salk-content-studio:latest
    container_name: content-studio
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      - STUDIO_ENV=production
      - STUDIO_USER=${STUDIO_USER}
      - STUDIO_PASS=${STUDIO_PASS}
      - STUDIO_JWT_SECRET=${STUDIO_JWT_SECRET}
      - ALLOWED_ORIGINS=https://studio.salkmedical.com
      - GOOGLE_API_KEY=${GOOGLE_API_KEY}
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/app/data
      - ./uploads:/app/uploads
      - ./settings:/app/settings
      - ./logs:/app/output/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

**IMPORTANTE:** A porta esta mapeada para `127.0.0.1:8000` (somente localhost). O acesso externo sera via Apache reverse proxy.

---

## 4. Arquivo de Variaveis de Ambiente

Criar o arquivo `/opt/content-studio/.env`:

```bash
# === CREDENCIAIS DE ACESSO ===
STUDIO_USER=gestora
STUDIO_PASS=<DEFINIR_SENHA_SEGURA>
STUDIO_JWT_SECRET=<GERAR_STRING_ALEATORIA_64_CHARS>

# === API KEY (fornecida pela equipe de produto) ===
GOOGLE_API_KEY=<SERA_FORNECIDA>
```

### Para gerar o JWT secret:
```bash
openssl rand -hex 32
```

### Permissoes do arquivo .env:
```bash
chmod 600 /opt/content-studio/.env
chown root:root /opt/content-studio/.env
```

**NOTA:** A equipe de produto fornecera os valores de `STUDIO_USER`, `STUDIO_PASS` e `GOOGLE_API_KEY`. O `STUDIO_JWT_SECRET` deve ser gerado no servidor e informado de volta.

---

## 5. Apache Reverse Proxy

### Pre-requisitos
Verificar que os modulos estao habilitados:
```bash
a]2enmod proxy proxy_http proxy_wstunnel headers rewrite ssl
```

No WHM, os modulos podem ser habilitados em:
**WHM > Apache Configuration > Global Configuration** ou via EasyApache 4.

### VirtualHost

Criar configuracao para `studio.salkmedical.com`.
No WHM, pode ser feito via **WHM > Apache Configuration > Include Editor** (Pre-VirtualHost Include para All Versions).

Ou criar arquivo de configuracao diretamente:

```apache
<VirtualHost *:443>
    ServerName studio.salkmedical.com
    
    # SSL — usar certificado AutoSSL do WHM ou Let's Encrypt
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/studio.salkmedical.com.crt
    SSLCertificateKeyFile /etc/ssl/private/studio.salkmedical.com.key
    SSLCertificateChainFile /etc/ssl/certs/studio.salkmedical.com.ca-bundle
    # Ajustar paths conforme o certificado gerado pelo WHM/AutoSSL
    
    # Headers de seguranca
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
    Header always set X-XSS-Protection "1; mode=block"
    
    # Reverse Proxy para o container Docker
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/
    
    # WebSocket (se necessario no futuro)
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteRule /(.*) ws://127.0.0.1:8000/$1 [P,L]
    
    # Timeout para operacoes longas (geracao de imagem/video)
    ProxyTimeout 120
    
    # Logs
    ErrorLog /opt/content-studio/logs/apache-error.log
    CustomLog /opt/content-studio/logs/apache-access.log combined
</VirtualHost>

# Redirecionar HTTP para HTTPS
<VirtualHost *:80>
    ServerName studio.salkmedical.com
    RewriteEngine On
    RewriteRule ^(.*)$ https://studio.salkmedical.com$1 [R=301,L]
</VirtualHost>
```

---

## 6. SSL / Certificado HTTPS

**Opcao A (recomendada):** Usar AutoSSL do WHM
- WHM > SSL/TLS > Manage AutoSSL
- Verificar que `studio.salkmedical.com` esta coberto

**Opcao B:** Let's Encrypt via cPanel/WHM plugin
- WHM > AutoSSL Providers > selecionar Let's Encrypt

**Opcao C:** Certbot manual
```bash
certbot certonly --webroot -w /var/www/html -d studio.salkmedical.com
```

O certificado precisa estar ativo ANTES de testarmos o deploy.

---

## 7. DNS

Alterar o registro DNS de `studio.salkmedical.com`:

| Tipo | Nome | Valor Atual | Novo Valor |
|------|------|-------------|------------|
| CNAME | studio | synkra-content-studio.onrender.com | **(remover)** |
| A | studio | — | 162.240.13.51 |

**Ou** se o DNS eh gerenciado no WHM:
- WHM > DNS Functions > Edit DNS Zone > salkmedical.com
- Remover o CNAME `studio` apontando para Render
- Criar registro A `studio` apontando para `162.240.13.51`

**TTL:** 300 (5 minutos) durante a migracao, depois pode subir para 3600.

---

## 8. Firewall

Verificar que as seguintes portas estao abertas:

| Porta | Protocolo | Direcao | Finalidade |
|-------|-----------|---------|-----------|
| 80 | TCP | Entrada | HTTP (redirect para HTTPS) |
| 443 | TCP | Entrada | HTTPS (acesso dos usuarios) |
| 8000 | TCP | **Somente localhost** | Docker → Apache (NAO expor externamente) |

**IMPORTANTE:** A porta 8000 NAO deve ser acessivel da internet. O acesso externo passa exclusivamente pelo Apache (443).

---

## 9. SSH Deploy Key

Precisamos que um usuario SSH possa fazer deploy automatizado (CI/CD via GitHub Actions).

### Criar usuario dedicado:
```bash
useradd -m -s /bin/bash deployer
usermod -aG docker deployer
```

### Configurar chave SSH:
```bash
mkdir -p /home/deployer/.ssh
chmod 700 /home/deployer/.ssh
touch /home/deployer/.ssh/authorized_keys
chmod 600 /home/deployer/.ssh/authorized_keys
chown -R deployer:deployer /home/deployer/.ssh
```

**A chave publica sera fornecida pela equipe de desenvolvimento para adicionar em `authorized_keys`.**

### Permissoes do deployer sobre o content-studio:
```bash
chown -R deployer:deployer /opt/content-studio
```

### Restringir acesso (opcional mas recomendado):
O usuario `deployer` so precisa de acesso a:
- `/opt/content-studio/` (leitura e escrita)
- Comandos `docker` e `docker compose`
- Nao precisa de acesso root nem a outros sites do servidor

---

## 10. Backup

Incluir no backup regular do servidor:

| Path | Frequencia | Retencao |
|------|-----------|----------|
| `/opt/content-studio/data/` | Diario | 30 dias |
| `/opt/content-studio/uploads/` | Diario | 30 dias |
| `/opt/content-studio/settings/` | Semanal | 90 dias |
| `/opt/content-studio/.env` | Semanal | 90 dias |

**NAO precisa de backup:**
- `/opt/content-studio/logs/` (rotacional)
- Imagens Docker (sao reconstruidas no deploy)

---

## 11. Monitoramento (Opcional mas Recomendado)

### Health check basico via cron:
```bash
# /etc/cron.d/content-studio-health
*/5 * * * * root curl -sf http://127.0.0.1:8000/api/health > /dev/null || (cd /opt/content-studio && docker compose restart)
```
Isso verifica a cada 5 minutos e reinicia o container se nao responder.

---

## Checklist de Entrega

Ao concluir, informar a equipe de desenvolvimento com:

- [ ] Docker Engine instalado e funcionando (`docker --version`)
- [ ] Docker Compose v2 instalado (`docker compose version`)
- [ ] Estrutura `/opt/content-studio/` criada com permissoes
- [ ] `docker-compose.yml` criado conforme especificacao
- [ ] `.env` criado com JWT secret gerado (enviar o secret para a equipe de produto)
- [ ] Modulos Apache habilitados (proxy, proxy_http, ssl, headers, rewrite)
- [ ] VirtualHost configurado para `studio.salkmedical.com`
- [ ] Certificado SSL ativo para `studio.salkmedical.com`
- [ ] DNS alterado: `studio.salkmedical.com` → A record 162.240.13.51
- [ ] Porta 8000 acessivel SOMENTE em localhost (nao exposta externamente)
- [ ] Usuario `deployer` criado com acesso Docker e SSH
- [ ] Chave publica SSH adicionada ao `deployer` (aguardar envio da equipe de dev)
- [ ] Backup configurado para `/opt/content-studio/{data,uploads,settings}`
- [ ] Health check cron ativo (opcional)

---

## Teste de Validacao

Apos tudo configurado, executar:

```bash
# 1. Subir o container (primeira vez sera com imagem de teste)
cd /opt/content-studio
docker compose pull
docker compose up -d

# 2. Verificar se o container esta rodando
docker compose ps
# Esperado: content-studio  running (healthy)

# 3. Testar acesso local
curl -s http://127.0.0.1:8000/api/health
# Esperado: {"status":"ok", ...}

# 4. Testar acesso via Apache
curl -s https://studio.salkmedical.com/api/health
# Esperado: {"status":"ok", ...}
```

Se os 4 testes passarem, informar a equipe de desenvolvimento para prosseguir com o deploy da versao final.

---

## Contatos

| Responsavel | Escopo |
|-------------|--------|
| Equipe de Produto | Credenciais, API keys, validacao funcional |
| Squad Infra | Servidor, Docker, Apache, DNS, SSL, backup |
| Equipe de Desenvolvimento | Deploy key SSH, CI/CD pipeline, imagem Docker |

---

*Documento gerado em 2026-03-31. Versao 1.0.*
