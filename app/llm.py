from langchain_ollama import ChatOllama
# Note that in our application architecture, this module is responsible for creating and configuring the LLM instance.
# No other file should have knowledge about LLM model specific implementaion.
#The architecture should support multiple LLM providers, and this module should be the only place where the provider is specified.  

from app.config import (
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
)

def get_llm():
    if LLM_PROVIDER == "ollama":
        return ChatOllama(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
        )
#If you want to use another LLM provider, you can add an elif block here to support it.
#In that case specify the provider name in the LLM_PROVIDER environment variable, and implement the corresponding LLM class in this module.
    raise ValueError(
        f"Unsupported LLM provider: {LLM_PROVIDER}"
    )

