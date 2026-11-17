FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Only what the /api/chat path needs (app.py -> src/openai/azureai_config.py, src/chat_store.py for history)
RUN pip install --no-cache-dir flask openai python-dotenv gunicorn mysql-connector-python==9.1.0

COPY app.py .
COPY src ./src

EXPOSE 5002
# Long timeout: local LLM responses can take a while
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--workers", "2", "--threads", "4", "--timeout", "300", "app:app"]
