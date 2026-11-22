FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml .
COPY quality_gate/ quality_gate/
RUN python -m pip install --no-cache-dir .
USER 65534:65534
ENTRYPOINT ["python", "-m", "quality_gate"]
