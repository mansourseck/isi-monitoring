from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from db import query, execute, init_db, wait_for_db, gen_matricule
import os, time
from functools import wraps

app = Flask(__name__)
app.secret_key = "isi-web-secret-2025"


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
                return render_template("shared/403.html"), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def get_user():
    return session.get("user", {})


# ── Auth ─────────────────────────────────────────────
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    role = session["user"]["role"]
    if role == "admin": return redirect(url_for("admin_dashboard"))
    elif role == "prof": return redirect(url_for("prof_dashboard"))
    else: return redirect(url_for("etudiant_dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        rows = query("SELECT * FROM utilisateurs WHERE username=%s AND password=%s",
                     [request.form["username"], request.form["password"]])
        if rows:
            u = rows[0]
            u["created_at"] = str(u["created_at"]) if u.get("created_at") else None
            if u["role"] == "prof":
                p = query("SELECT * FROM professeurs WHERE user_id=%s", [u["id"]])
                if p: u["prof"] = p[0]
            elif u["role"] == "etudiant":
                e = query("""
                    SELECT e.*, c.nom as classe_nom, c.id as classe_id,
                           f.nom as filiere_nom, f.code as filiere_code,
                           n.nom as niveau_nom, d.nom as dept_nom
                    FROM etudiants e
                    LEFT JOIN classes c ON c.id=e.classe_id
                    LEFT JOIN filieres f ON f.id=c.filiere_id
                    LEFT JOIN niveaux n ON n.id=c.niveau_id
                    LEFT JOIN departements d ON d.id=f.departement_id
                    WHERE e.user_id=%s
                """, [u["id"]])
                if e: u["etudiant"] = e[0]
            session["user"] = u
            if u.get("must_change_password"):
                return redirect(url_for("change_password"))
            return redirect(url_for("index"))
        flash("Identifiants incorrects", "danger")
    return render_template("shared/login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        uid = session["user"]["id"]
        rows = query("SELECT id FROM utilisateurs WHERE id=%s AND password=%s",
                     [uid, request.form["old_password"]])
        if rows:
            execute("UPDATE utilisateurs SET password=%s, must_change_password=FALSE WHERE id=%s",
                    [request.form["new_password"], uid])
            session["user"]["must_change_password"] = False
            flash("Mot de passe modifie", "success")
            return redirect(url_for("index"))
        flash("Ancien mot de passe incorrect", "danger")
    return render_template("shared/change_password.html", user=get_user())


# ══════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════
@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    stats = {
        "etudiants":    query("SELECT COUNT(*) as c FROM etudiants")[0]["c"],
        "profs":        query("SELECT COUNT(*) as c FROM professeurs")[0]["c"],
        "classes":      query("SELECT COUNT(*) as c FROM classes")[0]["c"],
        "matieres":     query("SELECT COUNT(*) as c FROM matieres")[0]["c"],
        "absences":     query("SELECT COUNT(*) as c FROM absences")[0]["c"],
        "departements": query("SELECT COUNT(*) as c FROM departements")[0]["c"],
    }
    return render_template("admin/dashboard.html", user=get_user(), stats=stats)


@app.route("/admin/departements")
@role_required("admin")
def admin_departements():
    depts = query("SELECT * FROM departements ORDER BY nom")
    return render_template("admin/departements.html", user=get_user(), depts=depts)


@app.route("/admin/departements/ajouter", methods=["POST"])
@role_required("admin")
def admin_add_dept():
    try:
        execute("INSERT INTO departements (nom,code,description) VALUES (%s,%s,%s)",
                [request.form["nom"], request.form["code"].upper(), request.form.get("description","")])
        flash("Departement cree", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_departements"))


@app.route("/admin/departements/<int:did>/supprimer")
@role_required("admin")
def admin_del_dept(did):
    execute("DELETE FROM departements WHERE id=%s", [did])
    flash("Departement supprime", "success")
    return redirect(url_for("admin_departements"))


@app.route("/admin/filieres")
@role_required("admin")
def admin_filieres():
    filieres = query("SELECT f.*,d.nom as dept_nom FROM filieres f LEFT JOIN departements d ON d.id=f.departement_id ORDER BY f.nom")
    depts = query("SELECT * FROM departements ORDER BY nom")
    return render_template("admin/filieres.html", user=get_user(), filieres=filieres, depts=depts)


@app.route("/admin/filieres/ajouter", methods=["POST"])
@role_required("admin")
def admin_add_filiere():
    try:
        execute("INSERT INTO filieres (nom,code,departement_id) VALUES (%s,%s,%s)",
                [request.form["nom"], request.form["code"].upper(), request.form.get("departement_id") or None])
        flash("Filiere creee", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_filieres"))


@app.route("/admin/filieres/<int:fid>/supprimer")
@role_required("admin")
def admin_del_filiere(fid):
    execute("DELETE FROM filieres WHERE id=%s", [fid])
    flash("Filiere supprimee", "success")
    return redirect(url_for("admin_filieres"))


@app.route("/admin/classes")
@role_required("admin")
def admin_classes():
    classes = query("""
        SELECT c.*,n.nom as niveau_nom,f.nom as filiere_nom,f.code as filiere_code,
               d.nom as dept_nom, COUNT(e.id) as nb_etudiants
        FROM classes c
        LEFT JOIN niveaux n ON n.id=c.niveau_id
        LEFT JOIN filieres f ON f.id=c.filiere_id
        LEFT JOIN departements d ON d.id=f.departement_id
        LEFT JOIN etudiants e ON e.classe_id=c.id
        GROUP BY c.id,n.nom,f.nom,f.code,d.nom ORDER BY c.nom
    """)
    niveaux = query("SELECT * FROM niveaux ORDER BY nom")
    filieres = query("SELECT * FROM filieres ORDER BY nom")
    return render_template("admin/classes.html", user=get_user(),
                           classes=classes, niveaux=niveaux, filieres=filieres)


@app.route("/admin/classes/ajouter", methods=["POST"])
@role_required("admin")
def admin_add_classe():
    niv = query("SELECT nom FROM niveaux WHERE id=%s", [request.form.get("niveau_id")])
    fil = query("SELECT code FROM filieres WHERE id=%s", [request.form.get("filiere_id")])
    nom = request.form.get("nom_custom","").strip() or (f"{niv[0]['nom']} {fil[0]['code']}" if niv and fil else "Nouvelle classe")
    try:
        execute("INSERT INTO classes (nom,niveau_id,filiere_id) VALUES (%s,%s,%s)",
                [nom, request.form.get("niveau_id"), request.form.get("filiere_id")])
        flash(f"Classe {nom} creee", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_classes"))


@app.route("/admin/matieres")
@role_required("admin")
def admin_matieres():
    classe_id = request.args.get("classe_id","")
    sql = "SELECT m.*,c.nom as classe_nom FROM matieres m LEFT JOIN classes c ON c.id=m.classe_id WHERE 1=1"
    params = []
    if classe_id:
        sql += " AND m.classe_id=%s"; params.append(classe_id)
    sql += " ORDER BY m.semestre,m.nom"
    matieres = query(sql, params)
    classes = query("SELECT * FROM classes ORDER BY nom")
    return render_template("admin/matieres.html", user=get_user(),
                           matieres=matieres, classes=classes, classe_id=classe_id)


@app.route("/admin/matieres/ajouter", methods=["POST"])
@role_required("admin")
def admin_add_matiere():
    try:
        execute("INSERT INTO matieres (nom,code,credits,coefficient,classe_id,semestre) VALUES (%s,%s,%s,%s,%s,%s)",
                [request.form["nom"], request.form["code"].upper(),
                 int(request.form.get("credits",3)), float(request.form.get("coefficient",1)),
                 request.form.get("classe_id"), int(request.form.get("semestre",1))])
        flash("Matiere creee", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_matieres"))


@app.route("/admin/matieres/<int:mid>/supprimer")
@role_required("admin")
def admin_del_matiere(mid):
    execute("DELETE FROM matieres WHERE id=%s", [mid])
    flash("Matiere supprimee", "success")
    return redirect(url_for("admin_matieres"))


@app.route("/admin/profs")
@role_required("admin")
def admin_profs():
    dept_id = request.args.get("dept_id","")
    sql = """SELECT u.id as user_id,u.nom,u.prenom,u.email,u.telephone,u.username,
                    p.id as prof_id,p.grade,p.specialite,
                    d.nom as dept_nom,d.code as dept_code,d.id as dept_id
             FROM utilisateurs u JOIN professeurs p ON p.user_id=u.id
             LEFT JOIN departements d ON d.id=p.departement_id
             WHERE u.role='prof'"""
    params = []
    if dept_id:
        sql += " AND p.departement_id=%s"; params.append(dept_id)
    sql += " ORDER BY u.nom"
    profs = query(sql, params)
    depts = query("SELECT * FROM departements ORDER BY nom")
    return render_template("admin/profs.html", user=get_user(),
                           profs=profs, depts=depts, dept_id=dept_id)


@app.route("/admin/profs/ajouter", methods=["GET","POST"])
@role_required("admin")
def admin_add_prof():
    if request.method == "POST":
        try:
            uid = execute("""INSERT INTO utilisateurs (username,password,role,nom,prenom,email,telephone,must_change_password)
                             VALUES (%s,%s,'prof',%s,%s,%s,%s,TRUE) RETURNING id""",
                          [request.form["username"], request.form.get("password","prof123"),
                           request.form["nom"], request.form["prenom"],
                           request.form.get("email",""), request.form.get("telephone","")])
            pid = execute("""INSERT INTO professeurs (user_id,departement_id,grade,specialite)
                             VALUES (%s,%s,%s,%s) RETURNING id""",
                          [uid, request.form.get("departement_id") or None,
                           request.form.get("grade",""), request.form.get("specialite","")])
            for mid in request.form.getlist("matiere_ids"):
                execute("INSERT INTO prof_matieres (prof_id,matiere_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        [pid, int(mid)])
            flash("Professeur cree avec succes", "success")
            return redirect(url_for("admin_profs"))
        except Exception as e:
            flash(str(e), "danger")
    depts = query("SELECT * FROM departements ORDER BY nom")
    matieres = query("SELECT m.*,c.nom as classe_nom FROM matieres m LEFT JOIN classes c ON c.id=m.classe_id ORDER BY m.semestre,m.nom")
    return render_template("admin/add_prof.html", user=get_user(), depts=depts, matieres=matieres)


@app.route("/admin/profs/<int:prof_id>")
@role_required("admin")
def admin_view_prof(prof_id):
    rows = query("""SELECT u.*,p.id as prof_id,p.grade,p.specialite,
                           d.nom as dept_nom,d.code as dept_code,d.id as dept_id
                    FROM utilisateurs u JOIN professeurs p ON p.user_id=u.id
                    LEFT JOIN departements d ON d.id=p.departement_id WHERE p.id=%s""", [prof_id])
    if not rows:
        flash("Professeur non trouve","danger"); return redirect(url_for("admin_profs"))
    prof = rows[0]
    prof["created_at"] = str(prof["created_at"]) if prof.get("created_at") else None
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
    depts = query("SELECT * FROM departements ORDER BY nom")
    matieres = query("SELECT m.*,c.nom as classe_nom FROM matieres m LEFT JOIN classes c ON c.id=m.classe_id ORDER BY m.semestre,m.nom")
    return render_template("admin/view_prof.html", user=get_user(), prof=prof, depts=depts, matieres=matieres)


@app.route("/admin/profs/<int:prof_id>/modifier", methods=["POST"])
@role_required("admin")
def admin_edit_prof(prof_id):
    rows = query("SELECT user_id FROM professeurs WHERE id=%s", [prof_id])
    if rows:
        execute("UPDATE utilisateurs SET nom=%s,prenom=%s,email=%s,telephone=%s WHERE id=%s",
                [request.form["nom"],request.form["prenom"],request.form.get("email",""),request.form.get("telephone",""),rows[0]["user_id"]])
        execute("UPDATE professeurs SET departement_id=%s,grade=%s,specialite=%s WHERE id=%s",
                [request.form.get("departement_id") or None, request.form.get("grade",""), request.form.get("specialite",""), prof_id])
        execute("DELETE FROM prof_matieres WHERE prof_id=%s", [prof_id])
        for mid in request.form.getlist("matiere_ids"):
            execute("INSERT INTO prof_matieres (prof_id,matiere_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", [prof_id, int(mid)])
        flash("Professeur modifie","success")
    return redirect(url_for("admin_view_prof", prof_id=prof_id))


@app.route("/admin/profs/<int:prof_id>/supprimer")
@role_required("admin")
def admin_del_prof(prof_id):
    rows = query("SELECT user_id FROM professeurs WHERE id=%s",[prof_id])
    if rows: execute("DELETE FROM utilisateurs WHERE id=%s",[rows[0]["user_id"]])
    flash("Professeur supprime","success")
    return redirect(url_for("admin_profs"))


@app.route("/admin/etudiants")
@role_required("admin")
def admin_etudiants():
    classe_id = request.args.get("classe_id","")
    search = request.args.get("search","")
    sql = """SELECT u.id as user_id,u.nom,u.prenom,u.email,u.username,
                    e.id as etudiant_id,e.matricule,c.nom as classe_nom,
                    f.code as filiere_code,n.nom as niveau_nom
             FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
             LEFT JOIN classes c ON c.id=e.classe_id
             LEFT JOIN filieres f ON f.id=c.filiere_id
             LEFT JOIN niveaux n ON n.id=c.niveau_id
             WHERE u.role='etudiant'"""
    params = []
    if classe_id: sql += " AND e.classe_id=%s"; params.append(classe_id)
    if search:
        sql += " AND (u.nom ILIKE %s OR u.prenom ILIKE %s OR e.matricule ILIKE %s)"
        params += [f"%{search}%"]*3
    sql += " ORDER BY u.nom"
    etudiants = query(sql, params)
    classes = query("SELECT * FROM classes ORDER BY nom")
    return render_template("admin/etudiants.html", user=get_user(),
                           etudiants=etudiants, classes=classes, classe_id=classe_id, search=search)


@app.route("/admin/etudiants/ajouter", methods=["POST"])
@role_required("admin")
def admin_add_etudiant():
    try:
        cid = request.form.get("classe_id")
        cl = query("""SELECT c.*,n.nom as nnom,f.code as fcode FROM classes c
                      JOIN niveaux n ON n.id=c.niveau_id JOIN filieres f ON f.id=c.filiere_id
                      WHERE c.id=%s""", [cid]) if cid else []
        mat = gen_matricule(cl[0]["nnom"].replace(" ","") if cl else "L3", cl[0]["fcode"] if cl else "RI")
        uid = execute("""INSERT INTO utilisateurs (username,password,role,nom,prenom,email,telephone,must_change_password)
                         VALUES (%s,%s,'etudiant',%s,%s,%s,%s,TRUE) RETURNING id""",
                      [request.form["username"],"etudiant123",request.form["nom"],
                       request.form["prenom"],request.form.get("email",""),request.form.get("telephone","")])
        execute("INSERT INTO etudiants (user_id,matricule,classe_id) VALUES (%s,%s,%s)", [uid, mat, cid])
        flash(f"Etudiant cree — Matricule: {mat}", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("admin_etudiants"))


@app.route("/admin/etudiants/<int:eid>/supprimer")
@role_required("admin")
def admin_del_etudiant(eid):
    rows = query("SELECT user_id FROM etudiants WHERE id=%s",[eid])
    if rows: execute("DELETE FROM utilisateurs WHERE id=%s",[rows[0]["user_id"]])
    flash("Etudiant supprime","success")
    return redirect(url_for("admin_etudiants"))


@app.route("/admin/absences")
@role_required("admin")
def admin_absences():
    classe_id = request.args.get("classe_id","")
    sql = """SELECT a.*,u.nom,u.prenom,e.matricule,m.nom as matiere_nom,c.nom as classe_nom
             FROM absences a JOIN etudiants e ON e.id=a.etudiant_id
             JOIN utilisateurs u ON u.id=e.user_id JOIN matieres m ON m.id=a.matiere_id
             JOIN classes c ON c.id=e.classe_id WHERE 1=1"""
    params = []
    if classe_id: sql += " AND e.classe_id=%s"; params.append(classe_id)
    sql += " ORDER BY a.date_absence DESC"
    absences = query(sql, params)
    for r in absences:
        if r.get("date_absence"): r["date_absence"] = str(r["date_absence"])
    classes = query("SELECT * FROM classes ORDER BY nom")
    return render_template("admin/absences.html", user=get_user(),
                           absences=absences, classes=classes, classe_id=classe_id)


@app.route("/admin/absences/<int:aid>/modifier", methods=["POST"])
@role_required("admin")
def admin_edit_absence(aid):
    execute("UPDATE absences SET justifiee=%s,motif=%s WHERE id=%s",
            [request.form.get("justifiee")=="on", request.form.get("motif",""), aid])
    flash("Absence modifiee","success")
    return redirect(url_for("admin_absences"))


@app.route("/admin/absences/<int:aid>/supprimer")
@role_required("admin")
def admin_del_absence(aid):
    execute("DELETE FROM absences WHERE id=%s",[aid])
    flash("Absence supprimee","success")
    return redirect(url_for("admin_absences"))


@app.route("/admin/edt")
@role_required("admin")
def admin_edt():
    classe_id = request.args.get("classe_id","")
    semestre = request.args.get("semestre","1")
    jours = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi"]
    classes = query("SELECT * FROM classes ORDER BY nom")
    if not classe_id and classes: classe_id = str(classes[0]["id"])
    sql = """SELECT e.*,m.nom as matiere_nom,c.nom as classe_nom,u.nom as prof_nom,u.prenom as prof_prenom
             FROM emploi_du_temps e JOIN matieres m ON m.id=e.matiere_id JOIN classes c ON c.id=e.classe_id
             LEFT JOIN professeurs p ON p.id=e.prof_id LEFT JOIN utilisateurs u ON u.id=p.user_id
             WHERE 1=1"""
    params = []
    if classe_id: sql += " AND e.classe_id=%s"; params.append(classe_id)
    if semestre: sql += " AND e.semestre=%s"; params.append(semestre)
    sql += " ORDER BY e.jour,e.heure_debut"
    edt_list = query(sql, params)
    for r in edt_list:
        r["heure_debut"] = str(r["heure_debut"]) if r.get("heure_debut") else None
        r["heure_fin"] = str(r["heure_fin"]) if r.get("heure_fin") else None
    edt = {}
    for r in edt_list:
        j = r["jour"]
        if j not in edt: edt[j] = []
        edt[j].append(r)
    matieres = query("SELECT * FROM matieres WHERE classe_id=%s ORDER BY nom", [classe_id]) if classe_id else []
    profs = query("SELECT p.id as prof_id,u.nom,u.prenom FROM professeurs p JOIN utilisateurs u ON u.id=p.user_id ORDER BY u.nom")
    return render_template("admin/edt.html", user=get_user(),
                           classes=classes, classe_id=classe_id, semestre=semestre,
                           edt=edt, jours=jours, matieres=matieres, profs=profs)


@app.route("/admin/edt/ajouter", methods=["POST"])
@role_required("admin")
def admin_add_edt():
    execute("""INSERT INTO emploi_du_temps (classe_id,matiere_id,prof_id,jour,heure_debut,heure_fin,salle,semestre)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            [request.form["classe_id"], request.form["matiere_id"],
             request.form.get("prof_id") or None, request.form["jour"],
             request.form["heure_debut"], request.form["heure_fin"],
             request.form.get("salle",""), int(request.form.get("semestre",1))])
    flash("Creneau ajoute","success")
    return redirect(url_for("admin_edt", classe_id=request.form["classe_id"], semestre=request.form.get("semestre",1)))


@app.route("/admin/edt/<int:eid>/supprimer")
@role_required("admin")
def admin_del_edt(eid):
    execute("DELETE FROM emploi_du_temps WHERE id=%s",[eid])
    return redirect(url_for("admin_edt"))


# ══════════════════════════════════════════════════
# PROFESSEUR
# ══════════════════════════════════════════════════
def get_prof_id():
    u = session.get("user",{})
    p = u.get("prof",{})
    return p.get("id") if p else None


@app.route("/prof")
@role_required("prof")
def prof_dashboard():
    pid = get_prof_id()
    matieres = query("""SELECT m.*,c.nom as classe_nom FROM matieres m
        JOIN prof_matieres pm ON pm.matiere_id=m.id LEFT JOIN classes c ON c.id=m.classe_id
        WHERE pm.prof_id=%s ORDER BY m.semestre,m.nom""", [pid]) if pid else []
    edt = query("""SELECT e.*,m.nom as matiere_nom,c.nom as classe_nom
        FROM emploi_du_temps e JOIN matieres m ON m.id=e.matiere_id JOIN classes c ON c.id=e.classe_id
        WHERE e.prof_id=%s ORDER BY e.jour""", [pid]) if pid else []
    for r in edt:
        r["heure_debut"] = str(r["heure_debut"]) if r.get("heure_debut") else None
        r["heure_fin"] = str(r["heure_fin"]) if r.get("heure_fin") else None
    prof = {"matieres": matieres, "emploi_du_temps": edt}
    return render_template("prof/dashboard.html", user=get_user(), prof=prof)


@app.route("/prof/profil")
@role_required("prof")
def prof_profil():
    pid = get_prof_id()
    rows = query("""SELECT p.*,d.nom as dept_nom,d.code as dept_code FROM professeurs p
                    LEFT JOIN departements d ON d.id=p.departement_id WHERE p.id=%s""", [pid]) if pid else []
    prof = rows[0] if rows else {}
    return render_template("prof/profil.html", user=get_user(), prof=prof)


@app.route("/prof/mes-classes")
@role_required("prof")
def prof_classes():
    pid = get_prof_id()
    matieres = query("""SELECT m.*,c.nom as classe_nom,c.id as classe_id FROM matieres m
        JOIN prof_matieres pm ON pm.matiere_id=m.id LEFT JOIN classes c ON c.id=m.classe_id
        WHERE pm.prof_id=%s ORDER BY m.semestre,m.nom""", [pid]) if pid else []
    classes_map = {}
    for m in matieres:
        c = m.get("classe_nom","")
        if c not in classes_map: classes_map[c] = []
        classes_map[c].append(m)
    return render_template("prof/classes.html", user=get_user(), classes_map=classes_map)


@app.route("/prof/etudiants")
@role_required("prof")
def prof_etudiants():
    pid = get_prof_id()
    matieres = query("SELECT DISTINCT classe_id FROM prof_matieres pm JOIN matieres m ON m.id=pm.matiere_id WHERE pm.prof_id=%s", [pid]) if pid else []
    all_e = []
    for m in matieres:
        if m.get("classe_id"):
            ets = query("""SELECT u.id as user_id,u.nom,u.prenom,u.email,e.id as etudiant_id,
                                  e.matricule,c.nom as classe_nom,f.code as filiere_code
                           FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
                           LEFT JOIN classes c ON c.id=e.classe_id LEFT JOIN filieres f ON f.id=c.filiere_id
                           WHERE e.classe_id=%s ORDER BY u.nom""", [m["classe_id"]])
            all_e.extend(ets)
    return render_template("prof/etudiants.html", user=get_user(), etudiants=all_e)


@app.route("/prof/notes", methods=["GET","POST"])
@role_required("prof")
def prof_notes():
    pid = get_prof_id()
    if request.method == "POST":
        try:
            execute("""INSERT INTO notes (etudiant_id,matiere_id,semestre,note_devoir,note_examen,saisie_par)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (etudiant_id,matiere_id,semestre)
                       DO UPDATE SET note_devoir=EXCLUDED.note_devoir,note_examen=EXCLUDED.note_examen,saisie_par=EXCLUDED.saisie_par,date_saisie=NOW()""",
                    [int(request.form["etudiant_id"]), int(request.form["matiere_id"]),
                     int(request.form["semestre"]),
                     float(request.form["note_devoir"]) if request.form.get("note_devoir") else None,
                     float(request.form["note_examen"]) if request.form.get("note_examen") else None,
                     pid])
            flash("Note enregistree","success")
        except Exception as e:
            flash(str(e),"danger")
        return redirect(url_for("prof_notes"))
    classe_id = request.args.get("classe_id","")
    semestre = request.args.get("semestre","1")
    matieres_prof = query("""SELECT m.*,c.nom as classe_nom,c.id as classe_id FROM matieres m
        JOIN prof_matieres pm ON pm.matiere_id=m.id LEFT JOIN classes c ON c.id=m.classe_id
        WHERE pm.prof_id=%s ORDER BY m.semestre,m.nom""", [pid]) if pid else []
    classe_ids = list(set(m["classe_id"] for m in matieres_prof if m.get("classe_id")))
    etudiants = []
    for cid in classe_ids:
        ets = query("""SELECT u.nom,u.prenom,e.id as etudiant_id,e.matricule,c.nom as classe_nom
                       FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
                       LEFT JOIN classes c ON c.id=e.classe_id WHERE e.classe_id=%s ORDER BY u.nom""", [cid])
        etudiants.extend(ets)
    sql = """SELECT n.*,m.nom as matiere_nom,m.code as matiere_code,m.credits,m.coefficient,
                    u.nom as etudiant_nom,u.prenom as etudiant_prenom,e.matricule,c.nom as classe_nom
             FROM notes n JOIN matieres m ON m.id=n.matiere_id
             JOIN etudiants e ON e.id=n.etudiant_id JOIN utilisateurs u ON u.id=e.user_id
             JOIN classes c ON c.id=e.classe_id WHERE n.saisie_par=%s AND n.semestre=%s"""
    params = [pid, semestre]
    if classe_id: sql += " AND e.classe_id=%s"; params.append(classe_id)
    sql += " ORDER BY u.nom,m.nom"
    notes = query(sql, params) if pid else []
    for r in notes:
        if r.get("date_saisie"): r["date_saisie"] = str(r["date_saisie"])
    classes_du_prof = [{"id":cid} for cid in classe_ids]
    classes_info = query("SELECT * FROM classes WHERE id=ANY(%s::int[])", [classe_ids]) if classe_ids else []
    return render_template("prof/notes.html", user=get_user(),
                           matieres=matieres_prof, etudiants=etudiants, notes=notes,
                           classes=classes_info, classe_id=classe_id, semestre=semestre)


@app.route("/prof/absences", methods=["GET","POST"])
@role_required("prof")
def prof_absences():
    pid = get_prof_id()
    if request.method == "POST":
        try:
            execute("INSERT INTO absences (etudiant_id,matiere_id,justifiee,motif,saisie_par) VALUES (%s,%s,%s,%s,%s)",
                    [int(request.form["etudiant_id"]), int(request.form["matiere_id"]),
                     request.form.get("justifiee")=="on", request.form.get("motif",""), pid])
            flash("Absence enregistree","success")
        except Exception as e:
            flash(str(e),"danger")
        return redirect(url_for("prof_absences"))
    matieres_prof = query("""SELECT m.*,c.nom as classe_nom FROM matieres m
        JOIN prof_matieres pm ON pm.matiere_id=m.id LEFT JOIN classes c ON c.id=m.classe_id
        WHERE pm.prof_id=%s""", [pid]) if pid else []
    classe_ids = list(set(m["classe_id"] for m in matieres_prof if m.get("classe_id")))
    etudiants = []
    for cid in classe_ids:
        ets = query("""SELECT u.nom,u.prenom,e.id as etudiant_id,e.matricule,c.nom as classe_nom
                       FROM utilisateurs u JOIN etudiants e ON e.user_id=u.id
                       LEFT JOIN classes c ON c.id=e.classe_id WHERE e.classe_id=%s ORDER BY u.nom""", [cid])
        etudiants.extend(ets)
    absences = query("""SELECT a.*,u.nom,u.prenom,m.nom as matiere_nom
        FROM absences a JOIN etudiants e ON e.id=a.etudiant_id
        JOIN utilisateurs u ON u.id=e.user_id JOIN matieres m ON m.id=a.matiere_id
        WHERE a.saisie_par=%s ORDER BY a.date_absence DESC""", [pid]) if pid else []
    for r in absences:
        if r.get("date_absence"): r["date_absence"] = str(r["date_absence"])
    return render_template("prof/absences.html", user=get_user(),
                           matieres=matieres_prof, etudiants=etudiants, absences=absences)


@app.route("/prof/edt")
@role_required("prof")
def prof_edt():
    pid = get_prof_id()
    semestre = request.args.get("semestre","1")
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
    return render_template("prof/edt.html", user=get_user(), edt=edt, jours=jours, semestre=semestre)


# ══════════════════════════════════════════════════
# ETUDIANT
# ══════════════════════════════════════════════════
def get_etudiant_id():
    u = session.get("user",{})
    e = u.get("etudiant",{})
    return e.get("etudiant_id") if e else None


def calc_bulletin(eid):
    result = {}
    for s in [1,2]:
        notes = query("""SELECT n.note_finale,m.credits,m.coefficient
                         FROM notes n JOIN matieres m ON m.id=n.matiere_id
                         WHERE n.etudiant_id=%s AND n.semestre=%s""", [eid, s])
        if notes:
            total = sum((r["note_finale"] or 0)*r["coefficient"] for r in notes)
            coeff = sum(r["coefficient"] for r in notes if r.get("note_finale"))
            cred = sum(r["credits"] for r in notes if r.get("note_finale") and r["note_finale"] >= 10)
            moy = round(total/coeff,2) if coeff else 0
            result[f"s{s}"] = {"moyenne": moy, "credits_valides": cred, "valide": moy>=10 and cred>=60}
    return result


@app.route("/etudiant")
@role_required("etudiant")
def etudiant_dashboard():
    eid = get_etudiant_id()
    notes_s1 = query("""SELECT n.*,m.nom as matiere_nom FROM notes n JOIN matieres m ON m.id=n.matiere_id
                        WHERE n.etudiant_id=%s AND n.semestre=1""", [eid]) if eid else []
    notes_s2 = query("""SELECT n.*,m.nom as matiere_nom FROM notes n JOIN matieres m ON m.id=n.matiere_id
                        WHERE n.etudiant_id=%s AND n.semestre=2""", [eid]) if eid else []
    absences = query("""SELECT a.*,m.nom as matiere_nom FROM absences a JOIN matieres m ON m.id=a.matiere_id
                        WHERE a.etudiant_id=%s ORDER BY a.date_absence DESC""", [eid]) if eid else []
    for r in absences:
        if r.get("date_absence"): r["date_absence"] = str(r["date_absence"])
    bulletin = calc_bulletin(eid) if eid else {}
    return render_template("etudiant/dashboard.html", user=get_user(),
                           notes_s1=notes_s1, notes_s2=notes_s2, absences=absences, bulletin=bulletin)


@app.route("/etudiant/profil")
@role_required("etudiant")
def etudiant_profil():
    return render_template("etudiant/profil.html", user=get_user())


@app.route("/etudiant/notes")
@role_required("etudiant")
def etudiant_notes():
    eid = get_etudiant_id()
    semestre = request.args.get("semestre","1")
    notes = query("""SELECT n.*,m.nom as matiere_nom,m.code as matiere_code,m.credits,m.coefficient
                     FROM notes n JOIN matieres m ON m.id=n.matiere_id
                     WHERE n.etudiant_id=%s AND n.semestre=%s ORDER BY m.nom""",
                  [eid, semestre]) if eid else []
    for r in notes:
        if r.get("date_saisie"): r["date_saisie"] = str(r["date_saisie"])
    bulletin = calc_bulletin(eid) if eid else {}
    return render_template("etudiant/notes.html", user=get_user(),
                           notes=notes, semestre=semestre, bulletin=bulletin)


@app.route("/etudiant/absences")
@role_required("etudiant")
def etudiant_absences():
    eid = get_etudiant_id()
    absences = query("""SELECT a.*,m.nom as matiere_nom FROM absences a JOIN matieres m ON m.id=a.matiere_id
                        WHERE a.etudiant_id=%s ORDER BY a.date_absence DESC""", [eid]) if eid else []
    for r in absences:
        if r.get("date_absence"): r["date_absence"] = str(r["date_absence"])
    return render_template("etudiant/absences.html", user=get_user(), absences=absences)


@app.route("/etudiant/edt")
@role_required("etudiant")
def etudiant_edt():
    u = session.get("user",{})
    e = u.get("etudiant",{})
    classe_id = e.get("classe_id") if e else None
    semestre = request.args.get("semestre","1")
    jours = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi"]
    edt_list = query("""SELECT e.*,m.nom as matiere_nom,u.nom as prof_nom,u.prenom as prof_prenom
        FROM emploi_du_temps e JOIN matieres m ON m.id=e.matiere_id
        LEFT JOIN professeurs p ON p.id=e.prof_id LEFT JOIN utilisateurs u ON u.id=p.user_id
        WHERE e.classe_id=%s AND e.semestre=%s ORDER BY e.jour,e.heure_debut""",
        [classe_id, semestre]) if classe_id else []
    for r in edt_list:
        r["heure_debut"] = str(r["heure_debut"]) if r.get("heure_debut") else None
        r["heure_fin"] = str(r["heure_fin"]) if r.get("heure_fin") else None
    edt = {}
    for r in edt_list:
        j = r["jour"]
        if j not in edt: edt[j] = []
        edt[j].append(r)
    return render_template("etudiant/edt.html", user=get_user(), edt=edt, jours=jours, semestre=semestre)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    wait_for_db()
    init_db()
    print("[Web] Demarrage port 8081")
    app.run(host="0.0.0.0", port=8081, debug=False)
