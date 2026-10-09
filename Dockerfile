FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY conduit ./conduit
COPY sql ./sql
# Editable so conduit/ and sql/ stay side by side; the code finds sql/ relative to itself.
RUN pip install --no-cache-dir --no-deps -e .

ENTRYPOINT ["conduit"]
