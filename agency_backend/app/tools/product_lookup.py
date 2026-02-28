"""
product_lookup tool — Standalone tool for Custom LLM voice calls.
=================================================================
Uses RAG (FAISS vectorstore) to retrieve product information
about Naturals Ice Cream: prices, flavors, ingredients, availability.

Interface:
    TOOL_DEFINITION  — dict describing the tool (name, description, params)
    validate(args)   — validates & cleans arguments, returns clean dict
    execute(args)    — retrieves info from RAG, returns result dict
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


# =====================================================================
# TOOL DEFINITION (used by dispatcher to build system prompt)
# =====================================================================

TOOL_DEFINITION = {
    "name": "product_lookup",
    "description": (
        "Look up Naturals Ice Cream product information. Use when customer asks about "
        "ice cream flavors, prices, ingredients, nutrition info, availability, or "
        "any product-related question."
    ),
    "parameters": {
        "query": {
            "type": "string",
            "required": True,
            "description": "The customer's product question, e.g. 'mango ice cream price'",
        },
    },
}


# =====================================================================
# VALIDATE
# =====================================================================

def validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate & clean tool arguments."""
    query = (args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required. What product info does the customer need?")
    return {"query": query}


# =====================================================================
# EXECUTE
# =====================================================================

async def execute(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute product_lookup: validates args, queries RAG vectorstore.

    Returns:
        {
            "success": True/False,
            "message": "product info or error",
            "chunks": ["chunk1", "chunk2", ...]  (if success)
        }
    """
    logger.info(f"[product_lookup] === EXECUTE START ===")
    logger.info(f"[product_lookup] Raw args: {args}")

    # Step 1: Validate
    try:
        clean_args = validate(args)
        logger.info(f"[product_lookup] Validated query: {clean_args['query']}")
    except ValueError as e:
        logger.warning(f"[product_lookup] Validation FAILED: {e}")
        return {"success": False, "message": str(e)}

    query = clean_args["query"]

    # Step 2: Retrieve from RAG
    try:
        from ..services.rag import get_retriever

        logger.info(f"[product_lookup] Querying RAG vectorstore for: '{query}'")
        retriever = get_retriever(k=3)
        docs = retriever.invoke(query)

        if not docs:
            logger.warning(f"[product_lookup] No docs found for: '{query}'")
            return {
                "success": True,
                "message": "Is savaal ke liye koi product jaankari nahi mili.",
                "chunks": [],
            }

        chunks = [doc.page_content for doc in docs]
        combined = "\n\n".join(chunks)

        logger.info(f"[product_lookup] Found {len(docs)} chunks ({len(combined)} chars)")
        for i, chunk in enumerate(chunks):
            logger.info(f"[product_lookup] Chunk[{i}]: {chunk[:120]}...")

        logger.info(f"[product_lookup] === EXECUTE DONE (success) ===")
        return {
            "success": True,
            "message": combined,
            "chunks": chunks,
        }

    except FileNotFoundError as e:
        logger.error(f"[product_lookup] Vectorstore NOT FOUND: {e}")
        return {
            "success": False,
            "message": "Abhi product database taiyaar nahi hai. Thodi der mein try karein.",
        }
    except Exception as e:
        logger.error(f"[product_lookup] Execution ERROR: {type(e).__name__}: {e}", exc_info=True)
        return {
            "success": False,
            "message": "Product lookup abhi nahi ho paa raha hai.",
        }
