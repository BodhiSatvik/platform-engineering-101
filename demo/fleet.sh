#!/usr/bin/env bash
# Facilitator demo, end of Lab 1: eight teams were each told "fence your own namespace".
# This builds what each team got done before its deadline, then runs the security review.
#   demo/fleet.sh          build the eight namespaces and audit them
#   demo/fleet.sh clean    delete them
set -euo pipefail
k() { kubectl --context kind-pe101 "$@"; }
TEAMS="payments claims quotes billing fraud mobile search rewards"

if [ "${1:-}" = clean ]; then
  for team in $TEAMS; do k delete namespace "team-$team" --wait=false; done
  exit
fi

did() { # what each team got around to
  case $1 in
    payments) echo "restricted quota limits ingress egress" ;;
    claims) echo "restricted quota limits ingress" ;;
    quotes) echo "" ;;
    billing) echo "quota limits" ;;
    fraud) echo "baseline ingress" ;;
    mobile) echo "limits" ;;
    search) echo "restricted quota" ;;
    rewards) echo "ingress egress" ;;
  esac
}

for team in $TEAMS; do
  ns="team-$team"
  k create namespace "$ns" --dry-run=client -o yaml | k apply -f - >/dev/null
  k -n "$ns" create serviceaccount team --dry-run=client -o yaml | k apply -f - >/dev/null
  k -n "$ns" create rolebinding team-edit --clusterrole edit --serviceaccount "$ns:team" \
    --dry-run=client -o yaml | k apply -f - >/dev/null
  for fence in $(did "$team"); do
    case $fence in
      restricted | baseline) k label namespace "$ns" "pod-security.kubernetes.io/enforce=$fence" --overwrite >/dev/null ;;
      quota) k -n "$ns" create quota budget --hard=requests.cpu=1,requests.memory=1Gi,limits.cpu=2,limits.memory=2Gi,pods=10 \
        --dry-run=client -o yaml | k apply -f - >/dev/null ;;
      limits) printf '%s\n' "apiVersion: v1" "kind: LimitRange" "metadata: {name: defaults}" \
        "spec: {limits: [{type: Container, default: {cpu: 250m, memory: 256Mi}, defaultRequest: {cpu: 100m, memory: 128Mi}}]}" |
        k -n "$ns" apply -f - >/dev/null ;;
      ingress | egress) printf '%s\n' "apiVersion: networking.k8s.io/v1" "kind: NetworkPolicy" "metadata: {name: default-deny-$fence}" \
        "spec: {podSelector: {}, policyTypes: [$( [ "$fence" = ingress ] && echo Ingress || echo Egress )]}" |
        k -n "$ns" apply -f - >/dev/null ;;
    esac
  done
done

printf '\nThe security review: each team, checked as that team\n\n'
for team in $TEAMS; do
  line=$(kubectl audit-tenant --context kind-pe101 -n "team-$team" --as "system:serviceaccount:team-$team:team" --no-color 2>/dev/null |
    grep ' passed · ' || true)
  printf '  %-10s %s\n' "$team" "${line% · exit*}"
done
printf '\nEight teams, eight different gaps. Security reviews each list, and does it again next quarter.\n'
