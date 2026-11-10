"""Conservative query routing for Sentinel AI; it does not generate answers."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryIntent:
    kind: str
    entity_type: str | None = None
    identifier: str | None = None
    unsupported: bool = False


_GREETING = re.compile(
    r"^(?:hi(?:\s+there)?|hello(?:\s+there)?|hey(?:\s+there)?|good\s+(?:morning|afternoon|evening)|howdy|thanks|thank\s+you|"
    r"how\s+are\s+you|what'?s\s+up)[!.?,\s]*$", re.IGNORECASE
)
_ID_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9_-]{1,})(?![A-Za-z0-9])")
_ID_PATTERNS = {
    "invoice": re.compile(r"^(?:INV|INVOICE)[-_]?[A-Z0-9]+$"),
    "vendor": re.compile(r"^(?:VEN|VENDOR|VND|REAL)[-_]?[A-Z0-9]+$|^V(?:[-_][A-Z0-9]+|[0-9]+)$"),
    "purchase_order": re.compile(r"^(?:PO|PURCHASE[_-]?ORDER)[-_]?[A-Z0-9]+$"),
    "contract": re.compile(r"^(?:CON|CONTRACT|CTR)[-_]?[A-Z0-9]+$|^C(?:[-_][A-Z0-9]+|[0-9]+)$"),
}
_STOP_TOKENS = {
    "WHY", "WAS", "WERE", "WHAT", "SHOW", "FIND", "TELL", "ABOUT", "THE", "FOR",
    "WITH", "FROM", "RISK", "SIGNALS", "FLAGGED", "FLAG", "INVOICE", "VENDOR", "PO",
    "CONTRACT", "RELATIONSHIP", "RELATED", "LINKED", "INVESTIGATION", "EVIDENCE", "HI",
    "HELLO", "PLEASE", "EXPLAIN", "LIST", "AND", "ITS", "IT", "THIS", "THAT",
}


def is_greeting(message: str) -> bool:
    return bool(_GREETING.fullmatch(message.strip()))


def identify_intent(message: str) -> QueryIntent:
    text = message.strip()
    lowered = text.casefold()
    candidates = [token for token in _ID_TOKEN.findall(text) if token.upper() not in _STOP_TOKENS]
    explicit = (
        ("invoice", r"\binvoice\b|\binv\d"),
        ("vendor", r"\bvendor\b|\bsupplier\b"),
        ("purchase_order", r"\bpurchase\s+order\b|\bpo[-_ ]?\w+"),
        ("contract", r"\bcontract\b|\bctr[-_ ]?\w+"),
    )
    kind = next((name for name, pattern in explicit if re.search(pattern, lowered, re.I)), None)
    # Prefer a typed prefix; this is a cue for exact lookup, not proof of existence.
    identifier = None
    entity_type = None
    for token in candidates:
        upper = token.upper()
        for candidate_type, pattern in _ID_PATTERNS.items():
            if pattern.fullmatch(upper):
                entity_type, identifier = candidate_type, token
                break
        if identifier:
            break
    if entity_type:
        kind = kind or entity_type
    elif kind and candidates:
        # A nearby candidate may be a non-prefixed vendor ID; repository lookup
        # will still require an exact match and never uses fuzzy substitution.
        identifier = candidates[-1]
        entity_type = kind

    if re.search(r"\b(relationship|connected|connection|shared|linked|network|related)\b", lowered):
        kind = "relationship"
    elif kind is None and re.search(r"\b(invoice|vendor|supplier|purchase order|\bpo\b|contract|investigation|evidence|rule|gnn|risk score|detector)\b", lowered):
        kind = "general"
    elif kind is None and re.search(r"\b(weather|forecast|sports|stock price|politics|recipe|translate|capital of)\b", lowered):
        return QueryIntent("unsupported", unsupported=True)
    elif kind is None:
        kind = "general"
    return QueryIntent(kind, entity_type, identifier)
