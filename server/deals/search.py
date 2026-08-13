import re
import unicodedata


def normalize_deal_search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.strip().casefold())
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    without_apostrophes = without_marks.replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[&/+]+|[^a-z0-9]+", " ", without_apostrophes).split())
