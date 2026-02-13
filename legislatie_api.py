"""
API REST pour legislatie.just.ro
Version 4.1 - URL HTTPS corrigée - Support complet des filtres
Déploiement sur Render
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
import re
from datetime import datetime, timedelta
import threading
import requests

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legislatie_api")

app = Flask(__name__)
CORS(app)

# Configuration - URL HTTPS corrigée
SOAP_URL = os.environ.get("SOAP_URL", "https://legislatie.just.ro/apiws")
TOKEN_LIFETIME = int(os.environ.get("TOKEN_LIFETIME", "3600"))  # 1 heure par défaut

# Cache pour le token
_token_cache = {"token": None, "expires_at": None}
_token_lock = threading.Lock()

def get_new_token():
    """Obtient un nouveau token via GetToken"""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
    }
    
    # Construction de la requête SOAP GetToken
    body = '''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Header>
    <Action xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">
      http://tempuri.org/IFreeWebService/GetToken
    </Action>
  </soap:Header>
  <soap:Body>
    <GetToken xmlns="http://tempuri.org/" />
  </soap:Body>
</soap:Envelope>'''
    
    try:
        response = requests.post(SOAP_URL, headers=headers, data=body, timeout=30, verify=True)
        
        if response.status_code != 200:
            raise Exception(f"Erreur GetToken: {response.status_code}")
        
        # Extraction du token avec regex
        match = re.search(r'<GetTokenResult>([^<]+)</GetTokenResult>', response.text)
        if not match:
            raise Exception("Token non trouvé dans la réponse")
        
        token = match.group(1).strip()
        
        # Mise en cache
        with _token_lock:
            _token_cache["token"] = token
            _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=TOKEN_LIFETIME)
        
        logger.info(f"Nouveau token obtenu: {token[:20]}...")
        return token
        
    except Exception as e:
        logger.error(f"Erreur get_new_token: {str(e)}")
        raise

def get_cached_token():
    """Retourne le token en cache ou en obtient un nouveau"""
    with _token_lock:
        token = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at")
        
        if token and expires_at and expires_at > datetime.utcnow():
            return token, True
    
    token = get_new_token()
    return token, False

def build_search_xml(page, per_page, title=None, year=None, number=None, text=None):
    """Construit la requête SOAP Search selon la documentation"""
    
    # Paramètres obligatoires
    search_params = f"""
        <a:NumarPagina>{page}</a:NumarPagina>
        <a:RezultatePagina>{per_page}</a:RezultatePagina>
    """
    
    # Paramètres optionnels (avec i:nil="true" si non fournis)
    if title:
        search_params += f"<a:SearchTitlu>{title}</a:SearchTitlu>"
    else:
        search_params += '<a:SearchTitlu i:nil="true" xmlns:i="http://www.w3.org/2001/XMLSchema-instance" />'
    
    if year:
        search_params += f"<a:SearchAn>{year}</a:SearchAn>"
    else:
        search_params += '<a:SearchAn i:nil="true" xmlns:i="http://www.w3.org/2001/XMLSchema-instance" />'
    
    if number:
        search_params += f"<a:SearchNumar>{number}</a:SearchNumar>"
    else:
        search_params += '<a:SearchNumar i:nil="true" xmlns:i="http://www.w3.org/2001/XMLSchema-instance" />'
    
    if text:
        search_params += f"<a:SearchText>{text}</a:SearchText>"
    else:
        search_params += '<a:SearchText i:nil="true" xmlns:i="http://www.w3.org/2001/XMLSchema-instance" />'
    
    # Construction complète de l'enveloppe SOAP
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Header>
    <Action xmlns="http://schemas.microsoft.com/ws/2005/05/addressing/none">
      http://tempuri.org/IFreeWebService/Search
    </Action>
  </soap:Header>
  <soap:Body>
    <Search xmlns="http://tempuri.org/">
      <SearchModel xmlns:a="http://schemas.datacontract.org/2004/07/FreeWebService">
        {search_params}
      </SearchModel>
      <tokenKey>{{token}}</tokenKey>
    </Search>
  </soap:Body>
</soap:Envelope>'''
    
    return xml

def parse_lege(xml_content):
    """Extrait les informations d'un élément Legi"""
    
    def extract(tag):
        pattern = rf'<a:{tag}>(.*?)</a:{tag}>'
        match = re.search(pattern, xml_content, re.DOTALL)
        return match.group(1).strip() if match else ""
    
    # Extraction de l'ID depuis le lien HTML
    link = extract('LinkHtml')
    doc_id = ""
    if link:
        doc_id = link.split('/')[-1]
    
    return {
        "id": doc_id,
        "title": extract('Titlu'),
        "type": extract('TipAct'),
        "number": extract('Numar'),
        "issuer": extract('Emitent'),
        "effective_date": extract('DataVigoare'),
        "publication": extract('Publicatie'),
        "text": extract('Text'),
        "url": link
    }

def do_search(token, page, per_page, title=None, year=None, number=None, text=None):
    """Exécute une recherche SOAP avec les paramètres donnés"""
    
    # Construction de la requête XML
    xml_template = build_search_xml(page, per_page, title, year, number, text)
    xml_body = xml_template.replace('{{token}}', token)
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
    }
    
    # Log pour debug
    logger.info(f"📡 Envoi requête SOAP - Page: {page}, Title: {title}, Year: {year}, Text: {text}")
    
    try:
        response = requests.post(SOAP_URL, headers=headers, data=xml_body, timeout=60, verify=True)
        
        if response.status_code != 200:
            logger.error(f"❌ Erreur SOAP {response.status_code}")
            logger.debug(f"Réponse: {response.text[:500]}")
            raise Exception(f"Erreur SOAP: {response.status_code}")
        
        logger.info(f"✅ Réponse SOAP reçue: {len(response.text)} caractères")
        return response.text
        
    except requests.exceptions.SSLError as e:
        logger.error(f"❌ Erreur SSL: {str(e)}")
        raise Exception("Erreur de connexion SSL - Vérifier le certificat")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ Erreur de connexion: {str(e)}")
        raise Exception("Impossible de se connecter au service SOAP")
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {str(e)}")
        raise

@app.route("/")
def index():
    return jsonify({
        "name": "Legislatie.just.ro API Proxy",
        "version": "4.1",
        "description": "API REST pour le service SOAP de legislatie.just.ro",
        "endpoints": {
            "GET /health": "Vérification de l'état",
            "GET /token": "Obtenir un token (debug)",
            "GET /search": "Rechercher des actes"
        },
        "search_parameters": {
            "page": "Numéro de page (défaut: 0)",
            "per_page": "Résultats par page (défaut: 10, max: 100)",
            "title": "Recherche dans le titre",
            "text": "Recherche dans le texte",
            "year": "Année (ex: 2023)",
            "number": "Numéro de l'acte"
        },
        "example": "/search?title=procedura&year=2023&per_page=5"
    })

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "legislatie.just.ro proxy",
        "soap_url": SOAP_URL
    })

@app.route("/token")
def get_token_endpoint():
    """Endpoint pour obtenir un token (debug)"""
    try:
        token, cached = get_cached_token()
        return jsonify({
            "success": True,
            "token": token,
            "cached": cached,
            "expires_at": _token_cache.get("expires_at").isoformat() if _token_cache.get("expires_at") else None
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/search")
def search_endpoint():
    """Endpoint principal de recherche"""
    try:
        # Récupération des paramètres
        page = int(request.args.get("page", 0))
        per_page = min(int(request.args.get("per_page", 10)), 100)
        title = request.args.get("title")
        year = request.args.get("year")
        number = request.args.get("number")
        text = request.args.get("text")
        
        # Validation
        if page < 0:
            page = 0
        if per_page < 1:
            per_page = 10
        
        logger.info(f"🔍 Recherche: page={page}, per_page={per_page}, title={title}, year={year}, text={text[:50] if text else None}")
        
        # Obtention du token
        token, was_cached = get_cached_token()
        
        # Première tentative de recherche
        try:
            soap_response = do_search(token, page, per_page, title, year, number, text)
        except Exception as e:
            # Si erreur et token était en cache, réessayer avec nouveau token
            if was_cached:
                logger.warning("⚠️ Token expiré, régénération...")
                token = get_new_token()
                soap_response = do_search(token, page, per_page, title, year, number, text)
            else:
                raise
        
        # Extraction des résultats
        results = []
        legi_pattern = r'<a:Legi>(.*?)</a:Legi>'
        
        for match in re.finditer(legi_pattern, soap_response, re.DOTALL):
            lege_xml = match.group(1)
            try:
                lege = parse_lege(lege_xml)
                if lege["title"]:  # Ne garder que les entrées valides
                    results.append(lege)
            except Exception as e:
                logger.warning(f"⚠️ Erreur parsing d'un acte: {str(e)}")
                continue
        
        logger.info(f"✅ {len(results)} résultats trouvés")
        
        # Construction de la réponse
        response_data = {
            "success": True,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "query": {
                "title": title,
                "text": text,
                "year": year,
                "number": number
            },
            "results": results
        }
        
        # Ajouter un aperçu du texte pour chaque résultat
        for result in response_data["results"]:
            if result.get("text"):
                result["text_preview"] = result["text"][:500] + "..." if len(result["text"]) > 500 else result["text"]
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.exception("❌ Erreur dans /search")
        return jsonify({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({"success": False, "error": "Endpoint non trouvé"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"success": False, "error": "Erreur interne du serveur"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    
    logger.info(f"🚀 Démarrage de l'API sur le port {port}")
    logger.info(f"🔌 URL SOAP: {SOAP_URL}")
    app.run(host="0.0.0.0", port=port, debug=debug)
