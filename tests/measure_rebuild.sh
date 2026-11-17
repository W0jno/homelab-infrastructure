#!/usr/bin/env bash
# Slide 11 "Wdrożenie od zera z kodu" / "Czas wdrożenia" / "Czas odtworzenia".
# DESTROYS and recreates the k3s VMs, then redeploys everything from this repo and times each phase.
# The Immich LXC is never touched (prevent_destroy). Run from a machine inside the LAN.
#
# Usage: CLOUDFLARED_TOKEN=... tests/measure_rebuild.sh --yes
set -euo pipefail

[[ "${1:-}" == "--yes" ]] || { echo "This destroys the k3s cluster. Re-run with --yes." >&2; exit 1; }
: "${CLOUDFLARED_TOKEN:?set CLOUDFLARED_TOKEN (tunnel token, not stored in git)}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TF="$REPO/terraform/environments/production"
export KUBECONFIG="$REPO/ansible/.kube/config"
RESULTS="$REPO/tests/results"; mkdir -p "$RESULTS"
NODES=(192.168.1.201 192.168.1.202 192.168.1.203)
declare -A T

phase() {  # phase <name> <command...>
  local name=$1; shift
  local start=$SECONDS
  echo "==> $name"
  "$@"
  T[$name]=$((SECONDS - start))
  echo "    $name: ${T[$name]}s"
}

wait_ssh() {
  for ip in "${NODES[@]}"; do
    until nc -z -w 2 "$ip" 22; do sleep 2; done
  done
}

deploy_manifests() {
  kubectl create secret generic cloudflared-token --from-literal=token="$CLOUDFLARED_TOKEN" \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f "$REPO/k8s/manifests/"
  kubectl rollout status deployment/portfolio-deployment --timeout=600s
  kubectl rollout status deployment/cloudflared-deployment --timeout=600s
}

TOTAL_START=$SECONDS
phase terraform_destroy terraform -chdir="$TF" destroy -auto-approve -target=proxmox_virtual_environment_vm.k3s
phase terraform_apply   terraform -chdir="$TF" apply -auto-approve
phase vms_boot          wait_ssh
phase ansible_k3s       bash -c "cd '$REPO/ansible' && ansible-playbook playbooks/site.yml"
phase k8s_workloads     deploy_manifests
T[total_rebuild]=$((SECONDS - TOTAL_START))

{
  echo "{"
  echo "  \"measured_at\": \"$(date -Iseconds)\","
  for k in terraform_destroy terraform_apply vms_boot ansible_k3s k8s_workloads; do
    echo "  \"${k}_s\": ${T[$k]},"
  done
  echo "  \"total_rebuild_s\": ${T[total_rebuild]}"
  echo "}"
} | tee "$RESULTS/rebuild.json"

echo "==> verifying with the live test suite"
cd "$REPO/tests" && pytest --live live/test_functional.py
