FROM python:3.12-alpine

WORKDIR /app
COPY aio /app/aio

ENV PYTHONUNBUFFERED=1
ENV AIO_VERSION=0.3.34
ARG AIO_COMMIT=unknown
ENV AIO_COMMIT=$AIO_COMMIT
EXPOSE 8800

ENTRYPOINT ["python", "-m", "aio.app"]
CMD ["--bind", "0.0.0.0", "--port", "8800"]
