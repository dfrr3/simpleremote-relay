FROM python:3.11-slim

WORKDIR /app

COPY relay_server.py .

EXPOSE 10000
EXPOSE 5899

CMD ["python", "relay_server.py"]
