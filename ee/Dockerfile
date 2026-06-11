FROM quay.io/centos/centos:stream9

ENV PIP_ROOT_USER_ACTION=ignore

RUN dnf install -y --allowerasing \
    python3 \
    python3-pip \
    python3-devel \
    openssh-clients \
    git \
    unzip \
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

RUN useradd -u 1000 -m runner
USER 1000
WORKDIR /home/runner

LABEL org.opencontainers.image.title="tuyere-ee" \
      org.opencontainers.image.description="Tuyere Execution Environment — all Ansible collections, SDKs, and tools pre-installed" \
      org.opencontainers.image.source="https://github.com/avijra/ansibleForge"
