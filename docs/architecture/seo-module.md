# SEO Module Architecture — Content Studio

**Story:** 15.3  
**Status:** Draft  
**Last Updated:** 2026-04-07  
**Owner:** @architect (Aria)  

---

## 1. Overview

Modulo SEO para healthcare B2B focado em engenheiros clinicos e gestores hospitalares que pesquisam specs tecnicas no Google antes de especificar equipamentos medicos. O modulo gera blog tecnico + landing pages otimizadas a partir do claims-bank.yaml e pillar content existente.

**Justificativa:** Google/SEO validado como canal #2 pela IC (Score 90/100). O sistema tem ZERO presenca SEO atualmente. Engenheiros clinicos pesquisam termos tecnicos (Ra, CRI, carga VA, radiotransparencia) no Google antes de abrir processo de compra.

**Produtos cobertos:** LEV (foco cirurgico LED), KRATUS (mesa cirurgica), OSTUS (serra cirurgica), KRONUS (suporte cirurgico).

**Objetivo Fase 1 (meses 1-3):** Indexacao basica, 4 landing pages de produto, 8 artigos pillar.  
**Objetivo Fase 2 (meses 4-6):** 2 artigos/semana, rich snippets ativos, primeiras posicoes top-10 em long-tail.

---

## 2. Blog Engine

### 2.1 Gerador de Artigos SEO

O blog engine gera artigos tecnicos a partir de duas fontes primarias:

1. **Pillar Content** — temas-ancora por cluster de keywords (ex: "Iluminacao Cirurgica: Guia Completo")
2. **claims-bank.yaml** — dados tecnicos pre-aprovados (Constitution Article IV — No Invention)

### 2.2 Pipeline de Geracao

```
claims-bank.yaml + seo-keywords.yaml
        │
        ▼
┌─────────────────────┐
│  Topic Planner       │  Seleciona cluster + keywords alvo
│  (Helix/Atlas)       │  Mapeia claims relevantes
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Article Generator   │  Gera artigo com estrutura SEO
│  (Helix copywriter)  │  H1/H2/H3, meta description, FAQ
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  SEO Validator       │  Keyword density, readability
│  (Shield)            │  Claims compliance check
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Human Review Gate   │  Aprovacao gestora antes de publicar
└─────────────────────┘
```

### 2.3 Estrutura do Artigo

```yaml
article:
  meta:
    title: "string (max 60 chars, keyword no inicio)"
    description: "string (max 155 chars, keyword + CTA)"
    slug: "string (kebab-case, max 5 palavras)"
    canonical_url: "string"
    og_image: "string (1200x630)"
    published_at: "ISO 8601"
    updated_at: "ISO 8601"
    author: "Mendel Medical"
  content:
    h1: "string (keyword principal)"
    intro: "string (150-200 palavras, keyword nos primeiros 100 chars)"
    sections: "H2/H3 com keywords secundarias"
    faq: "3-5 perguntas com schema FAQ"
    cta: "CTA contextual para landing page do produto"
  seo:
    primary_keyword: "string"
    secondary_keywords: ["string"]
    claims_used: ["LEV-01", "LEV-03"]
    internal_links: ["URL"]
    word_count: "1500-2500"
```

### 2.4 Tipos de Artigo

| Tipo | Palavras | Frequencia | Exemplo |
|------|----------|------------|---------|
| Pillar Page | 2500-4000 | 2/mes | "Guia Completo: Iluminacao LED em Centro Cirurgico" |
| Cluster Post | 1200-1800 | 2/semana | "Ra 99 vs Ra 90: Impacto na Identificacao de Tecidos" |
| Comparativo | 1500-2000 | 2/mes | "Foco LED vs Halogeno: Analise Tecnica Completa" |
| FAQ Tecnico | 800-1200 | 1/semana | "Perguntas Frequentes sobre Mesa Cirurgica Eletrica" |

---

## 3. Landing Page Generator

### 3.1 Uma Landing Page por Produto

Cada produto publicavel recebe uma landing page otimizada:

| Produto | URL | Keyword Principal | Claims Base |
|---------|-----|-------------------|-------------|
| LEV | /produtos/foco-cirurgico-led-lev | foco cirurgico LED | LEV-01 a LEV-10 |
| KRATUS | /produtos/mesa-cirurgica-kratus | mesa cirurgica eletrica | KRA-01 a KRA-08 |
| OSTUS | /produtos/serra-cirurgica-ostus | serra cirurgica ortopedica | OST-01 a OST-05 |
| KRONUS | /produtos/suporte-cirurgico-kronus | suporte cirurgico | KRO-01 a KRO-04 |

### 3.2 Estrutura da Landing Page

```
┌───────────────────────────────────────┐
│  Hero Section                         │
│  H1 com keyword + tagline             │
│  Imagem hero do produto (NB2)         │
│  CTA primario: "Solicitar Orcamento"  │
├───────────────────────────────────────┤
│  Specs Tecnicas                       │
│  Tabela com dados do claims-bank      │
│  Icons por spec (Ra, peso, dimensoes) │
├───────────────────────────────────────┤
│  Diferenciais                         │
│  3-4 blocos com claims acessiveis     │
│  Icones + texto curto                 │
├───────────────────────────────────────┤
│  FAQ (Schema markup)                  │
│  5-8 perguntas tecnicas               │
│  Respostas com claims oficiais        │
├───────────────────────────────────────┤
│  CTA Final                            │
│  "Fale com um consultor"              │
│  Formulario ou WhatsApp               │
├───────────────────────────────────────┤
│  Schema MedicalDevice (JSON-LD)       │
│  Dados estruturados no <head>         │
└───────────────────────────────────────┘
```

### 3.3 Regra de Logo

Conforme brand-guidelines.yaml:
- Landing pages tecnicas (specs, engenharia) → Logo **Mendel Medical**
- Landing pages comerciais (CTA venda, preco) → Logo **Salk Medical**
- Na pratica, landing pages de produto usam **Salk Medical** (CTA de venda presente)

---

## 4. Schema Markup (Dados Estruturados)

### 4.1 MedicalDevice Schema

Aplicado em cada landing page de produto:

```json
{
  "@context": "https://schema.org",
  "@type": "MedicalDevice",
  "name": "LEV 4 - Foco Cirurgico LED de Teto",
  "manufacturer": {
    "@type": "Organization",
    "name": "Mendel Medical",
    "url": "https://mendelmedical.com.br"
  },
  "description": "Foco cirurgico LED com indice de reproducao de cor Ra 99, campo de luz concentrada ate 160.000 lux, vida util de 60.000 horas",
  "category": "Iluminacao Cirurgica",
  "url": "https://salkmedical.com.br/produtos/foco-cirurgico-led-lev",
  "brand": {
    "@type": "Brand",
    "name": "LEV"
  },
  "additionalProperty": [
    {
      "@type": "PropertyValue",
      "name": "Indice de Reproducao de Cor (Ra)",
      "value": "99"
    },
    {
      "@type": "PropertyValue",
      "name": "Iluminancia Central",
      "value": "160.000 lux"
    },
    {
      "@type": "PropertyValue",
      "name": "Vida Util LED",
      "value": "60.000 horas"
    }
  ]
}
```

### 4.2 Product Schema

Complementar ao MedicalDevice para e-commerce signals:

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "KRATUS - Mesa Cirurgica Eletrica",
  "brand": { "@type": "Brand", "name": "KRATUS" },
  "manufacturer": { "@type": "Organization", "name": "Mendel Medical" },
  "description": "Mesa cirurgica eletrica com capacidade de 340 kg, curso vertical 570-1020 mm, radiotransparente",
  "category": "Mobiliario Cirurgico",
  "offers": {
    "@type": "Offer",
    "priceCurrency": "BRL",
    "availability": "https://schema.org/InStock",
    "seller": { "@type": "Organization", "name": "Salk Medical" }
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.8",
    "reviewCount": "45"
  }
}
```

### 4.3 FAQ Schema

Aplicado em artigos e landing pages com secao FAQ:

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "Qual a diferenca entre Ra 99 e Ra 90 em focos cirurgicos?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "O indice Ra 99 reproduz cores com fidelidade quase perfeita, permitindo diferenciacao precisa entre tecidos durante cirurgias. Ra 90 pode mascarar variacoes sutis de cor, impactando a seguranca do procedimento."
      }
    },
    {
      "@type": "Question",
      "name": "Quanto tempo dura um LED cirurgico?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "A linha LEV possui vida util de 60.000 horas, equivalente a aproximadamente 20 anos de uso em centro cirurgico com 8 horas diarias de operacao."
      }
    }
  ]
}
```

### 4.4 HowTo Schema

Para artigos tutoriais/guias:

```json
{
  "@context": "https://schema.org",
  "@type": "HowTo",
  "name": "Como especificar um foco cirurgico LED para licitacao",
  "description": "Guia tecnico para engenheiros clinicos elaborarem especificacao tecnica de foco cirurgico LED conforme normas vigentes",
  "step": [
    {
      "@type": "HowToStep",
      "name": "Definir requisitos de iluminacao",
      "text": "Determinar iluminancia central minima (recomendado >= 160.000 lux), Ra minimo (>= 95), e temperatura de cor (4.300-4.500 K)"
    },
    {
      "@type": "HowToStep",
      "name": "Verificar conformidade regulatoria",
      "text": "Confirmar registro ANVISA vigente e conformidade com norma IEC 60601-2-41"
    },
    {
      "@type": "HowToStep",
      "name": "Avaliar TCO (Total Cost of Ownership)",
      "text": "Calcular custo total incluindo consumo energetico, troca de lampadas (LED = 60.000h vs halogeno = 1.500h) e manutencao"
    }
  ]
}
```

---

## 5. Keyword Strategy

### 5.1 Cinco Clusters

| Cluster | Intent Principal | Volume | Exemplo |
|---------|-----------------|--------|---------|
| **Produto/Marca** | Commercial/Transactional | Baixo-Medio | "foco cirurgico LED", "mesa cirurgica eletrica" |
| **Problema** | Informational | Alto | "iluminacao centro cirurgico", "ergonomia sala cirurgica" |
| **Comparativo** | Commercial | Medio | "foco LED vs halogeno", "mesa nacional vs importada" |
| **Tecnico** | Informational | Baixo | "Ra CRI iluminacao cirurgica", "radiotransparencia mesa" |
| **Regulatorio** | Informational | Medio | "ANVISA equipamento medico", "licitacao hospitalar" |

### 5.2 Estrategia por Cluster

- **Produto/Marca:** Landing pages + artigos de produto. Conversao direta.
- **Problema:** Blog posts educativos. Topo de funil. Captura atencao de quem ainda nao conhece a marca.
- **Comparativo:** Artigos de comparacao tecnica. Meio de funil. Engenheiro clinico comparando opcoes.
- **Tecnico:** Artigos profundos para especialistas. Autoridade tecnica. Link building natural.
- **Regulatorio:** Guias sobre ANVISA, licitacoes, pregao eletronico. Alto volume, publico decisor.

### 5.3 Banco de Keywords

Arquivo: `squads/content-production/data/seo-keywords.yaml`

50+ termos mapeados com volume estimado, intent, produto-alvo e prioridade.

---

## 6. URL Structure

### 6.1 Blog

```
/blog/{categoria}/{slug}
```

Categorias:
- `/blog/iluminacao-cirurgica/` — Artigos sobre focos, LEV, iluminacao
- `/blog/mobiliario-cirurgico/` — Artigos sobre mesas, suportes, KRATUS, KRONUS
- `/blog/instrumentos-cirurgicos/` — Artigos sobre serras, OSTUS
- `/blog/regulatorio/` — ANVISA, licitacoes, normas
- `/blog/engenharia-clinica/` — Artigos para engenheiros clinicos, specs, TCO

Exemplos:
- `/blog/iluminacao-cirurgica/ra-99-vs-ra-90-impacto-cirurgia`
- `/blog/regulatorio/como-especificar-equipamento-medico-licitacao`
- `/blog/engenharia-clinica/tco-foco-cirurgico-led-vs-halogeno`

### 6.2 Produtos

```
/produtos/{produto-slug}
```

URLs fixas:
- `/produtos/foco-cirurgico-led-lev`
- `/produtos/mesa-cirurgica-kratus`
- `/produtos/serra-cirurgica-ostus`
- `/produtos/suporte-cirurgico-kronus`

### 6.3 Regras de URL

- Sempre kebab-case, sem acentos
- Max 5 palavras no slug do blog
- Canonical URL obrigatoria em todas as paginas
- Redirecionamento 301 se URL mudar

---

## 7. Internal Linking Strategy

### 7.1 Arquitetura de Links Internos

```
        Pillar Page (2500-4000 palavras)
       /         |          \
      /          |           \
Cluster A    Cluster B    Cluster C
(1200-1800)  (1200-1800)  (1200-1800)
     \           |           /
      \          |          /
       Landing Page (Produto)
```

### 7.2 Regras de Linking

| De | Para | Frequencia |
|----|------|------------|
| Cluster Post | Pillar Page pai | Sempre (1 link no intro, 1 no final) |
| Cluster Post | Landing Page do produto | Sempre (CTA contextual) |
| Cluster Post | Outro Cluster Post relacionado | 1-2 links por artigo |
| Pillar Page | Todos os Cluster Posts filhos | Sempre (sumario linkado) |
| Pillar Page | Landing Pages relevantes | 2-3 links contextuais |
| Landing Page | Pillar Page relevante | 1-2 links na secao "Saiba Mais" |
| Landing Page | Artigos FAQ relacionados | 2-3 links |

### 7.3 Anchor Text

- Usar keyword alvo do artigo destino como anchor text
- Variar anchors (nao repetir sempre o mesmo texto)
- Nunca usar "clique aqui" — sempre anchor descritivo

---

## 8. Content Calendar SEO

### 8.1 Fase 1 — Foundation (Meses 1-3)

| Semana | Entrega |
|--------|---------|
| 1-2 | 4 Landing pages de produto (LEV, KRATUS, OSTUS, KRONUS) |
| 3-4 | Pillar Page: "Iluminacao LED em Centro Cirurgico" |
| 5-6 | Pillar Page: "Mesa Cirurgica: Guia Completo para Engenheiros Clinicos" |
| 7-8 | 4 Cluster Posts (2 por pillar) |
| 9-10 | Pillar Page: "Licitacao de Equipamentos Medicos" |
| 11-12 | 4 Cluster Posts + Setup Search Console |

**Total Fase 1:** 4 landing pages + 3 pillar pages + 8 cluster posts = 15 paginas

### 8.2 Fase 2 — Growth (Meses 4-6)

| Cadencia | Tipo |
|----------|------|
| 2x/semana | Cluster Posts (1 problema + 1 tecnico/comparativo) |
| 2x/mes | Pillar Pages novas |
| 1x/mes | Atualizacao de pillar pages existentes |
| Continuo | Otimizacao de artigos com CTR baixo |

**Total Fase 2:** ~24 cluster posts + 6 pillar pages + otimizacoes

### 8.3 Fase 3 — Scale (Meses 7+)

- 3 artigos/semana
- Link building ativo (parcerias com portais hospitalares)
- Content refresh trimestral
- Expansao para video SEO (YouTube)

---

## 9. Technical SEO

### 9.1 Sitemap

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://salkmedical.com.br/produtos/foco-cirurgico-led-lev</loc>
    <lastmod>2026-04-07</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>https://salkmedical.com.br/blog/iluminacao-cirurgica/guia-completo-led</loc>
    <lastmod>2026-04-07</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
```

Geracao automatica a cada deploy. Submetido ao Google Search Console.

### 9.2 Robots.txt

```
User-agent: *
Allow: /
Disallow: /api/
Disallow: /admin/
Sitemap: https://salkmedical.com.br/sitemap.xml
```

### 9.3 Canonical URLs

Toda pagina inclui `<link rel="canonical">` no `<head>`. Previne duplicacao quando o mesmo conteudo e acessivel por URLs diferentes.

### 9.4 Meta Tags

```html
<title>Foco Cirurgico LED Ra 99 | LEV - Salk Medical</title>
<meta name="description" content="Foco cirurgico LED com reproducao de cor Ra 99, 160.000 lux e vida util de 60.000 horas. Fabricacao nacional Mendel Medical. Solicite orcamento.">
<meta name="robots" content="index, follow">
```

### 9.5 Open Graph

```html
<meta property="og:title" content="Foco Cirurgico LED Ra 99 | LEV">
<meta property="og:description" content="Reproducao de cor Ra 99. A luz mais proxima da realidade para centro cirurgico.">
<meta property="og:image" content="https://salkmedical.com.br/images/lev-hero-1200x630.jpg">
<meta property="og:url" content="https://salkmedical.com.br/produtos/foco-cirurgico-led-lev">
<meta property="og:type" content="product">
<meta property="og:site_name" content="Salk Medical">
```

### 9.6 Performance

- Core Web Vitals como meta: LCP < 2.5s, FID < 100ms, CLS < 0.1
- Imagens WebP com lazy loading
- CSS/JS minificado
- CDN para assets estaticos

---

## 10. Metricas

### 10.1 KPIs Primarios

| Metrica | Fonte | Meta Fase 1 | Meta Fase 2 |
|---------|-------|-------------|-------------|
| Paginas indexadas | Google Search Console | 15 | 50+ |
| Impressoes organicas/mes | Search Console | 1.000 | 10.000 |
| Cliques organicos/mes | Search Console | 100 | 1.500 |
| CTR medio | Search Console | 3% | 5% |
| Posicao media (long-tail) | Search Console | Top 20 | Top 10 |
| Keywords no top 10 | Search Console | 5 | 25 |

### 10.2 KPIs Secundarios

| Metrica | Fonte | Meta |
|---------|-------|------|
| Tempo na pagina | Analytics | > 3 min (artigos) |
| Bounce rate blog | Analytics | < 65% |
| Conversoes (formulario/WhatsApp) | Analytics | 2% do trafego organico |
| Backlinks adquiridos | Search Console | 10/trimestre |
| Rich snippets ativos | Search Console | 100% landing pages |

### 10.3 Dashboard

Integrar com Google Search Console API para exibir metricas no Content Studio:
- Grafico de impressoes e cliques (30/90 dias)
- Top 10 keywords por cliques
- Paginas com maior CTR
- Alertas para paginas com queda de posicao

---

## 11. Integracao com Pipeline Existente

### 11.1 Claims como Fonte Unica de Verdade

```
claims-bank.yaml ──→ Blog Engine (artigos tecnicos)
       │
       ├──→ Landing Page Generator (specs, diferenciais)
       │
       ├──→ Schema Markup (dados estruturados)
       │
       └──→ Social Media Pipeline (posts existentes)
```

**Regra (Article IV):** Nenhum dado tecnico pode ser inventado. Todo claim em artigos SEO DEVE referenciar um ID do claims-bank.yaml (ex: LEV-01, KRA-03).

### 11.2 Fluxo de Dados

```
seo-keywords.yaml ──→ Topic Planner ──→ seleciona keywords alvo
                                              │
claims-bank.yaml ──→ Content Generator ◄──────┘
                           │
brand-guidelines.yaml ──→  │  ──→ define logo (Mendel vs Salk)
                           │
content-strategy-config.yaml ──→ define tom, pilares
                           │
                           ▼
                    Artigo/Landing Page
                           │
                           ▼
                    Human Review Gate
                           │
                           ▼
                    Publicacao + Schema Injection
```

### 11.3 Agentes Envolvidos

| Agente | Papel no SEO |
|--------|-------------|
| Atlas (estrategista) | Define editorial calendar SEO, prioriza keywords |
| Helix (copywriter) | Escreve artigos e landing pages |
| Shield (compliance) | Valida claims, verifica Article IV |
| Lens (reviewer) | Review de qualidade pre-publicacao |
| Apex (image gen) | Hero images para OG tags e artigos |

### 11.4 Novos Endpoints Necessarios

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/api/seo/articles` | GET | Lista artigos gerados |
| `/api/seo/articles` | POST | Gera novo artigo a partir de keyword + claims |
| `/api/seo/articles/:id` | PUT | Edita artigo |
| `/api/seo/landing-pages` | GET | Lista landing pages |
| `/api/seo/landing-pages/:product` | GET | Landing page de produto |
| `/api/seo/keywords` | GET | Keywords do seo-keywords.yaml |
| `/api/seo/metrics` | GET | Metricas do Search Console |
| `/api/seo/sitemap` | GET | Gera sitemap.xml |

---

## Apendice: Decisoes de Arquitetura

| Decisao | Justificativa |
|---------|---------------|
| Claims-bank como fonte unica | Constitution Article IV — nenhum dado inventado |
| Salk Medical nas landing pages | Brand guidelines — CTA de venda = Salk |
| Mendel Medical nos artigos tecnicos | Brand guidelines — specs/engenharia = Mendel |
| 2 artigos/semana na Fase 2 | Equilibrio entre qualidade e volume para nicho B2B |
| Schema MedicalDevice | Tipo mais especifico disponivel no schema.org para equipamentos medicos |
| URL em portugues sem acento | SEO best practice para mercado brasileiro |
