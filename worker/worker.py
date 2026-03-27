import os, time, requests, psycopg2
from datetime import datetime

DB_URL = os.environ.get("DATABASE_URL")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", 30))

TARGETS = [
    {"name": "Portail Web ISI",     "host": "service_web",   "ip": "172.20.0.10", "port": 8081, "vlan": 10},
    {"name": "Serveur Fichiers ISI","host": "service_files",  "ip": "172.20.0.20", "port": 8082, "vlan": 20},
]

def get_db(): return psycopg2.connect(DB_URL)

def init_db():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS services (id SERIAL PRIMARY KEY, name VARCHAR(100) UNIQUE, ip VARCHAR(50), vlan INTEGER);
        CREATE TABLE IF NOT EXISTS metrics (id SERIAL PRIMARY KEY, service_id INTEGER REFERENCES services(id), status VARCHAR(10), latency_ms FLOAT, http_code INTEGER, checked_at TIMESTAMP DEFAULT NOW());
    """)
    for t in TARGETS:
        cur.execute("INSERT INTO services (name,ip,vlan) VALUES (%s,%s,%s) ON CONFLICT (name) DO NOTHING",
                    (t["name"], t["ip"], t["vlan"]))
    conn.commit(); cur.close(); conn.close()
    print("[DB] OK")

def check_http(host, port):
    try:
        start = time.time()
        r = requests.get(f"http://{host}:{port}/health", timeout=3)
        return True, round((time.time()-start)*1000, 2), r.status_code
    except:
        return False, 0.0, 0

def save(sid, status, lat, code):
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO metrics (service_id,status,latency_ms,http_code) VALUES (%s,%s,%s,%s)",
                (sid, status, lat, code))
    conn.commit(); cur.close(); conn.close()

def get_sid(name):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM services WHERE name=%s", (name,))
    row = cur.fetchone(); cur.close(); conn.close()
    return row[0] if row else None

def check_all():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Verification...")
    for t in TARGETS:
        sid = get_sid(t["name"])
        if not sid: continue
        ok, lat, code = check_http(t["host"], t["port"])
        status = ("UP" if code < 400 else "DEGRADED") if ok else "DOWN"
        print(f"  [{t['name']}] {status} — {lat}ms — HTTP {code or 'N/A'}")
        save(sid, status, lat, code or None)

def main():
    print("[Worker] Demarrage...")
    time.sleep(20)
    while True:
        try: init_db(); break
        except Exception as e: print(f"DB... {e}"); time.sleep(5)
    while True:
        try: check_all()
        except Exception as e: print(f"[Err] {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
