"""Coffee orders: a small web app that keeps its orders in Postgres."""

import html
import os
import socket
from string import Template

import psycopg
from flask import Flask, redirect, request

CAFE = "C.O.D.E Café"  # Make the app yours: put your café's name here.
DATABASE_URL = os.environ["DATABASE_URL"]  # Where the database lives, and the password to get in.

app = Flask(__name__)


def db():
    conn = psycopg.connect(DATABASE_URL, connect_timeout=3)
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id serial PRIMARY KEY, name text, drink text)")
    return conn


# If the database cannot be reached, the app stops here with an error.
# Kubernetes then starts it again, and again, until the database answers.
db().close()


@app.get("/")
def home():
    with db() as conn:
        orders = conn.execute("SELECT name, drink FROM orders ORDER BY id DESC LIMIT 20").fetchall()
    rows = "".join(f"<li><b>{html.escape(n)}</b> {html.escape(d)}</li>" for n, d in orders)
    return PAGE.substitute(cafe=html.escape(CAFE), rows=rows or "<li>No orders yet.</li>", pod=socket.gethostname())


@app.post("/orders")
def place_order():
    name, drink = request.form["name"].strip()[:40], request.form["drink"].strip()[:40]
    if name and drink:
        with db() as conn:
            conn.execute("INSERT INTO orders (name, drink) VALUES (%s, %s)", (name, drink))
    return redirect("/", code=303)


@app.get("/healthz")  # "Is the process alive?" Kubernetes restarts the app if this fails.
def healthz():
    return "ok"


@app.get("/ready")  # "Can it serve orders?" Kubernetes sends no traffic until this works.
def ready():
    with db() as conn:
        conn.execute("SELECT 1")
    return "ready"


PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>$cafe</title>
<style>
  body { margin: 0; background: #fbf6ef; color: #2b1d16; font: 16px/1.5 system-ui, sans-serif; }
  main { max-width: 32rem; margin: 3rem auto; padding: 0 1rem; }
  h1 { margin: 0; font-size: 2rem; } h1 span { color: #e8701a; }
  form { display: flex; gap: .5rem; flex-wrap: wrap; margin: 1.5rem 0; }
  input { flex: 1 1 8rem; padding: .6rem; border: 1px solid #d8c8b8; border-radius: .5rem; font: inherit; }
  button { padding: .6rem 1rem; border: 0; border-radius: .5rem; background: #e8701a; color: #fff; font: inherit; cursor: pointer; }
  ul { list-style: none; padding: 0; } li { padding: .5rem 0; border-bottom: 1px solid #eadfd3; }
  footer { margin-top: 2rem; color: #8a7565; font-size: .85rem; font-family: ui-monospace, monospace; }
</style></head>
<body><main>
  <h1>&#9749; $cafe <span>orders</span></h1>
  <form method="post" action="/orders">
    <input name="name" placeholder="Your name" maxlength="40" required>
    <input name="drink" placeholder="Your drink" maxlength="40" required>
    <button>Order</button>
  </form>
  <ul>$rows</ul>
  <footer>served by pod $pod</footer>
</main></body></html>
""")
