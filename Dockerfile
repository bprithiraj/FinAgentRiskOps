FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps . && useradd --create-home app && mkdir /data && chown app:app /data
USER app
ENV FINAGENT_DATA_DIR=/data LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
EXPOSE 8082
CMD ["uvicorn", "finagent.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8082", "--workers", "1"]
