# Triage watcher image: standard library only, no pip install.
# Build from the repo root: docker build -f agent/Dockerfile .
FROM python:3.12-slim
WORKDIR /srv
COPY agent ./agent
USER 10001
ENTRYPOINT ["python", "-m", "agent.triage"]
