import re

def _extract_between(s: str, left: str, right: str, get_last: bool = True) -> str:
    """
    Extract substring between regex patterns (delimiters excluded).
    """
    pattern = f".*{left}(.*?){right}" if get_last else f"{left}(.*?){right}"
    match = re.search(pattern, s, re.DOTALL)
    return match.group(1) if match else ""

def extract_md_codeblock(s: str) -> str:
    """
    Extract content of the last fenced code block from markdown.
    """
    return _extract_between(s, r"```\S*\n", r"```", get_last=True)

def extract_pesudo_xml(s: str, tag: str) -> str:
    """
    Extract content inside pseudo-xml tag from text.
    """
    return _extract_between(s, f"<{tag}.*?>", f"</{tag}>", get_last=True)
