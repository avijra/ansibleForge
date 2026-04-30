FROM node:22-slim AS ui-build
WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.13-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client sshpass && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY ansible_forge/ ansible_forge/
RUN pip install --no-cache-dir .

COPY --from=ui-build /build/dist ui/dist/

ENV ANSIBLEFORGE_HOST=0.0.0.0
ENV ANSIBLEFORGE_PORT=8420
EXPOSE 8420

CMD ["uvicorn", "ansible_forge.main:app", "--host", "0.0.0.0", "--port", "8420"]
