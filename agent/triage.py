"""Preflight triage watcher: diagnoses failing preview environments and comments on the PR.

Runs in the cluster as a CronJob. For each preview app (Argo CD Application `preview-pr-<N>`):
detect problems in code -> confirm on the next run (debounce) -> collect pod status, warning
events and Loki logs -> ask the LLM for root cause and fix -> post one comment per failing commit.

Settings (env): GITHUB_REPO, GITHUB_TOKEN, LOKI_URL, the LLM_* settings from agent/review.py,
K8S_API (default: in-cluster API; use http://localhost:8001 with `kubectl proxy` locally).
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from agent.review import ask_llm

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
STATE = (
    "preflight-system",
    "preflight-triage-state",
)  # ConfigMap: pr-N -> "seen:<sha>" | "<sha>"
BAD_WAITING = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "CreateContainerError",
}
SMOKE_INVOICE = {
    "customer_tax_id": "SMOKE",
    "issue_date": "2026-01-01",
    "lines": [
        {
            "description": "smoke",
            "quantity": "1",
            "unit_price": "10",
            "vat_rate": "0.19",
        }
    ],
}

PROMPT = """A Kubernetes preview environment for a pull request is failing. The app is a FastAPI
invoice API that loads a scikit-learn model file at startup (env MODEL_PATH).
If the image cannot be pulled, the CI pipeline did not publish it: the build, the tests or the
model quality gate failed.

## Signals detected
{signals}

## Pod status
{pods}

## Warning events
{events}

## Last log lines
{logs}

## Your task
Reply with ONLY a JSON object with these keys:
  "root_cause": 1-2 sentences naming the most likely cause, citing the evidence,
  "fix": 1-2 sentences with the concrete change to make,
  "confidence": "low" | "medium" | "high".
"""


# ---------- Kubernetes, Loki and GitHub over plain HTTP ----------


def http(
    url: str, method: str = "GET", body=None, headers=None, context=None, timeout=20
):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers or {}
    )
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read().decode()
        return response.status, (json.loads(raw) if raw.startswith(("{", "[")) else raw)


def k8s(path: str, method: str = "GET", body=None, content_type="application/json"):
    base = os.environ.get("K8S_API", "https://kubernetes.default.svc")
    headers = {"Content-Type": content_type}
    context = None
    if base.startswith("https"):
        headers["Authorization"] = f"Bearer {(SA_DIR / 'token').read_text()}"
        context = ssl.create_default_context(cafile=str(SA_DIR / "ca.crt"))
    return http(base + path, method, body, headers, context)


def loki_logs(namespace: str, limit: int = 40) -> list[str]:
    query = urllib.parse.urlencode(
        {"query": f'{{namespace="{namespace}"}}', "limit": limit, "since": "30m"}
    )
    _, data = http(f"{os.environ['LOKI_URL']}/loki/api/v1/query_range?{query}")
    lines = [
        (ts, line) for stream in data["data"]["result"] for ts, line in stream["values"]
    ]
    return [line.rstrip() for _, line in sorted(lines)][-limit:]


def post_comment(pr: int, body: str) -> None:
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    url = (
        f"https://api.github.com/repos/{os.environ['GITHUB_REPO']}/issues/{pr}/comments"
    )
    http(url, "POST", {"body": body}, headers)


# ---------- Detection and evidence (pure functions, unit-tested) ----------


def pod_problems(pods: dict) -> list[str]:
    problems = []
    for pod in pods.get("items", []):
        name = pod["metadata"]["name"]
        status = pod.get("status", {})
        for cond in status.get("conditions", []):
            if cond.get("type") == "PodScheduled" and cond.get("status") == "False":
                problems.append(
                    f"{name}: cannot be scheduled ({cond.get('message', '')})"
                )
        for cs in status.get("containerStatuses", []):
            waiting = cs.get("state", {}).get("waiting", {})
            last = cs.get("lastState", {}).get("terminated", {})
            if waiting.get("reason") in BAD_WAITING:
                problems.append(
                    f"{name}: {waiting['reason']} {waiting.get('message', '')}".strip()
                )
            if last.get("reason") in ("OOMKilled", "Error"):
                problems.append(
                    f"{name}: last run ended {last['reason']} (exit code {last.get('exitCode')})"
                )
    return list(dict.fromkeys(problems))  # de-duplicate, keep order


def pod_summary(pods: dict) -> str:
    rows = []
    for pod in pods.get("items", []):
        for cs in pod.get("status", {}).get("containerStatuses", []):
            state = next(iter(cs.get("state", {})), "?")
            rows.append(
                f"{pod['metadata']['name']}/{cs['name']}: {state}, restarts={cs.get('restartCount', 0)}"
            )
    return "\n".join(rows) or "no pods"


def warning_events(events: dict, limit: int = 15) -> list[str]:
    warnings = [e for e in events.get("items", []) if e.get("type") == "Warning"]
    warnings.sort(key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "")
    return [
        f"{e.get('reason')}: {e.get('message', '').strip()} (x{e.get('count', 1)})"
        for e in warnings
    ][-limit:]


def next_state(
    previous: str | None, sha: str, failing: bool
) -> tuple[str | None, bool]:
    """Debounce: report only if the same commit fails on two consecutive runs, and only once.

    Returns (new state value, whether to report now).
    """
    if not failing:
        return (
            previous if previous == sha else None
        ), False  # keep "reported", drop "seen"
    if previous == sha:
        return sha, False  # already reported this commit
    if previous == f"seen:{sha}":
        return sha, True  # failing twice in a row: report
    return f"seen:{sha}", False  # first sighting: wait one run


def render(
    pr: int, sha: str, signals: list[str], evidence: str, ai: dict | None, ai_error: str
) -> str:
    parts = [
        f"## 🔥 Preflight triage: preview `pr-{pr}` is failing",
        f"Commit `{sha[:7]}`. Signals detected:\n"
        + "\n".join(f"- {s}" for s in signals),
    ]
    if ai:
        parts.append(
            f"### 🧠 Likely root cause ({ai.get('confidence', '?')} confidence)\n{ai.get('root_cause', '')}"
            f"\n\n**Suggested fix:** {ai.get('fix', '')}"
        )
    else:
        parts.append(
            f"> ℹ️ AI diagnosis unavailable ({ai_error}). The signals and evidence are accurate."
        )
    parts.append(
        f"<details><summary>Evidence</summary>\n\n```text\n{evidence}\n```\n</details>"
    )
    return "\n\n".join(parts) + "\n"


# ---------- One pass over all preview environments ----------


def smoke_test(namespace: str) -> list[str]:
    proxy = f"/api/v1/namespaces/{namespace}/services/preflight-app:80/proxy"
    try:
        k8s(f"{proxy}/health")
        status, _ = k8s(f"{proxy}/invoices", "POST", SMOKE_INVOICE)
        return (
            [] if status == 201 else [f"smoke test: POST /invoices returned {status}"]
        )
    except urllib.error.HTTPError as error:
        return [
            f"smoke test: {error.url.split('/proxy')[-1]} returned HTTP {error.code}"
        ]
    except Exception as error:
        return [f"smoke test failed: {type(error).__name__}: {error}"[:200]]


def check(app: dict, state: dict) -> dict:
    """Check one preview app; return the state patch for it."""
    pr = int(app["metadata"]["name"].removeprefix("preview-pr-"))
    sha = app["spec"]["source"]["targetRevision"]
    namespace = f"pr-{pr}"
    _, pods = k8s(f"/api/v1/namespaces/{namespace}/pods")
    signals = pod_problems(pods)
    if (
        not signals
        and app.get("status", {}).get("health", {}).get("status") == "Healthy"
    ):
        signals = smoke_test(namespace)

    key = f"pr-{pr}"
    new, report = next_state(state.get(key), sha, failing=bool(signals))
    print(
        f"{key} {sha[:7]}: {'FAILING ' + '; '.join(signals) if signals else 'ok'} -> {new}, report={report}"
    )
    if report:
        _, events = k8s(f"/api/v1/namespaces/{namespace}/events")
        try:
            logs = "\n".join(loki_logs(namespace)) or "no log lines"
        except Exception as error:
            logs = f"(Loki unavailable: {error})"
        evidence = "\n\n".join(
            [
                "# pods\n" + pod_summary(pods),
                "# warning events\n" + ("\n".join(warning_events(events)) or "none"),
                "# logs\n" + logs,
            ]
        )
        ai, ai_error = None, ""
        try:
            ai = ask_llm(
                PROMPT.format(
                    signals="\n".join(signals),
                    pods=pod_summary(pods),
                    events="\n".join(warning_events(events)) or "none",
                    logs=logs[-6000:],
                )
            )
        except Exception as error:  # the comment must post even without the LLM
            ai_error = f"{type(error).__name__}: {error}"[:200]
        post_comment(pr, render(pr, sha, signals, evidence, ai, ai_error))
    return {key: new}


def main() -> None:
    _, apps = k8s("/apis/argoproj.io/v1alpha1/namespaces/argocd/applications")
    ns, name = STATE
    _, configmap = k8s(f"/api/v1/namespaces/{ns}/configmaps/{name}")
    state = configmap.get("data") or {}
    previews = [
        a for a in apps["items"] if a["metadata"]["name"].startswith("preview-pr-")
    ]
    patch = {}
    for app in previews:
        try:
            patch.update(check(app, state))
        except Exception as error:  # one broken preview must not stop the others
            print(
                f"{app['metadata']['name']}: check failed: {type(error).__name__}: {error}"
            )
    live = {a["metadata"]["name"].removeprefix("preview-") for a in previews}
    for key in state.keys() - live:  # forget PRs whose preview no longer exists
        patch[key] = None
    if patch:
        k8s(
            f"/api/v1/namespaces/{ns}/configmaps/{name}",
            "PATCH",
            {"data": patch},
            "application/merge-patch+json",
        )


if __name__ == "__main__":
    main()
