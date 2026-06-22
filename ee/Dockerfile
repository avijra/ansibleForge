FROM quay.io/centos/centos:stream9

ENV PIP_ROOT_USER_ACTION=ignore

# Python 3.12 is required: modern Ansible collections (amazon.aws, kubernetes.core,
# community.general, ...) need ansible-core >= 2.17, which in turn requires Python
# >= 3.11. CentOS Stream 9's default python3 (3.9) caps ansible-core at 2.15 and
# breaks current collections.
# libvirt-devel (needed to build libvirt-python for community.libvirt) lives in
# the CRB repo, which is disabled by default on CentOS Stream 9.
RUN dnf install -y --allowerasing --enablerepo=crb \
    python3.12 \
    python3.12-pip \
    python3.12-devel \
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
    libvirt-devel \
    glibc-langpack-en \
  && dnf clean all

# Make python3.12 the default python3 so ansible module interpreter discovery
# (auto -> /usr/bin/python3) and installed console scripts all use 3.12.
RUN alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 2 \
  && alternatives --set python3 /usr/bin/python3.12 \
  && python3 --version

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN python3.12 -m pip install --no-cache-dir \
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
RUN python3.12 -m pip install --no-cache-dir -r /tmp/requirements.txt \
  && rm -f /tmp/requirements.txt

RUN python3.12 -m pip install --no-cache-dir \
    ansible-lint \
    molecule \
    "molecule-plugins[docker]"

COPY requirements.yml /tmp/requirements.yml
RUN ansible-galaxy collection install -r /tmp/requirements.yml --force \
    -p /usr/share/ansible/collections \
  && rm -f /tmp/requirements.yml

COPY ee-entrypoint.sh /usr/local/bin/ee-entrypoint.sh
RUN chmod 0755 /usr/local/bin/ee-entrypoint.sh

# Arbitrary-UID safe (OpenShift "restricted" SCC pattern). Tuyere runs this
# image as the host user's uid with gid 0 so workspace files stay host-owned.
# Make HOME and /etc/passwd group-0 writable so the entrypoint can register the
# runtime uid and tools can persist state (~/.ansible, ssh keys, galaxy cache).
RUN useradd -u 1000 -g 0 -m runner \
  && mkdir -p /home/runner/.ansible/tmp /tmp/.ansible \
  && chgrp -R 0 /home/runner /tmp/.ansible \
  && chmod -R g=rwX /home/runner /tmp/.ansible \
  && chmod g=rw /etc/passwd \
  && echo "runner ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runner \
  && chmod 0440 /etc/sudoers.d/runner

ENV HOME=/home/runner
USER 1000
WORKDIR /home/runner
ENTRYPOINT ["/usr/local/bin/ee-entrypoint.sh"]

LABEL org.opencontainers.image.title="tuyere-ee" \
      org.opencontainers.image.description="Tuyere Execution Environment — all Ansible collections, SDKs, and tools pre-installed" \
      org.opencontainers.image.source="https://github.com/avijra/ansibleForge"
