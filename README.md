# Platform Engineering 101: Ship One App Twice

Deploy an app to Kubernetes the hard way, then the platform way, and see what platform teams at big companies build.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/BodhiSatvik/platform-engineering-101)

**2 hours · no Docker or Kubernetes experience needed · everything runs in your browser**

| Lab | You are | What happens |
|---|---|---|
| [Lab 1: on your own](#lab-1-on-your-own-35-min) | an app team with no platform team | You ship a small app and a database by hand. Every step is a new request from someone. It works. It is not safe. |
| [Lab 2: with a platform](#lab-2-with-a-platform-30-min) | the same app team, at a company that has a platform team | You describe the app in 5 lines. The platform does the rest, the same way for every team. |
| [Lab 3: be the platform team](#lab-3-be-the-platform-team-5-min) | the platform team | You fix one problem, once, for every team. |

## Before you start (5 minutes)

**In a Codespace (recommended).** Click the button above, then **Create codespace**. You need a free GitHub account. The Codespace builds a small Kubernetes cluster for you. This takes about 5 minutes. When the terminal prints `ready. Open README.md and start Lab 1.`, you can start.

**On your own laptop.** You need Docker, [kind](https://kind.sigs.k8s.io/), kubectl and Python 3.10 or newer. Then:

```bash
./setup/setup.sh
export PATH="$PWD/bin:$PWD/.venv/bin:$PATH"
```

The setup script installs tools only into this folder (`bin/` and `.venv/`) and works only on the `kind-pe101` cluster that it creates.

**How each step works.** Each step has four parts:

- **Why**: what the step is for, in plain words.
- **Do**: the commands. Copy and paste them.
- **Look behind the curtain**: one command that shows what Kubernetes did, and what to notice.
- **At a big company**: how the same step goes when there are hundreds of teams.

---

## Lab 1: on your own (35 min)

> Your first ticket at a big company: "Ship the coffee-orders app by Friday." There is no platform team. You have a cluster, a terminal and this page. Every step below is a new request from someone. Count the files you touch and the new words you learn.

The app is in `app/`. It is a small Python web app that takes coffee orders and keeps them in a Postgres database. Open `app/app.py` and change `CAFE` to your café's name.

### Step 1. "It has to run on a server, not on your laptop." (your tech lead)

**Why.** A server does not have your laptop's Python, your packages or your settings. A *container image* packs your app and everything it needs into one file that runs the same anywhere.

**Do.**

```bash
docker build -t coffee:v1 app
kind load docker-image coffee:v1 --name pe101
```

The first line builds the image from `app/Dockerfile`. The second line copies it into your cluster, so the cluster can run it.

**Look behind the curtain.** Open `app/Dockerfile`. Each line is one layer of the image: a base with Python, your packages, your code, and the command that starts the app. `USER 10001` makes the app run as a plain user, not as root.

**At a big company.** No one builds images on a laptop. A pipeline builds every image, scans it for known security holes, and stores it in a company registry. Someone has to set up and run that pipeline.

### Step 2. "Here is your space. Do not touch anyone else's." (the cluster admin)

**Why.** Many teams share one cluster. A *namespace* is a separate area for one team's objects. *RBAC* (role-based access control) says who may do what, and where.

**Do.**

```bash
kubectl create namespace coffee-diy
kubectl config set-context --current --namespace coffee-diy
kubectl create serviceaccount team
kubectl create rolebinding team-edit --clusterrole edit --serviceaccount coffee-diy:team
```

The last two lines make a login for your team (`team`, a stand-in for your team's real logins) and let it edit things in `coffee-diy` only.

**Look behind the curtain.** Ask Kubernetes what your team may do:

```bash
kubectl auth can-i delete pods --as system:serviceaccount:coffee-diy:team
kubectl auth can-i get secrets -n kube-system --as system:serviceaccount:coffee-diy:team
```

Expect `yes`, then `no`. Your team may change its own space, but not the cluster's.

**At a big company.** You file a ticket for the namespace and wait. Someone guesses how much CPU and memory you may use. Someone else sets up your access. Each one is a different team with its own queue.

### Step 3. "Orders must be stored somewhere. Stand up Postgres." (your tech lead)

**Why.** Your app needs a database. On your own, you run it yourself.

**Do.**

```bash
kubectl apply -f lab1/postgres.yaml
kubectl rollout status deploy/postgres
```

`lab1/postgres.yaml` holds three objects: a *Secret* (the password), a *Deployment* (keep one copy of the database running) and a *Service* (a stable name, `postgres`, that other pods use to find it). Read the comments in the file.

**Look behind the curtain.** Read the password back:

```bash
kubectl get secret postgres -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d; echo
```

A Secret is only base64-encoded, and base64 is not encryption. The password is also in plain text in `lab1/postgres.yaml`, which would be in your git repo. Anyone who can read the repo can read your database.

**At a big company.** A secrets manager (for example HashiCorp Vault) keeps passwords. Apps get them while they run, and people never see them. Getting your app access to it can take a ticket and days. The database itself needs disks, backups, upgrades and someone on call.

### Step 4. "Ship it!" (you)

**Why.** A *Deployment* tells Kubernetes "keep this many copies of this container running". `lab1/deployment.yaml` is written the way a busy developer writes it on a Friday afternoon.

**Do.**

```bash
kubectl apply -f lab1/deployment.yaml
kubectl get pods --watch
```

Wait about 30 seconds, then press `Ctrl+C`. The app pod says `Error` or `CrashLoopBackOff`: it starts, crashes, and Kubernetes starts it again, and again.

**Something broke. Find out why.**

```bash
kubectl logs deploy/coffee | grep Error
```

Find the line `failed to resolve host 'postgress'`. There is a typo in the database address. Fix it in `lab1/deployment.yaml` (`postgress` becomes `postgres`), then apply again:

```bash
kubectl apply -f lab1/deployment.yaml
kubectl rollout status deploy/coffee
```

**Look behind the curtain.** `kubectl describe pod -l app=coffee` shows the pod's *events*: pulled the image, started, failed, backed off. Note what the file does not have: CPU and memory limits, health checks, a non-root setting. Nothing stopped you.

**At a big company.** This is a normal day: a wall of logs, and one line that matters. Now picture it at 3 a.m., for a service you did not write.

### Step 5. "What is the URL?" (the front-end team)

**Why.** Pods come and go, and each new pod gets a new address. A *Service* keeps one stable name and sends traffic to whichever pods are alive.

**Do.**

```bash
kubectl apply -f lab1/service.yaml
```

Open a **second terminal** (the **+** in the terminal panel) and run:

```bash
kubectl port-forward svc/coffee 8080:80
```

Open port 8080: in a Codespace, use the pop-up or the **Ports** tab; on a laptop, http://localhost:8080. Place an order. Keep this tab open.

**Look behind the curtain.** In the first terminal, run `kubectl describe service coffee`. The `Endpoints` line lists the pod addresses behind the name.

**At a big company.** `port-forward` is a debugging tool. Real traffic needs an *ingress* (a front door for the cluster), a DNS name, a TLS certificate for HTTPS, and firewall rules. Each one is another tool to learn or another ticket to file.

### Step 6. "What happens when things fail?" (the reliability team)

**Why.** Machines die. Kubernetes replaces lost pods, but only for what you told it to keep.

**Do.** Delete the app pod and watch Kubernetes replace it:

```bash
kubectl delete pod -l app=coffee
kubectl get pods
```

Did your page stop working? Your port-forward was tied to the pod you deleted. In the second terminal, press `Ctrl+C` and run the port-forward again. Then scale out, and refresh the page a few times. The footer shows which pod served you.

```bash
kubectl scale deploy coffee --replicas 3
```

Now delete the database pod:

```bash
kubectl delete pod -l app=postgres
kubectl rollout status deploy/postgres
```

Refresh the page. **Your orders are gone.** The database kept its data in an `emptyDir`, which lives only as long as its pod.

**At a big company.** A real database needs a disk that outlives the pod, replicas, backups and tested restores. Some companies have whole teams that only do this.

### Step 7. "Prove your namespace is fenced off from other teams." (security)

**Why.** Your team shares the cluster with every other team. Security wants proof that your team cannot break out of its space, and that a bad pod cannot hurt the others.

**Do.** Check the namespace from your team's side, as your team, with [`kubectl audit-tenant`](https://github.com/BodhiSatvik/kubectl-audit-tenant):

```bash
kubectl audit-tenant -n coffee-diy --as system:serviceaccount:coffee-diy:team
```

Expect this last line:

```text
3 passed · 11 failed (AT-04.1, AT-04.2, AT-04.3 and 8 more) · 0 skipped · 0 errors · exit 1
```

**Look behind the curtain.** Read two `FAIL` lines and the `fix` line under each. Your team could run a privileged pod that takes over the machine. It could open a port on every machine in the cluster. It has no CPU or memory budget, and no network rules. The tool asked the cluster directly (*may I?* questions and *dry runs* that store nothing), and the cluster said yes.

**At a big company.** Each `fix` line is another file and another idea to learn: Pod Security, quotas, limit ranges, network policies. Now multiply by every team. (Facilitator: this is the moment for [the fleet demo](#for-facilitators).)

### Count it up

| What production needs | Lab 1 |
|---|---|
| It runs, and restarts when it crashes | ✓ |
| Others can reach it | by hand, until the pod restarts |
| It has a database | ✓ |
| The password stays secret | ✗ in plain text, in two files |
| The data survives a restart | ✗ |
| CPU and memory limits, health checks, non-root | ✗ |
| More copies when traffic grows | ✗ only by hand |
| Fenced off from other teams | ✗ 3 of 14 checks |
| HTTPS, a DNS name, alerts, backups, the same again for staging and production | ✗ not even started |

You wrote **85 lines of YAML in 3 files**, ran 6 setup commands, fixed a crash and learned about 15 new words. You also had to hear from **5 people**: your tech lead, the cluster admin, the front-end team, the reliability team and security. That is two kinds of *glue*, the work that holds the parts together: the files you wrote, and the people you had to hear from. Every app team at your company does all of this, each a little differently, and keeps it up to date forever.

---

## Lab 2: with a platform (30 min)

> Now there is a platform team. They turned the steps from Lab 1 into software, once, for every team. You are the app team again. Leave the Lab 1 app running, so you can compare.

### Step 1. Start the platform

**Why.** In real life the platform team runs this for you all the time. Here you start it yourself and watch it work.

**Do.** Open a **third terminal** and run:

```bash
kopf run --standalone --all-namespaces platform/operator.py
```

Leave it open. This is the platform's *control loop*. It watches for app requests and makes the cluster match them. Its log tells you each step as it happens.

### Step 2. Describe your app

**Why.** You say *what* you want. The platform decides *how*, the same way for everyone.

Open `lab2/app.yaml`:

```yaml
name: coffee
image: coffee:v1            # the same image you built in Lab 1
plan: small                 # small, medium or large: the platform picks CPU and memory
replicas: {min: 2, max: 4}  # the platform keeps 2 copies, and adds up to 4 when busy
database: postgres          # the platform runs a Postgres database for you
```

That is the whole request: 5 lines, and no Kubernetes words.

### Step 3. Ship it

**Do.** In your first terminal:

```bash
platform deploy lab2/app.yaml
```

Expect:

```text
▸ deploying coffee
  ✓ request accepted: the platform takes it from here
  ✓ workspace: namespace coffee, with a budget, default limits, pod security and network rules  1s
  ✓ team access: your team can work inside coffee, and nowhere else  1s
  ✓ database: Postgres with a generated password that no person has seen  39s
  ✓ app: 2 copies running as non-root, with health checks, small size  46s
  ✓ autoscaler: 2 to 4 copies, adds copies when CPU passes 70%  46s
➜ ready in 46s. open it: platform open coffee
```

Your times will differ: about a minute, a bit longer the first time, while the database image downloads. Watch the third terminal while it runs: the control loop logs the same steps.

### Step 4. Open it

```bash
platform open coffee
```

Open port 8081 (Codespace: the **Ports** tab; laptop: http://localhost:8081) and place an order. Put it next to your Lab 1 tab on port 8080. Same app, same image.

### Step 5. Make a mistake on purpose

Change `plan: small` to `plan: huge` in `lab2/app.yaml`, then deploy again:

```bash
platform deploy lab2/app.yaml
```

```text
▸ deploying coffee
  ✗ plan: "huge" is not one of the choices.
    fix: use one of "small", "medium", "large"
```

The platform checks every request before it changes anything, and tells you how to fix it. Your app keeps running. Change it back to `small`.

### Step 6. Look behind the curtain

**Why.** The platform is not magic. It writes the same kinds of objects you wrote in Lab 1, plus the ones you did not have time for.

```bash
kubectl get all,quota,limitrange,networkpolicy,serviceaccount,rolebinding,secret,pvc,clusters.postgresql.cnpg.io -n coffee
```

About 25 objects of 13 kinds, from your 5 lines. Then open `platform/operator.py` and find `APP = Template`. That is the Deployment the platform wrote for you. Compare it with your `lab1/deployment.yaml`: CPU and memory sizes, two health checks (`/healthz`: is it alive? `/ready`: can it serve?), non-root, no extra Linux privileges. The password lives in the Secret `coffee-db-app`. The database made it, nobody typed it, and it is in no file in your repo. Now find `DATABASE_URL` in `platform/operator.py`: the platform hands your app the database's address and password from that Secret. Nobody types them, so the Lab 1 typo (`postgress`) cannot happen here.

**At a big company.** This is what a platform team builds: one API for many teams, guardrails built in, the cluster's details hidden. Many large companies run a platform like this. Some also handle databases, message queues and caches through the same API.

### Step 7. Break it again

```bash
kubectl -n coffee delete pod -l cnpg.io/cluster=coffee-db
kubectl -n coffee wait --for=condition=Ready clusters.postgresql.cnpg.io/coffee-db --timeout=180s
```

Refresh port 8081. **Your orders are still there.** The platform's database keeps its data on a disk that outlives the pod. Now delete the app's pods:

```bash
kubectl -n coffee delete pod -l app=coffee
```

Wait a few seconds and refresh. `platform open` reconnected by itself.

### Step 8. Trust, but verify

**Why.** The platform says your namespace is fenced. Check it yourself, the same way security checked Lab 1:

```bash
kubectl audit-tenant -n coffee --as system:serviceaccount:coffee:team
```

```text
13 passed · 1 failed (AT-08) · 0 skipped · 0 errors · exit 1
```

13 of 14, up from 3. But read the `FAIL`: `no default deny for egress`. The platform blocks traffic *into* your namespace, but not traffic *out* of it. Your app could reach any other team's database. That gap is in the platform's template, so every team has it. Hold that thought for Lab 3.

### Step 9. Day-two work

```bash
platform status
platform logs coffee
platform restart coffee
```

`restart` replaces the copies one at a time, so the app stays up. It is an *action*: it does not change what you asked for in `lab2/app.yaml`.

**At a big company.** You still own your app. If your code breaks at 3 a.m., your team gets the call. The platform team gets the call for the platform: the database, the network rules, the control loop. `platform status` and `platform logs` help you see which side has the problem before you call anyone.

### Lab 1 and Lab 2, side by side

| | Lab 1: on your own | Lab 2: with a platform |
|---|---|---|
| You wrote | 85 lines of YAML in 3 files, plus 6 commands | 5 lines |
| People you had to hear from | 5: tech lead, cluster admin, front-end, reliability, security | none: the platform answers their requests, for every team |
| Time | about 35 minutes, with a crash to debug | about 1 minute |
| The database password | in plain text, in two files | generated, seen by no one |
| A database pod restarts | orders lost | orders kept |
| Limits, health checks, non-root, autoscaling | none | all, for every app |
| Fenced off from other teams | 3 of 14 checks | 13 of 14 checks |

---

## Lab 3: be the platform team (5 min)

> The audit found the same gap in every team's namespace: nothing stops traffic going out. One app team cannot fix that for the others. The platform team can.

**Prove the gap first.** From team coffee's app, try to open a connection to the Lab 1 team's database:

```bash
kubectl -n coffee exec deploy/coffee -- python -c "import socket; socket.create_connection(('postgres.coffee-diy', 5432), 3); print('connected to the other team database')"
```

It connects. Any app could reach any other team's database.

**Fix it once.** In `platform/operator.py`, change one line:

```python
EGRESS_DEFAULT_DENY = True  # Lab 3: the platform team turns this on, once, for every team.
```

In the third terminal, press `Ctrl+C` and start the platform again:

```bash
kopf run --standalone --all-namespaces platform/operator.py
```

At start, the control loop checks every app again and applies the new rules: deny all outgoing traffic, except DNS (name lookups), the app's own pods, and what the database needs.

**Check it.**

```bash
kubectl audit-tenant -n coffee --as system:serviceaccount:coffee:team
```

```text
14 passed · 0 failed · 0 skipped · 0 errors · exit 0
```

Run the connection test again: it now times out. Refresh port 8081: your app still works and still talks to its own database.

One change by the platform team, and every team gets it, without a ticket or a meeting. That is the *leverage* of platform engineering.

**At a big company.** One change reached every team at once. A mistake would too. So platform teams review each change, test it, and roll it out in stages: first to a few teams that can live with a problem, then to everyone. Here you edited a file and restarted the control loop by hand, which is fine on a lab cluster.

---

## What you built, and where it lives in real platforms

| Piece in this repo | Its job | In real platforms |
|---|---|---|
| `platform` command (`bin/platform`) | The one tool app teams use | Command-line tools, web consoles, Terraform providers and AI-assistant tools, all calling one API |
| `Application` kind (`platform/crd.yaml`) | The platform's API: what you may ask for | An internal platform API, checked before anything changes |
| `platform/operator.py` | The control loop: makes the cluster match each request | Controllers, operators and workflow engines |
| CloudNativePG | Runs Postgres for the platform | Open-source operators for Postgres, Kafka, Cassandra and caches |
| The workspace template | A fenced namespace per app, with a budget | "Namespace as a service" |
| `kubectl audit-tenant` | Proves the fences hold, from the team's side | Security reviews and pipeline gates |

## Clean up

- **Codespace**: on github.com, open **Your codespaces** and delete this one. Nothing else to do.
- **Laptop**: `kind delete cluster --name pe101`

## Go further

- Find and fix six broken fences in a 60-minute lab: [audit-tenant workshop](https://github.com/BodhiSatvik/kubectl-audit-tenant/blob/main/playbooks/workshop.md).
- Check a namespace on a real cluster, safely: [real-cluster playbook](https://github.com/BodhiSatvik/kubectl-audit-tenant/blob/main/playbooks/real-cluster.md).
- Read: *Platform Engineering* by Camille Fournier and Ian Nowland; *Team Topologies* by Matthew Skelton and Manuel Pais.
- Try an internal developer portal: [Backstage](https://backstage.io).

**Tell us how it went.** A [short report](https://github.com/BodhiSatvik/kubectl-audit-tenant/issues/new?template=playbook-report.yml&playbook=platform-engineering-101) helps the next group, whether things worked or broke. If `kubectl audit-tenant` was useful, a star on [its repo](https://github.com/BodhiSatvik/kubectl-audit-tenant) helps other platform teams find it.

---

## For facilitators

**Timing (2 hours).**

| Time | Part |
|---|---|
| 0:00 | Everyone opens a Codespace. Talk while they start (15 min): the deploy button, why platform engineering exists, "why not just use Vercel?" |
| 0:15 | Lab 1 (35 min), then the fleet demo (2 min) |
| 0:50 | Break (10 min) |
| 1:00 | Talk (10 min): what a platform team does, and how a real platform works |
| 1:10 | Lab 2 (30 min) |
| 1:40 | Lab 3 on the projector (5 min). Attendees can follow along. |
| 1:45 | Wrap-up and questions (15 min) |

**Before the session.**

- Run the whole workshop once yourself in a Codespace (about 50 minutes without the talks).
- Before each session, run `test/runbook-test.sh` (about 8 minutes). It runs every command on this page, as written, and checks each result. It deletes and rebuilds the `pe101` cluster, and works in a copy of the repo, so your files stay as they are.
- Do a practice run with 2 or 3 people. Ask them to help in the room.
- One week before, send attendees this repo and ask them to make a GitHub account and open the Codespace once. That checks the button and their free Codespace hours (a session uses about 10 of the 120 free core-hours a month).

**The fleet demo (end of Lab 1).** On your own Codespace, run `demo/fleet.sh`. It makes eight team namespaces, each fenced as far as that team got before its deadline, and audits each one as that team:

```text
  payments   13 passed · 1 failed (AT-05) · 0 skipped · 0 errors
  claims     12 passed · 2 failed (AT-05, AT-08) · 0 skipped · 0 errors
  quotes     3 passed · 11 failed (AT-04.1, AT-04.2, AT-04.3 and 8 more) · 0 skipped · 0 errors
  billing    6 passed · 8 failed (AT-04.1, AT-04.2, AT-04.3 and 5 more) · 0 skipped · 0 errors
  ...
```

Even the most careful team missed something nobody told it about. `demo/fleet.sh clean` removes the eight namespaces.

**If something goes wrong.**

| Problem | Fix |
|---|---|
| A Codespace will not start, or the person has no hours left | Pair them with a neighbour. The labs work well in pairs. |
| The Codespace slept and `kubectl` cannot connect | `docker start pe101-control-plane`, wait 30 seconds, try again |
| `platform deploy` waits and says "waiting for the platform" | The control loop is not running: Lab 2, step 1 |
| `kubectl audit-tenant` or `platform`: command not found | `export PATH="$PWD/bin:$PWD/.venv/bin:$PATH"` |
| Lab 1 pod shows `ErrImagePull` | The image was not loaded: `kind load docker-image coffee:v1 --name pe101` |
| Port 8080 or 8081 already in use | Stop the old port-forward with `Ctrl+C`, or close its terminal |
