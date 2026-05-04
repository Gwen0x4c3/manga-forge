from app.core.llm import get_llm_client
from app.core.vector_store import vector_store


def get_llm():
    return get_llm_client()


def get_vector_store():
    return vector_store
