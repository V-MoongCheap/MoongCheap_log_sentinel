FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rules.yaml ./
COPY triage/ ./triage/
RUN useradd -u 10001 triage && mkdir /data && chown triage /data
USER 10001
ENTRYPOINT ["python", "-m", "triage"]