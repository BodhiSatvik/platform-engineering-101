"""The platform team's operator: it turns an Application into a running, fenced app.

It watches Application objects. For each one it applies the same kinds of Kubernetes
objects you wrote by hand in Lab 1, plus the ones Lab 1 never got to, the same way
every time, for every team. Start it in Lab 2:

    kopf run --standalone --all-namespaces platform/operator.py
"""

import json
import re
import subprocess
import time
from string import Template

import kopf

# Decided once by the platform team, for every app.
PLANS = {  # plan: (CPU request, memory request, CPU limit, memory limit) for one copy, in m and Mi
    "small": (100, 128, 250, 256),
    "medium": (250, 256, 500, 512),
    "large": (500, 512, 1000, 1024),
}
DATABASE = (100, 256, 500, 512)  # the same four numbers for each Postgres database
EGRESS_DEFAULT_DENY = False  # Lab 3: the platform team turns this on, once, for every team.


# ---------------------------------------------------------------- the templates
# Each one is plain Kubernetes YAML. $name, $image and friends are filled in per app.

WORKSPACE = Template("""
# The app's own namespace: a fenced space that no other team shares.
apiVersion: v1
kind: Namespace
metadata:
  name: $name
  labels:
    pod-security.kubernetes.io/enforce: restricted  # refuse root, privileged and host-access pods
  ownerReferences:  # delete the Application and Kubernetes deletes all of this with it
  - {apiVersion: platform.example.com/v1, kind: Application, name: $name, uid: $uid}
---
# A budget: the most CPU, memory and pods this app may ever use, and no NodePort services.
apiVersion: v1
kind: ResourceQuota
metadata: {name: budget, namespace: $name}
spec:
  hard:
    requests.cpu: ${cpu_req}m
    requests.memory: ${mem_req}Mi
    limits.cpu: ${cpu_lim}m
    limits.memory: ${mem_lim}Mi
    pods: "$pods"
    services.nodeports: "0"
    services.loadbalancers: "0"
---
# Defaults for any container that forgets to say how much CPU and memory it needs.
apiVersion: v1
kind: LimitRange
metadata: {name: defaults, namespace: $name}
spec:
  limits:
  - type: Container
    defaultRequest: {cpu: 100m, memory: 128Mi}
    default: {cpu: 250m, memory: 256Mi}
---
# Network rules: nothing gets in from other namespaces...
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny-ingress, namespace: $name}
spec: {podSelector: {}, policyTypes: [Ingress]}
---
# ...except traffic between this app's own pods (the app and its database)...
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-same-namespace, namespace: $name}
spec:
  podSelector: {}
  policyTypes: [Ingress]
  ingress: [{from: [{podSelector: {}}]}]
---
# ...and the database operator, which checks on the database from its own namespace.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-database-operator, namespace: $name}
spec:
  podSelector: {matchLabels: {cnpg.io/podRole: instance}}
  policyTypes: [Ingress]
  ingress: [{from: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: cnpg-system}}}]}]
""")

EGRESS = Template("""
# Nothing goes out either...
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny-egress, namespace: $name}
spec: {podSelector: {}, policyTypes: [Egress]}
---
# ...except name lookups (DNS) and traffic to this app's own pods...
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-dns-and-same-namespace, namespace: $name}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
  - to: [{namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}, podSelector: {matchLabels: {k8s-app: kube-dns}}}]
    ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
  - to: [{podSelector: {}}]
---
# ...and the database's calls to the Kubernetes API, which the database operator needs.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-database-to-api, namespace: $name}
spec:
  podSelector: {matchLabels: {cnpg.io/podRole: instance}}
  policyTypes: [Egress]
  egress: [{ports: [{port: 443, protocol: TCP}, {port: 6443, protocol: TCP}]}]
""")

TEAM_ACCESS = Template("""
# Your team's login (a stand-in) may work inside this namespace, and nowhere else.
apiVersion: v1
kind: ServiceAccount
metadata: {name: team, namespace: $name}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: team-edit, namespace: $name}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: edit}
subjects: [{kind: ServiceAccount, name: team, namespace: $name}]
""")

POSTGRES = Template("""
# A Postgres database, run by CloudNativePG. It makes a password and stores it in the
# Secret "$name-db-app". No person ever sees it.
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: {name: $name-db, namespace: $name}
spec:
  instances: 1
  storage: {size: 1Gi}  # a real disk: the data survives when the pod restarts
  resources:
    requests: {cpu: ${db_cpu_req}m, memory: ${db_mem_req}Mi}
    limits: {cpu: ${db_cpu_lim}m, memory: ${db_mem_lim}Mi}
  bootstrap:
    initdb: {database: app, owner: app}
""")

APP = Template("""
apiVersion: apps/v1
kind: Deployment
metadata: {name: $name, namespace: $name}
spec:  # no "replicas" here: the autoscaler below owns the number of copies
  selector: {matchLabels: {app: $name}}
  template:
    metadata: {labels: {app: $name}}
    spec:
      automountServiceAccountToken: false  # the app does not need to talk to Kubernetes
      securityContext: {runAsNonRoot: true, seccompProfile: {type: RuntimeDefault}}
      containers:
      - name: app
        image: $image
        ports: [{containerPort: $port}]
        env: $env
        resources:
          requests: {cpu: ${cpu_req}m, memory: ${mem_req}Mi}
          limits: {cpu: ${cpu_lim}m, memory: ${mem_lim}Mi}
        readinessProbe: {httpGet: {path: /ready, port: $port}, periodSeconds: 5}
        livenessProbe: {httpGet: {path: /healthz, port: $port}, periodSeconds: 10}
        securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
---
apiVersion: v1
kind: Service
metadata: {name: $name, namespace: $name}
spec:
  selector: {app: $name}
  ports: [{port: 80, targetPort: $port}]
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: $name, namespace: $name}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: $name}
  minReplicas: $min
  maxReplicas: $max
  metrics: [{type: Resource, resource: {name: cpu, target: {type: Utilization, averageUtilization: 70}}}]
""")


# ---------------------------------------------------------------- the control loop

@kopf.on.create("platform.example.com", "v1", "applications")
@kopf.on.update("platform.example.com", "v1", "applications")
@kopf.on.resume("platform.example.com", "v1", "applications")
def reconcile(name, uid, spec, meta, logger, **_):
    progress = Progress(name, meta["generation"], logger)
    if not re.fullmatch(r"[a-z]([-a-z0-9]{0,28}[a-z0-9])?", name):
        progress.fail("name: use 1 to 30 lowercase letters, digits and dashes. It becomes your namespace name.")
        raise kopf.PermanentError("invalid name")

    plan, low, high = spec["plan"], spec["replicas"]["min"], spec["replicas"]["max"]
    cpu_req, mem_req, cpu_lim, mem_lim = PLANS[plan]
    database = spec["database"] == "postgres"
    db = DATABASE if database else (0, 0, 0, 0)
    peak = high + 1  # a rollout starts a new copy before it stops an old one
    sizes = dict(cpu_req=cpu_req, mem_req=mem_req, cpu_lim=cpu_lim, mem_lim=mem_lim)

    apply(WORKSPACE.substitute(
        name=name, uid=uid, pods=peak + 3,
        cpu_req=peak * cpu_req + db[0], mem_req=peak * mem_req + db[1],
        cpu_lim=peak * cpu_lim + db[2], mem_lim=peak * mem_lim + db[3]))
    if EGRESS_DEFAULT_DENY:
        apply(EGRESS.substitute(name=name))
    progress.step(f"workspace: namespace {name}, with a budget, default limits, pod security and network rules")

    apply(TEAM_ACCESS.substitute(name=name))
    progress.step(f"team access: your team can work inside {name}, and nowhere else")

    env = []
    if database:
        apply(POSTGRES.substitute(name=name, db_cpu_req=db[0], db_mem_req=db[1], db_cpu_lim=db[2], db_mem_lim=db[3]))
        wait_for_database(progress, name)
        env = [{"name": "DATABASE_URL", "valueFrom": {"secretKeyRef": {"name": f"{name}-db-app", "key": "uri"}}}]
        progress.step("database: Postgres with a generated password that no person has seen")

    apply(APP.substitute(
        name=name, image=json.dumps(spec["image"]), port=spec["port"], env=json.dumps(env),
        min=low, max=high, **sizes))
    wait_for_app(progress, name, low, spec["image"])
    progress.step(f"app: {low} copies running as non-root, with health checks, {plan} size")
    progress.step(f"autoscaler: {low} to {high} copies, adds copies when CPU passes 70%")
    progress.done(f"{low} copies running")


# ---------------------------------------------------------------- helpers

def kubectl(*args, stdin=None):
    """Run kubectl. Return its output, or raise with kubectl's own words."""
    result = subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        raise kopf.TemporaryError(result.stderr.strip() or result.stdout.strip(), delay=15)
    return result.stdout


def apply(manifest):
    kubectl("apply", "--server-side", "--force-conflicts", "--field-manager=platform", "-f", "-", stdin=manifest)


def wait_for_database(progress, name):
    try:
        kubectl("-n", name, "wait", "--for=condition=Ready", f"clusters.postgresql.cnpg.io/{name}-db", "--timeout=240s")
    except kopf.TemporaryError:  # the platform's side failed, not the app team's: say so
        progress.fail("database: not ready yet. The platform keeps trying. If this lasts, tell the platform team.")
        raise


def wait_for_app(progress, name, copies, image):
    """Wait for the copies to be ready. If they cannot start, stop early and say how to fix it."""
    for _ in range(40):  # about two minutes
        if int(kubectl("-n", name, "get", "deploy", name, "-o", "jsonpath={.status.readyReplicas}") or 0) >= copies:
            return
        reasons = kubectl("-n", name, "get", "pods", "-l", f"app={name}", "-o",
                          "jsonpath={.items[*].status.containerStatuses[*].state.waiting.reason}")
        problem = diagnose(name, reasons, image)
        if problem:
            progress.fail(problem)
            raise kopf.TemporaryError(problem, delay=20)  # try again later: the fix may land meanwhile
        time.sleep(3)
    progress.fail(f"app: not ready after two minutes. see what is happening: platform logs {name}")
    raise kopf.TemporaryError("app not ready", delay=20)


def diagnose(name, reasons, image):
    """Pod trouble, in words an app team can act on. None means: no known problem, keep waiting."""
    if "ImagePull" in reasons or "ErrImage" in reasons:
        return (f"image: the cluster cannot find {image}. fix: build it and load it into the cluster: "
                f"docker build -t {image} app && kind load docker-image {image} --name pe101")
    if "CreateContainerConfigError" in reasons:
        return ("image: it runs as root, and the platform runs only non-root containers. "
                "fix: add a line like  USER 10001  to your Dockerfile, then build and load it again")
    if "CrashLoopBackOff" in reasons:
        return f"app: it starts and then crashes. see why: platform logs {name}"
    return None


class Progress:
    """Writes each step to the Application's status, where the `platform` command reads it."""

    def __init__(self, name, generation, logger):
        self.name, self.generation, self.logger, self.steps = name, generation, logger, []
        self._write(phase="Provisioning", message="starting")

    def step(self, text):
        self.steps.append(text)
        self.logger.info(text)
        self._write(phase="Provisioning", message=text)

    def done(self, message):
        self._write(phase="Ready", message=message)

    def fail(self, message):
        self.logger.error(message)
        self._write(phase="Failed", message=message)

    def _write(self, **status):
        status.update(steps=self.steps, observedGeneration=self.generation)
        kubectl("patch", f"applications.platform.example.com/{self.name}", "--subresource=status",
                "--type=merge", "-p", json.dumps({"status": status}))
