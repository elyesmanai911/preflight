import json

from agent import review

TRIVY = {
    "Results": [
        {
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-1",
                    "Severity": "HIGH",
                    "PkgName": "starlette",
                    "FixedVersion": "0.47.2",
                },
                {
                    "VulnerabilityID": "CVE-1",
                    "Severity": "HIGH",
                    "PkgName": "starlette",
                    "FixedVersion": "0.47.2",
                },
                {"VulnerabilityID": "CVE-2", "Severity": "CRITICAL", "PkgName": "libc"},
                {"VulnerabilityID": "CVE-3", "Severity": "LOW", "PkgName": "zlib"},
            ]
        },
        {"Vulnerabilities": None},
    ]
}
MAIN = {"precision": 0.96, "recall": 0.80, "f1": 0.877}
PR = {"precision": 0.96, "recall": 0.70, "f1": 0.80}


def test_cve_list_counts_and_dedupes_serious_findings():
    counts, cves = review.cve_list(TRIVY)
    assert counts["HIGH"] == 2 and counts["CRITICAL"] == 1 and counts["LOW"] == 1
    assert [c["id"] for c in cves] == ["CVE-2", "CVE-1"]  # critical first, CVE-1 once
    assert cves[0]["fixed_in"] == "no fix yet"


def test_metrics_table_marks_regressions():
    table = review.metrics_table(MAIN, PR)
    assert "| f1 | 0.8770 | 0.8000 | -0.0770 ⚠️ |" in table
    assert "| precision | 0.9600 | 0.9600 | +0.0000  |" in table


def test_metrics_table_without_baseline():
    assert "| f1 | n/a | 0.8000 | |" in review.metrics_table(None, PR)


def test_parse_json_reply_handles_fences():
    assert review.parse_json_reply('```json\n{"risk_level": "low"}\n```') == {
        "risk_level": "low"
    }


def run_main(tmp_path, monkeypatch, capsys):
    (tmp_path / "diff").write_text("+ changed line")
    (tmp_path / "trivy.json").write_text(json.dumps(TRIVY))
    (tmp_path / "pr.json").write_text(json.dumps(PR))
    (tmp_path / "main.json").write_text(json.dumps(MAIN))
    args = ["review", "--diff", f"{tmp_path}/diff", "--trivy", f"{tmp_path}/trivy.json"]
    args += ["--metrics", f"{tmp_path}/pr.json", "--baseline", f"{tmp_path}/main.json"]
    args += ["--preview-url", "http://pr-1.example", "--image", "img:sha"]
    monkeypatch.setattr("sys.argv", args)
    review.main()
    return capsys.readouterr().out


def test_comment_includes_ai_review(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LLM_BASE_URL", "http://llm")
    monkeypatch.setenv("LLM_MODEL", "m")
    fake = {
        "risk_level": "high",
        "summary": "Recall dropped.",
        "what_to_test": ["Post an 18% VAT invoice"],
        "fix_now": ["CVE-2"],
        "cve_note": "Rest can wait.",
        "model_note": "The model misses more anomalies.",
    }
    monkeypatch.setattr(review, "ask_llm", lambda prompt: fake)
    out = run_main(tmp_path, monkeypatch, capsys)
    assert "🔴 high" in out and "- [ ] Post an 18% VAT invoice" in out
    assert "**Fix now:** `CVE-2`" in out and "http://pr-1.example" in out
    assert "AI review unavailable" not in out


def test_comment_still_posts_when_llm_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LLM_BASE_URL", "http://llm")
    monkeypatch.setenv("LLM_MODEL", "m")

    def broken(prompt):
        raise TimeoutError("rate limited")

    monkeypatch.setattr(review, "ask_llm", broken)
    out = run_main(tmp_path, monkeypatch, capsys)
    assert "AI review unavailable (TimeoutError: rate limited)" in out
    assert "-0.0770 ⚠️" in out and "critical: 1" in out
