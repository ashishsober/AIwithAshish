import os
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv()

# The local Ollama model. The pod gets it from QWEN_MODEL (k8s/chat-api.yaml); this default is for local runs.
# Switched from qwen3:30b-a3b to qwen3.6:35b-a3b on 2026-11-19 (same mixture-of-experts design, about 3B
# parameters per token, so similar speed; newer model).
model_name = "qwen3.6:35b-a3b"
DEPLOYMENT = os.getenv("QWEN_MODEL", model_name)

# Tokens the model may generate per answer, its thinking included (on Ollama the thinking counts too).
# qwen3.6 thinks at length: 3,213 tokens for an ordinary question in a test on 2026-11-19, so 4,096 could cut
# answers short. At about 165 tokens a second, 16,384 is under 2 minutes even in the worst case.
MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "16384"))

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = "2024-12-01-preview"


def get_qwen_client() -> OpenAI:
    """Create the OpenAI-compatible client for local Qwen via Ollama."""
    return OpenAI(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key="ollama",
    )


def get_azure_client():
    if endpoint and subscription_key:
        return AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=subscription_key,
        )
    return get_qwen_client()


def chat_with_messages(messages: list, model: str = DEPLOYMENT, temperature: float = 0.7, max_tokens: int = MAX_TOKENS) -> str:
    """Send a conversation ([{"role": "user" | "assistant", "content": ...}, ...], ending with the new
    question) to the Qwen model and return the generated reply."""
    client = get_qwen_client()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def chat_with_qwen(prompt: str, model: str = DEPLOYMENT, temperature: float = 0.7, max_tokens: int = MAX_TOKENS) -> str:
    """Send a prompt to the Qwen model and return the generated text."""
    return chat_with_messages([{"role": "user", "content": prompt}], model=model,
                              temperature=temperature, max_tokens=max_tokens)