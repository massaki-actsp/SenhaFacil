from __future__ import annotations

import json
import queue
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, Response, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "senhafacil.sqlite3"

app = Flask(__name__)
db_lock = threading.Lock()
subscriber_lock = threading.Lock()
subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}

CATEGORIES = {
    "consulta": {"prefix": "MED", "label": "Consulta"},
    "retorno": {"prefix": "RET", "label": "Retorno"},
    "prioritario": {"prefix": "PRI", "label": "Prioritario"},
}


@contextmanager
def db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clinics (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                location_label TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                clinic_id TEXT NOT NULL,
                category TEXT NOT NULL,
                prefix TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                ticket_code TEXT NOT NULL,
                status TEXT NOT NULL,
                room TEXT,
                device_token TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                called_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (clinic_id) REFERENCES clinics(id),
                UNIQUE (clinic_id, issued_at, sequence)
            );

            CREATE TABLE IF NOT EXISTS daily_counters (
                clinic_id TEXT NOT NULL,
                counter_date TEXT NOT NULL,
                value INTEGER NOT NULL,
                PRIMARY KEY (clinic_id, counter_date),
                FOREIGN KEY (clinic_id) REFERENCES clinics(id)
            );
            """
        )
        existing = conn.execute("SELECT id FROM clinics WHERE slug = ?", ("unidade-centro",)).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO clinics (id, name, slug, location_label, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "clinic-demo",
                    "Senha Facil - Unidade Centro",
                    "unidade-centro",
                    "Recepcao principal",
                    datetime.now().isoformat(),
                ),
            )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def get_clinic_by_slug(slug: str) -> dict[str, Any] | None:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM clinics WHERE slug = ?", (slug,)).fetchone()
        return row_to_dict(row)


def get_today() -> str:
    return date.today().isoformat()


def ticket_payload(ticket: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ticket["id"],
        "clinic_id": ticket["clinic_id"],
        "category": ticket["category"],
        "category_label": CATEGORIES[ticket["category"]]["label"],
        "ticket_code": ticket["ticket_code"],
        "status": ticket["status"],
        "room": ticket["room"],
        "issued_at": ticket["issued_at"],
        "called_at": ticket["called_at"],
        "position": queue_position(ticket["clinic_id"], ticket["id"]),
    }


def queue_position(clinic_id: str, ticket_id: str) -> int:
    with db_connection() as conn:
        current = conn.execute(
            "SELECT issued_at FROM tickets WHERE id = ? AND clinic_id = ?",
            (ticket_id, clinic_id),
        ).fetchone()
        if not current:
            return 0
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM tickets
            WHERE clinic_id = ?
              AND date(issued_at) = ?
              AND status = 'aguardando'
              AND issued_at < ?
            """,
            (clinic_id, get_today(), current["issued_at"]),
        ).fetchone()
        return int(row["total"])


def publish(clinic_id: str, event: dict[str, Any], ticket_id: str | None = None) -> None:
    keys = [f"clinic:{clinic_id}"]
    if ticket_id:
        keys.append(f"ticket:{ticket_id}")
    with subscriber_lock:
        targets = [subscriber for key in keys for subscriber in subscribers.get(key, [])]
    for subscriber in targets:
        subscriber.put(event)


def subscribe(key: str):
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    with subscriber_lock:
        subscribers.setdefault(key, []).append(messages)
    try:
        yield messages
    finally:
        with subscriber_lock:
            subscribers[key].remove(messages)
            if not subscribers[key]:
                del subscribers[key]


def sse_stream(key: str):
    for messages in subscribe(key):
        yield "event: connected\ndata: {}\n\n"
        while True:
            try:
                event = messages.get(timeout=25)
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"


def generate_ticket(clinic_id: str, category: str, device_token: str) -> dict[str, Any]:
    if category not in CATEGORIES:
        raise ValueError("Categoria invalida.")

    now = datetime.now().isoformat()
    today = get_today()
    meta = CATEGORIES[category]
    ticket_id = str(uuid4())

    with db_lock:
        with db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO daily_counters (clinic_id, counter_date, value)
                VALUES (?, ?, 0)
                ON CONFLICT(clinic_id, counter_date) DO NOTHING
                """,
                (clinic_id, today),
            )
            conn.execute(
                """
                UPDATE daily_counters
                SET value = value + 1
                WHERE clinic_id = ? AND counter_date = ?
                """,
                (clinic_id, today),
            )
            sequence = conn.execute(
                "SELECT value FROM daily_counters WHERE clinic_id = ? AND counter_date = ?",
                (clinic_id, today),
            ).fetchone()["value"]
            ticket_code = f"{meta['prefix']}-{sequence:03d}"
            conn.execute(
                """
                INSERT INTO tickets (
                    id, clinic_id, category, prefix, sequence, ticket_code, status,
                    device_token, issued_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'aguardando', ?, ?)
                """,
                (ticket_id, clinic_id, category, meta["prefix"], sequence, ticket_code, device_token, now),
            )
            conn.execute("COMMIT")

    ticket = get_ticket(ticket_id)
    publish(clinic_id, {"type": "queue_update", "data": {"ticket": ticket_payload(ticket)}})
    return ticket


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with db_connection() as conn:
        return row_to_dict(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())


def get_active_ticket(clinic_id: str, device_token: str) -> dict[str, Any] | None:
    with db_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM tickets
            WHERE clinic_id = ?
              AND device_token = ?
              AND date(issued_at) = ?
              AND status IN ('aguardando', 'chamado')
            ORDER BY issued_at DESC
            LIMIT 1
            """,
            (clinic_id, device_token, get_today()),
        ).fetchone()
        return row_to_dict(row)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/fila/<slug>")
def patient_app(slug: str):
    clinic = get_clinic_by_slug(slug)
    if not clinic:
        return "Unidade nao encontrada.", 404
    return render_template("patient.html", clinic=clinic, categories=CATEGORIES)


@app.get("/gestao/<slug>")
def management(slug: str):
    clinic = get_clinic_by_slug(slug)
    if not clinic:
        return "Unidade nao encontrada.", 404
    return render_template("management.html", clinic=clinic)


@app.get("/painel/<slug>")
def display_panel(slug: str):
    clinic = get_clinic_by_slug(slug)
    if not clinic:
        return "Unidade nao encontrada.", 404
    return render_template("display.html", clinic=clinic)


@app.get("/relatorios/<slug>")
def reports(slug: str):
    clinic = get_clinic_by_slug(slug)
    if not clinic:
        return "Unidade nao encontrada.", 404
    return render_template("reports.html", clinic=clinic)


@app.get("/admin/<slug>/base")
def database_admin(slug: str):
    clinic = get_clinic_by_slug(slug)
    if not clinic:
        return "Unidade nao encontrada.", 404
    return render_template("database_admin.html", clinic=clinic)


@app.post("/api/senhas/gerar")
def api_generate_ticket():
    data = request.get_json(force=True)
    clinic = get_clinic_by_slug(data.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    device_token = data.get("device_token") or str(uuid4())

    existing = get_active_ticket(clinic["id"], device_token)
    if existing:
        return jsonify({"ticket": ticket_payload(existing), "device_token": device_token, "recovered": True})

    try:
        ticket = generate_ticket(clinic["id"], data.get("category", ""), device_token)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"ticket": ticket_payload(ticket), "device_token": device_token, "recovered": False}), 201


@app.get("/api/senhas/recuperar")
def api_recover_ticket():
    clinic = get_clinic_by_slug(request.args.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    ticket = get_active_ticket(clinic["id"], request.args.get("device_token", ""))
    return jsonify({"ticket": ticket_payload(ticket) if ticket else None})


@app.get("/api/senhas")
def api_tickets():
    clinic = get_clinic_by_slug(request.args.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tickets
            WHERE clinic_id = ? AND date(issued_at) = ?
            ORDER BY
                CASE status WHEN 'chamado' THEN 0 WHEN 'aguardando' THEN 1 ELSE 2 END,
                issued_at ASC
            """,
            (clinic["id"], get_today()),
        ).fetchall()
    return jsonify({"tickets": [ticket_payload(dict(row)) for row in rows]})


@app.post("/api/senhas/proxima")
def api_call_next():
    data = request.get_json(force=True)
    clinic = get_clinic_by_slug(data.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    room = data.get("room") or "Consultorio 1"
    now = datetime.now().isoformat()

    with db_lock:
        with db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM tickets
                WHERE clinic_id = ?
                  AND date(issued_at) = ?
                  AND status = 'aguardando'
                ORDER BY
                  CASE category WHEN 'prioritario' THEN 0 ELSE 1 END,
                  issued_at ASC
                LIMIT 1
                """,
                (clinic["id"], get_today()),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return jsonify({"ticket": None, "message": "Fila vazia."})
            conn.execute(
                "UPDATE tickets SET status = 'chamado', room = ?, called_at = ? WHERE id = ?",
                (room, now, row["id"]),
            )
            conn.execute("COMMIT")

    ticket = get_ticket(row["id"])
    payload = ticket_payload(ticket)
    event = {"type": "ticket_called", "data": {"ticket": payload}}
    publish(clinic["id"], event, ticket["id"])
    return jsonify({"ticket": payload})


@app.post("/api/senhas/<ticket_id>/finalizar")
def api_complete(ticket_id: str):
    now = datetime.now().isoformat()
    with db_connection() as conn:
        conn.execute("UPDATE tickets SET status = 'finalizado', completed_at = ? WHERE id = ?", (now, ticket_id))
    ticket = get_ticket(ticket_id)
    if ticket:
        publish(ticket["clinic_id"], {"type": "queue_update", "data": {"ticket": ticket_payload(ticket)}})
    return jsonify({"ok": True})


@app.get("/api/admin/senhas")
def api_admin_tickets():
    clinic = get_clinic_by_slug(request.args.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    period = request.args.get("period", "today")
    where_date = "AND date(issued_at) = ?" if period != "all" else ""
    params: tuple[Any, ...] = (clinic["id"], get_today()) if period != "all" else (clinic["id"],)

    with db_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM tickets
            WHERE clinic_id = ?
            {where_date}
            ORDER BY issued_at DESC
            """,
            params,
        ).fetchall()
        counter = conn.execute(
            """
            SELECT value FROM daily_counters
            WHERE clinic_id = ? AND counter_date = ?
            """,
            (clinic["id"], get_today()),
        ).fetchone()
    return jsonify(
        {
            "tickets": [ticket_payload(dict(row)) for row in rows],
            "today_counter": int(counter["value"]) if counter else 0,
        }
    )


@app.delete("/api/admin/senhas/<ticket_id>")
def api_admin_delete_ticket(ticket_id: str):
    ticket = get_ticket(ticket_id)
    if not ticket:
        return jsonify({"error": "Senha nao encontrada."}), 404

    with db_lock:
        with db_connection() as conn:
            conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))

    publish(ticket["clinic_id"], {"type": "queue_update", "data": {"deleted_ticket_id": ticket_id}})
    publish(
        ticket["clinic_id"],
        {"type": "ticket_removed", "data": {"ticket_id": ticket_id, "reason": "deleted"}},
        ticket_id,
    )
    return jsonify({"ok": True})


@app.post("/api/admin/fila/resetar")
def api_admin_reset_queue():
    data = request.get_json(force=True)
    clinic = get_clinic_by_slug(data.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    today = get_today()

    with db_lock:
        with db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id FROM tickets
                WHERE clinic_id = ? AND date(issued_at) = ?
                """,
                (clinic["id"], today),
            ).fetchall()
            ticket_ids = [row["id"] for row in rows]
            conn.execute(
                "DELETE FROM tickets WHERE clinic_id = ? AND date(issued_at) = ?",
                (clinic["id"], today),
            )
            conn.execute(
                """
                INSERT INTO daily_counters (clinic_id, counter_date, value)
                VALUES (?, ?, 0)
                ON CONFLICT(clinic_id, counter_date)
                DO UPDATE SET value = 0
                """,
                (clinic["id"], today),
            )
            conn.execute("COMMIT")

    publish(clinic["id"], {"type": "queue_reset", "data": {"scope": "today"}})
    for ticket_id in ticket_ids:
        publish(
            clinic["id"],
            {"type": "ticket_removed", "data": {"ticket_id": ticket_id, "reason": "reset"}},
            ticket_id,
        )
    return jsonify({"ok": True, "deleted": len(ticket_ids)})


@app.delete("/api/admin/registros")
def api_admin_delete_all_records():
    clinic = get_clinic_by_slug(request.args.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404

    with db_lock:
        with db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT id FROM tickets WHERE clinic_id = ?", (clinic["id"],)).fetchall()
            ticket_ids = [row["id"] for row in rows]
            conn.execute("DELETE FROM tickets WHERE clinic_id = ?", (clinic["id"],))
            conn.execute("DELETE FROM daily_counters WHERE clinic_id = ?", (clinic["id"],))
            conn.execute("COMMIT")

    publish(clinic["id"], {"type": "queue_reset", "data": {"scope": "all"}})
    for ticket_id in ticket_ids:
        publish(
            clinic["id"],
            {"type": "ticket_removed", "data": {"ticket_id": ticket_id, "reason": "deleted_all"}},
            ticket_id,
        )
    return jsonify({"ok": True, "deleted": len(ticket_ids)})


@app.get("/api/eventos/ticket/<ticket_id>")
def ticket_events(ticket_id: str):
    return Response(sse_stream(f"ticket:{ticket_id}"), mimetype="text/event-stream")


@app.get("/api/eventos/clinica/<clinic_id>")
def clinic_events(clinic_id: str):
    return Response(sse_stream(f"clinic:{clinic_id}"), mimetype="text/event-stream")


@app.get("/api/relatorios/emissoes")
def api_reports():
    clinic = get_clinic_by_slug(request.args.get("clinic_slug", ""))
    if not clinic:
        return jsonify({"error": "Unidade nao encontrada."}), 404
    period = request.args.get("period", "daily")
    today = date.today()
    start = today if period == "daily" else today - timedelta(days=6)

    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT date(issued_at) AS day, category, COUNT(*) AS total
            FROM tickets
            WHERE clinic_id = ? AND date(issued_at) BETWEEN ? AND ?
            GROUP BY date(issued_at), category
            ORDER BY day ASC, category ASC
            """,
            (clinic["id"], start.isoformat(), today.isoformat()),
        ).fetchall()
    return jsonify(
        {
            "period": period,
            "start": start.isoformat(),
            "end": today.isoformat(),
            "rows": [dict(row) for row in rows],
        }
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
