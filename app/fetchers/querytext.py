"""Provider query syntax without rewriting the student's search words."""

_DOAJ_DISABLED = str.maketrans({char: " " for char in '?*~^/\\:[]{}<>!&|'})
_LUCENE_LITERAL = str.maketrans({char: "\\" + char for char in "+-="})
_SOLR_LITERAL = str.maketrans({char: "\\" + char for char in '+-!(){}[]^"~*?:\\/|&=<>'})
_SOLR_QUERY = {key: value for key, value in _SOLR_LITERAL.items() if chr(key) not in '"()'}


def _balanced(text: str) -> str:
    chars = list(text)
    quotes = [i for i, char in enumerate(chars) if char == '"']
    if len(quotes) % 2:
        chars[quotes[-1]] = " "
    openings: list[int] = []
    quoted = False
    for i, char in enumerate(chars):
        if char == '"':
            quoted = not quoted
        elif not quoted:
            if char == "(":
                openings.append(i)
            elif char == ")":
                if openings:
                    openings.pop()
                else:
                    chars[i] = " "
    for i in openings:
        chars[i] = " "
    return " ".join("".join(chars).split())


def lucene_safe(text: str) -> str:
    """Drop disabled DOAJ syntax; retain balanced phrases, groups and operators."""
    text = _balanced(text.translate(_DOAJ_DISABLED))
    return text.translate(_LUCENE_LITERAL) if any(char.isalnum() for char in text) else ""


def solr_safe(text: str) -> str:
    """Escape Solr punctuation; retain balanced phrases, groups and operators."""
    text = _balanced(text)
    return text.translate(_SOLR_QUERY) if any(char.isalnum() for char in text) else ""


def solr_escape_term(term: str) -> str:
    """Escape one boolean_terms token, keeping its outer phrase quotes."""
    if term.startswith('"') and term.endswith('"'):
        return '"' + term[1:-1].translate(_SOLR_LITERAL) + '"'
    return term.translate(_SOLR_LITERAL)
