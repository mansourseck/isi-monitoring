# ISI Monitor v2 — Systeme de gestion academique

## Architecture

| Service | URL | Role |
|---|---|---|
| API REST | http://localhost:8082 | Backend central partage |
| Portail Web | http://web.isi-monitor.local:8081 | Gestion (Admin/Prof/Etudiant) |
| Portail Fichiers | http://files.isi-monitor.local:8082 | Bulletins PDF (Admin/Prof/Etudiant) |
| Dashboard monitoring | http://localhost:5000 | Supervision temps reel |

## Demarrer dans WSL2

```bash
# 1. Copier et extraire
cp /mnt/c/Users/USER/Downloads/isi-monitor-v2.zip ~/
cd ~ && unzip isi-monitor-v2.zip && cd isi-monitor-v2

# 2. Lancer
docker-compose up --build

# 3. Ajouter les noms (PowerShell admin Windows)
Add-Content C:\Windows\System32\drivers\etc\hosts "127.0.0.1 web.isi-monitor.local"
Add-Content C:\Windows\System32\drivers\etc\hosts "127.0.0.1 files.isi-monitor.local"
```

## Comptes par defaut

| Username | Mot de passe | Role |
|---|---|---|
| admin | admin123 | Administrateur |
| prof1 | prof123 | Professeur |
| etudiant1 | etudiant123 | Etudiant |

## Fonctionnalites par role

### Admin
- Gerer departements, filieres, classes, niveaux, matieres
- Creer comptes profs (avec matieres, dept, grade, EDT)
- Creer comptes etudiants (matricule auto-genere)
- Voir et modifier absences de toutes les classes
- Rapports complets (par classe, par prof, general)

### Professeur
- Voir son profil, ses cours, son EDT
- Saisir notes (devoir 40% + examen 60%) par semestre
- Gerer absences de ses cours
- Telecharger rapport de ses classes + son EDT

### Etudiant
- Voir ses notes S1 et S2 avec moyennes et credits
- Voir ses absences
- Voir son EDT
- Telecharger son bulletin (avec notes, absences, EDT)
- Changer son mot de passe

## Notes
- Semestre valide si moyenne >= 10 ET credits valides >= 60
- Note finale = Devoir x 40% + Examen x 60%
- Matricule genere automatiquement (ex: ISI-L3RI-2025-0001)
