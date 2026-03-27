from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from db import query, execute, init_db, wait_for_db
import os, time
from functools import wraps

app = Flask(__name__)
app.secret_key = "isi-files-secret-2025"


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            if session["user"]["role"] not in roles:
                return "Acces refuse", 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def get_user():
    return session.get("user", {})


def calc_bulletin(eid):
    result = {}
    for s in [1, 2]:
        notes = query("""SELECT n.note_finale, m.credits, m.coefficient
                         FROM notes n JOIN matieres m ON m.id=n.matiere_id
                         WHERE n.etudiant_id=%s AND n.semestre=%s""", [eid, s])
        if notes:
            total = sum((r["note_finale"] or 0)*r["coefficient"] for r in notes)
            coeff = sum(r["coefficient"] for r in notes if r.get("note_finale"))
            cred = sum(r["credits"] for r in notes if r.get("note_finale") and r["note_finale"] >= 10)
            moy = round(total/coeff, 2) if coeff else 0
            result[f"s{s}"] = {"moyenne": moy, "credits_valides": cred, "valide": moy >= 10 and cred >= 60}
    return result


# ── Auth ─────────────────────────────────────────────
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    role = session["user"]["role"]
    if role == "admin": return redirect(url_for("admin_home"))
    elif role == "prof": return redirect(url_for("prof_home"))
    else: return redirect(url_for("etudiant_home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        rows = query(
            "SELECT * FROM utilisateurs WHERE username=%s AND password=%s",
            [request.form["username"], request.form["password"]]
        )
        if rows:
            u = rows[0]
            u["created_at"] = str(u["created_at"]) if u.get("created_at") else None

            # Cas professeur
            if u["role"] == "prof":
                p = query("SELECT id as prof_id, * FROM professeurs WHERE user_id=%s", [u["id"]])
                if p:
                    u["prof"] = p[0]

            # Cas étudiant
            elif u["role"] == "etudiant":
                e = query("""
                    SELECT e.id as etudiant_id, e.*, 
                           c.nom as classe_nom, c.id as classe_id,
                           f.nom as filiere_nom, f.code as filiere_code,
                           n.nom as niveau_nom, d.nom as dept_nom
                    FROM etudiants e
                    LEFT JOIN classes c ON c.id=e.classe_id
                    LEFT JOIN filieres f ON f.id=c.filiere_id
                    LEFT JOIN niveaux n ON n.id=c.niveau_id
                    LEFT JOIN departements d ON d.id=f.departement_id
                    WHERE e.user_id=%s
                """, [u["id"]])
                if e:
                    u["etudiant"] = e[0]

            # Sauvegarde dans la session
            session["user"] = u
            return redirect(url_for("index"))

        flash("Identifiants incorrects", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ══════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════
@app.route("/admin")
@role_required("admin")
def admin_home():
    classes = query("""SELECT c.*,f.nom as filiere_nom,n.nom as niveau_nom,d.nom as dept_nom,
                              COUNT(e.id) as nb_etudiants
                       FROM classes c LEFT JOIN filieres f ON f.id=c.filiere_id
                       LEFT JOIN niveaux n ON n.id=c.niveau_id
                       LEFT JOIN departements d ON d.id=f.departement_id
                       LEFT JOIN etudiants e ON e.classe_id=c.id
                       GROUP BY c.id,f.nom,n.nom,d.nom ORDER BY c.nom""")
    profs = query("""SELECT p.id as prof_id,u.nom,u.prenom,p.grade,d.nom as dept_nom
                     FROM professeurs p JOIN utilisateurs u ON u.id=p.user_id
                     LEFT JOIN departements d ON d.id=p.departement_id ORDER BY u.nom""")
    stats = {
        "etudiants": query("SELECT COUNT(*) as c FROM etudiants")[0]["c"],
        "profs":     query("SELECT COUNT(*) as c FROM professeurs")[0]["c"],
        "classes":   query("SELECT COUNT(*) as c FROM classes")[0]["c"],
        "notes":     query("SELECT COUNT(*) as c FROM notes")[0]["c"],
    }
    return render_template("admin/home.html", user=get_user(), classes=classes, profs=profs, stats=stats)


@app.route("/admin/rapport/classe/<int:classe_id>")
@role_required("admin")
def admin_rapport_classe(classe_id):
    classes = query("""SELECT c.*,f.nom as filiere_nom,n.nom as niveau_nom,d.nom as dept_nom
                       FROM classes c LEFT JOIN filieres f ON f.id=c.filiere_id
                       LEFT JOIN niveaux n ON n.id=c.niveau_id
                       LEFT JOIN departements d ON d.id=f.departement_id
                       WHERE c.id=%s""", [classe_id])
    classe = classes[0] if classes else {}
    etudiants = query("""SELECT u.nom,u.prenom,e.id as etudiant_id,e.matricule
                         FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
                         WHERE e.classe_id=%s ORDER BY u.nom""", [classe_id])
    data = []
    for e in etudiants:
        eid = e["etudiant_id"]
        notes_s1 = query("""SELECT n.*,m.nom as matiere_nom,m.code,m.credits,m.coefficient
                             FROM notes n JOIN matieres m ON m.id=n.matiere_id
                             WHERE n.etudiant_id=%s AND n.semestre=1 ORDER BY m.nom""", [eid])
        notes_s2 = query("""SELECT n.*,m.nom as matiere_nom,m.code,m.credits,m.coefficient
                             FROM notes n JOIN matieres m ON m.id=n.matiere_id
                             WHERE n.etudiant_id=%s AND n.semestre=2 ORDER BY m.nom""", [eid])
        nb_abs = query("SELECT COUNT(*) as c FROM absences WHERE etudiant_id=%s", [eid])[0]["c"]
        bulletin = calc_bulletin(eid)
        data.append({"etudiant": e, "notes_s1": notes_s1, "notes_s2": notes_s2,
                     "bulletin": bulletin, "nb_absences": nb_abs})
    return render_template("admin/rapport_classe.html", user=get_user(), classe=classe, data=data)


@app.route("/admin/rapport/general")
@role_required("admin")
def admin_rapport_general():
    classes = query("""SELECT c.*,f.nom as filiere_nom,n.nom as niveau_nom,d.nom as dept_nom
                       FROM classes c LEFT JOIN filieres f ON f.id=c.filiere_id
                       LEFT JOIN niveaux n ON n.id=c.niveau_id
                       LEFT JOIN departements d ON d.id=f.departement_id ORDER BY c.nom""")
    profs = query("""SELECT p.*,u.nom,u.prenom,d.nom as dept_nom FROM professeurs p
                     JOIN utilisateurs u ON u.id=p.user_id
                     LEFT JOIN departements d ON d.id=p.departement_id ORDER BY u.nom""")
    stats = {
        "etudiants": query("SELECT COUNT(*) as c FROM etudiants")[0]["c"],
        "profs":     query("SELECT COUNT(*) as c FROM professeurs")[0]["c"],
        "classes":   query("SELECT COUNT(*) as c FROM classes")[0]["c"],
        "notes":     query("SELECT COUNT(*) as c FROM notes")[0]["c"],
    }
    all_data = []
    for c in classes:
        etudiants = query("""SELECT u.nom,u.prenom,e.id as etudiant_id,e.matricule
                             FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
                             WHERE e.classe_id=%s ORDER BY u.nom""", [c["id"]])
        class_data = []
        for e in etudiants:
            class_data.append({"etudiant": e, "bulletin": calc_bulletin(e["etudiant_id"])})
        all_data.append({"classe": c, "etudiants": class_data})
    return render_template("admin/rapport_general.html", user=get_user(),
                           all_data=all_data, profs=profs, stats=stats)


@app.route("/admin/rapport/prof/<int:prof_id>")
@role_required("admin")
def admin_rapport_prof(prof_id):
    rows = query("""SELECT p.*,u.nom,u.prenom,u.email,u.telephone,
                           d.nom as dept_nom,d.code as dept_code
                    FROM professeurs p JOIN utilisateurs u ON u.id=p.user_id
                    LEFT JOIN departements d ON d.id=p.departement_id WHERE p.id=%s""", [prof_id])
    prof = rows[0] if rows else {}
    prof["matieres"] = query("""SELECT m.*,c.nom as classe_nom FROM matieres m
        JOIN prof_matieres pm ON pm.matiere_id=m.id LEFT JOIN classes c ON c.id=m.classe_id
        WHERE pm.prof_id=%s ORDER BY m.semestre,m.nom""", [prof_id])
    edt = query("""SELECT e.*,m.nom as matiere_nom,c.nom as classe_nom
        FROM emploi_du_temps e JOIN matieres m ON m.id=e.matiere_id JOIN classes c ON c.id=e.classe_id
        WHERE e.prof_id=%s ORDER BY e.semestre,e.jour,e.heure_debut""", [prof_id])
    for r in edt:
        r["heure_debut"] = str(r["heure_debut"]) if r.get("heure_debut") else None
        r["heure_fin"] = str(r["heure_fin"]) if r.get("heure_fin") else None
    prof["emploi_du_temps"] = edt
    return render_template("admin/rapport_prof.html", user=get_user(), prof=prof)


# ══════════════════════════════════════════════════
# PROFESSEUR
# ══════════════════════════════════════════════════
@app.route("/prof")
@role_required("prof")
def prof_home():
    u = session["user"]
    pid = u.get("prof", {}).get("id") if u.get("prof") else None
    matieres = query("""SELECT m.*,c.nom as classe_nom,c.id as classe_id FROM matieres m
        JOIN prof_matieres pm ON pm.matiere_id=m.id LEFT JOIN classes c ON c.id=m.classe_id
        WHERE pm.prof_id=%s ORDER BY m.semestre,m.nom""", [pid]) if pid else []
    classe_ids = list(set(m["classe_id"] for m in matieres if m.get("classe_id")))
    classes = query("SELECT * FROM classes WHERE id=ANY(%s::int[]) ORDER BY nom", [classe_ids]) if classe_ids else []
    return render_template("prof/home.html", user=get_user(), matieres=matieres, classes=classes)


@app.route("/prof/rapport/classe/<int:classe_id>")
@role_required("prof")
def prof_rapport_classe(classe_id):
    u = session["user"]
    pid = u.get("prof", {}).get("id") if u.get("prof") else None
    matieres_prof = query("""SELECT DISTINCT classe_id FROM prof_matieres pm
        JOIN matieres m ON m.id=pm.matiere_id WHERE pm.prof_id=%s""", [pid]) if pid else []
    ses_classes = [m["classe_id"] for m in matieres_prof]
    if classe_id not in ses_classes:
        return "Acces refuse", 403
    classes = query("SELECT c.*,f.nom as filiere_nom,n.nom as niveau_nom FROM classes c LEFT JOIN filieres f ON f.id=c.filiere_id LEFT JOIN niveaux n ON n.id=c.niveau_id WHERE c.id=%s", [classe_id])
    classe = classes[0] if classes else {}
    etudiants = query("""SELECT u.nom,u.prenom,e.id as etudiant_id,e.matricule
                         FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
                         WHERE e.classe_id=%s ORDER BY u.nom""", [classe_id])
    matieres_of_prof = query("""SELECT m.id FROM matieres m JOIN prof_matieres pm ON pm.matiere_id=m.id
                                WHERE pm.prof_id=%s AND m.classe_id=%s""", [pid, classe_id])
    mat_ids = [m["id"] for m in matieres_of_prof]
    data = []
    for e in etudiants:
        eid = e["etudiant_id"]
        notes = query("""SELECT n.*,m.nom as matiere_nom,m.code,m.credits,m.coefficient
                         FROM notes n JOIN matieres m ON m.id=n.matiere_id
                         WHERE n.etudiant_id=%s AND n.matiere_id=ANY(%s::int[]) ORDER BY m.nom""",
                      [eid, mat_ids]) if mat_ids else []
        absences = query("""SELECT a.*,m.nom as matiere_nom FROM absences a JOIN matieres m ON m.id=a.matiere_id
                            WHERE a.etudiant_id=%s AND a.matiere_id=ANY(%s::int[]) ORDER BY a.date_absence DESC""",
                         [eid, mat_ids]) if mat_ids else []
        for r in absences:
            if r.get("date_absence"): r["date_absence"] = str(r["date_absence"])
        bulletin = calc_bulletin(eid)
        data.append({"etudiant": e, "notes": notes, "absences": absences, "bulletin": bulletin})
    matieres_noms = query("""SELECT m.* FROM matieres m JOIN prof_matieres pm ON pm.matiere_id=m.id
                             WHERE pm.prof_id=%s AND m.classe_id=%s ORDER BY m.nom""", [pid, classe_id])
    return render_template("prof/rapport_classe.html", user=get_user(),
                           classe=classe, data=data, matieres_prof=matieres_noms)


@app.route("/prof/edt")
@role_required("prof")
def prof_edt_pdf():
    u = session["user"]
    pid = u.get("prof", {}).get("id") if u.get("prof") else None
    semestre = request.args.get("semestre", "1")
    jours = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi"]
    edt_list = query("""SELECT e.*,m.nom as matiere_nom,c.nom as classe_nom
        FROM emploi_du_temps e JOIN matieres m ON m.id=e.matiere_id JOIN classes c ON c.id=e.classe_id
        WHERE e.prof_id=%s AND e.semestre=%s ORDER BY e.jour,e.heure_debut""",
        [pid, semestre]) if pid else []
    for r in edt_list:
        r["heure_debut"] = str(r["heure_debut"]) if r.get("heure_debut") else None
        r["heure_fin"] = str(r["heure_fin"]) if r.get("heure_fin") else None
    edt = {}
    for r in edt_list:
        j = r["jour"]
        if j not in edt: edt[j] = []
        edt[j].append(r)
    rows = query("""SELECT p.*,d.nom as dept_nom FROM professeurs p
                    LEFT JOIN departements d ON d.id=p.departement_id WHERE p.id=%s""", [pid]) if pid else []
    prof = rows[0] if rows else {}
    return render_template("prof/edt.html", user=get_user(), prof=prof, edt=edt, jours=jours, semestre=semestre)


# ══════════════════════════════════════════════════
# ETUDIANT
# ══════════════════════════════════════════════════
@app.route("/etudiant")
@role_required("etudiant")
def etudiant_home():
    u = session["user"]
    etu = u.get("etudiant", {})
    eid = etu.get("etudiant_id") if etu else None
    bulletin = calc_bulletin(eid) if eid else {}
    return render_template("etudiant/home.html", user=get_user(), etu=etu or {}, bulletin=bulletin)


@app.route("/etudiant/bulletin/<int:semestre>")
@role_required("etudiant")
def etudiant_bulletin(semestre):
    u = session["user"]
    etu = u.get("etudiant", {})
    eid = etu.get("etudiant_id") if etu else None
    if not eid: return "Erreur", 400
    notes = query("""SELECT n.*,m.nom as matiere_nom,m.code as matiere_code,m.credits,m.coefficient
                     FROM notes n JOIN matieres m ON m.id=n.matiere_id
                     WHERE n.etudiant_id=%s AND n.semestre=%s ORDER BY m.nom""", [eid, semestre])
    for r in notes:
        if r.get("date_saisie"): r["date_saisie"] = str(r["date_saisie"])
    absences = query("""SELECT a.*,m.nom as matiere_nom FROM absences a JOIN matieres m ON m.id=a.matiere_id
                        WHERE a.etudiant_id=%s ORDER BY a.date_absence DESC""", [eid])
    for r in absences:
        if r.get("date_absence"): r["date_absence"] = str(r["date_absence"])
    bulletin = calc_bulletin(eid)
    classe_id = etu.get("classe_id")
    edt_list = query("""SELECT e.*,m.nom as matiere_nom,u.nom as prof_nom,u.prenom as prof_prenom
        FROM emploi_du_temps e JOIN matieres m ON m.id=e.matiere_id
        LEFT JOIN professeurs p ON p.id=e.prof_id LEFT JOIN utilisateurs u ON u.id=p.user_id
        WHERE e.classe_id=%s AND e.semestre=%s ORDER BY e.jour,e.heure_debut""",
        [classe_id, semestre]) if classe_id else []
    for r in edt_list:
        r["heure_debut"] = str(r["heure_debut"]) if r.get("heure_debut") else None
        r["heure_fin"] = str(r["heure_fin"]) if r.get("heure_fin") else None
    jours = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi"]
    edt = {}
    for r in edt_list:
        j = r["jour"]
        if j not in edt: edt[j] = []
        edt[j].append(r)
    return render_template("etudiant/bulletin.html", user=get_user(),
                           etu=etu, notes=notes, absences=absences,
                           bulletin=bulletin, semestre=semestre, edt=edt, jours=jours)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    wait_for_db()
    init_db()
    print("[Files] Demarrage port 8082")
    app.run(host="0.0.0.0", port=8082, debug=False)
