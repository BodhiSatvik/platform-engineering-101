#!/usr/bin/env bash
# Facilitator self-test: runs every README command, as written, and checks each result.
# It DELETES and rebuilds the kind cluster "pe101". It works in a temporary copy of this repo,
# so your files (the Lab 1 typo, the Lab 3 switch) stay as they are. About 8 minutes.
#   test/runbook-test.sh
set -uo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
W="$(mktemp -d)/pe101"
fails=0
# pipefail off inside checks: audit-tenant and `platform deploy` exit 1 on purpose when they report a problem
check() { if (set +o pipefail; eval "$2"); then echo "PASS  $1"; else echo "FAIL  $1"; fails=$((fails + 1)); fi; }
edit() { sed -i.bak "$1" "$2" && rm -f "$2.bak"; } # in-place edit that works with GNU and BSD sed
stop() { pkill -f "kopf run" || true; pkill -f "platform forward" || true; pkill -f "port-forward svc/coffee" || true; }

stop
cp -R "$SRC" "$W" && cd "$W"
kind delete cluster --name pe101 >/dev/null 2>&1 || true

echo "== setup"
./setup/setup.sh >"$W/setup.log" 2>&1
check "setup exits 0 and prints ready" 'grep -q "ready. Open README.md" "$W/setup.log"'
export PATH="$PWD/bin:$PWD/.venv/bin:$PATH"

echo "== Lab 1"
docker build -q -t coffee:v1 app >/dev/null 2>&1 && kind load docker-image coffee:v1 --name pe101 >/dev/null 2>&1
check "1 image built and loaded" 'docker exec pe101-control-plane crictl images | grep -q coffee'
kubectl create namespace coffee-diy >/dev/null
kubectl config set-context --current --namespace coffee-diy >/dev/null
kubectl create serviceaccount team >/dev/null
kubectl create rolebinding team-edit --clusterrole edit --serviceaccount coffee-diy:team >/dev/null
check "2 team may delete pods here" '[ "$(kubectl auth can-i delete pods --as system:serviceaccount:coffee-diy:team)" = yes ]'
check "2 team may not read kube-system secrets" '[ "$(kubectl auth can-i get secrets -n kube-system --as system:serviceaccount:coffee-diy:team 2>/dev/null)" = no ]'
kubectl apply -f lab1/postgres.yaml >/dev/null && kubectl rollout status deploy/postgres >/dev/null
check "3 password readable from the Secret" '[ "$(kubectl get secret postgres -o jsonpath="{.data.POSTGRES_PASSWORD}" | base64 -d)" = coffee-is-life ]'
kubectl apply -f lab1/deployment.yaml >/dev/null
sleep 30
check "4 app crashes" 'kubectl get pods -l app=coffee --no-headers | grep -q -E "Error|CrashLoopBackOff"'
check "4 logs name the typo" 'kubectl logs deploy/coffee | grep Error | grep -q postgress'
edit 's/@postgress:/@postgres:/' lab1/deployment.yaml
kubectl apply -f lab1/deployment.yaml >/dev/null && kubectl rollout status deploy/coffee >/dev/null
check "4 fixed app runs" '[ "$(kubectl get deploy coffee -o jsonpath="{.status.readyReplicas}")" = 1 ]'
kubectl apply -f lab1/service.yaml >/dev/null
(kubectl port-forward svc/coffee 8080:80 >/dev/null 2>&1 &)
sleep 3
curl -s -d "name=Lin&drink=mocha" localhost:8080/orders >/dev/null
check "5 order shows on 8080" 'curl -s localhost:8080/ | grep -q "<b>Lin</b>"'
check "5 service has endpoints" 'kubectl describe service coffee | grep -q -E "Endpoints:\s+[0-9]"'
kubectl delete pod -l app=coffee >/dev/null
sleep 5
check "6 port-forward died with its pod" '! curl -s -m 3 localhost:8080/ >/dev/null'
pkill -f "port-forward svc/coffee 8080" || true
kubectl rollout status deploy/coffee >/dev/null
(kubectl port-forward svc/coffee 8080:80 >/dev/null 2>&1 &)
sleep 3
kubectl scale deploy coffee --replicas 3 >/dev/null && kubectl rollout status deploy/coffee >/dev/null
kubectl delete pod -l app=postgres >/dev/null && kubectl rollout status deploy/postgres >/dev/null
sleep 3
check "6 orders lost after the database restarts" 'curl -s localhost:8080/ | grep -q "No orders yet"'
check "7 audit: 3 passed, 11 failed" 'kubectl audit-tenant -n coffee-diy --as system:serviceaccount:coffee-diy:team --no-color 2>/dev/null | grep -q "^3 passed · 11 failed"'

echo "== Lab 2"
(nohup kopf run --standalone --all-namespaces platform/operator.py >"$W/operator.log" 2>&1 &)
sleep 4
platform deploy lab2/app.yaml >"$W/deploy.out" 2>&1
check "3 deploy reaches ready" 'grep -q "ready in" "$W/deploy.out"'
platform open coffee >/dev/null
sleep 4
curl -s -d "name=Ada&drink=flat white" localhost:8081/orders >/dev/null
check "4 order shows on 8081" 'curl -s localhost:8081/ | grep -q "<b>Ada</b>"'
edit 's/plan: small /plan: huge  /' lab2/app.yaml
check "5 bad plan rejected, with a fix" 'platform deploy lab2/app.yaml 2>&1 | grep -q "fix: use one of"'
edit 's/plan: huge  /plan: small /' lab2/app.yaml
n=$(kubectl get all,quota,limitrange,networkpolicy,serviceaccount,rolebinding,secret,pvc,clusters.postgresql.cnpg.io -n coffee --no-headers 2>/dev/null | wc -l | tr -d ' ')
check "6 behind the curtain: about 25 objects ($n)" '[ "$n" -ge 20 ]'
kubectl -n coffee delete pod -l cnpg.io/cluster=coffee-db >/dev/null
kubectl -n coffee wait --for=condition=Ready clusters.postgresql.cnpg.io/coffee-db --timeout=180s >/dev/null
sleep 3
check "7 orders survive the database restart" 'curl -s localhost:8081/ | grep -q "<b>Ada</b>"'
kubectl -n coffee delete pod -l app=coffee >/dev/null
ok=no; for _ in $(seq 20); do curl -s -m 2 localhost:8081/ | grep -q "<b>Ada</b>" && ok=yes && break; sleep 2; done
check "7 platform open reconnects" '[ $ok = yes ]'
check "8 audit: 13 passed, 1 failed (AT-08)" 'kubectl audit-tenant -n coffee --as system:serviceaccount:coffee:team --no-color 2>/dev/null | grep -q "^13 passed · 1 failed (AT-08)"'
check "9 status Ready" 'platform status | grep -q -E "coffee +Ready"'
check "9 logs show requests" 'platform logs coffee | grep -q GET'
check "9 restart works" 'platform restart coffee 2>&1 | grep -q "all copies restarted"'

echo "== platform behavior (not a README step)"
sed 's/coffee:v1 /coffee:v9 /' lab2/app.yaml >"$W/v9.yaml"
check "a missing image fails fast, with a fix" 'platform deploy "$W/v9.yaml" 2>&1 | grep -q "cannot find coffee:v9"'
check "deploying the old file again rolls back" 'platform deploy lab2/app.yaml 2>&1 | grep -q "ready in"'

echo "== Lab 3"
reach='kubectl -n coffee exec deploy/coffee -- python -c "import socket; socket.create_connection((\"postgres.coffee-diy\", 5432), 3)" >/dev/null 2>&1'
check "before: the app can reach the other team's database" "$reach"
edit 's/^EGRESS_DEFAULT_DENY = False/EGRESS_DEFAULT_DENY = True/' platform/operator.py
pkill -f "kopf run" || true
sleep 2
(nohup kopf run --standalone --all-namespaces platform/operator.py >"$W/operator3.log" 2>&1 &)
for _ in $(seq 60); do grep -q "Resuming is processed" "$W/operator3.log" && break; sleep 2; done
check "audit: 14 passed" 'kubectl audit-tenant -n coffee --as system:serviceaccount:coffee:team --no-color 2>/dev/null | grep -q "^14 passed · 0 failed"'
check "after: the other team's database is blocked" "! $reach"
ok=no; for _ in $(seq 20); do curl -s -m 2 localhost:8081/ | grep -q "<b>Ada</b>" && ok=yes && break; sleep 2; done
check "after: the app still works" '[ $ok = yes ]'

echo "== facilitator"
check "fleet demo runs" 'demo/fleet.sh | grep -q "Eight teams"'
demo/fleet.sh clean >/dev/null

echo "== reset the cluster for the next run"
stop
platform delete coffee >/dev/null
kubectl delete namespace coffee-diy --wait=false >/dev/null
kubectl config set-context --current --namespace default >/dev/null
echo "== $fails failed checks"
exit $((fails > 0))
