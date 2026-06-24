FROM python:3.12-slim

# uv creates venv symlinks pointing to "python"; python:3.12-slim only has "python3"
RUN ln -sf /usr/local/bin/python3 /usr/local/bin/python

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY . .

EXPOSE 8080

# Call the venv's uvicorn directly — no uv at runtime, no package reinstall on cold start
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
