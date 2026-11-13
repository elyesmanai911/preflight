"""Preflight release agent: builds the single PR comment.

Facts (preview URL, metric numbers, CVE counts) are computed here. The LLM only adds judgement:
risk summary, what to test, which CVEs to fix now, and what the metric change means.
If the LLM is unavailable, the comment still posts with the facts.

LLM settings (any OpenAI-compatible endpoint):
  LLM_BASE_URL  e.g. https://generativelanguage.googleapis.com/v1beta/openai  or  http://localhost:11434/v1
  LLM_MODEL     e.g. gemini-flash-latest  or  qwen2.5:3b
  LLM_API_KEY   empty for Ollama
  LLM_TIMEOUT   seconds per request (default 180; CPU-only Ollama needs more)
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

MAX_DIFF_CHARS = 12_000  # keeps prompts well inside free-tier token limits
MAX_CVES = 25
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

# Instructions go LAST: if a provider truncates a long prompt, it cuts the start, not the task.
PROMPT = """You review a pull request for an invoice API with an anomaly-detection model.

## Diff
{diff}

## Model metrics (main → this PR)
{metrics}

## HIGH/CRITICAL vulnerabilities in the image
{cves}

## Your task
Review the pull request above. Reply with ONLY a JSON object, no markdown fences, with these keys:
  "risk_level": "low" | "medium" | "high",
  "summary": 2-3 sentences: what changed and its blast radius,
  "what_to_test": list of up to 4 short manual checks,
  "fix_now": list of CVE ids from the list above worth fixing before merge (empty if none),
  "cve_note": one sentence on the remaining CVEs,
  "model_note": one sentence on what the metric change means (or that the model is unchanged).
"""


def cve_list(trivy: dict) -> tuple[dict, list[dict]]:
    """Severity counts plus the HIGH/CRITICAL findings, de-duplicated by CVE id."""
    counts = dict.fromkeys(SEVERITY_ORDER, 0)
    serious = {}
    for result in trivy.get("Results", []):
        for vuln in result.get("Vulnerabilities") or []:
            severity = vuln.get("Severity", "UNKNOWN")
            counts[severity] = counts.get(severity, 0) + 1
            if severity in ("CRITICAL", "HIGH"):
                serious.setdefault(
                    vuln["VulnerabilityID"],
                    {
                        "id": vuln["VulnerabilityID"],
                        "severity": severity,
                        "package": vuln.get("PkgName", "?"),
                        "fixed_in": vuln.get("FixedVersion") or "no fix yet",
                    },
                )
    ranked = sorted(serious.values(), key=lambda v: SEVERITY_ORDER.index(v["severity"]))
    return counts, ranked[:MAX_CVES]


def metrics_table(main: dict | None, pr: dict) -> str:
    rows = ["| Metric | main | this PR | Δ |", "|---|---|---|---|"]
    for key in ("precision", "recall", "f1"):
        if main is None:
            rows.append(f"| {key} | n/a | {pr[key]:.4f} | |")
            continue
        delta = pr[key] - main[key]
        mark = "⚠️" if delta < -0.005 else ("✅" if delta > 0.005 else "")
        rows.append(
            f"| {key} | {main[key]:.4f} | {pr[key]:.4f} | {delta:+.4f} {mark} |"
        )
    return "\n".join(rows)


def ask_llm(prompt: str) -> dict:
    base_url = os.environ["LLM_BASE_URL"].rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(
            {
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {
                    "type": "json_object"
                },  # JSON mode: the reply must parse
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}",
        },
    )
    for attempt in range(3):
        try:
            timeout = float(os.environ.get("LLM_TIMEOUT", "180"))
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = json.load(response)["choices"][0]["message"]["content"]
            return parse_json_reply(content)
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:300]
            if (
                error.code in (429, 503) and attempt < 2
            ):  # rate limited / overloaded: wait, retry
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {error.code}: {body}") from error


def parse_json_reply(content: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or add text around it; take the object."""
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"no JSON object in reply: {content[:150]!r}")
    return json.loads(content[start : end + 1])


def render(
    preview_url: str,
    image: str,
    table: str,
    counts: dict,
    ai: dict | None,
    ai_error: str,
) -> str:
    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}
    counts_line = " · ".join(f"{sev.lower()}: {n}" for sev, n in counts.items() if n)
    parts = [
        "## 🛫 Preflight report",
        f"🔗 **Preview:** {preview_url}  \nImage: `{image}`",
    ]
    if ai:
        level = str(ai.get("risk_level", "?")).lower()
        tests = "\n".join(f"- [ ] {t}" for t in ai.get("what_to_test", []))
        parts.append(
            f"### 🧠 Risk: {risk_icon.get(level, '⚪')} {level}\n{ai.get('summary', '')}\n\n**What to test**\n{tests}"
        )
    parts.append(
        f"### 📈 Model\n{table}" + (f"\n\n{ai.get('model_note', '')}" if ai else "")
    )
    security = f"### 🛡️ Security\nImage vulnerabilities: {counts_line or 'none'}"
    if ai:
        fix_now = ", ".join(f"`{c}`" for c in ai.get("fix_now", [])) or "nothing urgent"
        security += f"\n\n**Fix now:** {fix_now}  \n{ai.get('cve_note', '')}"
    parts.append(security)
    if not ai:
        parts.append(
            f"> ℹ️ AI review unavailable ({ai_error}). The facts above are still accurate."
        )
    return "\n\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Preflight PR comment.")
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--trivy", type=Path, required=True, help="Trivy JSON report")
    parser.add_argument(
        "--metrics", type=Path, required=True, help="this PR's metrics.json"
    )
    parser.add_argument("--baseline", type=Path, help="main's metrics.json (optional)")
    parser.add_argument("--preview-url", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    pr_metrics = json.loads(args.metrics.read_text())
    main_metrics = (
        json.loads(args.baseline.read_text())
        if args.baseline and args.baseline.exists()
        else None
    )
    counts, cves = cve_list(json.loads(args.trivy.read_text()))
    table = metrics_table(main_metrics, pr_metrics)

    ai, ai_error = None, ""
    if os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_MODEL"):
        prompt = PROMPT.format(
            diff=args.diff.read_text()[:MAX_DIFF_CHARS],
            metrics=table,
            cves="\n".join(
                f"- {c['id']} ({c['severity']}) in {c['package']}, fixed in {c['fixed_in']}"
                for c in cves
            )
            or "none",
        )
        try:
            ai = ask_llm(prompt)
        except Exception as error:  # any LLM failure must not block the comment
            ai_error = f"{type(error).__name__}: {error}"[:200]
    else:
        ai_error = "LLM_BASE_URL / LLM_MODEL not set"

    print(render(args.preview_url, args.image, table, counts, ai, ai_error))


if __name__ == "__main__":
    main()
