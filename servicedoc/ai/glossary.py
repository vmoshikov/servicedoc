from __future__ import annotations


def glossary_system_block(glossary_text: str | None) -> str | None:
    """Formats GLOSSARY.md content as an extra system-prompt segment, so
    every AI call (batch describe, release notes, README overview) uses the
    same internal terminology."""
    if not glossary_text:
        return None
    return f"## Глоссарий терминов проекта (используй эти определения)\n\n{glossary_text}"
