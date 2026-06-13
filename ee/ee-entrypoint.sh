#!/bin/bash
# Arbitrary-UID support. Tuyere launches this image with the host user's uid
# (and gid 0) so files written into the mounted workspace stay owned by the host
# user. When that uid has no /etc/passwd entry, glibc getpwuid() fails and tools
# such as ssh-keygen, openssh_keypair and ansible-doc break with
# "No user exists for uid ...". Register the runtime uid on the fly.
set +e

myuid="$(id -u)"
mygid="$(id -g)"

if ! getent passwd "$myuid" >/dev/null 2>&1; then
  echo "runner:x:${myuid}:${mygid}:Tuyere Runner:/home/runner:/bin/bash" >> /etc/passwd 2>/dev/null
fi

export HOME="${HOME:-/home/runner}"

if [ "$#" -eq 0 ]; then
  set -- /bin/bash
fi

exec "$@"
