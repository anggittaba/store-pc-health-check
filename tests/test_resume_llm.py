import json

import pytest

from pchealth import llm, resume
from tests.conftest import END


def test_template_resume_mentions_counts_and_never_claims_sent(filled):
    r = filled.execute("SELECT * FROM resumes WHERE date=?", (END.isoformat(),)).fetchone()
    text = r["text"]
    assert text.startswith("PC health recap · Sun 11 Oct 2026")
    assert "Check it before you send it." in text
    assert r["writer"] == "template"
    expl = json.loads(r["explanations"])
    flagged = {x[0] for x in filled.execute("SELECT DISTINCT store_code FROM issues WHERE date=?", (END.isoformat(),))}
    assert set(expl) == flagged


def test_ordinal_and_low():
    assert [resume.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]
    assert resume.low("LAN degraded") == "LAN degraded" and resume.low("Overheating") == "overheating"
    assert resume.low("Windows not activated") == "Windows not activated"


class FakeProvider:
    name = "fake:model"

    def __init__(self, out):
        self.out = out
        self.calls = 0

    def complete(self, system, user, schema, name):
        self.calls += 1
        facts = json.loads(user)
        return self.out(facts) if callable(self.out) else self.out


def _rerun(filled, cfg, provider):
    from pchealth import engine
    return engine.run_day(filled, cfg, END.isoformat(), provider=provider)


def test_llm_output_used_when_it_passes_checks(filled, cfg):
    good = lambda f: {"summary": f"{f['stores_flagged']} stores need attention today.",
                      "stores": [{"store_code": s["store_code"], "explanation": f"{s['store_name']} needs a look."} for s in f["stores"]]}
    res = _rerun(filled, cfg, FakeProvider(good))
    assert res.writer == "fake:model"
    r = filled.execute("SELECT text FROM resumes WHERE date=?", (END.isoformat(),)).fetchone()
    assert "Drafted by AI" in r["text"]
    _rerun(filled, cfg, None)  # restore template for other tests


def test_llm_output_with_invented_number_is_rejected(filled, cfg):
    bad = lambda f: {"summary": "4321 stores are down.",
                     "stores": [{"store_code": s["store_code"], "explanation": "ok"} for s in f["stores"]]}
    res = _rerun(filled, cfg, FakeProvider(bad))
    assert res.writer.startswith("template (AI output rejected")
    _rerun(filled, cfg, None)


def test_llm_output_missing_a_store_is_rejected(filled, cfg):
    res = _rerun(filled, cfg, FakeProvider({"summary": "x", "stores": []}))
    assert res.writer.startswith("template (AI output rejected")
    _rerun(filled, cfg, None)


def test_llm_never_changes_severity(filled, cfg):
    before = [tuple(r) for r in filled.execute("SELECT store_code, issue_type, severity FROM issues WHERE date=? ORDER BY 1,2", (END.isoformat(),))]
    good = lambda f: {"summary": "All critical.", "stores": [{"store_code": s["store_code"], "explanation": "critical"} for s in f["stores"]]}
    _rerun(filled, cfg, FakeProvider(good))
    after = [tuple(r) for r in filled.execute("SELECT store_code, issue_type, severity FROM issues WHERE date=? ORDER BY 1,2", (END.isoformat(),))]
    assert before == after
    _rerun(filled, cfg, None)


def test_provider_from_env(monkeypatch):
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "PCHEALTH_LLM"):
        monkeypatch.delenv(k, raising=False)
    assert llm.provider_from_env() is None
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm.provider_from_env().name.startswith("gemini:")
    monkeypatch.setenv("PCHEALTH_LLM", "off")
    assert llm.provider_from_env() is None


def test_openai_and_gemini_payloads():
    seen = {}

    def post(url, payload, headers, timeout=30.0):
        seen["url"], seen["payload"], seen["headers"] = url, payload, headers
        body = json.dumps({"summary": "s", "stores": []})
        if "openai" in url:
            return {"choices": [{"message": {"content": body}}]}
        return {"candidates": [{"content": {"parts": [{"text": body}]}}]}

    o = llm.OpenAIProvider("k", post=post).complete("sys", "user", llm.RESUME_SCHEMA, "daily_resume")
    assert o["summary"] == "s" and seen["payload"]["response_format"]["json_schema"]["strict"] is True
    g = llm.GeminiProvider("k", post=post).complete("sys", "user", llm.RESUME_SCHEMA, "daily_resume")
    assert g["summary"] == "s"
    schema = seen["payload"]["generationConfig"]["responseSchema"]
    assert schema["properties"]["stores"]["items"]["type"] == "OBJECT"
