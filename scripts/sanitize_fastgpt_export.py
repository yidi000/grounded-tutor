"""Create a review-only workflow copy; never treat this as a universal secret scanner."""

import json
import re
import sys
from pathlib import Path

REDACTED_URL = "https://example.invalid/redacted"
PRIVATE = re.compile(
    r"authorization|apikey|teamid|tmbid|memberid|dataset|collection|appid|userid|"
    r"cookie|secret|password|accesstoken|refreshtoken|requestauth|fileurllist|valuedesc"
)
URL = re.compile(r"https?://[^\s\"'<>]+")
TOKEN = re.compile(
    r"(?:Bearer\s+\S+|(?:fastgpt|tvly|tvly-dev|sk)-[A-Za-z0-9_-]+)", re.IGNORECASE
)
ACCOUNT_ID = re.compile(r"\b[a-fA-F0-9]{24}\b")


def private(key):
    return bool(PRIVATE.search(re.sub(r"[^a-z0-9]", "", key.lower())))


def sanitize(value):
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items() if not private(key)}
    if isinstance(value, list):
        return [
            sanitize(item)
            for item in value
            if not (
                isinstance(item, dict)
                and isinstance(item.get("key"), str)
                and private(item["key"])
            )
        ]
    if isinstance(value, str):
        # FastGPT stores HTTP bodies and some settings as JSON inside string values.
        if value.lstrip().startswith(("{", "[")):
            try:
                embedded = json.loads(value)
            except ValueError:
                pass
            else:
                return json.dumps(
                    sanitize(embedded), ensure_ascii=False, sort_keys=True
                )
        return ACCOUNT_ID.sub(
            "REDACTED", TOKEN.sub("REDACTED", URL.sub(REDACTED_URL, value))
        )
    return value


def main():
    if len(sys.argv) != 3:
        print("Usage: sanitize_fastgpt_export.py INPUT OUTPUT", file=sys.stderr)
        return 2
    try:
        source, target = map(Path, sys.argv[1:])
        # Never overwrite any existing file, including aliases or a previous review.
        if (
            source.resolve() == target.resolve()
            or target.exists()
            or target.is_symlink()
        ):
            raise ValueError
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise TypeError
        result = (
            json.dumps(sanitize(data), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        with target.open("x", encoding="utf-8") as output:
            output.write(result)
    except (OSError, ValueError, TypeError, RecursionError):
        print("Sanitization failed; input and error details withheld.", file=sys.stderr)
        return 1
    print("Sanitized copy written. Manual review is required before publication.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
