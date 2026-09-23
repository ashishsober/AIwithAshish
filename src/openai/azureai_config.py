import os
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv()

model_name = "qwen2.5:7b-instruct"
DEPLOYMENT = os.getenv("QWEN_MODEL", "qwen2.5:7b-instruct")

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = "2024-12-01-preview"


def get_qwen_client() -> OpenAI:
    """Create the OpenAI-compatible client for local Qwen via Ollama."""
    return OpenAI(
        base_url="http://localhost:11434/v1",
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


def chat_with_qwen(prompt: str, model: str = DEPLOYMENT, temperature: float = 0.7, max_tokens: int = 200) -> str:
    """Send a prompt to the Qwen model and return the generated text."""
    client = get_qwen_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""