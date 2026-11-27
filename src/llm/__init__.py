from src.llm.azure import build_azure_llm

BUILDER_REGISTRY = {
    "azure": build_azure_llm
}


__all__ = [
    "BUILDER_REGISTRY",
]