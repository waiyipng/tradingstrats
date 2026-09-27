"""Sentiment and topic keyword sets tuned for big-bank catalysts (rates, credit, capital markets)."""

POSITIVE_KEYWORDS = {
    "beat", "beats", "strong", "growth", "profit", "record", "raise", "upgrade",
    "rally", "net interest income", "trading revenue", "deal volume", "buyback",
    "dividend increase", "capital return", "resilient", "outperform",
}
NEGATIVE_KEYWORDS = {
    "miss", "misses", "decline", "drop", "weak", "loss", "downgrade", "provision",
    "credit loss", "default", "delinquency", "writedown", "regulatory", "fine",
    "lawsuit", "investigation", "rate cut", "recession", "layoffs",
}
TOPIC_KEYWORDS = {
    "earnings": {"earnings", "revenue", "profit", "quarter", "guidance"},
    "rates": {"fed", "interest rate", "rate hike", "rate cut", "federal reserve"},
    "credit": {"credit loss", "provision", "delinquency", "default", "charge-off"},
    "capital_markets": {"trading revenue", "underwriting", "ipo", "deal volume"},
    "regulatory": {"regulatory", "fine", "lawsuit", "investigation", "capital requirement"},
}
