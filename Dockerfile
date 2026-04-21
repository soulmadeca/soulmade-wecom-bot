FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY wecom_coze_bridge.py .
EXPOSE 8080
CMD ["/usr/local/bin/gunicorn", "wecom_coze_bridge:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120"]
