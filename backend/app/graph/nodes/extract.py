from __future__ import annotations


def _previous_context(state):
    return (
        getattr(state, "previous_chunk", "") or "",
        getattr(state, "active_field", None),
    )


async def extract_chunk_node(state, llm=None) -> dict:
    """Node: extract structured FieldUpdate items from `state.cleaned_chunk`.

    Uses an injected `llm` implementing `extract(prompt, **kwargs)`.
    Appends an `ExtractedChunk` to `state.extracted_data` and returns it.
    The LLM is expected to return only information explicitly spoken by the
    doctor; this node enforces that by prompt design but delegates to `llm`.
    """
    from app.graph.state import ExtractedChunk, FieldUpdate, Comment

    cleaned = getattr(state, "cleaned_chunk", "") or ""
    detected = getattr(state, "detected_fields", []) or []

    # If no cleaned text, return empty extraction
    if not cleaned:
        extracted = ExtractedChunk(chunk_text="", updates=[])
        state.extracted_data.append(extracted)
        return {"extracted_chunk": extracted}

    previous_chunk, active_field = _previous_context(state)
    report = getattr(state, "report", None)
    if report is None:
        report_state = {}
    elif hasattr(report, "model_dump"):
        report_state = report.model_dump()
    else:
        report_state = report.dict()

    # The provider owns the extraction prompt and structured response contract.
    prompt = (
        "Apply the extraction rules to the current transcript. "
        "Preserve the doctor's wording in update content."
    )

    # Use Groq as the single configured provider, or dummy when no key exists.
    if llm is None:
        try:
            from app.services.llm.provider import build_default_llm

            llm = build_default_llm()
        except Exception:
            try:
                from app.services.llm.provider import DummyLLM

                llm = DummyLLM()
            except Exception:
                llm = None

    # Call the provider with all context needed for continuation detection.
    updates_list = []
    comment = None
    if llm is not None:
        resp = await llm.extract(
            prompt=prompt,
            chunk=cleaned,
            report_state=report_state,
            detected_fields=detected,
            previous_chunk=previous_chunk,
            active_field=active_field,
        )
        if not isinstance(resp, dict):
            raise TypeError("LLM extraction response must be a dictionary")

        for raw_update in resp.get("updates") or []:
            updates_list.append(FieldUpdate(**raw_update))

        # Preserve compatibility with injected test/providers that explicitly
        # return a doctor comment object. The production provider returns only
        # the six-field updates contract.
        raw_comment = resp.get("comment")
        if raw_comment and isinstance(raw_comment, dict):
            comment = Comment(**raw_comment)

    extracted = ExtractedChunk(chunk_text=cleaned, updates=updates_list, comment=comment)
    state.extracted_data.append(extracted)

    return {"extracted_chunk": extracted}
