EXTRACTION_PROMPT = """
Extract structured report updates from the transcript chunk. Return JSON with `updates` list.
Each update should include: target_section, operation (append/update), content.
"""
