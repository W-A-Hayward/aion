"""Claim comparisons for the cascade evaluation. Pure functions, no AWS.

A claim is {"ticker" | "persona": str, "label"?, "beta"?, "verdict"?, "impact_pct"?, "shock_pct"?}.
The agent builds claims from the tool results it used (agent/agent.py, claims_from_result). The functions
here rebuild the same claims from stored tool calls (a fallback), compare claims with the golden values
(eval/golden.json), and measure agreement and stability between runs.

Tolerance for numbers: within 0.005 absolute or within 2% of the reference value.
"""
import json
import math

ABS_TOL = 0.005
REL_TOL = 0.02
TEXT_FIELDS = ("label", "verdict")
NUMBER_FIELDS = ("beta", "impact_pct")
TRUNCATION_MARK = "[truncated]"


# ----------------------------------------------------------------------------- numbers

def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isnan(value)


def close(value, reference, abs_tol=ABS_TOL, rel_tol=REL_TOL):
    """True if value is within abs_tol of reference, or within rel_tol of |reference|."""
    if not is_number(value) or not is_number(reference):
        return False
    diff = abs(value - reference)
    return diff <= abs_tol + 1e-12 or diff <= rel_tol * abs(reference) + 1e-12


# ----------------------------------------------------------------------------- building claims

def _text(value):
    return value if isinstance(value, str) and value else None


def _number(value):
    return value if is_number(value) else None


def claims_from_result(name, params, result):
    """Claims from one tool result. Same rules as agent.claims_from_result; keep the two in step."""
    if not isinstance(result, dict) or result.get("error"):
        return []
    params = params if isinstance(params, dict) else {}
    ticker = result.get("ticker") or params.get("ticker")
    persona = result.get("persona") or params.get("persona")
    out = []

    def add(key, subject, **fields):
        fields = {k: v for k, v in fields.items() if v is not None}
        if subject and fields:
            out.append(dict({key: subject}, **fields))

    def rows(key):
        return [r for r in (result.get(key) or []) if isinstance(r, dict)]

    def box(key):
        value = result.get(key)
        return value if isinstance(value, dict) else {}

    if name == "get_portfolio_exposure":
        for h in rows("holdings"):
            add("ticker", h.get("ticker"), beta=_number(h.get("beta")))
        add("persona", persona, beta=_number(box("portfolio_beta").get("beta")))
    elif name == "get_asset_sensitivity":
        add("ticker", ticker, beta=_number(box("sensitivity").get("beta_simple")))
    elif name == "explain_channel":
        add("ticker", ticker, label=_text(box("confidence").get("label")))
    elif name == "get_validation":
        add("ticker", ticker, label=_text(box("validation").get("label")))
    elif name == "run_scenario":
        shock = _number(result.get("oil_shock_pct"))
        shock = int(shock) if shock is not None and shock == int(shock) else shock
        for s in rows("scenario"):
            add("persona", persona, impact_pct=_number(s.get("impact_pct")), shock_pct=shock)
        for h in rows("holding_impacts"):
            add("ticker", h.get("ticker"), impact_pct=_number(h.get("impact_pct")), shock_pct=shock)
    elif name == "compare_alternative":
        c = box("comparison")
        add("ticker", result.get("holding"), beta=_number(c.get("beta_holding")))
        add("ticker", result.get("alternative"), beta=_number(c.get("beta_alternative")))

    for holder in [result] + [v for v in result.values() if isinstance(v, dict)]:
        verdict = _text(holder.get("verdict"))
        if verdict:
            if ticker:
                add("ticker", ticker, verdict=verdict)
            else:
                add("persona", persona, verdict=verdict)
    return out


def dedupe(claims):
    seen, out = set(), []
    for c in claims:
        key = json.dumps(c, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def claims_from_tool_calls(tool_calls):
    """Rebuild claims from stored tool calls ({"name", "input", "output"}). Returns (claims, unparsed):
    unparsed counts the calls whose output could not be read as JSON (for example a truncated output)."""
    claims, unparsed = [], 0
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        output = call.get("output")
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except ValueError:
                unparsed += 1
                continue
        claims.extend(claims_from_result(call.get("name"), call.get("input"), output))
    return dedupe(claims), unparsed


# ----------------------------------------------------------------------------- claims vs golden

def impact_key(kind, subject, shock):
    return "%s|%s|%d" % (kind, subject, int(shock))


def _subject(claim):
    if claim.get("ticker"):
        return "ticker", claim["ticker"]
    if claim.get("persona"):
        return "persona", claim["persona"]
    return None, None


def _golden_value(expected, kind, subject, field, claim):
    if field == "label":
        return (expected.get("labels") or {}).get(subject) if kind == "ticker" else None
    if field == "verdict":
        return (expected.get("verdicts") or {}).get(subject)
    if field == "beta":
        if kind == "ticker":
            return (expected.get("betas") or {}).get(subject)
        if subject == expected.get("persona"):
            return (expected.get("portfolio_beta") or {}).get("beta")
        return None
    if field == "impact_pct":
        if not is_number(claim.get("shock_pct")):
            return None
        return (expected.get("impacts") or {}).get(impact_key(kind, subject, claim["shock_pct"]))
    return None


def check_claims(claims, expected):
    """Compare claims with one question's golden values. Labels and verdicts must be equal; numbers
    must be close() to the golden number. A claim with no golden value is listed as unchecked
    and does not fail the check."""
    problems, unchecked, checked = [], [], 0
    for claim in claims or []:
        kind, subject = _subject(claim)
        if subject is None:
            continue
        for field in TEXT_FIELDS + NUMBER_FIELDS:
            if field not in claim:
                continue
            desc = "%s %s %s=%r" % (kind, subject, field, claim[field])
            if field == "impact_pct":
                desc += " at shock %s" % claim.get("shock_pct")
            want = _golden_value(expected or {}, kind, subject, field, claim)
            if want is None:
                unchecked.append(desc)
                continue
            checked += 1
            ok = claim[field] == want if field in TEXT_FIELDS else close(claim[field], want)
            if not ok:
                problems.append("%s, golden %r" % (desc, want))
    return {"pass": not problems, "checked": checked, "problems": problems, "unchecked": unchecked}


# ----------------------------------------------------------------------------- consistency

def _text_map(claims, field):
    out = {}
    for c in claims or []:
        if c.get("ticker") and field in c:
            out.setdefault(c["ticker"], set()).add(c[field])
    return out


def agreement(claims_a, claims_b):
    """Label and verdict agreement between two runs, over tickers that both runs state.
    Returns {"label": {"agree", "compared", "disagree": [ticker]}, "verdict": {...}}."""
    out = {}
    for field in TEXT_FIELDS:
        a, b = _text_map(claims_a, field), _text_map(claims_b, field)
        shared = sorted(set(a) & set(b))
        disagree = [t for t in shared if a[t] != b[t]]
        out[field] = {"agree": len(shared) - len(disagree), "compared": len(shared), "disagree": disagree}
    return out


def _number_map(claims):
    out = {}
    for c in claims or []:
        kind, subject = _subject(c)
        if subject is None:
            continue
        for field in NUMBER_FIELDS:
            if is_number(c.get(field)):
                key = "%s|%s|%s|%s" % (kind, subject, field, c.get("shock_pct", ""))
                out.setdefault(key, []).append(c[field])
    return out


def stability(runs):
    """How much repeated runs of one question agree. `runs` is a list of claim lists.
    For labels, verdicts and numbers: stable = stated in every run with the same value (numbers: all
    close() to the first run); partial = stated in some runs only; unstable = stated in every run
    with different values."""
    out = {"runs": len(runs)}
    for field in TEXT_FIELDS:
        maps = [_text_map(r, field) for r in runs]
        keys = set().union(*maps) if maps else set()
        stable = [k for k in keys if all(k in m for m in maps) and len({frozenset(m[k]) for m in maps}) == 1]
        partial = [k for k in keys if not all(k in m for m in maps)]
        out[field] = {"stable": len(stable), "total": len(keys), "partial": sorted(partial),
                      "unstable": sorted(k for k in keys if k not in stable and k not in partial)}
    maps = [_number_map(r) for r in runs]
    keys = set().union(*maps) if maps else set()
    stable, partial, unstable, spread = 0, [], [], 0.0
    for k in sorted(keys):
        if not all(k in m for m in maps):
            partial.append(k)
            continue
        values = [v for m in maps for v in m[k]]
        spread = max(spread, max(values) - min(values))
        if all(close(v, values[0]) for v in values):
            stable += 1
        else:
            unstable.append(k)
    out["numbers"] = {"stable": stable, "total": len(keys), "partial": partial, "unstable": unstable,
                      "max_spread": spread}
    return out
