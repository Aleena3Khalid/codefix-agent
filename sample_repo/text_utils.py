"""Small text helpers."""

def slugify(text):
    """Lowercase, trim, and replace spaces with hyphens: "Hello World" -> "hello-world"."""
    return "-".join(text.strip().lower().split())


def word_count(text):
    """Count the words in `text`."""
    return len(text.split(" "))


def truncate(text, limit):
    """Shorten text to at most `limit` characters, ending with "..." when cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."