import re

def _extract_between(s: str, l: str, r: str, get_last: bool = True) -> str:
    """
    Extract substring between regex patterns l and r (delimiters excluded).
    """
    pattern = f".*{l}(.*?){r}" if get_last else f"{l}(.*?){r}"
    match = re.search(pattern, s, re.DOTALL)
    return match.group(1) if match else ""

def extract_md_codeblock(s: str) -> str:
    """
    Extract content of the last fenced code block from markdown.
    """
    return _extract_between(s, r"```\S*\n", r"```", get_last=True)
