"""Utils: public validation code of a training certificate"""

import re
import secrets

# Crockford Base32: no I, L, O or U. The first three are the characters that get
# misread when a code is copied off a printed certificate; keeping 0 and 1 in the
# alphabet is what gives the misread ones somewhere to fold to.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 12
GROUP_SIZE = 4

_FOLD = str.maketrans({"I": "1", "L": "1", "O": "0"})
_NOT_ALPHABET = re.compile(f"[^{ALPHABET}]")


def generate_code() -> str:
    """A fresh validation code: 32^12, i.e. 60 bits of entropy.

    secrets.choice over the alphabet, not base64.b32encode: the RFC 4648
    alphabet puts I, L and O back in and pads with '=', which defeats the point.
    """
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    """Fold what a human typing off paper gets wrong, then drop everything that
    is not in the alphabet (the group dashes, spaces).

    The order matters: stripping first would delete the very I/L/O characters
    the fold is meant to rescue.
    """
    if not code:
        return ""

    return _NOT_ALPHABET.sub("", code.upper().translate(_FOLD))


def format_code(code: str) -> str:
    """XXXX-XXXX-XXXX, for printing. Codes are stored bare."""
    if not code:
        return ""

    return "-".join(code[i : i + GROUP_SIZE] for i in range(0, len(code), GROUP_SIZE))
