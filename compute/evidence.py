"""Evidence table, confidence labels and graph edges for the cascade MVP.

Follows docs/data_contract.md. The notebook compute/run_evidence.ipynb calls these
functions top to bottom.

Part A reads the issuer documents in s3://$BUCKET/raw/manual_docs/, asks a Bedrock model
for verbatim oil-related excerpts, and writes processed/evidence plus Knowledge Base
documents under evidence/.
Part B combines sensitivities, chain reconciliation and evidence into processed/confidence
and processed/edges.
"""

from __future__ import annotations

import html
import io
import json
import logging
import os
import re
from html.parser import HTMLParser

import numpy as np
import pandas as pd

log = logging.getLogger("cascade.evidence")
logging.getLogger("pypdf").setLevel(logging.ERROR)   # quiet pypdf font warnings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Main channel per ticker. Any ticker missing from this map defaults to "none".
MAIN_CHANNEL = {
    # core
    "XOM": "direct", "ENB.TO": "direct", "XIU.TO": "direct", "XESG.TO": "direct",
    "TLT": "rates", "XBB.TO": "rates", "ZST.TO": "rates", "QQQ": "rates", "SHOP.TO": "rates",
    "VFV.TO": "currency", "XSP.TO": "currency",
    "ATD.TO": "company-specific",
    "RY.TO": "none", "SPY": "none",
    # extras
    "CNQ.TO": "direct", "XEG.TO": "direct",
    "XLB.TO": "rates", "XRB.TO": "rates", "AGG": "rates",
}

CHANNELS = ("direct", "rates", "currency", "company-specific", "none")
DIRECTIONS = ("positive", "negative", "mixed")

DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-5-5"

MANIFEST_KEY = "raw/manual_docs/manifest_docs.csv"
DOCS_PREFIX = "raw/manual_docs/"
EVIDENCE_TABLE_KEY = "processed/evidence/part-0.parquet"
KB_PREFIX = "evidence/"

PASSAGE_CHARS = 1500
PASSAGE_OVERLAP = 200
MAX_PASSAGES_PER_DOC = 25
MAX_PER_TICKER_CHANNEL = 3
MAX_EXCERPT_WORDS = 40
MAX_TOKENS = 500

KEYWORDS = [
    "oil", "crude", "Brent", "WTI", "fuel", "gasoline", "energy price", "commodity",
    "petroleum", "interest rate", "yield", "inflation", "Canadian dollar",
    "exchange rate", "currency", "duration",
]
# These keywords count double in the passage score.
DOUBLE_KEYWORDS = {"oil", "crude", "Brent", "WTI", "fuel", "gasoline", "commodity"}
_KEYWORD_RES = [
    (re.compile(r"\b" + re.escape(k), re.IGNORECASE), 2 if k in DOUBLE_KEYWORDS else 1)
    for k in KEYWORDS
]
CACHE_PREFIX = "processed/_evidence_cache/"

EVIDENCE_COLUMNS = ["evidence_id", "ticker", "doc_type", "channel", "direction",
                    "source_url", "section", "excerpt", "s3_key"]
CONFIDENCE_COLUMNS = ["ticker", "channel", "label", "reason_code", "reason_text"]
EDGE_COLUMNS = ["from_node", "to_node", "edge_type", "beta", "lo", "hi", "evidence_id"]

SYSTEM_PROMPT = (
    "You read one passage from an investor document about a ticker and decide whether it "
    "describes how oil prices (or oil-linked energy prices, interest rates or the Canadian "
    "dollar) affect that ticker. Answer by calling the record_evidence tool exactly once. "
    '"direction" is the effect of HIGHER oil prices on the ticker. '
    '"channel": direct = oil revenue or costs; rates = through interest rates or yields; '
    "currency = through the Canadian dollar or exchange rate; company-specific = a named "
    "business exposure to fuel or energy prices; none = not about oil. "
    "The excerpt must be copied character for character from the passage. "
    'If the passage is not relevant, set relevant to false, channel to "none", direction to '
    '"mixed" and excerpt and section to empty strings.'
)

EVIDENCE_TOOL_NAME = "record_evidence"
TOOL_CONFIG = {
    "tools": [{
        "toolSpec": {
            "name": EVIDENCE_TOOL_NAME,
            "description": "Record whether the passage links oil prices to the ticker.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "relevant": {"type": "boolean",
                                 "description": "True if the passage says how oil prices affect the ticker."},
                    "channel": {"type": "string", "enum": list(CHANNELS)},
                    "direction": {"type": "string", "enum": list(DIRECTIONS),
                                  "description": "Effect of HIGHER oil on the ticker."},
                    "excerpt": {"type": "string",
                                "description": "Verbatim sentence(s) from the passage, max 40 words."},
                    "section": {"type": "string", "description": "Heading if visible, else empty."},
                },
                "required": ["relevant", "channel", "direction", "excerpt", "section"],
            }},
        }
    }],
    "toolChoice": {"tool": {"name": EVIDENCE_TOOL_NAME}},
}


# ---------------------------------------------------------------------------
# S3 and Bedrock helpers
# ---------------------------------------------------------------------------

def _s3_client(region: str | None = None):
    import boto3

    return boto3.client("s3", region_name=region or os.environ.get("AWS_REGION", DEFAULT_REGION))


def _bedrock_client(region: str | None = None):
    """bedrock-runtime client with adaptive retries (6 attempts)."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "bedrock-runtime",
        region_name=region or os.environ.get("AWS_REGION", DEFAULT_REGION),
        config=Config(retries={"max_attempts": 6, "mode": "adaptive"}),
    )


def read_parquet_s3(bucket: str, key: str, s3=None) -> pd.DataFrame:
    s3 = s3 or _s3_client()
    return pd.read_parquet(io.BytesIO(s3.get_object(Bucket=bucket, Key=key)["Body"].read()))


def write_parquet_s3(df: pd.DataFrame, bucket: str, table: str, s3=None) -> str:
    s3 = s3 or _s3_client()
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    key = f"processed/{table}/part-0.parquet"
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return key


class Usage:
    """Running total of Bedrock token usage."""

    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, response: dict):
        u = response.get("usage") or {}
        self.calls += 1
        self.input_tokens += int(u.get("inputTokens", 0))
        self.output_tokens += int(u.get("outputTokens", 0))

    def log_totals(self):
        log.info("Bedrock usage: %d calls, %d input tokens, %d output tokens",
                 self.calls, self.input_tokens, self.output_tokens)


# ---------------------------------------------------------------------------
# Steps 1-2: read documents and split into passages
# ---------------------------------------------------------------------------

def normalize_ws(text: str) -> str:
    """Collapse every run of whitespace to one space and trim."""
    return re.sub(r"\s+", " ", text or "").strip()


class _TextExtractor(HTMLParser):
    """Strip tags with the standard library. Skips script, style and head-only noise."""

    _SKIP = {"script", "style", "noscript", "template"}
    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section",
              "article", "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw_html)
    parser.close()
    return html.unescape("".join(parser.parts))


def extract_pages(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """Return [(page number or None, normalized text)]. PDFs use pypdf, HTML uses html.parser."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = normalize_ws(page.extract_text() or "")
            if text:
                pages.append((i, text))
        return pages
    if name.endswith((".html", ".htm")):
        text = normalize_ws(html_to_text(data.decode("utf-8", errors="replace")))
        return [(None, text)] if text else []
    raise ValueError(f"Unsupported file type: {filename}")


def split_passages(text: str, size: int = PASSAGE_CHARS, overlap: int = PASSAGE_OVERLAP) -> list[str]:
    """Split text into passages of about `size` characters with `overlap` characters shared."""
    text = normalize_ws(text)
    if not text:
        return []
    step = size - overlap
    out = []
    start = 0
    while start < len(text):
        out.append(text[start:start + size])
        if start + size >= len(text):
            break
        start += step
    return out


def passages_for_pages(pages: list[tuple[int | None, str]]) -> list[dict]:
    """Passages with their page number: [{"page", "text"}]."""
    return [{"page": page, "text": p} for page, text in pages for p in split_passages(text)]


# ---------------------------------------------------------------------------
# Step 3: keyword prefilter
# ---------------------------------------------------------------------------

def score_passage(text: str) -> int:
    """Number of distinct keywords in the passage; oil/crude/Brent/WTI/fuel/gasoline/commodity count double."""
    return sum(w for rx, w in _KEYWORD_RES if rx.search(text))


def prefilter(passages: list[dict], limit: int = MAX_PASSAGES_PER_DOC) -> list[dict]:
    """Score every passage and keep the top `limit` (score > 0; ties go to the earlier passage).

    The kept passages stay in document order and keep their page number.
    """
    scored = [(score_passage(p["text"]), i) for i, p in enumerate(passages)]
    scored = [s for s in scored if s[0] > 0]
    top = sorted(scored, key=lambda s: (-s[0], s[1]))[:limit]
    return [passages[i] for i in sorted(i for _, i in top)]


# ---------------------------------------------------------------------------
# Step 4: Bedrock call, parsing and the verbatim check
# ---------------------------------------------------------------------------

def is_verbatim(excerpt: str, passage: str) -> bool:
    """True if the excerpt is a non-empty substring of the passage after whitespace normalization."""
    e = normalize_ws(excerpt)
    return bool(e) and e in normalize_ws(passage)


def converse_once(client, model_id: str, ticker: str, doc_type: str, passage: str,
                  usage: Usage) -> dict | None:
    """One Converse call that forces the record_evidence tool. Returns the toolUse input, or None."""
    user = f"Ticker: {ticker}\nDocument type: {doc_type}\n\nPassage:\n{passage}"
    resp = client.converse(
        modelId=model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
        toolConfig=TOOL_CONFIG,
    )
    usage.add(resp)
    for block in resp.get("output", {}).get("message", {}).get("content", []):
        tool = block.get("toolUse")
        if tool and tool.get("name") == EVIDENCE_TOOL_NAME and isinstance(tool.get("input"), dict):
            return tool["input"]
    return None


def classify_passage(client, model_id: str, ticker: str, doc_type: str, passage: str,
                     usage: Usage) -> dict | None:
    """Ask the model about one passage. No tool result: retry once, then return None."""
    for _ in range(2):
        obj = converse_once(client, model_id, ticker, doc_type, passage, usage)
        if obj is not None:
            return obj
    log.warning("Skipping passage for %s: no record_evidence result twice", ticker)
    return None


def validate_answer(obj: dict, passage: str) -> dict | None:
    """Return a clean {channel, direction, excerpt, section} for a relevant, verbatim answer, else None."""
    if obj.get("relevant") is not True:
        return None
    channel, direction = obj.get("channel"), obj.get("direction")
    if channel not in CHANNELS or channel == "none" or direction not in DIRECTIONS:
        return None
    excerpt = obj.get("excerpt")
    if not isinstance(excerpt, str):
        return None
    excerpt = normalize_ws(excerpt)
    if not excerpt or len(excerpt.split()) > MAX_EXCERPT_WORDS or not is_verbatim(excerpt, passage):
        return None
    section = obj.get("section")
    section = normalize_ws(section) if isinstance(section, str) else ""
    return {"channel": channel, "direction": direction, "excerpt": excerpt, "section": section}


# ---------------------------------------------------------------------------
# Step 5: select rows
# ---------------------------------------------------------------------------

def select_evidence(candidates: list[dict], per_group: int = MAX_PER_TICKER_CHANNEL) -> list[dict]:
    """Keep at most `per_group` rows per (ticker, channel), longest excerpt first.

    Each candidate has ticker, doc_type, channel, direction, source_url, section, excerpt,
    s3_key and passage. Identical excerpts for a (ticker, channel) are kept once.
    evidence_id = "<ticker>-<channel>-<n>" with n starting at 1.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in candidates:
        groups.setdefault((c["ticker"], c["channel"]), []).append(c)
    out = []
    for (ticker, channel), rows in sorted(groups.items()):
        seen = set()
        ranked = []
        for r in sorted(rows, key=lambda r: -len(r["excerpt"])):   # stable: ties keep document order
            if r["excerpt"] in seen:
                continue
            seen.add(r["excerpt"])
            ranked.append(r)
        for n, r in enumerate(ranked[:per_group], start=1):
            out.append({**r, "evidence_id": f"{ticker}-{channel}-{n}"})
    return out


def evidence_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=EVIDENCE_COLUMNS).astype(object) if rows else \
        pd.DataFrame({c: pd.Series(dtype=object) for c in EVIDENCE_COLUMNS})


def _read_manifest(bucket: str, s3) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=MANIFEST_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), dtype=str).fillna("")
    missing = {"file", "ticker", "doc_type", "source_url"} - set(df.columns)
    if missing:
        raise ValueError(f"{MANIFEST_KEY} is missing columns {sorted(missing)}")
    return df


def load_document_text(bucket: str, key: str, s3=None) -> str:
    """Whole normalized text of one document, as the pipeline sees it (pages joined by a space)."""
    s3 = s3 or _s3_client()
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return " ".join(t for _, t in extract_pages(key, data))


# ---------------------------------------------------------------------------
# Steps 1-5 together, with a per-document cache so a run can resume
# ---------------------------------------------------------------------------

def _cache_key(file: str) -> str:
    return f"{CACHE_PREFIX}{file}.json"


def read_cache(bucket: str, m, s3) -> dict | None:
    """Cached result for one manifest row, or None if absent or made for different manifest values."""
    try:
        body = s3.get_object(Bucket=bucket, Key=_cache_key(m.file))["Body"].read()
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    payload = json.loads(body)
    if (payload.get("ticker"), payload.get("doc_type"), payload.get("source_url")) != \
            (m.ticker, m.doc_type, m.source_url):
        log.info("Cache for %s was made for different manifest values; reprocessing", m.file)
        return None
    return payload


def write_cache(bucket: str, m, payload: dict, s3) -> None:
    s3.put_object(Bucket=bucket, Key=_cache_key(m.file), ContentType="application/json",
                  Body=json.dumps(payload).encode("utf-8"))


def process_document(m, bucket: str, model_id: str, s3, client, usage: Usage) -> dict:
    """Run the model over one document. Returns the cache payload with the kept rows."""
    key = DOCS_PREFIX + m.file
    payload = {"file": m.file, "ticker": m.ticker, "doc_type": m.doc_type,
               "source_url": m.source_url, "sent": 0, "skipped": 0, "candidates": []}
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    pages = extract_pages(m.file, data)
    kept = prefilter(passages_for_pages(pages))
    payload["sent"] = len(kept)
    for p in kept:
        obj = classify_passage(client, model_id, m.ticker, m.doc_type, p["text"], usage)
        if obj is None:
            payload["skipped"] += 1
            continue
        clean = validate_answer(obj, p["text"])
        if clean is None:
            continue
        payload["candidates"].append({
            "ticker": m.ticker, "doc_type": m.doc_type, "source_url": m.source_url,
            "s3_key": key, "passage": p["text"], "page": p["page"], **clean,
        })
    return payload


def load_candidates(bucket: str, model_id: str | None, s3, client, usage: Usage,
                    only_cached: bool = False) -> tuple[list[dict], dict[str, dict]]:
    """Candidates from every manifest document. Cached documents are not sent to the model again.

    With only_cached=True nothing is processed; documents with no cache are skipped.
    Returns (candidates, per-document stats {file: {"sent", "skipped", "kept", "cached"}}).
    """
    manifest = _read_manifest(bucket, s3)
    candidates, stats = [], {}
    for m in manifest.itertuples(index=False):
        payload = read_cache(bucket, m, s3)
        cached = payload is not None
        if payload is None:
            if only_cached:
                continue
            try:
                payload = process_document(m, bucket, model_id, s3, client, usage)
            except Exception as exc:  # one unreadable file must not stop the run
                log.warning("Skipping %s: %s", DOCS_PREFIX + m.file, exc)
                continue
            write_cache(bucket, m, payload, s3)
        candidates += payload["candidates"]
        stats[m.file] = {"sent": payload["sent"], "skipped": payload["skipped"],
                         "kept": len(payload["candidates"]), "cached": cached}
    return candidates, stats


def log_skipped(stats: dict[str, dict]) -> None:
    for file, st in stats.items():
        log.info("%s: %d passages sent, %d skipped (no tool result after retry), %d kept%s",
                 file, st["sent"], st["skipped"], st["kept"], " (from cache)" if st["cached"] else "")


def _to_frame_and_passages(candidates: list[dict]) -> tuple[pd.DataFrame, dict[str, dict]]:
    chosen = select_evidence(candidates)
    df = evidence_frame(chosen)
    return df, {r["evidence_id"]: {"passage": r["passage"], "page": r["page"]} for r in chosen}


def build_evidence(bucket: str | None = None, model_id: str | None = None, s3=None,
                   client=None, usage: Usage | None = None) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Read the manifest and documents, call the model and return (evidence frame, passages).

    A document with processed/_evidence_cache/<file>.json is not sent to the model again, so
    an interrupted run resumes where it stopped. `passages` maps evidence_id to
    {"passage", "page"} for the Knowledge Base documents.
    """
    bucket = bucket or os.environ["BUCKET"]
    model_id = model_id or os.environ.get("EVIDENCE_MODEL_ID", DEFAULT_MODEL_ID)
    s3 = s3 or _s3_client()
    client = client or _bedrock_client()
    usage = usage or Usage()
    candidates, stats = load_candidates(bucket, model_id, s3, client, usage)
    log_skipped(stats)
    usage.log_totals()
    return _to_frame_and_passages(candidates)


# ---------------------------------------------------------------------------
# Steps 6-7: write outputs
# ---------------------------------------------------------------------------

def kb_document(row: dict, passage: str) -> str:
    """Text of the Knowledge Base document for one evidence row."""
    return (
        f"Ticker: {row['ticker']}\n"
        f"Channel: {row['channel']}\n"
        f"Direction: {row['direction']}\n"
        f"Source: {row['source_url']}\n"
        f"Section: {row['section']}\n"
        f"\nExcerpt: {row['excerpt']}\n"
        f"\nPassage: {passage}\n"
    )


def kb_metadata(row: dict) -> dict:
    """Metadata sidecar content, in the exact format the Knowledge Base expects."""
    return {"metadataAttributes": {
        "ticker": row["ticker"], "doc_type": row["doc_type"], "channel": row["channel"],
        "direction": row["direction"], "source_url": row["source_url"], "section": row["section"],
    }}


def write_evidence(df: pd.DataFrame, passages: dict[str, dict], bucket: str | None = None,
                   s3=None) -> list[str]:
    """Write processed/evidence and one Knowledge Base document + metadata file per row.

    Objects under evidence/ that do not belong to the current rows are deleted first, so the
    number of .metadata.json files equals the number of evidence rows.
    """
    bucket = bucket or os.environ["BUCKET"]
    s3 = s3 or _s3_client()
    wanted = set()
    for r in df.to_dict("records"):
        wanted |= {f"{KB_PREFIX}{r['evidence_id']}.txt", f"{KB_PREFIX}{r['evidence_id']}.txt.metadata.json"}
    stale = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=KB_PREFIX):
        stale += [o["Key"] for o in page.get("Contents", []) if o["Key"] not in wanted]
    for key in stale:
        s3.delete_object(Bucket=bucket, Key=key)
    if stale:
        log.info("Removed %d stale objects under %s", len(stale), KB_PREFIX)

    keys = [write_parquet_s3(df, bucket, "evidence", s3)]
    for r in df.to_dict("records"):
        base = f"{KB_PREFIX}{r['evidence_id']}.txt"
        body = kb_document(r, passages[r["evidence_id"]]["passage"])
        s3.put_object(Bucket=bucket, Key=base, Body=body.encode("utf-8"), ContentType="text/plain")
        s3.put_object(Bucket=bucket, Key=base + ".metadata.json",
                      Body=json.dumps(kb_metadata(r)).encode("utf-8"), ContentType="application/json")
        keys += [base, base + ".metadata.json"]
    return keys


# ---------------------------------------------------------------------------
# Part B: confidence and edges
# ---------------------------------------------------------------------------

def main_channel(ticker: str) -> str:
    return MAIN_CHANNEL.get(ticker, "none")


def _sign(x) -> int:
    return int(np.sign(x)) if pd.notna(x) else 0


def label_row(sens: dict, share: float | None, evidence_directions: set[str],
              chain: str | None = None) -> tuple[str, str, str]:
    """Apply the contract label rule to one ticker. Returns (label, reason_code, reason_text).

    green  = p_simple<0.05 AND p_ex2022<0.05 with the same sign AND
             (share_explained>=0.5 OR an evidence row with the same direction as beta_simple)
    yellow = p_simple<0.05 but the rest fails
    grey   = p_simple>=0.05 (or missing)
    """
    beta, p = sens.get("beta_simple"), sens.get("p_simple")
    if pd.isna(p) or p >= 0.05:
        if pd.isna(p):
            return "grey", "NOT_SIG", "Not enough weekly data to measure a link to oil."
        return "grey", "NOT_SIG", (f"No clear link to oil: beta {beta:+.2f} with p = {p:.2f}, "
                                   "which is within normal noise.")
    p_ex, beta_ex = sens.get("p_ex2022"), sens.get("beta_ex2022")
    stable = pd.notna(p_ex) and p_ex < 0.05 and _sign(beta) == _sign(beta_ex)
    has_share = share is not None and pd.notna(share)
    explained = bool(has_share and share >= 0.5)
    word = "positive" if beta > 0 else "negative"
    cited = word in evidence_directions
    if not stable:
        if pd.isna(p_ex):
            why = "there is not enough data to test without 2022"
        elif _sign(beta) != _sign(beta_ex):
            why = f"the sign flips without 2022 (beta {beta_ex:+.2f})"
        else:
            why = f"it is not significant without 2022 (p = {p_ex:.2f})"
        return "yellow", "SIG_UNSTABLE", f"Moves with oil in 2021-2026 but not reliably: {why}."
    if explained:
        via = f"the {chain} chain" if chain else "the chain"
        return "green", "SIG_STABLE_EXPLAINED", (
            f"Moves with oil in 2021-2026 and still does without 2022; {via} explains {share:.0%} of it.")
    if cited:
        return "green", "SIG_STABLE_CITED", (
            "Moves with oil in 2021-2026 and still does without 2022; "
            f"a source document describes the same ({word}) direction.")
    if has_share:
        gap = f"the chain explains only {share:.0%} of it"
    else:
        gap = "no transmission chain was tested"
    return "yellow", "SIG_UNEXPLAINED", (
        f"Moves with oil in 2021-2026 and still does without 2022, but {gap} and no source "
        "document supports the direction.")


def build_confidence(sens: pd.DataFrame, chain_rec: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    """One confidence row per ticker in sensitivities."""
    share, chain_name = {}, {}
    for r in chain_rec.to_dict("records"):
        share[r["ticker"]] = r["share_explained"]
        chain_name[r["ticker"]] = r["chain"]
    dirs: dict[str, set[str]] = {}
    for r in evidence.to_dict("records"):
        dirs.setdefault(r["ticker"], set()).add(r["direction"])
    rows = []
    for s in sens.to_dict("records"):
        t = s["ticker"]
        label, code, text = label_row(s, share.get(t), dirs.get(t, set()), chain_name.get(t))
        rows.append({"ticker": t, "channel": main_channel(t), "label": label,
                     "reason_code": code, "reason_text": text})
    return pd.DataFrame(rows, columns=CONFIDENCE_COLUMNS)


def build_edges(links_df: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    """Measured edges from processed/links plus one cited edge per evidence row (oil -> ticker)."""
    rows = [{"from_node": r["from_node"], "to_node": r["to_node"], "edge_type": "measured",
             "beta": r["beta"], "lo": r["lo"], "hi": r["hi"], "evidence_id": None}
            for r in links_df.to_dict("records")]
    rows += [{"from_node": "oil", "to_node": r["ticker"], "edge_type": "cited",
              "beta": np.nan, "lo": np.nan, "hi": np.nan, "evidence_id": r["evidence_id"]}
             for r in evidence.to_dict("records")]
    df = pd.DataFrame(rows, columns=EDGE_COLUMNS)
    return df.astype({"beta": float, "lo": float, "hi": float})


def evidence_from_cache(bucket: str, s3=None) -> pd.DataFrame | None:
    """Evidence rows rebuilt from every cached document, or None if no document is cached."""
    s3 = s3 or _s3_client()
    candidates, stats = load_candidates(bucket, None, s3, None, Usage(), only_cached=True)
    if not stats:
        return None
    return _to_frame_and_passages(candidates)[0]


def run_part_b(bucket: str | None = None, s3=None) -> dict[str, pd.DataFrame]:
    """Read the three inputs, write processed/confidence and processed/edges, return both."""
    bucket = bucket or os.environ["BUCKET"]
    s3 = s3 or _s3_client()
    sens = read_parquet_s3(bucket, "processed/sensitivities/part-0.parquet", s3)
    chain_rec = read_parquet_s3(bucket, "processed/chain_reconciliation/part-0.parquet", s3)
    evidence = evidence_from_cache(bucket, s3)
    if evidence is None:   # no cache yet: use the written table
        evidence = read_parquet_s3(bucket, EVIDENCE_TABLE_KEY, s3)
    links_df = read_parquet_s3(bucket, "processed/links/part-0.parquet", s3)
    out = {"confidence": build_confidence(sens, chain_rec, evidence),
           "edges": build_edges(links_df, evidence)}
    for name, df in out.items():
        write_parquet_s3(df, bucket, name, s3)
    return out


# ---------------------------------------------------------------------------
# Final checks
# ---------------------------------------------------------------------------

def check_outputs(bucket: str | None = None, s3=None) -> dict:
    """Run the three done-checks against S3 and return the results (raises nothing).

    - every evidence excerpt is found in its source document text
    - RY.TO is labelled grey
    - number of .metadata.json files under evidence/ equals the evidence row count
    """
    bucket = bucket or os.environ["BUCKET"]
    s3 = s3 or _s3_client()
    ev = read_parquet_s3(bucket, EVIDENCE_TABLE_KEY, s3)
    texts = {k: normalize_ws(load_document_text(bucket, k, s3)) for k in ev["s3_key"].unique()}
    bad = [r["evidence_id"] for r in ev.to_dict("records")
           if normalize_ws(r["excerpt"]) not in texts[r["s3_key"]]]
    conf = read_parquet_s3(bucket, "processed/confidence/part-0.parquet", s3)
    ry = conf.loc[conf["ticker"] == "RY.TO", "label"].tolist()
    n_meta = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=KB_PREFIX):
        n_meta += sum(o["Key"].endswith(".metadata.json") for o in page.get("Contents", []))
    result = {
        "excerpts_not_found": bad,
        "excerpts_ok": not bad,
        "ry_label": ry,
        "ry_grey": ry == ["grey"],
        "metadata_files": n_meta,
        "evidence_rows": len(ev),
        "metadata_count_ok": n_meta == len(ev),
    }
    log.info("Checks: %s", result)
    return result
