"""Conservative QR candidate extraction; business validation remains upstream.

maimai-py 1.5.2 documents the SGWCMAID prefix but no public length/alphabet
contract. MAX_INPUT_BYTES is a resource limit, not a claimed QR format rule.
"""

import unicodedata


MAX_INPUT_BYTES = 4096
PREFIX = "SGWCMAID"


class InvalidCode(ValueError):
    def __init__(self, message="二维码内容无效，请发送以 SGWCMAID 开头的完整二维码文本。"):
        self.message = message
        super().__init__(message)


def parse_codes(text: str) -> list[str]:
    """Accept only whitespace-separated complete candidates, preserving order.

    The caller removes the configured command prefix and rejects >1 distinct
    result. Embedded prose/URLs are rejected rather than silently extracted.
    A syntactically accepted candidate is NOT proof that a real QR is valid.
    """
    if not isinstance(text, str):
        raise InvalidCode()
    try:
        if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise InvalidCode("二维码文本过长，已拒绝处理。")
    except UnicodeError:
        raise InvalidCode() from None
    # Permit ordinary transport whitespace, never invisible controls or bidi.
    if any(unicodedata.category(c).startswith("C") and c not in "\t\r\n" for c in text):
        raise InvalidCode()
    result = []
    for value in text.split():
        if not value.startswith(PREFIX) or value == PREFIX:
            raise InvalidCode()
        if value not in result:
            result.append(value)
    return result
