# Strands Decider 2B SageMaker serving image (CPU, linux/amd64).
# Weights are NOT baked in: SageMaker downloads model.tar.gz from S3 and extracts
# it to /opt/ml/model at endpoint-creation. This image carries only code + deps,
# keeping it ~2GB.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PORT=8080 \
    MODEL_DIR=/opt/ml/model

WORKDIR /app

# torch CPU wheel from the PyTorch CPU index; everything else from PyPI.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /app/requirements.txt

COPY serve.py /app/serve.py

EXPOSE 8080

# SageMaker starts the container with `docker run <image> serve`, so "serve" is
# appended as an argument. With `sh -c "<cmd>"`, that trailing "serve" becomes the
# shell's $0 and is ignored, so uvicorn never sees it. (The exec form passed the
# arg straight to uvicorn, which rejected it with "unexpected extra argument serve".)
ENTRYPOINT ["sh", "-c", "exec python -m uvicorn serve:app --host 0.0.0.0 --port 8080 --log-level warning"]
