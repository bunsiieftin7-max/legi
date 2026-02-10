# API REST pour Legislatie.just.ro

API REST moderne pour accéder au service SOAP de legislatie.just.ro, compatible avec n8n et autres outils d'automatisation.

## 🚀 Fonctionnalités

- ✅ Conversion SOAP → REST
- ✅ Cache de tokens automatique
- ✅ Endpoints documentés
- ✅ Compatible n8n, Make, Zapier
- ✅ CORS activé
- ✅ Déployable en un clic

## 📋 Endpoints

### `GET /`
Documentation de l'API

### `GET /health`
Vérifier l'état du service

### `GET /token`
Obtenir un token (avec cache automatique)

**Réponse :**
```json
{
  "success": true,
  "token": "ABC123...",
  "cached": true
}
```

### `GET /search`
Rechercher dans la législation roumaine

**Paramètres (tous optionnels) :**
- `title` - Titre de la loi (ex: "Codul civil")
- `year` - Année (ex: 2009)
- `number` - Numéro (ex: 287)
- `text` - Recherche textuelle
- `page` - Numéro de page (défaut: 0)
- `per_page` - Résultats par page (défaut: 10, max: 100)

**Exemples :**
```bash
# Rechercher le Code civil
curl "https://votre-api.com/search?title=Codul civil"

# Rechercher les lois de 2009
curl "https://votre-api.com/search?year=2009&per_page=20"

# Recherche combinée
curl "https://votre-api.com/search?title=Codul penal&year=2009"
```

**Réponse :**
```json
{
  "success": true,
  "total": 10,
  "page": 0,
  "per_page": 10,
  "results": [
    {
      "id": "109884",
      "title": "LEGE nr. 287/2009 privind Codul civil",
      "number": "287",
      "year": 2009,
      "type": "LEGE",
      "issuer": "PARLAMENTUL",
      "effective_date": "2011-10-01",
      "publication": "Monitorul Oficial nr. 511 din 24 iulie 2009",
      "text_preview": "...",
      "text_full": "...",
      "url": "https://legislatie.just.ro/Public/DetaliiDocument/109884"
    }
  ]
}
```

### `GET /codes`
Obtenir les codes juridiques principaux (Civil, Pénal, Travail, etc.)

**Réponse :**
```json
{
  "success": true,
  "total": 7,
  "codes": [
    {
      "code_name": "Codul civil",
      "details": { ... }
    }
  ]
}
```

## 🛠️ Installation locale

```bash
# Cloner le repo
git clone <votre-repo>
cd <dossier>

# Installer les dépendances
pip install -r requirements.txt

# Lancer le serveur
python legislatie_api.py

# L'API sera disponible sur http://localhost:5000
```

## ☁️ Déploiement

### Option 1 : Render.com (Gratuit - Recommandé)

1. Créer un compte sur [render.com](https://render.com)
2. Nouveau → Web Service
3. Connecter votre repo GitHub
4. Configuration :
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `gunicorn legislatie_api:app`
   - **Environment** : Python 3
5. Déployer !

URL : `https://votre-service.onrender.com`

### Option 2 : Railway.app (Gratuit)

1. Compte sur [railway.app](https://railway.app)
2. New Project → Deploy from GitHub
3. Sélectionner votre repo
4. Railway détecte automatiquement Python
5. Déployer !

### Option 3 : Heroku

```bash
# Installer Heroku CLI
heroku login
heroku create votre-app-name
git push heroku main
```

### Option 4 : Hébergement PHP partagé

Si vous préférez PHP, utilisez le script PHP fourni dans le zip original.

## 🔌 Intégration n8n

### Workflow de base

```
[Webhook/Trigger]
    ↓
[HTTP Request: GET]
URL: https://votre-api.com/search?title={{$json.query}}
    ↓
[Process Results]
```

### Exemple concret - Recherche Code Civil

**Nœud HTTP Request :**
- Method: `GET`
- URL: `https://votre-api.onrender.com/search?title=Codul civil&per_page=5`

**Nœud Code (traiter les résultats) :**
```javascript
const results = items[0].json.results;

return results.map(law => ({
  json: {
    title: law.title,
    url: law.url,
    text: law.text_preview
  }
}));
```

## 📊 Exemples d'utilisation

### Professeur de droit autonome

**Workflow complet :**

```
[Webhook WordPress - Question étudiant]
    ↓
[Extract Keywords] - Identifier le domaine juridique
    ↓
[HTTP Request] - Chercher les textes pertinents
    URL: /search?title={{$json.code_name}}
    ↓
[OpenAI] - Générer réponse pédagogique avec contexte
    System: "Tu es professeur de droit roumain. Voici les textes : {{$json.results}}"
    User: {{$json.question}}
    ↓
[Supabase] - Sauvegarder l'échange
    ↓
[Return to WordPress]
```

### Script de synchronisation complète

```python
import requests

api_url = "https://votre-api.onrender.com"

# Obtenir tous les codes principaux
codes = requests.get(f"{api_url}/codes").json()

for code in codes['codes']:
    print(f"Téléchargement: {code['code_name']}")
    
    # Sauvegarder dans votre base de données
    # ...
```

## 🔒 Sécurité

Pour production :
- Ajouter authentification (API key)
- Rate limiting
- HTTPS obligatoire

## 📝 Licence

MIT

## 🤝 Contribution

Pull requests bienvenues !

## 📧 Support

Créer une issue sur GitHub
