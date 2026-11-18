FROM python:3.10-slim

WORKDIR /app

# System dependencies (যদি neonize বা অন্যান্য প্যাকেজের জন্য বিল্ড টুলস লাগে)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --no-cache-dir --upgrade pip
RUN if [ -f "/app/requirements.txt" ]; then pip install --no-cache-dir -r /app/requirements.txt; fi

CMD ["python", "bot.py"]
