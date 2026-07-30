FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/

# portfolio.json lives on a mounted volume so data survives redeploys.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# 2 workers is plenty for a single-user dashboard; the JSON store assumes
# writes never truly overlap, which holds for one person clicking around.
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "30", "app:app"]
