from __future__ import annotations

import re
import unicodedata


# Unicode spaces that commonly appear in PDFs/web text.
_SPECIAL_SPACES = {
    "\u00a0": " ",   # NO-BREAK SPACE
    "\u2007": " ",   # FIGURE SPACE
    "\u202f": " ",   # NARROW NO-BREAK SPACE
}


def normalize_text(text: str) -> str:
    """
    Conservatively normalize extracted source text.

    Design goals
    ------------
    - deterministic;
    - preserve wording, numbers, punctuation and case;
    - preserve paragraph/line structure where practical;
    - make hashing/retrieval stable;
    - never paraphrase;
    - never dehyphenate words automatically.

    The output of this function becomes the canonical text used by
    downstream provenance checks.
    """

    if not isinstance(text, str):
        raise TypeError(
            "text must be a string."
        )

    if not text:
        return ""

    # --------------------------------------------------------
    # 1. Normalize Unicode conservatively.
    #
    # NFC is intentional.
    # Do NOT use NFKC here because compatibility normalization
    # can alter source representation more aggressively.
    # --------------------------------------------------------

    text = unicodedata.normalize(
        "NFC",
        text,
    )

    # --------------------------------------------------------
    # 2. Standardize line endings.
    # --------------------------------------------------------

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    # PDF form-feed is treated as a line/page boundary.
    text = text.replace(
        "\f",
        "\n",
    )

    # --------------------------------------------------------
    # 3. Normalize selected Unicode spaces.
    # --------------------------------------------------------

    for old, new in _SPECIAL_SPACES.items():
        text = text.replace(
            old,
            new,
        )

    # --------------------------------------------------------
    # 4. Remove unsafe/invisible control characters.
    #
    # Preserve:
    #   \n newline
    #   \t tab (normalized below)
    #
    # Do NOT indiscriminately remove Unicode formatting
    # characters because scientific text may legitimately
    # contain unusual Unicode.
    # --------------------------------------------------------

    cleaned: list[str] = []

    for char in text:

        if char in {"\n", "\t"}:
            cleaned.append(char)
            continue

        category = unicodedata.category(
            char
        )

        # C0/C1 control characters.
        if category == "Cc":
            continue

        cleaned.append(char)

    text = "".join(cleaned)

    # --------------------------------------------------------
    # 5. Tabs -> ordinary spaces.
    # --------------------------------------------------------

    text = text.replace(
        "\t",
        " ",
    )

    # --------------------------------------------------------
    # 6. Remove trailing horizontal whitespace per line.
    #
    # Do not collapse the whole document with:
    #     " ".join(text.split())
    #
    # because that destroys provenance structure.
    # --------------------------------------------------------

    lines = []

    for line in text.split("\n"):

        # Collapse repeated horizontal spaces only.
        line = re.sub(
            r"[ ]{2,}",
            " ",
            line,
        )

        line = line.strip(" ")

        lines.append(line)

    text = "\n".join(lines)

    # --------------------------------------------------------
    # 7. Limit pathological runs of blank lines.
    #
    # Three+ line breaks -> exactly two.
    # This preserves paragraph separation while keeping hashes
    # stable across common PDF extraction artifacts.
    # --------------------------------------------------------

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    # --------------------------------------------------------
    # 8. Trim only document boundaries.
    # --------------------------------------------------------

    return text.strip()