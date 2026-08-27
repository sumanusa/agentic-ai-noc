import os

from dotenv import load_dotenv

load_dotenv()


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

