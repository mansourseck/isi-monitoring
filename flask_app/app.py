from flask import Flask, render_template, jsonify
import psycopg2
import os

app = Flask(__name__)
DB_URL = os.environ.get("DATABASE_URL")


def get_db():
    return psycopg2.connect(DB_URL)


def query(sql, params=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close()
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/services")
def api_services():
    rows = query("""
        SELECT
            s.id, s.name, s.ip, s.vlan,
            m.status, m.latency_ms, m.http_code, m.checked_at
        FROM services s
        LEFT JOIN LATERAL (
            SELECT * FROM metrics
            WHERE service_id = s.id
            ORDER BY checked_at DESC LIMIT 1
        ) m ON true
        ORDER BY s.vlan
    """)
    for r in rows:
        if r["checked_at"]:
            r["checked_at"] = r["checked_at"].strftime("%H:%M:%S")
    return jsonify(rows)


@app.route("/api/history/<int:service_id>")
def api_history(service_id):
    rows = query("""
        SELECT status, latency_ms, http_code, checked_at
        FROM metrics
        WHERE service_id = %s
        ORDER BY checked_at DESC
        LIMIT 20
    """, [service_id])
    for r in rows:
        if r["checked_at"]:
            r["checked_at"] = r["checked_at"].strftime("%H:%M:%S")
    return jsonify(rows)


@app.route("/api/stats")
def api_stats():
    rows = query("""
        SELECT
            s.name,
            COUNT(*) FILTER (WHERE m.status = 'UP') as up_count,
            COUNT(*) as total,
            ROUND(AVG(m.latency_ms)::numeric, 2) as avg_latency
        FROM services s
        JOIN metrics m ON m.service_id = s.id
        GROUP BY s.name
    """)
    return jsonify(rows)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
