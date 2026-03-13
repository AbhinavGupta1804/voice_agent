"""RAG service for Naturals Ice Cream knowledge base."""
import os
import logging
from pathlib import Path
from typing import List, Optional

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from ..config import Config

logger = logging.getLogger(__name__)

# Paths
DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
VECTORSTORE_PATH = Path(__file__).parent.parent.parent / "vectorstore"
KNOWLEDGE_FILE = "Natural_Ice_Cream_Final_Database.txt"



def load_knowledge_text() -> str:
    """Load knowledge base text from docs folder."""
    file_path = DOCS_DIR / KNOWLEDGE_FILE
    if not file_path.exists():
        raise FileNotFoundError(f"Knowledge file not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def chunk_knowledge(text: str) -> List[Document]:
    """Split text into chunks for vectorization."""
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n"],
        chunk_size=500,
        chunk_overlap=50
    )
    
    chunks = splitter.split_text(text)
    documents = [Document(page_content=chunk) for chunk in chunks]
    
    logger.info(f"[RAG] Created {len(documents)} chunks from knowledge base")
    return documents


def build_vectorstore(documents: List[Document]) -> FAISS:
    """Build FAISS vectorstore from documents using OpenAI embeddings."""
    embeddings = OpenAIEmbeddings(
        api_key=Config.OPENAI_API_KEY,
        model="text-embedding-3-small"
    )
    
    vectorstore = FAISS.from_documents(documents, embeddings)
    
    # Save vectorstore
    VECTORSTORE_PATH.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(VECTORSTORE_PATH))
    logger.info(f"[RAG] Vectorstore saved to {VECTORSTORE_PATH}")
    
    return vectorstore


# ── In-memory cache ──
_cached_embeddings = None
_cached_vectorstore = None


def _get_embeddings():
    """Get or create cached embeddings instance."""
    global _cached_embeddings
    if _cached_embeddings is None:
        _cached_embeddings = OpenAIEmbeddings(
            api_key=Config.OPENAI_API_KEY,
            model="text-embedding-3-small"
        )
        logger.info("[RAG] Embeddings initialized (cached)")
    return _cached_embeddings


def _get_vectorstore():
    """Get or create cached vectorstore instance."""
    global _cached_vectorstore
    if _cached_vectorstore is None:
        _cached_vectorstore = FAISS.load_local(
            str(VECTORSTORE_PATH),
            _get_embeddings(),
            allow_dangerous_deserialization=True
        )
        logger.info("[RAG] Vectorstore loaded into memory (cached)")
    return _cached_vectorstore


def get_retriever(k: int = 3):
    """Get a retriever from the cached vectorstore."""
    vectorstore = _get_vectorstore()
    return vectorstore.as_retriever(search_kwargs={"k": k})


def test_rag():
    """Test function to verify RAG pipeline is working."""
    print("=" * 50)
    print("Testing RAG Pipeline")
    print("=" * 50)
    
    # Step 1: Load text
    print("\n[1] Loading knowledge text...")
    text = load_knowledge_text()
    print(f"    Loaded {len(text)} characters")
    
    # Step 2: Chunk text
    print("\n[2] Chunking text...")
    documents = chunk_knowledge(text)
    print(f"    Created {len(documents)} chunks")
    print("\n    ==== Chunk Details ====")
    for idx, doc in enumerate(documents, start=1):
        print(f"\n    --- Chunk {idx}/{len(documents)} ---")
        print(doc.page_content)
        print("\n    ------------------------")
    
    # Step 3: Build vectorstore
    print("\n[3] Building vectorstore...")
    vectorstore = build_vectorstore(documents)
    print(f"    Vectorstore built and saved to {VECTORSTORE_PATH}")
    
    # Step 4: Test retrieval
    print("\n[4] Testing retrieval...")
    test_query = "mango ice cream"
    retriever = get_retriever(k=3)
    results = retriever.invoke(test_query)
    
    print(f"    Query: '{test_query}'")
    print(f"    Found {len(results)} results:")
    for i, doc in enumerate(results, 1):
        preview = doc.page_content[:100].replace("\n", " ")
        print(f"    [{i}] {preview}...")
    
    print("\n" + "=" * 50)
    print("RAG Pipeline Test PASSED!")
    print("=" * 50)


if __name__ == "__main__":
    test_rag()
