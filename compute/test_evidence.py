"""Unit tests for compute/evidence.py using small fake frames (no AWS, no model calls)."""

import json

import numpy as np
import pandas as pd

from compute import evidence as ev


# --- verbatim check ---------------------------------------------------------

def test_verbatim_accepts_whitespace_differences():
    passage = "Higher crude prices\n  lift   revenue for producers."
    assert ev.is_verbatim("crude prices lift revenue", passage)


def test_verbatim_rejects_paraphrase_and_empty():
    passage = "Higher crude prices lift revenue for producers."
    assert not ev.is_verbatim("Rising oil prices raise revenue", passage)
    assert not ev.is_verbatim("", passage)
    assert not ev.is_verbatim("   ", passage)


def test_validate_answer_rules():
    passage = "Duration measures sensitivity to interest rate changes. Other text."
    good = {"relevant": True, "channel": "rates", "direction": "negative",
            "excerpt": "Duration measures sensitivity to interest rate changes.", "section": "Risk"}
    assert ev.validate_answer(good, passage)["channel"] == "rates"
    assert ev.validate_answer({**good, "excerpt": "Made up sentence."}, passage) is None
    assert ev.validate_answer({**good, "relevant": False}, passage) is None
    assert ev.validate_answer({**good, "channel": "none"}, passage) is None
    assert ev.validate_answer({**good, "direction": "up"}, passage) is None
    long = " ".join(["word"] * 41)
    assert ev.validate_answer({**good, "excerpt": long}, long) is None


def tool_reply(inp, name="record_evidence"):
    return {"output": {"message": {"content": [{"toolUse": {"toolUseId": "t", "name": name, "input": inp}}]}},
            "usage": {"inputTokens": 10, "outputTokens": 5}}


def test_classify_retries_once_then_skips():
    class Client:
        def __init__(self, replies):
            self.replies, self.calls = list(replies), 0

        def converse(self, **kw):
            self.calls += 1
            assert kw["inferenceConfig"] == {"maxTokens": 500}
            # "auto" since abb7dec: a forced tool choice is incompatible with the model's thinking
            # mode, so plain-text JSON answers are parsed as a fallback (see converse_once).
            assert kw["toolConfig"]["toolChoice"] == {"auto": {}}
            spec = kw["toolConfig"]["tools"][0]["toolSpec"]
            assert spec["name"] == "record_evidence"
            props = spec["inputSchema"]["json"]["properties"]
            assert set(props) == {"relevant", "channel", "direction", "excerpt", "section"}
            assert "enum" in props["channel"] and "enum" in props["direction"]
            return self.replies.pop(0)

    text_only = {"output": {"message": {"content": [{"text": "no tool"}]}},
                 "usage": {"inputTokens": 10, "outputTokens": 5}}
    u = ev.Usage()
    c = Client([text_only, tool_reply({"relevant": False})])
    assert ev.classify_passage(c, "m", "XOM", "doc", "p", u) == {"relevant": False}
    assert c.calls == 2 and u.input_tokens == 20 and u.output_tokens == 10
    c = Client([text_only, tool_reply({"relevant": True}, name="other_tool")])
    assert ev.classify_passage(c, "m", "XOM", "doc", "p", u) is None
    assert c.calls == 2
    # With toolChoice auto the model may answer in text; fenced JSON is accepted on the first try.
    fenced = {"output": {"message": {"content": [{"text": '```json\n{"relevant": false}\n```'}]}},
              "usage": {"inputTokens": 1, "outputTokens": 1}}
    counts = {}
    c = Client([fenced])
    assert ev.classify_passage(c, "m", "XOM", "doc", "p", u, counts) == {"relevant": False}
    assert c.calls == 1 and counts == {"text": 1}


# --- passages and selection -------------------------------------------------

def test_split_passages_overlap():
    text = "".join(chr(97 + i % 26) for i in range(3000))
    parts = ev.split_passages(text)
    assert all(len(p) <= 1500 for p in parts)
    assert parts[0][-200:] == parts[1][:200]
    assert parts[-1].endswith(text[-10:])


def test_score_counts_distinct_keywords_double_for_oil_terms():
    assert ev.score_passage("nothing relevant") == 0
    assert ev.score_passage("oil oil oil") == 2                     # distinct: repeats do not add
    assert ev.score_passage("Crude and Brent") == 4
    assert ev.score_passage("inflation and currency") == 2          # single-weight keywords
    assert ev.score_passage("oil, inflation, duration") == 4


def test_prefilter_keeps_top_25_by_score_in_order_with_pages():
    passages = []
    for i in range(60):
        text = "oil crude Brent" if i % 3 == 0 else ("inflation" if i % 3 == 1 else "nothing here")
        passages.append({"page": i + 1, "text": text})
    kept = ev.prefilter(passages)
    assert len(kept) == 25
    # 20 passages score 6; the 5 earliest score-1 passages fill the remaining slots
    assert sum(p["text"] == "oil crude Brent" for p in kept) == 20
    assert sum(p["text"] == "inflation" for p in kept) == 5
    assert [p["page"] for p in kept] == sorted(p["page"] for p in kept)
    assert all("page" in p for p in kept)
    inflation_pages = [p["page"] for p in kept if p["text"] == "inflation"]
    assert inflation_pages == [2, 5, 8, 11, 14]


def test_prefilter_late_high_score_beats_early_low_score():
    passages = [{"page": i, "text": "inflation"} for i in range(30)]
    passages.append({"page": 99, "text": "oil crude"})
    kept = ev.prefilter(passages)
    assert len(kept) == 25 and kept[-1]["page"] == 99


# --- resumable cache --------------------------------------------------------

class FakeS3:
    def __init__(self, files):
        self.objects = dict(files)
        self.gets = []

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        if Key not in self.objects:
            err = Exception("missing")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        import io
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body


class OilClient:
    def __init__(self):
        self.calls = 0

    def converse(self, **kw):
        self.calls += 1
        ans = {"relevant": True, "channel": "direct", "direction": "positive",
               "excerpt": "Higher oil prices lift revenue.", "section": "Outlook"}
        return tool_reply(ans)


def test_resume_skips_cached_document():
    html_doc = b"<html><p>Higher oil prices lift revenue.</p></html>"
    manifest = b"file,ticker,doc_type,source_url\na.html,XOM,page,http://a\n"
    s3 = FakeS3({"raw/manual_docs/manifest_docs.csv": manifest, "raw/manual_docs/a.html": html_doc})
    client = OilClient()
    df, passages = ev.build_evidence("b", "m", s3=s3, client=client)
    assert client.calls == 1 and len(df) == 1
    assert "processed/_evidence_cache/a.html.json" in s3.objects
    # second run: cache hit, no model call, same result
    df2, _ = ev.build_evidence("b", "m", s3=s3, client=client)
    assert client.calls == 1 and df2["evidence_id"].tolist() == df["evidence_id"].tolist()
    # Part B input comes from the cache without the model
    assert ev.evidence_from_cache("b", s3)["excerpt"].tolist() == df["excerpt"].tolist()
    # a changed manifest value invalidates the cache
    s3.objects["raw/manual_docs/manifest_docs.csv"] = manifest.replace(b"http://a", b"http://b")
    ev.build_evidence("b", "m", s3=s3, client=client)
    assert client.calls == 2


def test_html_to_text_strips_tags():
    out = ev.normalize_ws(ev.html_to_text("<html><script>x=1</script><p>Oil &amp; gas</p><b>fuel</b></html>"))
    assert out == "Oil & gas fuel"


def _cand(ticker, channel, excerpt):
    return {"ticker": ticker, "doc_type": "d", "channel": channel, "direction": "positive",
            "source_url": "u", "section": "", "excerpt": excerpt, "s3_key": "k", "passage": excerpt}


def test_select_evidence_max_three_longest_first():
    cands = [_cand("XOM", "direct", "a" * n) for n in (5, 30, 10, 20, 30)]
    cands.append(_cand("XOM", "rates", "r"))
    out = ev.select_evidence(cands)
    direct = [r for r in out if r["channel"] == "direct"]
    assert [r["evidence_id"] for r in direct] == ["XOM-direct-1", "XOM-direct-2", "XOM-direct-3"]
    assert [len(r["excerpt"]) for r in direct] == [30, 20, 10]   # duplicate excerpt dropped
    assert any(r["evidence_id"] == "XOM-rates-1" for r in out)


def test_kb_metadata_format():
    row = {"ticker": "XOM", "doc_type": "10-K", "channel": "direct", "direction": "positive",
           "source_url": "http://x", "section": "Risk", "excerpt": "e", "evidence_id": "XOM-direct-1"}
    meta = ev.kb_metadata(row)
    assert list(meta) == ["metadataAttributes"]
    assert list(meta["metadataAttributes"]) == [
        "ticker", "doc_type", "channel", "direction", "source_url", "section"]
    json.dumps(meta)
    text = ev.kb_document(row, "the passage")
    assert text.startswith("Ticker: XOM\nChannel: direct\nDirection: positive\nSource: http://x\nSection: Risk")
    assert "Excerpt: e" in text and "Passage: the passage" in text


# --- label rule -------------------------------------------------------------

def sens_row(ticker, beta, p, beta_ex=None, p_ex=0.01):
    return {"ticker": ticker, "beta_simple": beta, "p_simple": p,
            "beta_ex2022": beta if beta_ex is None else beta_ex, "p_ex2022": p_ex}


def test_label_rules():
    assert ev.label_row(sens_row("A", 0.5, 0.01), 0.64, set(), "oil>us10y>A")[:2] == ("green", "SIG_STABLE_EXPLAINED")
    assert ev.label_row(sens_row("A", 0.5, 0.01), 0.1, {"positive"})[:2] == ("green", "SIG_STABLE_CITED")
    assert ev.label_row(sens_row("A", 0.5, 0.01), 0.1, {"negative"})[:2] == ("yellow", "SIG_UNEXPLAINED")
    assert ev.label_row(sens_row("A", 0.5, 0.01), None, set())[:2] == ("yellow", "SIG_UNEXPLAINED")
    assert ev.label_row(sens_row("A", -0.5, 0.01), np.nan, {"negative"})[:2] == ("green", "SIG_STABLE_CITED")
    assert ev.label_row(sens_row("A", 0.5, 0.01, p_ex=0.2), 0.9, {"positive"})[:2] == ("yellow", "SIG_UNSTABLE")
    assert ev.label_row(sens_row("A", 0.5, 0.01, beta_ex=-0.2), 0.9, {"positive"})[:2] == ("yellow", "SIG_UNSTABLE")
    assert ev.label_row(sens_row("A", 0.5, 0.05), 0.9, {"positive"})[:2] == ("grey", "NOT_SIG")
    assert ev.label_row(sens_row("A", 0.5, np.nan), 0.9, {"positive"})[:2] == ("grey", "NOT_SIG")


def test_extra_universe_needs_q_below_010():
    def extra(q, universe="extra", **kw):
        r = sens_row("E", 0.5, 0.01, **kw)
        r.update({"universe": universe, "q_simple": q})
        return r

    assert ev.label_row(extra(0.05), 0.9, set())[:2] == ("green", "SIG_STABLE_EXPLAINED")
    assert ev.label_row(extra(0.05, p_ex=0.2), 0.9, set())[:2] == ("yellow", "SIG_UNSTABLE")
    assert ev.label_row(extra(0.10), 0.9, {"positive"})[:2] == ("grey", "NOT_SIG")
    assert ev.label_row(extra(0.30, p_ex=0.2), 0.9, {"positive"})[:2] == ("grey", "NOT_SIG")
    assert ev.label_row(extra(np.nan), 0.9, {"positive"})[0] == "grey"
    assert ev.label_row(extra(0.5), 0.9, {"positive"})[2].endswith(".")
    # core tickers ignore q_simple
    assert ev.label_row(extra(0.5, universe="core"), 0.9, set())[0] == "green"
    # build_confidence passes universe and q_simple through
    sens = pd.DataFrame([{**extra(0.5), "ticker": "E"}])
    out = ev.build_confidence(sens, pd.DataFrame(columns=["ticker", "share_explained", "chain"]),
                              pd.DataFrame(columns=["ticker", "direction"]))
    assert out.loc[0, "label"] == "grey"


def test_label_text_has_numbers():
    text = ev.label_row(sens_row("TLT", -0.4, 0.001), 0.64, set(), "rates")[2]
    assert "64%" in text and text.endswith(".")


def test_confidence_and_channels():
    sens = pd.DataFrame([
        sens_row("XOM", 0.8, 0.001), sens_row("RY.TO", 0.05, 0.6), sens_row("ZZZ", 0.9, 0.001),
    ])
    chain = pd.DataFrame(columns=["ticker", "chain", "beta_direct", "beta_chain", "share_explained"])
    evid = pd.DataFrame([{"ticker": "XOM", "direction": "positive", "evidence_id": "XOM-direct-1"}])
    conf = ev.build_confidence(sens, chain, evid).set_index("ticker")
    assert conf.loc["RY.TO", "label"] == "grey"
    assert conf.loc["RY.TO", "channel"] == "none"
    assert conf.loc["XOM", "label"] == "green" and conf.loc["XOM", "channel"] == "direct"
    assert conf.loc["ZZZ", "channel"] == "none"          # unknown ticker never raises
    assert conf.loc["ZZZ", "label"] == "yellow"


def test_channel_map():
    expected = {"XOM": "direct", "ENB.TO": "direct", "XIU.TO": "direct", "XESG.TO": "direct",
                "TLT": "rates", "XBB.TO": "rates", "ZST.TO": "rates", "QQQ": "rates", "SHOP.TO": "rates",
                "VFV.TO": "currency", "XSP.TO": "currency", "ATD.TO": "company-specific",
                "RY.TO": "none", "SPY": "none", "CNQ.TO": "direct", "XEG.TO": "direct",
                "XLB.TO": "rates", "XRB.TO": "rates", "AGG": "rates", "NVDA": "none"}
    assert {t: ev.main_channel(t) for t in expected} == expected


def test_edges():
    links = pd.DataFrame([{"link_id": "oil>us10y", "from_node": "oil", "to_node": "us10y",
                           "beta": 1.0, "lo": 0.5, "hi": 1.5, "p": 0.01, "unit": "u"}])
    evid = pd.DataFrame([{"ticker": "XOM", "evidence_id": "XOM-direct-1"}])
    e = ev.build_edges(links, evid)
    assert list(e.columns) == ev.EDGE_COLUMNS
    assert e["edge_type"].tolist() == ["measured", "cited"]
    cited = e.iloc[1]
    assert cited["from_node"] == "oil" and cited["to_node"] == "XOM"
    assert pd.isna(cited["beta"]) and cited["evidence_id"] == "XOM-direct-1"
    # None in pandas 2, NaN in pandas 3 (string dtype); both are written as a Parquet null.
    assert pd.isna(e.iloc[0]["evidence_id"])
