#!/usr/bin/env bash
# Builds the workshop cluster: a kind cluster with metrics, the Postgres operator
# and the platform's API. Safe to run again. A Codespace runs it by itself.
# It installs tools only into this repo (bin/ and .venv/), never system-wide.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=pe101
KIND_VERSION=0.33.0
AUDIT_TENANT_VERSION=0.1.2
CNPG_VERSION=1.30.1
METRICS_SERVER_VERSION=0.9.1

mkdir -p bin
export PATH="$PWD/bin:$PWD/.venv/bin:$PATH"
os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)
case "$arch" in x86_64) arch=amd64 ;; aarch64 | arm64) arch=arm64 ;; esac
sha256_check() { if command -v sha256sum >/dev/null; then sha256sum -c -; else shasum -a 256 -c -; fi; }
k() { kubectl --context "kind-$CLUSTER" "$@"; } # never touch any other cluster

if ! command -v kind >/dev/null; then
  echo "== installing kind $KIND_VERSION"
  url="https://kind.sigs.k8s.io/dl/v$KIND_VERSION/kind-$os-$arch"
  curl -fsSLo bin/kind "$url"
  echo "$(curl -fsSL "$url.sha256sum" | cut -d' ' -f1)  bin/kind" | sha256_check
  chmod +x bin/kind
fi

if ! command -v kubectl-audit_tenant >/dev/null; then
  echo "== installing kubectl audit-tenant $AUDIT_TENANT_VERSION"
  file="kubectl-audit-tenant_${AUDIT_TENANT_VERSION}_${os}_${arch}.tar.gz"
  base="https://github.com/BodhiSatvik/kubectl-audit-tenant/releases/download/v$AUDIT_TENANT_VERSION"
  tmp=$(mktemp -d)
  curl -fsSLo "$tmp/$file" "$base/$file"
  (cd "$tmp" && curl -fsSL "$base/checksums.txt" | grep " $file\$" | sha256_check)
  tar -xzf "$tmp/$file" -C bin kubectl-audit_tenant
  rm -rf "$tmp"
fi

if [ ! -x .venv/bin/kopf ]; then
  echo "== installing the platform's Python packages into .venv"
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r platform/requirements.txt
fi

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "== creating the cluster (a few minutes the first time)"
  kind create cluster --name "$CLUSTER" --wait 120s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "== metrics-server: lets autoscalers see CPU use"
k apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/v$METRICS_SERVER_VERSION/components.yaml" >/dev/null
# kind's kubelets use self-signed certificates, so metrics-server must skip that check here.
if ! k -n kube-system get deploy metrics-server -o jsonpath='{.spec.template.spec.containers[0].args}' | grep -q kubelet-insecure-tls; then
  k -n kube-system patch deploy metrics-server --type json \
    -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' >/dev/null
fi

echo "== CloudNativePG: the open-source Postgres operator the platform uses"
k apply --server-side -f "https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-${CNPG_VERSION%.*}/releases/cnpg-$CNPG_VERSION.yaml" >/dev/null
k -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout 180s

echo "== the platform's API: the Application kind"
k apply -f platform/crd.yaml >/dev/null

echo "== ready. Open README.md and start Lab 1."
