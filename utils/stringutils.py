import re
import unicodedata


def strNone(s):
    return "" if s is None else str(s)


def strFormatBR(s):
    return f"{s:_.2f}".replace(".", ",").replace("_", ".")


def remove_accents(text):
    nfkd_form = unicodedata.normalize("NFKD", text)
    only_ascii = nfkd_form.encode("ASCII", "ignore")
    return only_ascii


def slugify(text):
    text = remove_accents(text).lower()
    return re.sub(r"[\W_]+", "-", str(text))
