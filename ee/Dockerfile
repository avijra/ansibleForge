FROM quay.io/ansible/ansible-runner:latest

USER root

# System packages
RUN dnf install -y \
    openssh-clients \
    git \
    unzip \
    curl \
    rsync \
    sshpass \
    gcc \
    python3-devel \
    libffi-devel \
    openssl-devel \
  && dnf clean all

# OpenTofu
RUN curl -fsSL https://get.opentofu.org/install-opentofu.sh -o /tmp/install-opentofu.sh \
  && chmod +x /tmp/install-opentofu.sh \
  && /tmp/install-opentofu.sh --install-method rpm \
  && rm -f /tmp/install-opentofu.sh \
  && tofu --version

# Python packages (SDKs for all supported Ansible collections)
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
  && rm -f /tmp/requirements.txt

# ansible-lint and molecule
RUN pip3 install --no-cache-dir \
    ansible-lint \
    molecule \
    "molecule-plugins[docker]"

# Ansible collections
COPY requirements.yml /tmp/requirements.yml
RUN ansible-galaxy collection install -r /tmp/requirements.yml --force \
  && rm -f /tmp/requirements.yml

USER 1000

LABEL org.opencontainers.image.title="tuyere-ee" \
      org.opencontainers.image.description="Tuyere Execution Environment — all Ansible collections, SDKs, and tools pre-installed" \
      org.opencontainers.image.source="https://github.com/avijra/ansibleForge"
