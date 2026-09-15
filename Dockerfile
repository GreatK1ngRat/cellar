FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal on purpose -- this is a small single-user app,
# not a build environment.
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The SQLite file lives here, on a volume mounted by docker-compose.yml,
# so it survives image rebuilds and `docker compose down`.
RUN mkdir -p /app/data

RUN useradd --create-home --uid 1000 cellar \
    && chown -R cellar:cellar /app
USER cellar

EXPOSE 61618

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "61618"]
