import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.openai.azureai_config import chat_with_qwen


def ask_qwen(prompt: str, model: str = "qwen2.5:7b-instruct") -> str:
    """Convenience wrapper for calling the project Qwen/Ollama client."""
    return chat_with_qwen(prompt, model=model)


if __name__ == "__main__":
    print(ask_qwen("Say hello from Qwen in one short sentence."))
