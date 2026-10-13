# Presenting ASAN Macro on LinkedIn

Use this guide to describe and showcase the project on LinkedIn as a solo-built, data-driven AI agent.

---

## Elevator pitch (1–2 sentences)

I built **ASAN Macro**, an AI-powered trade analysis agent that turns raw trade data (CSV, URLs, optional APIs) into structured sentiment reports with “so what” and “what’s next” insights—using an LLM plus a database, RAG, and custom analysis tools (YoY growth, top flows, trends).

---

## Key bullets for your post or profile

- **Solo end-to-end build**: Architecture, tools, multi-backend agent, evaluation, adversarial safety, Comtrade ingest, and scheduling.
- **Dynamic data**: Ingest from local CSV, CSV URLs, and optional JSON APIs (e.g. UN Comtrade–style) so analysis isn’t limited to static files.
- **Richer analysis**: Custom tools for year-over-year growth, top flows by value, and trade trends so the LLM reasons over real metrics, not just raw rows.
- **LLM flexibility**: Supports OpenAI, Google Gemini, and local Ollama; model choice via env.
- **Responsible AI:** Query guard blocks instruction overrides before the model runs. Unit tests cover that guard. A live model run of inputs that pass the guard is not recorded yet.
- **Stack**: Python, SQLite, OpenAI / Gemini / Ollama, RAG-style retrieval, function-calling agents.

---

## Suggested LinkedIn post template

**Headline (optional):**  
Built an AI agent that turns trade data into executive-style sentiment reports.

**Body:**  
I designed and built **ASAN Macro** solo: an AI agent that analyzes trade data to study shifts in global trade (e.g. BRICS, US–China decoupling, South–South trade).

- **Data:** Dynamic ingestion—local CSV, CSV from URLs, and optional APIs—so the pipeline isn’t tied to one static dataset.
- **Analysis:** Custom tools compute YoY growth, top flows, and trends so the LLM can cite real numbers and themes.
- **Models:** Configurable OpenAI / Gemini / local Ollama, with a true tool-calling loop on OpenAI and portable single-shot backends for demos.
- **Assurance:** Evaluation for report completeness plus adversarial tests for prompt leak / jailbreak-style misuse.
- **Next (proposed by me):** Embedding RAG with citations, groundedness metrics, prompt-injection guards, tool-call tracing, and CI.

Tech: Python, SQLite, RAG, tool-augmented LLMs. Example of turning messy trade data into clear “so what” and “what’s next” for strategy and policy.

[Link to repo or demo]

---

## How to demo in a post or video

1. **Show the command:**  
   `python main.py -q "BRICS" -o report.txt -f linkedin`
2. **Show the report** (or a snippet) and the generated `LINKEDIN_SUMMARY.txt`.
3. **Mention data options:**  
   “I can point it at a CSV on the web with `--data-url` or load from an API so the same pipeline works for different data sources.”
4. **Optional:** Show `-f html` and open the generated HTML in a browser for a shareable report.

---

## Skills and keywords to include

- **AI/ML:** LLM agents, RAG, function calling, prompt engineering  
- **AI security:** Adversarial testing, prompt-injection awareness, secrets hygiene  
- **Data:** Data ingestion pipelines, SQL, CSV/JSON, optional API integration  
- **Analysis:** Trade analysis, sentiment synthesis, YoY growth, trend detection  
- **Tech:** Python, SQLite, OpenAI API, Google Gemini, Ollama  

---

## Repo description (short)

**ASAN Macro** – Solo-built AI trade analysis agent. Dynamic data ingestion (CSV, URLs, APIs), custom analysis tools (YoY growth, top flows, trends), multi-backend LLMs (OpenAI, Gemini, Ollama), evaluation + adversarial safety. Sentiment reports with “so what” and “what’s next.” Python, SQLite, RAG, tool-augmented LLMs.
