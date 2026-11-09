FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends mtr-tiny libcap2-bin \
 && setcap cap_net_raw+ep "$(command -v mtr-packet)" \
 && getcap "$(command -v mtr-packet)" | grep -q cap_net_raw \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
 && mkdir /data \
 && chown app:app /data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY topo_mapper ./topo_mapper

RUN pip install --no-cache-dir ".[web]"

USER app
VOLUME ["/data"]
ENTRYPOINT ["topo-mapper"]
CMD ["--help"]
