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

# SageMaker starts the container with `docker run <image> serve`. We ignore the
# arg and launch uvicorn on 8080 (the port SageMaker probes for /ping).
ENTRYPOINT ["python", "-m", "uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"]
