# backend/Dockerfile -- hand-written. Official python image, our code on top.
FROM python:3.12.11-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install --no-cache-dir ".[dev]" \
    && rm -rf app

COPY app ./app
RUN pip install --no-cache-dir --no-deps .

# Not root inside the container.
RUN useradd --system --uid 10001 acme
USER acme

EXPOSE 8000
# Two workers on purpose: proves live updates cross workers via Redis.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
