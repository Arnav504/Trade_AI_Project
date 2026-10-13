# Why OpenAI, Ollama, or Google (Gemini) API Calls Work or Don’t

This document traces how the project chooses and calls each LLM and what can make each path succeed or fail.

---

## 1. Where the choice happens

All LLM calls go through **`agent.run_agent()`** in `agent.py`. The backend is chosen in this order:

```
run_agent()
  ├─ 1. use_local_ollama()  → True?  → _run_agent_ollama()   [Ollama]
  ├─ 2. get_gemini_api_key() → truthy? → _run_agent_gemini() [Google Gemini]
  ├─ 3. _get_client()       → not None? → OpenAI API loop    [OpenAI]
  └─ 4. else                → return generic error string
```

So:

- **Ollama** is used only if `use_local_ollama()` is True.
- **Gemini** is used only if Ollama was skipped and `get_gemini_api_key()` is non-empty.
- **OpenAI** is used only if both Ollama and Gemini were skipped and `_get_client()` is not None.
- If none of the above, the user sees:  
  `"Error: Set USE_LOCAL_LLM=1 and run Ollama, or set OPENAI_API_KEY or GEMINI_API_KEY in .env."`

---

## 2. Where config comes from

- **`config.py`** reads everything from **environment variables**.
- Each function that needs env vars first tries to load **`.env`** from the project root (`PROJECT_ROOT / ".env"`) via `python-dotenv`, then reads `os.environ`.
- **`main.py`** loads `.env` at import time (lines 14–19) so that when `run_agent()` runs, the env is already set.
- **Evaluation scripts** (`evaluation/run_evaluation.py`, `evaluation/adversarial_test.py`) also load `.env` from `PROJECT_ROOT` before importing the agent.

So for any backend to be chosen and work:

1. **`.env` must be loadable** from the project root (path, permissions, and that the file isn’t ignored by the environment you run in).
2. **The right variables** must be set in `.env` (or in the shell) so that the corresponding config function returns a truthy value or a valid client.

---

## 3. Ollama (local LLM)

**Config (in `config.py`):**

- `use_local_ollama()` is True if:
  - `USE_LOCAL_LLM` is set to `1`, `true`, or `yes` (case-insensitive), **or**
  - `OLLAMA_MODEL` is set to any non-empty string.
- `get_ollama_base_url()` → default `http://localhost:11434/v1`.
- `get_ollama_model()` → from `OLLAMA_MODEL`, default `llama3.2`.

**What runs (in `agent.py`):**

- `_run_agent_ollama()`:
  1. Calls tools to build context (no LLM yet).
  2. Does `from openai import OpenAI` (OpenAI-compatible client).
  3. Builds `OpenAI(base_url=base_url, api_key="ollama")` and calls `client.chat.completions.create(...)` with that base URL (Ollama).

**Ollama works when:**

- `.env` is loaded and has `USE_LOCAL_LLM=1` (or `OLLAMA_MODEL=...`).
- The **`openai`** Python package is installed (`pip install openai` / `requirements.txt`).
- **Ollama** is running (e.g. `ollama serve`) and reachable at `OLLAMA_BASE_URL` (default localhost:11434).
- The model in `OLLAMA_MODEL` is pulled (e.g. `ollama pull qwen2:7b`).

**Ollama fails when:**

| Cause | What you see |
|------|----------------------|
| `.env` not loaded | `USE_LOCAL_LLM` / `OLLAMA_MODEL` not set → Ollama branch skipped; Gemini or OpenAI or generic error. |
| `openai` not installed | `Ollama error (...): No module named 'openai'` (from the `except` in `_run_agent_ollama`). |
| Ollama not running / wrong URL | `Ollama error (...): Connection refused` or similar. |
| Model not pulled | Ollama returns an error; it’s wrapped in `Ollama error (...): <message>`. |

---

## 4. Google Gemini

**Config:**

- `get_gemini_api_key()` returns `os.environ.get("GEMINI_API_KEY", "").strip()` or `None`.
- `get_gemini_model()` → from `GEMINI_MODEL`, default `gemini-2.0-flash`.

**What runs:**

- `_run_agent_gemini()`:
  1. `import google.generativeai as genai` → can raise **ImportError** if the package isn’t installed.
  2. `genai.configure(api_key=key)` and `genai.GenerativeModel(...).generate_content(prompt)`.

**Gemini works when:**

- **Ollama is not chosen** (e.g. `USE_LOCAL_LLM=0` or unset, and `OLLAMA_MODEL` unset).
- `.env` is loaded and has a non-empty **`GEMINI_API_KEY`**.
- The **`google-generativeai`** package is installed (`pip install google-generativeai`).  
  **Note:** `requirements.txt` did not originally list it; the README does. If you only install from `requirements.txt`, Gemini will fail with an import error until you add this dependency.
- Network allows HTTPS to Google’s API; key is valid and has quota.

**Gemini fails when:**

| Cause | What you see |
|------|----------------------|
| Ollama chosen first | Gemini never runs (Ollama path taken). |
| `.env` not loaded / no key | `get_gemini_api_key()` is falsy → generic error or next backend. |
| `google-generativeai` not installed | `Error: Install with: pip install google-generativeai`. |
| 429 / quota | One retry; then `[API quota exceeded - sample report]` + error message. |
| Invalid key / network | `Gemini API error: <details>`. |

---

## 5. OpenAI

**Config:**

- `_get_client()` in `agent.py`:
  1. `from openai import OpenAI` → can raise **ImportError** (then returns `None`).
  2. `key = get_openai_api_key()` (from `config.py`: `OPENAI_API_KEY` in env).
  3. If `key` is truthy, returns `OpenAI(api_key=key)`; else returns `None`.
- `get_openai_model()` → from `OPENAI_MODEL`, default `gpt-4o-mini`.

**What runs:**

- If `_get_client()` is not None, `run_agent()` uses the OpenAI client in a loop with tools (and optional tool calls) until the model returns text with `REPORT_START` / `REPORT_END` or max rounds.

**OpenAI works when:**

- **Ollama and Gemini are both skipped** (no `USE_LOCAL_LLM=1`/`OLLAMA_MODEL`, and no `GEMINI_API_KEY`).
- `.env` is loaded and has a non-empty **`OPENAI_API_KEY`**.
- The **`openai`** package is installed.
- Network and key are valid; account has quota.

**OpenAI fails when:**

| Cause | What you see |
|------|----------------------|
| Ollama or Gemini chosen first | OpenAI never runs. |
| `.env` not loaded / no key | `_get_client()` is None → generic error: "Set USE_LOCAL_LLM=1 and run Ollama, or set OPENAI_API_KEY or GEMINI_API_KEY in .env." |
| `openai` not installed | ImportError in `_get_client()` → returns None → same generic error. |
| Invalid key / quota / network | Exception during `client.chat.completions.create(...)` (not always caught and turned into a friendly message). |

---

## 6. Summary table

| Backend | Chosen when | Needs in env | Needs installed | Common failure |
|---------|-------------|--------------|------------------|----------------|
| **Ollama** | `USE_LOCAL_LLM=1` or `OLLAMA_MODEL` set | `.env` loaded, Ollama URL/model optional | `openai` | `.env` not loaded; `openai` missing; Ollama not running |
| **Gemini** | Ollama not chosen, `GEMINI_API_KEY` set | `GEMINI_API_KEY` | `google-generativeai` | Ollama chosen first; package not in requirements; key/quota |
| **OpenAI** | Ollama and Gemini both not chosen, `OPENAI_API_KEY` set | `OPENAI_API_KEY` | `openai` | Ollama/Gemini chosen first; no key; `openai` missing |

---

## 7. Fixes applied in this project

- **`requirements.txt`** was updated to include **`google-generativeai`** so that `pip install -r requirements.txt` is enough for Gemini when you set `GEMINI_API_KEY` and don’t use Ollama.
- This document (**`API_LLM_DIAGNOSIS.md`**) was added so you can see exactly why OpenAI, Ollama, or Google API calls are working or not, and what to set/install for each backend.
