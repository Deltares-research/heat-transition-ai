from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider


def build_azure_llm(model_name: str = "gpt-5.6-sol") -> type[Model[AsyncOpenAI]]:

    load_dotenv(Path(__file__).parents[2] / "secrets/azure_llm.env")

    return OpenAIChatModel(
        model_name=model_name,
        provider=AzureProvider(
            azure_endpoint=os.environ["API_BASE"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ["OPENAI_API_VERSION"],
        ),
    )
