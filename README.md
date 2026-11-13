# Preflight

[![CI](https://github.com/elyesmanai911/preflight/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/elyesmanai911/preflight/actions/workflows/ci.yml)

**Preview environments for every pull request, plus an AI release agent that explains them.**

Preflight is a GitOps platform where every pull request automatically gets an ephemeral
Kubernetes environment. An AI release agent then posts one PR comment that risk-scores the
diff, summarizes security scan findings, triages failed deployments from live logs, and
estimates the environment's cost. When the PR closes, the environment is torn down.

> 🚧 **Status: Phase 2 of 6.** Every PR now gets its own preview environment; the platform is being
> built phase by phase. Each phase ends with a tagged release; see the roadmap below.

## How it will work

1. A developer opens a PR on the demo app.
2. **CI** (GitHub Actions): lint → test → build image → Trivy scan → push to GHCR.
3. **GitOps** (Argo CD ApplicationSet, Pull Request generator): deploys the image into an
   isolated namespace `pr-<number>` with its own URL.
4. **AI release agent** (Python + Claude API) posts a single PR comment:
   - 🔗 preview URL and deploy status
   - 🧠 diff risk summary: what changed, blast radius, what to test
   - 🛡️ security digest: Trivy CVEs as "fix now / can wait"
   - 🔥 failure triage, if the deploy fails: root cause from pod events and Loki logs
   - 💰 cost estimate for the preview environment
5. PR merged or closed → namespace destroyed (a TTL reaper acts as a backstop).

## Architecture

```mermaid
flowchart TD
    PR[GitHub pull request] --> CI[GitHub Actions<br/>test · build · Trivy · push to GHCR]
    CI --> ARGO[Argo CD ApplicationSet<br/>PR generator]
    GITOPS[(GitOps repo<br/>Helm chart)] --> ARGO
    ARGO --> K8S[k3d locally / k3s on Azure VM<br/>namespace pr-N]
    K8S --> APP[Demo invoice API]
    K8S --> OBS[Prometheus + Loki + Grafana]
    AGENT[Preflight agent<br/>Python + Claude API] -->|reads diff, Trivy JSON,<br/>events, logs| OBS
    AGENT -->|one structured comment| PR
```

## The demo app

A small **invoice API** (FastAPI). It echoes real e-invoicing integration work: validation
and VAT totals now; signing, QR codes and Postgres in later phases. It also gives the AI agent
realistic failures to diagnose, such as a missing certificate, a failed validation, or a broken
DB migration.

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness check |
| `POST /invoices` | validate an invoice, compute totals (TND, 3 decimals) |
| `GET /invoices/{id}` | fetch a stored invoice |

### Run it locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/uvicorn app.main:app --reload   # http://localhost:8000/docs
```

### Run it in Docker

```bash
docker build -t preflight-app:dev .
docker run --rm -p 8000:8000 preflight-app:dev
```

## Run the platform locally

Needs Docker, [k3d](https://k3d.io), kubectl and Helm.

```bash
# 1. Cluster: port 8080 on your machine → the cluster's Traefik ingress
k3d cluster create preflight -p '8080:80@loadbalancer' --wait

# 2. Argo CD
helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install argocd argo/argo-cd --version 10.11.6 \
  -n argocd --create-namespace -f platform/argocd/values.yaml --wait

# 3. One preview environment per open PR
kubectl apply -f platform/argocd/preview-appset.yaml
```

Open a PR: within about 2 minutes, Argo CD deploys it to namespace `pr-<N>` and CI comments the
URL, `http://pr-<N>.preview.127.0.0.1.nip.io:8080`. Close the PR and the namespace is deleted.

Argo CD UI: `kubectl -n argocd port-forward svc/argocd-server 8081:80`, then open
http://localhost:8081 as `admin` with the password from
`kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`.

## Roadmap

- [x] **Phase 0: skeleton and story.** README, demo app, Dockerfile, tests (`v0.1`)
- [x] **Phase 1: CI pipeline.** GitHub Actions, GHCR, Trivy with SARIF, branch protection (`v0.2`)
- [x] **Phase 2: preview environments.** k3d, Argo CD ApplicationSet PR generator, Helm, per-PR ingress (`v0.3`)
- [ ] **Phase 3: AI agent v1.** diff risk summary and CVE digest as a PR comment (`v0.4`)
- [ ] **Phase 4: AI incident triage.** Prometheus, Loki, root-cause comments on broken PRs (`v0.5`)
- [ ] **Phase 5: FinOps and guardrails.** cost estimate, ResourceQuota, TTL reaper (`v0.6`)
- [ ] **Phase 6: cloud demo.** Terraform on Azure, Key Vault with External Secrets, demo video (`v1.0`)

### Out of scope (on purpose)

Multi-cluster or service mesh, self-hosted or fine-tuned LLMs, a custom dashboard (the PR
comment *is* the UI), supporting arbitrary apps, and a Go operator. These are possible v2
directions, not v1 work.
