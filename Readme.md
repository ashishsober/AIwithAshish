
# AIwithAshish

## Tech Stack

### AI/ML

| Component   | Technology                                          |
|-------------|-----------------------------------------------------|
| Backend     | FastAPI                                             |
| Orchestration | LangGraph — orchestrate the AI agents             |
| Inference   | Groq — fast and free LLM inference                 |
| Embeddings  | Jina AI                                             |
| Database    | PostgreSQL with PGVector for vector search          |
| Hosting     | Vercel (free tier)                                  |

### Infrastructure & DevOps

| Area    | Tools                                               |
|---------|-----------------------------------------------------|
| Infra   | AWS free tier ($200 credits)                        |
| DevOps  | OpenTofu, CircleCI / GitHub Actions, GitHub, Docker |
| Quality | Sentry, Opik, CloudWatch, Ruff, MyPy                |

## Screenshots

![Graph](static/image.png)

![Graph 2](static/image-1.png)

![Graph 3](static/image-2.png)

### React Agent

![React Agent](static/reactagent.png)

## Setup

### PostgreSQL

```bash
brew services start postgresql@14
psql --version
```

> Default superuser password: `Testing@123`

### Azure OpenAI API Key

```bash
echo 'export AZURE_OPENAI_API_KEY="api_key"' >> ~/.zshrc
source ~/.zshrc
```

- Dashboard: https://platform.openai.com/
- API Keys: https://platform.openai.com/api-keys

## Debugging

```
n            # next
s            # step in
p <variable> # print variable
c            # continue
```