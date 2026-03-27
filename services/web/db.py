import psycopg2
import os
import time

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
    return [dict(zip(cols, r)) for r in rows]


def execute(sql, params=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    conn.commit()
    lid = None
    try:
        lid = cur.fetchone()[0]
    except Exception:
        pass
    cur.close()
    conn.close()
    return lid


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        -- Departements
        CREATE TABLE IF NOT EXISTS departements (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(100) NOT NULL,
            code VARCHAR(20) UNIQUE NOT NULL,
            description TEXT
        );

        -- Filieres
        CREATE TABLE IF NOT EXISTS filieres (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(100) NOT NULL,
            code VARCHAR(20) UNIQUE NOT NULL,
            departement_id INTEGER REFERENCES departements(id) ON DELETE SET NULL
        );

        -- Niveaux
        CREATE TABLE IF NOT EXISTS niveaux (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(20) UNIQUE NOT NULL
        );

        -- Classes
        CREATE TABLE IF NOT EXISTS classes (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(60) UNIQUE NOT NULL,
            niveau_id INTEGER REFERENCES niveaux(id),
            filiere_id INTEGER REFERENCES filieres(id)
        );

        -- Utilisateurs (admin, prof, etudiant)
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id SERIAL PRIMARY KEY,
            username VARCHAR(60) UNIQUE NOT NULL,
            password VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL CHECK (role IN ('admin','prof','etudiant')),
            nom VARCHAR(100),
            prenom VARCHAR(100),
            email VARCHAR(150) UNIQUE,
            telephone VARCHAR(20),
            created_at TIMESTAMP DEFAULT NOW(),
            must_change_password BOOLEAN DEFAULT FALSE
        );

        -- Professeurs
        CREATE TABLE IF NOT EXISTS professeurs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES utilisateurs(id) ON DELETE CASCADE,
            departement_id INTEGER REFERENCES departements(id),
            grade VARCHAR(50),
            specialite VARCHAR(100)
        );

        -- Etudiants
        CREATE TABLE IF NOT EXISTS etudiants (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES utilisateurs(id) ON DELETE CASCADE,
            matricule VARCHAR(30) UNIQUE NOT NULL,
            classe_id INTEGER REFERENCES classes(id),
            annee_inscription INTEGER DEFAULT 2025
        );

        -- Matieres
        CREATE TABLE IF NOT EXISTS matieres (
            id SERIAL PRIMARY KEY,
            nom VARCHAR(100) NOT NULL,
            code VARCHAR(20) UNIQUE NOT NULL,
            credits INTEGER DEFAULT 3,
            coefficient FLOAT DEFAULT 1,
            classe_id INTEGER REFERENCES classes(id),
            semestre INTEGER DEFAULT 1 CHECK (semestre IN (1,2))
        );

        -- Affectation prof -> matiere -> classe
        CREATE TABLE IF NOT EXISTS prof_matieres (
            id SERIAL PRIMARY KEY,
            prof_id INTEGER REFERENCES professeurs(id) ON DELETE CASCADE,
            matiere_id INTEGER REFERENCES matieres(id) ON DELETE CASCADE,
            UNIQUE(prof_id, matiere_id)
        );

        -- Notes (devoir 40% + examen 60%)
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            etudiant_id INTEGER REFERENCES etudiants(id) ON DELETE CASCADE,
            matiere_id INTEGER REFERENCES matieres(id) ON DELETE CASCADE,
            semestre INTEGER NOT NULL CHECK (semestre IN (1,2)),
            note_devoir FLOAT CHECK (note_devoir >= 0 AND note_devoir <= 20),
            note_examen FLOAT CHECK (note_examen >= 0 AND note_examen <= 20),
            note_finale FLOAT GENERATED ALWAYS AS
                (ROUND((COALESCE(note_devoir,0)*0.4 + COALESCE(note_examen,0)*0.6)::numeric, 2)) STORED,
            saisie_par INTEGER REFERENCES professeurs(id),
            date_saisie TIMESTAMP DEFAULT NOW(),
            UNIQUE(etudiant_id, matiere_id, semestre)
        );

        -- Absences
        CREATE TABLE IF NOT EXISTS absences (
            id SERIAL PRIMARY KEY,
            etudiant_id INTEGER REFERENCES etudiants(id) ON DELETE CASCADE,
            matiere_id INTEGER REFERENCES matieres(id) ON DELETE CASCADE,
            date_absence DATE DEFAULT CURRENT_DATE,
            justifiee BOOLEAN DEFAULT FALSE,
            motif TEXT,
            saisie_par INTEGER REFERENCES professeurs(id)
        );

        -- Emploi du temps
        CREATE TABLE IF NOT EXISTS emploi_du_temps (
            id SERIAL PRIMARY KEY,
            classe_id INTEGER REFERENCES classes(id) ON DELETE CASCADE,
            matiere_id INTEGER REFERENCES matieres(id) ON DELETE CASCADE,
            prof_id INTEGER REFERENCES professeurs(id),
            jour VARCHAR(20) NOT NULL,
            heure_debut TIME NOT NULL,
            heure_fin TIME NOT NULL,
            salle VARCHAR(30),
            semestre INTEGER DEFAULT 1 CHECK (semestre IN (1,2))
        );

        -- Monitoring services
        CREATE TABLE IF NOT EXISTS services (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) UNIQUE,
            ip VARCHAR(50),
            vlan INTEGER
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id SERIAL PRIMARY KEY,
            service_id INTEGER REFERENCES services(id),
            status VARCHAR(10),
            latency_ms FLOAT,
            http_code INTEGER,
            checked_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Donnees initiales
    cur.execute("SELECT COUNT(*) FROM departements")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO departements (nom, code, description) VALUES
            ('Reseaux et Systemes', 'RS', 'Departement reseaux informatiques et systemes'),
            ('Gestion', 'GES', 'Departement gestion et administration'),
            ('IA et Big Data', 'IABD', 'Departement intelligence artificielle et big data')
        """)

    cur.execute("SELECT COUNT(*) FROM niveaux")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO niveaux (nom) VALUES
            ('L1'),('L2'),('L3'),('M1'),('M2')
        """)

    cur.execute("SELECT COUNT(*) FROM filieres")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO filieres (nom, code, departement_id)
            SELECT 'Reseaux et Informatique', 'RI', id FROM departements WHERE code='RS';
            INSERT INTO filieres (nom, code, departement_id)
            SELECT 'Systemes Embarques', 'SE', id FROM departements WHERE code='RS';
            INSERT INTO filieres (nom, code, departement_id)
            SELECT 'Gestion des Entreprises', 'GE', id FROM departements WHERE code='GES';
            INSERT INTO filieres (nom, code, departement_id)
            SELECT 'Intelligence Artificielle', 'IA', id FROM departements WHERE code='IABD';
            INSERT INTO filieres (nom, code, departement_id)
            SELECT 'Big Data et Analyse', 'BDA', id FROM departements WHERE code='IABD';
        """)

    cur.execute("SELECT COUNT(*) FROM classes")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO classes (nom, niveau_id, filiere_id)
            SELECT 'L3 RI', n.id, f.id FROM niveaux n, filieres f
            WHERE n.nom='L3' AND f.code='RI';
            INSERT INTO classes (nom, niveau_id, filiere_id)
            SELECT 'L2 RI', n.id, f.id FROM niveaux n, filieres f
            WHERE n.nom='L2' AND f.code='RI';
            INSERT INTO classes (nom, niveau_id, filiere_id)
            SELECT 'M1 IA', n.id, f.id FROM niveaux n, filieres f
            WHERE n.nom='M1' AND f.code='IA';
        """)

    cur.execute("SELECT COUNT(*) FROM utilisateurs")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO utilisateurs (username, password, role, nom, prenom, email)
            VALUES
            ('admin', 'admin123', 'admin', 'Administrateur', 'ISI', 'admin@isi.sn'),
            ('prof1', 'prof123', 'prof', 'Diallo', 'Mamadou', 'mdiallo@isi.sn'),
            ('etudiant1', 'etudiant123', 'etudiant', 'Ndiaye', 'Fatou', 'fndiaye@isi.sn')
        """)
        # Creer prof
        cur.execute("""
            INSERT INTO professeurs (user_id, departement_id, grade, specialite)
            SELECT u.id, d.id, 'Maitre de conferences', 'Reseaux et securite'
            FROM utilisateurs u, departements d
            WHERE u.username='prof1' AND d.code='RS'
        """)
        # Creer etudiant
        cur.execute("""
            INSERT INTO etudiants (user_id, matricule, classe_id)
            SELECT u.id, 'ISI-L3RI-2025-0001', c.id
            FROM utilisateurs u, classes c
            WHERE u.username='etudiant1' AND c.nom='L3 RI'
        """)

    cur.execute("SELECT COUNT(*) FROM matieres")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Reseaux Avances', 'RES601', 6, 3, c.id, 1 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Securite Informatique', 'SEC601', 4, 2, c.id, 1 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Programmation Systeme', 'SYS601', 4, 2, c.id, 1 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Base de Donnees', 'BDD601', 4, 2, c.id, 1 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Mathematiques Discretes', 'MATH601', 3, 1, c.id, 1 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Projet Reseau', 'PROJ601', 6, 3, c.id, 1 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Administration Systeme', 'ADM602', 6, 3, c.id, 2 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Virtualisation', 'VIRT602', 4, 2, c.id, 2 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Cloud Computing', 'CLOUD602', 4, 2, c.id, 2 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Gestion de Projet', 'GP602', 3, 1, c.id, 2 FROM classes c WHERE c.nom='L3 RI';
            INSERT INTO matieres (nom, code, credits, coefficient, classe_id, semestre)
            SELECT 'Stage Professionnel', 'STAGE602', 10, 4, c.id, 2 FROM classes c WHERE c.nom='L3 RI';
        """)
        # Affecter le prof aux matieres
        cur.execute("""
            INSERT INTO prof_matieres (prof_id, matiere_id)
            SELECT p.id, m.id FROM professeurs p, matieres m
            WHERE p.id=1 AND m.code IN ('RES601','SEC601','ADM602')
        """)

    cur.execute("SELECT COUNT(*) FROM emploi_du_temps")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO emploi_du_temps (classe_id, matiere_id, prof_id, jour, heure_debut, heure_fin, salle, semestre)
            SELECT c.id, m.id, pm.prof_id, 'Lundi', '08:00', '10:00', 'Salle A1', 1
            FROM classes c, matieres m, prof_matieres pm
            WHERE c.nom='L3 RI' AND m.code='RES601' AND pm.matiere_id=m.id AND pm.prof_id=1;
            INSERT INTO emploi_du_temps (classe_id, matiere_id, prof_id, jour, heure_debut, heure_fin, salle, semestre)
            SELECT c.id, m.id, pm.prof_id, 'Mercredi', '10:00', '12:00', 'Labo Reseaux', 1
            FROM classes c, matieres m, prof_matieres pm
            WHERE c.nom='L3 RI' AND m.code='SEC601' AND pm.matiere_id=m.id AND pm.prof_id=1;
            INSERT INTO emploi_du_temps (classe_id, matiere_id, prof_id, jour, heure_debut, heure_fin, salle, semestre)
            SELECT c.id, m.id, pm.prof_id, 'Vendredi', '14:00', '16:00', 'Salle B2', 2
            FROM classes c, matieres m, prof_matieres pm
            WHERE c.nom='L3 RI' AND m.code='ADM602' AND pm.matiere_id=m.id AND pm.prof_id=1;
        """)

    conn.commit()
    cur.close()
    conn.close()
    print("[DB] Schema et donnees initialises")


def wait_for_db():
    while True:
        try:
            conn = get_db()
            conn.close()
            print("[DB] Connexion OK")
            return
        except Exception as e:
            print(f"[DB] Attente... {e}")
            time.sleep(3)

import random, string
from datetime import datetime as _dt

def gen_matricule(niveau, filiere_code):
    year = _dt.now().year
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"ISI-{niveau}{filiere_code}-{year}-{suffix}"
