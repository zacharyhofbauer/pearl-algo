# LLM Provider Setup Guide

## Supported Providers

The LangGraph system supports **3 LLM providers** for agent reasoning:

1. **Groq** (Direct integration - Recommended for free tier)
2. **OpenAI** (Via LiteLLM)
3. **Anthropic Claude** (Via LiteLLM)

## Quick Setup

### 1. Get API Keys

- **Groq**: https://console.groq.com (Free tier available)
- **OpenAI**: https://platform.openai.com/api-keys
- **Anthropic**: https://console.anthropic.com/

### 2. Add to .env File

Add your API keys to `.env`:

```bash
# Choose one or all
GROQ_API_KEY=your_groq_key_here
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
```

### 3. Configure in config.yaml

Edit `config/config.yaml` to select your provider:

```yaml
llm:
  provider: "groq"  # Options: "groq", "openai", "anthropic"
  
  groq:
    api_key: "${GROQ_API_KEY}"
    model: "mixtral-8x7b-32768"
  
  openai:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o"  # or "gpt-4-turbo", "gpt-4o-mini"
  
  anthropic:
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-3-opus-20240229"  # or "claude-3-sonnet-20240229"
```

## Available Models

### Groq
- `mixtral-8x7b-32768` (default)
- `llama-3-70b-8192`
- `llama-3-8b-8192`

### OpenAI
- `gpt-4o` (default)
- `gpt-4-turbo`
- `gpt-4o-mini`

### Anthropic
- `claude-3-opus-20240229` (default)
- `claude-3-sonnet-20240229`
- `claude-3-haiku-20240307`

## Usage

The Quant Research Agent will automatically use the configured LLM provider to:
- Explain why trading signals were generated
- Analyze market regime (trending vs ranging)
- Provide risk/reward assessments

## Cost Considerations

- **Groq**: Free tier available, very fast
- **OpenAI**: Pay-per-use, high quality
- **Anthropic**: Pay-per-use, excellent reasoning

You can switch providers anytime by changing `llm.provider` in `config.yaml`.
