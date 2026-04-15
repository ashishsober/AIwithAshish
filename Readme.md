
# AIwithAshish

## Project Description

AIwithAshish is an intelligent agent orchestration platform that leverages advanced AI/ML technologies to build and deploy sophisticated multi-agent systems. The project combines LangGraph for workflow orchestration, FastAPI for backend services, and cutting-edge LLM inference to create intelligent agents capable of complex decision-making and task execution.

This platform supports multiple agent types including a React agent, a drafter agent, and custom Azure OpenAI-powered agents. It enables conditional routing, looping workflows, and multi-route graph execution for flexible and powerful agent behavior. The system is designed to scale efficiently using cloud infrastructure and is production-ready with comprehensive quality assurance tools.

**Key Features:**
- Multi-agent orchestration with LangGraph
- Conditional workflow graphs
- Looping workflow graphs
- Multi-route workflow graphs
- React agent implementation
- Drafter agent implementation
- Azure OpenAI integration

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

| Type           | Emoji   | Example Usage                              |
| -------------- | ------- | ------------------------------------------ |
| Info           | ℹ️      | `print("ℹ️ Info: Starting service...")`    |
| Success        | ✅       | `print("✅ WebSocket connected")`           |
| Warning        | ⚠️      | `print("⚠️ High memory usage detected")`   |
| Error          | ❌      | `print("❌ Failed to fetch data")`          |
| Critical       | 🔥      | `print("🔥 System overload")`              |
| Debug          | 🐞      | `print("🐞 Debug: packet =", packet)`      |
| Ping/Pong      | 📡 / 🏓 | `print("🏓 Pong received from server")`    |
| Connecting     | 🌐      | `print("🌐 Connecting to WebSocket...")`   |
| Reconnecting   | ♻️      | `print("♻️ Reconnecting...")`              |
| Disconnect     | 🔌      | `print("🔌 WebSocket disconnected")`       |
| Cleanup        | 🧹      | `print("🧹 Cleaning up resources")`        |
| Subscribed     | 📬      | `print("📬 Subscribed to ticker XYZ")`     |
| Unsubscribed   | 📭      | `print("📭 Unsubscribed from ticker XYZ")` |
| Packet Decoded | 📦      | `print("📦 Decoded packet:", packet)`      |
| Retry Attempt  | 🔁      | `print(f"🔁 Attempt {n}/5 to reconnect")`  |
| Timestamp      | 🕒      | `print("🕒 Received at:", timestamp)`      |
| File Read      | 📄      | `print("📄 Loaded tickers.txt")`           |
| Market Closed  | 🛑      | `print("🛑 Market closed")`                |
| Market Up      | 📈      | `print("📈 Price moving up")`              |
| Market Down    | 📉      | `print("📉 Price moving down")`            |
| Bullish Move   | 🟢      | `print("🟢 Bullish crossover detected")`   |
| Bearish Move   | 🔻      | `print("🔻 Bearish crossover detected")`   |
🔻
🔔
 # 🔒 ACQUIRE LOCK
 | Type                | Emoji   | Example Usage                                      |
|---------------------|---------|----------------------------------------------------|
| Trade Executed      | 🛒      | `print("🛒 Trade executed at price", price)`        |
| Trade Rejected      | 🚫      | `print("🚫 Trade rejected")`                        |
| Trade Pending       | ⏳      | `print("⏳ Trade pending confirmation")`            |
| Profit              | 💰      | `print("💰 Profit booked:", profit)`                |
| Loss                | 💸      | `print("💸 Loss incurred:", loss)`                  |
| Watchlist           | 👀      | `print("👀 Watching symbol:", symbol)`              |
| Alert               | 🚨      | `print("🚨 Price alert triggered!")`                |
| Settings/Config     | ⚙️      | `print("⚙️ Loading config...")`                    |
| Chart/Graph         | 📊      | `print("📊 Chart updated")`                        |
| Calculation         | 🧮      | `print("🧮 Calculating indicators...")`             |
| API Call            | 🌐      | `print("🌐 API request sent")`                      |
| Database            | 🗄️      | `print("🗄️ Writing to database")`                   |
| Save/Write          | 💾      | `print("💾 Data saved")`                            |
| Loading             | ⏱️      | `print("⏱️ Loading data...")`                      |
| Refresh/Update      | 🔄      | `print("🔄 Data refreshed")`                        |
| Star/Favorite       | ⭐      | `print("⭐ Favorite symbol added")`                  |
| Question/Help       | ❓      | `print("❓ Need help?")`                            |
| Up Arrow            | ⬆️      | `print("⬆️ Price breakout detected")`               |
| Down Arrow          | ⬇️      | `print("⬇️ Price breakdown detected")`              |
| Pause               | ⏸️      | `print("⏸️ Pausing trading...")`                    |
| Resume              | ▶️      | `print("▶️ Resuming trading...")`                   |
| Lock/Unlock         | 🔒/🔓   | `print("🔒 Lock acquired")` / `print("🔓 Lock released")` |