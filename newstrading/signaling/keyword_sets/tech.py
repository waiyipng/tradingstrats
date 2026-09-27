"""Sentiment and topic keyword sets tuned for big-tech catalysts (product, cloud, AI, antitrust)."""

POSITIVE_KEYWORDS = {
    "surge", "strong", "growth", "accelerat", "beat", "beats", "profit", "rally",
    "record", "guide", "guidance", "cloud", "ai", "demand", "upgrade", "expansion",
    "gain", "higher", "revenue", "wins", "launch", "innovation", "outperform",
}
NEGATIVE_KEYWORDS = {
    "miss", "misses", "decline", "drop", "weak", "slowdown", "sluggish", "risk",
    "regulatory", "antitrust", "lawsuit", "litigation", "delay", "downgrade",
    "loss", "pressure", "concern", "overhang", "recall", "outage",
}
TOPIC_KEYWORDS = {
    "earnings": {"earnings", "revenue", "profit", "quarter", "guidance"},
    "cloud": {"cloud", "infrastructure", "data center", "ai infrastructure"},
    "ai": {"ai", "artificial intelligence", "gemini", "copilot", "gpu"},
    "antitrust": {"antitrust", "lawsuit", "regulatory", "court"},
    "product": {"launch", "unveil", "chip", "device", "software"},
}
