# Error diagnosis

## What was fixed

1. **404 – "gemini-1.5-flash is not found"**  
   The model name was updated from `gemini-1.5-flash` to `gemini-2.0-flash` in `agent.py`. The API now accepts the request.

2. **FutureWarning about `google.generativeai`**  
   Google deprecated that package in favor of `google.genai`. The app still runs; the warning is safe to ignore for now. To remove it later, you can switch to the `google-genai` package.

---

## Current error: 429 (Gemini quota / rate limit)

**Message:**  
`429 You exceeded your current quota ... limit: 0 ... Please retry in 11.949753348s`

**Meaning:**

- The **model name is correct** (no more 404).
- Gemini is **rate limiting** your project:
  - Either you’ve hit the **free-tier limit** (per minute or per day), or  
  - The reported **limit: 0** can mean the free tier isn’t enabled for this project or region.

**What you can do:**

1. **Wait and retry**  
   The message says to retry in ~12 seconds. Run again after a short wait:
   ```bash
   python main.py -q "BRICS" -o report.txt
   ```

2. **Check Gemini quota**  
   - [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)  
   - [Usage / rate limit dashboard](https://ai.dev/rate-limit)

3. **Try again later**  
   If you hit the **daily** free-tier limit, wait until the next day and run again.

4. **Use a different key**  
   Create a new API key in [Google AI Studio](https://aistudio.google.com/apikey) (e.g. in a different Google account or project) and set that as `GEMINI_API_KEY` in `.env`.

5. **Use OpenAI instead**  
   If you have OpenAI quota again, remove or comment out `GEMINI_API_KEY` in `.env` and set `OPENAI_API_KEY`. The app will use OpenAI when `GEMINI_API_KEY` is not set.

---

## Summary

| Issue              | Status   | Action                                      |
|--------------------|----------|---------------------------------------------|
| 404 wrong model    | Fixed    | Model set to `gemini-2.0-flash` in code      |
| Deprecation warning| Informational | Safe to ignore; optional: migrate to `google-genai` |
| 429 quota/rate     | Current  | Wait and retry, check quota, or use another key/OpenAI |
