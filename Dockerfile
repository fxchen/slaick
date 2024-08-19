# Builder stage
FROM python:3.11.4-slim-buster as builder

# Environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY requirements.txt /build/
WORKDIR /build/
RUN pip install -U pip && pip install -r requirements.txt

# App stage
FROM python:3.11.4-slim-buster as app
WORKDIR /app/
COPY main.py /app/
COPY slaick.py /app/
COPY lib/ /app/lib/
COPY vendor/ /app/vendor/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/ /usr/local/lib/

# Example environment variables (overwritten by your own environment variables)
# ENV TRANSLATE_MARKDOWN=true
# ENV FILE_ACCESS_ENABLED=false
# ENV REDACTION_ENABLED=false

# Start the app
ENTRYPOINT ["python", "main.py"]
