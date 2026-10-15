"""CONTAINS expressions used by protocol variables.

A CONTAINS value is a plain string that may combine several texts:

- ``ml/min``                 contains "ml/min"
- ``ml/min & gotejo``        contains both texts
- ``ml/min | gotejo``        contains at least one of them
- ``ml/min & gotejo | bic``  (ml/min and gotejo) or bic

``&`` binds tighter than ``|`` and there are no parentheses, so an expression is
always "any of the groups, where every text of a group must be present".
Matching ignores case only: accents must match exactly.
"""

AND_SEPARATOR = "&"
OR_SEPARATOR = "|"


def normalize_text(text) -> str:
    """Lowercases a text so comparisons ignore case (accents are kept)"""

    return str(text).lower()


def is_expression(value) -> bool:
    """True when the value combines texts with & or |"""

    if value is None:
        return False

    text = str(value)
    return AND_SEPARATOR in text or OR_SEPARATOR in text


def parse_expression(value) -> list[list[str]]:
    """Splits a CONTAINS value into OR groups of AND terms, dropping empty terms.

    A value without separators becomes a single group holding the whole value,
    untrimmed, so it keeps matching exactly as a plain substring.
    """

    if not is_expression(value):
        return [[str(value)]]

    groups = []
    for raw_group in str(value).split(OR_SEPARATOR):
        terms = [t.strip() for t in raw_group.split(AND_SEPARATOR) if t.strip()]
        if terms:
            groups.append(terms)

    if not groups:
        # nothing but separators: fall back to the literal value
        return [[str(value)]]

    return groups


def has_empty_term(value) -> bool:
    """True when an expression has a blank term (ex.: 'a & ' or 'a || b')"""

    if not is_expression(value):
        return False

    for raw_group in str(value).split(OR_SEPARATOR):
        for term in raw_group.split(AND_SEPARATOR):
            if not term.strip():
                return True

    return False


def matches(text, value) -> bool:
    """Tests a text against a CONTAINS value"""

    if text is None or value is None:
        return False

    normalized = normalize_text(text)

    return any(
        all(normalize_text(term) in normalized for term in group)
        for group in parse_expression(value)
    )


def missing_terms(text, value) -> list[str]:
    """Lists the terms of a CONTAINS value that the text does not contain"""

    normalized = normalize_text(text) if text is not None else None
    missing = []

    for group in parse_expression(value):
        for term in group:
            if term in missing:
                continue
            if normalized is None or normalize_text(term) not in normalized:
                missing.append(term)

    return missing


def describe(value) -> str:
    """Portuguese description of a CONTAINS value (ex.: 'a' e 'b' ou 'c')"""

    return " ou ".join(
        " e ".join(f"'{term}'" for term in group) for group in parse_expression(value)
    )
