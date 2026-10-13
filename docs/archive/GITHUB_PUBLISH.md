# Publish ASAN Macro to GitHub

Your project is already a git repo with an initial commit on branch `main`. Follow these steps to put it on GitHub.

---

## Option A: Create the repo on GitHub, then push (recommended)

### 1. Create a new repository on GitHub

1. Go to [github.com/new](https://github.com/new).
2. **Repository name:** e.g. `asan-macro` or `AI-Project`.
3. **Description (optional):** e.g. `Maritime & trade analysis agent with LLM (Ollama/Gemini/OpenAI)`.
4. Choose **Public**.
5. **Do not** check "Add a README" or "Add .gitignore" (you already have them).
6. Click **Create repository**.

### 2. Push your local repo to GitHub

GitHub will show you commands. Use these (replace `YOUR_USERNAME` and `YOUR_REPO` with your GitHub username and repo name):

```bash
cd "/Users/arnavsahai/Desktop/AI Propject"

# Add GitHub as the remote "origin"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Push your main branch
git push -u origin main
```

**Example:** If your username is `arnavsahai` and repo is `asan-macro`:
```bash
git remote add origin https://github.com/arnavsahai/asan-macro.git
git push -u origin main
```

If GitHub asks for login, use your GitHub username and a **Personal Access Token** (not your password). Create one at: [github.com/settings/tokens](https://github.com/settings/tokens) (scope: `repo`).

---

## Option B: Using GitHub CLI (`gh`)

If you have [GitHub CLI](https://cli.github.com/) installed:

```bash
cd "/Users/arnavsahai/Desktop/AI Propject"
gh auth login
gh repo create asan-macro --public --source=. --remote=origin --push
```

---

## After publishing

- Your repo URL will be: `https://github.com/YOUR_USERNAME/YOUR_REPO`
- For the course: share this URL with your instructor (ensure the repo is **Public** or that the instructor has access).
- To update the repo later:
  ```bash
  git add .
  git commit -m "Your message"
  git push
  ```

---

## Important: `.env` is not pushed

Your `.env` file (with API keys) is in `.gitignore`, so it **will not** be uploaded. Anyone who clones the repo should copy `.env.example` to `.env` and add their own keys. The README explains this.
