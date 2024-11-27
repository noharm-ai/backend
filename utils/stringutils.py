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


def prepare_drug_name(name):
    bad_words = [
        n.upper()
        for n in [
            "manhã",
            "manha",
            "noite",
            "pela",
            "café",
            "cafe",
            "dia",
            "conforme",
            "HGT",
            "antes",
            "1cp",
            "2cp",
            "almoço",
            "almoco",
            "das",
            "refeições",
            "refeicoes",
            "jejum",
            "semana",
            "horas",
            "segunda",
            "terça",
            "terca",
            "quarta",
            "quinta",
            "sexta",
            "sábado",
            "sabado",
            "domingo",
            "ao",
            "as",
            "às",
            "tardinha",
        ]
    ]

    # Compile regex patterns for cleaning
    time_pattern = re.compile(r"\d{1,2}[\-\/:]\d{1,2}")  # Matches patterns like 12-12
    dosage_pattern = re.compile(
        r"\d{1,2}[a-zA-Z]{1,3}\/?(dia|hora|semana)", flags=re.IGNORECASE
    )  # Matches patterns like 3x/dia

    words = name.split()
    filtered_words = [
        word.upper()
        for word in words
        if word.upper() not in bad_words and len(word) >= 2
    ]

    if filtered_words:
        cleaned_name = " ".join(filtered_words)
        cleaned_name = time_pattern.sub(" ", cleaned_name)  # Remove time patterns
        cleaned_name = dosage_pattern.sub(" ", cleaned_name)  # Remove dosage patterns
        return cleaned_name.strip()

    return " ".join(words).upper()
