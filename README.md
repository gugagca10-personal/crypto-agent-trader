# Crypto Trader Agent

Agente autônomo de day trade / short-medium term em criptomoedas via Binance Spot, usando Claude AI para análise de oportunidades.

## Stack

| Camada | Tecnologia | Custo |
|---|---|---|
| Exchange | Binance Spot API (python-binance) | Grátis |
| Análise técnica | pandas-ta (RSI, MACD, BB, EMA) | Grátis |
| Análise IA | Claude Haiku (Anthropic API) | ~$0.01/dia |
| Sentimento | Alternative.me Fear & Greed | Grátis |
| Logs na nuvem | Cloudflare R2 | Grátis até 10GB |
| **Total** | | **~$0.30/mês** |

## Pipeline

```
Binance WebSocket / REST (candles 15m)
        ↓
pandas-ta → RSI, MACD, Bollinger Bands, EMA, Volume
        ↓
Filtro: signal_strength >= 25  → top 5 candidatos
        ↓
Claude Haiku → BUY / HOLD + confiança + SL/TP
        ↓
Risk Manager → position sizing (max 30% balance por trade)
        ↓
Order Executor → Binance place_market_buy
        ↓
Monitor a cada 60s → stop-loss / take-profit automático
        ↓
Cloudflare R2 → logs de trades e decisões
```

## Regras de negócio

- **Nunca** negocia BTC ou GUN (configurável via `EXCLUDED_SYMBOLS`)
- **Nunca** usa o capital já investido nessas criptos
- Capital inicial para o agente: **~$20 USDT**
- Max 2 posições abertas simultâneas
- Stop-loss padrão: 4% | Take-profit padrão: 8%
- Só executa se IA tiver ≥ 70% de confiança
- Mínimo R/R ratio: 2:1

## Setup

### 1. Pré-requisitos

```bash
python 3.11+
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Abra .env e preencha as chaves
```

**Chaves necessárias:**
- `BINANCE_API_KEY` + `BINANCE_API_SECRET` → [Binance API Management](https://www.binance.com/en/my/settings/api-management)
  - Permissões: *Enable Reading* + *Enable Spot & Margin Trading*
  - Desabilite saques por segurança
- `ANTHROPIC_API_KEY` → [Anthropic Console](https://console.anthropic.com/settings/keys)
- `CLOUDFLARE_*` → Opcional, para logs na nuvem

### 3. Testar em modo simulação

```bash
# .env: DRY_RUN=true, BINANCE_TESTNET=true
python main.py
```

Obtenha chaves do testnet em: https://testnet.binance.vision

### 4. Produção

```bash
# .env: DRY_RUN=false, BINANCE_TESTNET=false
python main.py
```

## Estrutura

```
.
├── main.py                  # Loop principal do agente
├── config.py                # Configuração via .env
├── requirements.txt
├── .env.example             # Template de variáveis (preencha → .env)
└── src/
    ├── data/
    │   ├── binance_client.py   # Wrapper Binance API
    │   └── market_data.py      # Fetch OHLCV + Fear&Greed
    ├── analysis/
    │   ├── technical.py        # Indicadores técnicos (pandas-ta)
    │   └── ai_analyzer.py      # Análise via Claude AI
    ├── trading/
    │   ├── risk_manager.py     # Position sizing, SL/TP
    │   └── executor.py         # Execução de ordens + tracking
    ├── storage/
    │   └── r2_client.py        # Cloudflare R2 para logs
    └── utils/
        └── logger.py           # Logging estruturado
```

## Hosting de baixo custo

| Opção | Custo | Indicado para |
|---|---|---|
| **Oracle Cloud Free Tier** | Grátis permanente | Produção 24/7 |
| Railway | $5/mês | Teste |
| Render | Grátis (dorme) | Não recomendado para bot |
| VPS Hetzner CX11 | €3.99/mês | Produção econômica |

## APIs utilizadas

- **Binance REST API** — candles, balance, ordens (grátis, 300k req/5min)
- **Binance WebSocket** — preços em tempo real (grátis)
- **Alternative.me** — Fear & Greed Index (grátis, sem limite documentado)
- **Anthropic Claude Haiku** — análise IA (~$0.01/dia com ciclos de 15min)

## Aviso de risco

Este software é experimental. Criptomoedas são ativos de alto risco. Nunca invista mais do que pode perder. Use em testnet primeiro.
