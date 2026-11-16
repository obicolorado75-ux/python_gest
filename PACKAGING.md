# PACKAGING.md — construction des applications Windows et macOS

Les paquets doivent être construits **et testés sur leur plateforme respective** :
un `.app`/`.dmg` fiable ne se produit que sur macOS, un installateur Windows sur
Windows (§4.1).

## Préparation commune

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
pytest                       # la suite doit être verte avant de construire
```

## Windows (`.exe` autonome, puis installateur)

Recommandation : **PyInstaller** en mode « one-dir » (démarrage plus rapide et
plus fiable que « one-file » avec Qt), complété par Inno Setup ou WiX.

```powershell
pip install pyinstaller
pyinstaller packaging\windows\gestdepot.spec --noconfirm
```

Puis :

1. testez `dist\GestDepot\GestDepot.exe` sur un poste **sans Python** ;
2. vérifiez l'écriture des données dans `%LOCALAPPDATA%\GestDepot\` ;
3. construisez l'installateur (Inno Setup) : raccourcis menu Démarrer et bureau,
   icône, licence, désinstallation **sans suppression des données** ;
4. signez le binaire si un certificat est disponible (réduit les alertes
   SmartScreen).

## macOS (`GestDepot.app`, puis `.dmg`)

```bash
pip install pyinstaller
pyinstaller packaging/macos/gestdepot.spec --noconfirm
codesign --deep --force --sign "Developer ID Application: …" dist/GestDepot.app
hdiutil create -volname "GestDepot" -srcfolder dist/GestDepot.app GestDepot.dmg
xcrun notarytool submit GestDepot.dmg --keychain-profile gestdepot --wait
```

Vérifications : données dans `~/Library/Application Support/GestDepot/`, lancement
hors ligne, impression A4 et ticket, mise à jour sans perte de données.

## Checklist de recette avant diffusion

- [ ] Lancement sans Internet, base créée automatiquement au premier démarrage.
- [ ] Assistant de premier lancement (dépôt + administrateur) fonctionnel.
- [ ] Vente, réception, dépense et clôture de caisse réalisées avec succès.
- [ ] Exports Excel et PDF concordent avec les données affichées.
- [ ] Ticket 80 mm généré et imprimable.
- [ ] Sauvegarde créée, vérifiée, puis restaurée avec succès.
- [ ] Mise à jour de version sans perte de données.
- [ ] Désinstallation : base et sauvegardes **conservées**.
- [ ] Icônes et numéro de version renseignés ; licence affichée si requise.

## Notes

- `pyside6-deploy` (Nuitka) est une alternative à PyInstaller : à valider par un
  prototype sur les deux plateformes.
- Ne jamais embarquer la base de démonstration dans le paquet de distribution.
- Conservez le dossier `packaging/` versionné pour reproduire les builds.
