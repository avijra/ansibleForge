FROM quay.io/centos/centos:stream9

ENV PIP_ROOT_USER_ACTION=ignore

RUN dnf install -y --allowerasing \
    python3 \
    python3-pip \
    python3-devel \
    openssh-clients \
    git \
    unzip \
    tar \
    gzip \
    which \
    procps-ng \
    sudo \
    curl \
    rsync \
    sshpass \
    gcc \
    libffi-devel \
    openssl-devel \
    glibc-langpack-en \
  && dnf clean all

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN pip3 install --no-cache-dir \
    ansible-core \
    ansible-runner

# OpenTofu
RUN curl -fsSL https://get.opentofu.org/install-opentofu.sh -o /tmp/install-opentofu.sh \
  && chmod +x /tmp/install-opentofu.sh \
  && /tmp/install-opentofu.sh --install-method rpm \
  && rm -f /tmp/install-opentofu.sh \
  && tofu --version

# Generic GitOps/Kubernetes CLIs (arch-matched via buildx TARGETARCH).
ARG TARGETARCH
ARG HELM_VERSION=v3.16.3
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    curl -fsSL "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/${arch}/kubectl" \
      -o /usr/local/bin/kubectl; \
    chmod +x /usr/local/bin/kubectl; \
    kubectl version --client=true; \
    curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${arch}.tar.gz" -o /tmp/helm.tgz; \
    tar -xzf /tmp/helm.tgz -C /tmp; \
    mv "/tmp/linux-${arch}/helm" /usr/local/bin/helm; \
    rm -rf /tmp/helm.tgz "/tmp/linux-${arch}"; \
    helm version

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
  && rm -f /tmp/requirements.txt

RUN pip3 install --no-cache-dir \
    ansible-lint \
    molecule \
    "molecule-plugins[docker]"

COPY requirements.yml /tmp/requirements.yml
RUN ansible-galaxy collection install -r /tmp/requirements.yml --force \
    -p /usr/share/ansible/collections \
  && rm -f /tmp/requirements.yml

RUN useradd -u 1000 -m runner \
  && mkdir -p /home/runner/.ansible/tmp /tmp/.ansible \
  && chown -R runner:runner /home/runner /tmp/.ansible \
  && echo "runner ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runner \
  && chmod 0440 /etc/sudoers.d/runner

ENV HOME=/home/runner
USER 1000
WORKDIR /home/runner

LABEL org.opencontainers.image.title="tuyere-ee" \
      org.opencontainers.image.description="Tuyere Execution Environment — all Ansible collections, SDKs, and tools pre-installed" \
      org.opencontainers.image.source="https://github.com/avijra/ansibleForge"
