FROM python:3.10-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY topo_mapper ./topo_mapper

RUN pip install --no-cache-dir -e ".[web]"

VOLUME ["/data"]
ENTRYPOINT ["topo-mapper"]
CMD ["--help"]
