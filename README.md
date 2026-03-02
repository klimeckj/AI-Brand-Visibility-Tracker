# AI Brand Visibility Tracker

> **⚠️ Testing prototype** — The n8n workflow integration requires a locally running n8n instance and is not available in the deployed version. Queries sent via the form will fail to connect.

A lightweight intelligence tool that continuously monitors how large language models represent a given brand in their responses — without any human bias in the evaluation loop.

---

## Business Value

In a world where consumers increasingly turn to AI assistants (ChatGPT, Gemini, Perplexity) instead of search engines, **organic search rank no longer tells the full story**. A brand can rank #1 on Google while being completely invisible — or negatively framed — inside LLM responses.

This tool answers a concrete business question:

> *"When a potential customer asks an AI about my product category, does my brand appear — and in what light?"*

Practical use cases:

- **Brand managers** track visibility across prompt types (informational, commercial, competitor) and catch sentiment shifts early.
- **Marketing teams** benchmark against competitors that the AI spontaneously names alongside (or instead of) their brand.
- **Product & SEO teams** get a data signal for content strategy: which brand narratives are being reinforced by LLMs, and which are missing.
- **Executives** gain a repeatable, auditable metric — visibility rate over time — rather than relying on anecdotal AI interactions.

All results are exportable to CSV for further analysis or reporting.

---

## Architecture Overview

```
┌─────────────────────────────────────┐
│          Streamlit Frontend         │
│  (Python · config-driven · REST     │
│   client · session state · export)  │
└────────────────┬────────────────────┘
                 │  HTTP POST  /analyze-brand
                 ▼
┌─────────────────────────────────────┐
│         n8n Workflow Engine         │
│          (self-hosted)              │
│                                     │
│  [1] Webhook Trigger                │
│       ↓                             │
│  [2] LLM Call – Unbiased Response   │──► Google Gemini API
│       ↓                             │    (Gemma 3 4B)
│  [3] LLM Call – Structured Analysis │──► Google Gemini API
│       ↓                             │    (Gemma 3 4B)
│  [4] JS Code – Parse & Sanitize     │
│       ↓                             │
│  [5] Webhook Response (JSON)        │
└─────────────────────────────────────┘
```

### Component Responsibilities

| Layer | Technology | Role |
|---|---|---|
| Frontend | Python / Streamlit | User input, result rendering, CSV export, session state |
| Orchestrator | n8n (self-hosted) | Workflow sequencing, HTTP integrations, data transformation |
| LLM Service | Google Gemini REST API (Gemma 3 4B) | Text generation + structured output analysis |
| Config | `config.json` | API key and webhook endpoint — kept outside source code |

---

## Two-Stage LLM Pipeline

The core of the system is a deliberately **two-prompt architecture** designed to eliminate confirmation bias:

### Stage 1 — Unbiased Response Generation

The LLM answers the user's prompt as it naturally would, with no mention of the target brand in the system instruction. This simulates the actual experience of a real user asking the same question.

```
Prompt: "Answer the following question in 3-5 sentences.
         Be factual and mention specific brands, products,
         or companies where relevant.

         Question: {user_prompt}"
```

This ensures the resulting text reflects the model's genuine knowledge representation, not a guided answer.

### Stage 2 — Structured Analysis

The raw Stage 1 text is passed to a second LLM call, together with the brand name and optional business description. The model is instructed to return **only** a JSON object:

```json
{
  "is_visible": true,
  "sentiment": "POSITIVE",
  "context": "The brand was mentioned as a leading option for...",
  "competitors": ["CompetitorA", "CompetitorB"]
}
```

Constraining the output to a strict schema allows downstream parsing to be deterministic. The prompt is designed to handle the `NONE` sentiment state explicitly — avoiding ambiguous `null` values when a brand is absent.

### Stage 3 — Output Sanitization (n8n Code Node)

LLMs occasionally wrap JSON in markdown fences (` ```json ... ``` `). The JavaScript code node strips this formatting before parsing, with a structured fallback that surfaces the raw output rather than silently failing:

```js
const cleanJsonText = rawLlmText
  .replace(/```json/gi, '')
  .replace(/```/g, '')
  .trim();

try {
  visibilityData = JSON.parse(cleanJsonText);
} catch (error) {
  visibilityData = {
    is_visible: false,
    sentiment: "UNKNOWN",
    context: "Parse error — raw output: " + rawLlmText.substring(0, 120),
    competitors: [],
    parse_error: true
  };
}
```

This makes parser failures visible and traceable in the UI, rather than surfacing as empty or misleading results.

---

## Integration Details

### Streamlit → n8n (REST)

The frontend sends a synchronous POST request to the n8n webhook. The payload carries only what the workflow needs:

```python
payload = {
    "brand": brand,
    "prompt": prompt,
    "api_key": API_KEY,
    "brand_description": brand_description
}
response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=30)
```

The `timeout=30` guard and explicit exception handling (`Timeout`, generic `Exception`) ensure that a slow or unavailable n8n instance degrades gracefully with a user-visible error rather than a silent hang.

### n8n → Google Gemini API (REST)

Both LLM calls in n8n are HTTP Request nodes hitting the Gemini REST endpoint directly:

```
POST https://generativelanguage.googleapis.com/v1beta/models/gemma-3-4b-it:generateContent?key={api_key}
```

The API key is passed through from the Streamlit payload rather than stored in n8n credentials, which keeps the workflow portable — any authorised caller can supply their own key. This also means the key never persists inside the n8n workflow definition or its logs at rest.

---

## Data & Security Considerations

- **API keys** are stored in `config.json`, which is excluded from version control (`.gitignore`). They are not hardcoded in application logic.
- **User prompts and brand descriptions** are treated as transient inputs — they are not persisted to any external database; results live only in Streamlit session state for the duration of the browser session.
- **LLM inputs do not contain PII by design**. The brand description field is optional and scoped to business context only.
- **n8n self-hosting** means all orchestration traffic stays within the operator's own infrastructure; no prompt data is routed through a third-party automation SaaS.
- The webhook endpoint is path-scoped (`/analyze-brand`) and intended to be placed behind a reverse proxy or VPN in production deployments.
- Audit trail: each result record is timestamped and carries the full raw JSON from n8n, supporting post-hoc inspection of what the model actually returned.

---

## Cost & Performance Notes

- **Model choice (Gemma 3 4B)**: A smaller, instruction-tuned model is sufficient for both the generation and the classification task. Using a lighter model over GPT-4-class alternatives reduces per-query API cost significantly while maintaining adequate output quality for brand mention detection.
- **Two sequential LLM calls** are the current bottleneck. In a higher-throughput scenario, Stage 1 results could be cached by prompt hash, calling Stage 2 only when a fresh analysis is needed.
- **Timeout at 30 s** is conservative for a 4B-parameter model; this can be tuned down once baseline latency is profiled per deployment environment.
- The `Force Rerun` feature in the Dashboard intentionally appends new records rather than overwriting, enabling statistical visibility tracking across multiple runs of the same prompt — a basic but effective technique for measuring output consistency and variance over time.

---

## Local Setup

**Prerequisites:** Python 3.10+, n8n (self-hosted), Google Gemini API key.

```bash
# 1. Clone and install dependencies
pip install -r requirements.txt

# 2. Create config.json
{
  "n8n_webhook_url": "http://localhost:5678/webhook/analyze-brand",
  "gemini_api_key": "YOUR_GEMINI_API_KEY"
}

# 3. Import n8n.json into your n8n instance and activate the workflow

# 4. Run the app
streamlit run app.py
```

The app will be available at `http://localhost:8501`.

---

## Project Structure

```
├── app.py            # Streamlit frontend — UI, API client, session state
├── n8n.json          # n8n workflow export — webhook, LLM calls, parser
├── config.json       # Runtime config — API keys and webhook URL (not versioned)
├── requirements.txt  # Python dependencies
└── README.md
```

