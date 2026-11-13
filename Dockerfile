FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ml ./ml
# Train inside the build: the image always carries the model built from this exact commit,
# and the build fails if the model misses the quality gate.
RUN python -m ml.train --out model
COPY app ./app
RUN useradd --uid 10001 app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
