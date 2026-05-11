# Security Guide

This file documents the security model of the agent and the operational rules to keep your keys and funds safe.

## Threat model

The agent runs locally with read access to your `.env` and write access to your Binance Spot account. Primary risks:

1. **Credential theft** — malware reading the `.env`, browser cookies, or shell history
2. **Supply-chain compromise** — a malicious dependency update exfiltrating keys
3. **Network tampering** — DNS hijack or local proxy redirecting API calls
4. **AI prompt injection** — market data crafted to manipulate Claude's decisions
5. **Runaway trades** — bugs or hallucinations causing oversized positions

## What the code already enforces

| Layer | Protection |
|---|---|
| `.env` permissions | Startup refuses to run if mode is wider than `600` |
| Symbol whitelist | AI's chosen symbol must be in the candidate list AND not in `EXCLUDED_SYMBOLS` |
| Double-check on execution | Executor re-validates against `EXCLUDED_SYMBOLS` even after AI validation |
| Balance ceiling | Refuses to run if USDT balance is > 3× configured budget |
| Circuit breaker | Halts new trades after 3 consecutive losses |
| Strict trade params | `MAX_TRADE_PERCENTAGE` clamped to `[0.01, 0.50]`, `STOP_LOSS` to `[0.005, 0.20]` |
| Pinned dependencies | Exact versions in `requirements.txt` — no `>=` |
| Timeouts | All HTTP calls have explicit timeouts |
| Hostname allowlist | Fear & Greed URL host is validated at runtime |
| Cloudflare account ID | Validated as 32-char hex before use |
| Order validation | Rejects orders with zero `executedQty` |
| Log permissions | `logs/` is `0700`, log files are `0600` |
| Narrow exceptions | No bare `except`; specific exception types caught |

## What you MUST do manually

### Binance API key
- Permissions: **Enable Reading** + **Enable Spot & Margin Trading** ONLY
- **NEVER** enable Withdrawals
- **NEVER** enable Futures unless explicitly using futures
- Always set an **IP allowlist** — your home IP for testing, server IP in production
- Rotate the key every 90 days

### Anthropic API key
- Set a **spending limit** in the console (`$5/month` is more than enough)
- Rotate every 90 days

### Cloudflare R2
- Use a token scoped only to the specific bucket — **never** "All R2 buckets" or "Account-level"
- Permission: **Object Read & Write** only, no admin

### .env file
- After editing, always run: `chmod 600 .env`
- Never copy `.env` between machines via Drive/Dropbox — those sync to the cloud
- Never commit it (already in `.gitignore`)

### Operational rules

- **Always test on Binance Testnet first** (`BINANCE_TESTNET=true`)
- **Always start in dry-run** (`DRY_RUN=true`) for at least a week
- **Never run in `sudo`** — the agent does not need root
- **Never run two instances** simultaneously against the same account
- **Review `logs/trader_*.log` daily** in the first month

## Incident response

If you suspect compromise:

1. Revoke ALL API keys immediately (Binance → API Management, Anthropic console, Cloudflare → R2 tokens)
2. Stop the agent: `pkill -f "python main.py"`
3. Check for persistence:
   ```bash
   ls -la ~/Library/LaunchAgents/
   ls -la ~/Library/LaunchDaemons/ 2>/dev/null
   ```
4. Check recent file creations in your home:
   ```bash
   find ~ -maxdepth 4 -newer /tmp -type f -name "*.plist" 2>/dev/null
   ```
5. Rotate the `.env`, change OS password, and re-issue all keys

## Supply chain

Before bumping any dependency in `requirements.txt`:

```bash
pip install pip-audit
pip-audit -r requirements.txt
```

Read the changelog of the bumped package. Be especially cautious with `python-binance`, `boto3`, and `anthropic`.

## Out of scope

The agent does NOT defend against:
- A compromised local user account (the OS already gives full access)
- A malicious Binance API change (you must trust the exchange)
- Severe market manipulation (flash crashes are real risk to capital — that's why capital is capped at $20)
