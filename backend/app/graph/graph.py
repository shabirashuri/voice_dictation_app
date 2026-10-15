# Note: no `from __future__ import annotations` here. LangGraph inspects the
# node type hints at runtime (e.g. RunnableConfig), which string annotations break.
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.graph.nodes.classify import classify_chunk_node
from app.graph.nodes.clean import clean_chunk_node
from app.graph.nodes.extract import extract_chunk_node
from app.graph.nodes.finalize_report import (
    final_validate_node,
    keep_comment_node,
    mark_review_node,
)
from app.graph.nodes.generate_comment import generate_comment_node
from app.graph.nodes.merge import merge_chunk_node
from app.graph.nodes.repair import repair_node, reject_node
from app.graph.nodes.validate_update import validate_update_node
from app.graph.state import LangGraphState
from app.graph.validation_router import (
    RECENT_CONTEXT_SIZE,
    route_after_clean,
    route_after_final_validate,
    route_after_validate,
)


# Each node works on a deep copy and returns only the fields it owns, so the
# underlying helper functions stay plain and testable.


async def clean_node(state: LangGraphState) -> dict:
    work = state.model_copy(deep=True)
    await clean_chunk_node(work)
    return {
        "cleaned_chunk": work.cleaned_chunk,
        "detected_fields": [],
        "updated_fields": [],
        "raw_updates": [],
        "raw_comment": None,
        "validation_errors": [],
        "retry_count": 0,
        "error_code": None,
        "error_message": None,
    }


async def classify_node(state: LangGraphState) -> dict:
    work = state.model_copy(deep=True)
    await classify_chunk_node(work)
    return {"detected_fields": work.detected_fields}


async def extract_node(state: LangGraphState, config: RunnableConfig) -> dict:
    llm = (config.get("configurable") or {}).get("llm")
    return await extract_chunk_node(state, llm=llm)


async def merge_node(state: LangGraphState) -> dict:
    work = state.model_copy(deep=True)
    await merge_chunk_node(work)
    recent = [*state.recent_context, state.cleaned_chunk or ""][-RECENT_CONTEXT_SIZE:]
    return {
        "report": work.report,
        "updated_fields": work.updated_fields,
        "previous_chunk": work.previous_chunk,
        "active_field": work.active_field,
        "recent_context": recent,
    }


def build_chunk_graph():
    """Per-chunk pipeline: clean -> classify -> extract -> validate -> (repair ->
    extract)* -> merge, or reject after the repair budget is spent."""
    graph = StateGraph(LangGraphState)
    graph.add_node("clean", clean_node)
    graph.add_node("classify", classify_node)
    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_update_node)
    graph.add_node("repair", repair_node)
    graph.add_node("reject", reject_node)
    graph.add_node("merge", merge_node)

    graph.add_edge(START, "clean")
    graph.add_conditional_edges("clean", route_after_clean, {"classify": "classify", "skip": END})
    graph.add_edge("classify", "extract")
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"merge": "merge", "repair": "repair", "reject": "reject"},
    )
    graph.add_edge("repair", "extract")
    graph.add_edge("merge", END)
    graph.add_edge("reject", END)
    return graph.compile()


async def generate_comment(state: LangGraphState, config: RunnableConfig) -> dict:
    llm = (config.get("configurable") or {}).get("llm")
    return await generate_comment_node(state, llm=llm)


def build_finish_graph():
    """Finish path: final validation -> comment decision -> (keep clinician
    comment | generate one AI comment) -> mark awaiting clinician review."""
    graph = StateGraph(LangGraphState)
    graph.add_node("final_validate", final_validate_node)
    graph.add_node("keep_comment", keep_comment_node)
    graph.add_node("generate_comment", generate_comment)
    graph.add_node("mark_review", mark_review_node)

    graph.add_edge(START, "final_validate")
    graph.add_conditional_edges(
        "final_validate",
        route_after_final_validate,
        {"keep_comment": "keep_comment", "generate_comment": "generate_comment", "invalid": END},
    )
    graph.add_edge("keep_comment", "mark_review")
    graph.add_edge("generate_comment", "mark_review")
    graph.add_edge("mark_review", END)
    return graph.compile()


chunk_graph = build_chunk_graph()
finish_graph = build_finish_graph()
