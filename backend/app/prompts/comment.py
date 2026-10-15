"""Prompt for the one-time AI comment generated at finalize."""

REPORT_FIELDS = (
    "patient",
    "specimen",
    "gross_description",
    "microscopic_description",
    "diagnosis",
    "comments",
)


def build_comment_prompt(report: dict) -> str:
    """Build the comment prompt from the validated report fields only."""
    lines = [
        "You are an assistant that generates a concise clinician-facing comment based ONLY on the provided report fields.\n",
        "Do NOT invent findings, do not modify any fields except to produce the comment text.\n",
        "Do not state that something is absent, normal or negative unless the report says so.\n",
        "Do not add numbers, measurements, laterality or diagnoses that are not in the report.\n",
        "Return only the comment text (no JSON).\n\n",
        "Report:\n",
    ]
    lines.extend(f"{field}: {report.get(field) or ''}\n" for field in REPORT_FIELDS)
    return "".join(lines)
