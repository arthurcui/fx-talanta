FROM python:3.14-slim-bookworm AS build
WORKDIR /build
COPY pyproject.toml requirements.lock ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -c requirements.lock .

FROM python:3.14-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels fx-talanta \
    && rm -r /wheels \
    && useradd --uid 10001 --create-home app \
    && mkdir /app /artifacts && chown app:app /app /artifacts
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["fx-talanta"]
CMD ["offline-demo"]
