"""
API REST pour accéder à legislatie.just.ro
Version corrigée - utilise requests au lieu de zeep pour éviter les problèmes de namespace
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
import re
from datetime import datetime, timedelta
import threading
import requests

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legislatie_api")

# App
app = Flask(__name__)
CORS(app)

# Configuration
SOAP_URL = os.environ.get("SOAP_URL", "https://legislatie.just.ro/apiws/FreeWebService.svc/SOAP")
TOKEN_LIFETIME = int(os.environ.get("TOKEN_LIFETIME", "3600"))
DEBUG = os.environ.get("DEBUG", "False").lower() in ("1", "true", "yes")

# Token cache
_token_cache = {"token": None, "expires_at": None}
_token_lock = threading.Lock()


def get_cached_token():
    """Obtient un token (avec cache)"""
    token = _token_cache.get("token")
    expires_at = _token_cache.get("expires_at")
    
    if token and expires_at and expires_at > datetime.utcnow():
        logger.debug("Token depuis le cache")
        return token, True
    
    with _token_lock:
        token = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at")
        
        if token and expires_at and expires_at > datetime.utcnow():
            return token, True
        
        # Obtenir nouveau token
        try:
            headers = {
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
            }
            body = '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><GetToken xmlns="http://tempuri.org/" /></soap:Body></soap:Envelope>'
            
            response = requests.post(SOAP_URL, headers=headers, data=body, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"Erreur SOAP GetToken: {response.status_code}")
            
            # Extraire le token
            match = re.search(r'<GetTokenResult>([^<]+)</GetTokenResult>', response.text)
            if not match:
                raise Exception("Token non trouvé dans la réponse")
            
            token = match.group(1).strip()
            _token_cache["token"] = token
            _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=TOKEN_LIFETIME)
            
            logger.info("Nouveau token obtenu")
            return token, False
            
        except Exception as e:
            logger.error(f"Erreur get token: {e}")
            raise


def extract_tag(xml, tag):
    """Extrait le contenu d'une balise XML"""
    pattern = rf'<a:{tag}>(.*?)</a:{tag}>'
    match = re.search(pattern, xml, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def format_lege_from_xml(xml_content):
    """Formate un document légal depuis le XML"""
    link = extract_tag(xml_content, 'LinkHtml')
    
    return {
        "id": link.split('/')[-1] if link else "",
        "title": extract_tag(xml_content, 'Titlu'),
        "number": extract_tag(xml_content, 'Numar'),
        "type": extract_tag(xml_content, 'TipAct'),
        "issuer": extract_tag(xml_content, 'Emitent'),
        "effective_date": extract_tag(xml_content, 'DataVigoare'),
        "publication": extract_tag(xml_content, 'Publicatie'),
        "text_preview": extract_tag(xml_content, 'Text')[:500],
        "text_full": extract_tag(xml_content, 'Text'),
        "url": link
    }


@app.route("/", methods=["GET"])
def index():
    """Documentation"""
    return jsonify({
        "service": "Legislatie.just.ro API Proxy",
        "version": "3.0",
        "description": "Proxy REST pour le service SOAP legislatie.just.ro",
        "endpoints": {
            "GET /health": "Vérifier l'état du service",
            "GET /token": "Obtenir un token (mis en cache)",
            "GET /search": "Rechercher dans la législation"
        },
        "search_params": {
            "title": "Titre de la loi (ex: Codul civil)",
            "year": "Année (ex: 2009)",
            "number": "Numéro",
            "text": "Texte à rechercher",
            "page": "Numéro de page (défaut: 0)",
            "per_page": "Résultats par page (défaut: 10, max: 100)"
        },
        "example": {
            "search_civil_code": "/search?title=Codul civil&per_page=5",
            "search_by_year": "/search?year=2009"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    try:
        token, _ = get_cached_token()
        return jsonify({
            "status": "healthy",
            "soap_url": SOAP_URL,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route("/token", methods=["GET"])
def token_endpoint():
    """Endpoint pour obtenir le token"""
    try:
        token, cached = get_cached_token()
        return jsonify({
            "success": True,
            "token": token,
            "cached": cached
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/search", methods=["GET"])
def search():
    """Recherche dans la législation"""
    try:
        token, _ = get_cached_token()
        
        page = int(request.args.get("page", 0))
        per_page = min(int(request.args.get("per_page", 10)), 100)
        
        # Construire le XML de recherche
        search_params = f"<a:NumarPagina>{page}</a:NumarPagina><a:RezultatePagina>{per_page}</a:RezultatePagina>"
        
        if request.args.get("title"):
            search_params += f"<a:SearchTitlu>{request.args.get('title')}</a:SearchTitlu>"
        if request.args.get("year"):
            search_params += f"<a:SearchAn>{request.args.get('year')}</a:SearchAn>"
        if request.args.get("number"):
            search_params += f"<a:SearchNumar>{request.args.get('number')}</a:SearchNumar>"
        if request.args.get("text"):
            search_params += f"<a:SearchText>{request.args.get('text')}</a:SearchText>"
        
        # Corps SOAP
        body = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <Search xmlns="http://tempuri.org/">
      <SearchModel xmlns:a="http://schemas.datacontract.org/2004/07/FreeWebService">
        {search_params}
      </SearchModel>
      <tokenKey>{token}</tokenKey>
    </Search>
  </soap:Body>
</soap:Envelope>'''
        
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
        }
        
        logger.info(f"Recherche: title={request.args.get('title')}, page={page}")
        
        response = requests.post(SOAP_URL, headers=headers, data=body, timeout=180)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Erreur SOAP Search: {response.status_code}"
            }), 500
        
        # Parser les résultats
        results = []
        pattern = r'<a:Legi>(.*?)</a:Legi>'
        matches = re.findall(pattern, response.text, re.DOTALL)
        
        for match in matches:
            results.append(format_lege_from_xml(match))
        
        return jsonify({
            "success": True,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "query": {
                "title": request.args.get("title"),
                "year": request.args.get("year"),
                "number": request.args.get("number"),
                "text": request.args.get("text")
            },
            "results": results
        })
        
    except Exception as e:
        logger.exception("Erreur /search")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/codes", methods=["GET"])
def get_main_codes():
    """Codes juridiques principaux"""
    base_codes = [
        {"name": "Codul civil", "year": 2009},
        {"name": "Codul penal", "year": 2009},
        {"name": "Codul de procedură civilă", "year": 2010},
        {"name": "Codul de procedură penală", "year": 2010},
        {"name": "Codul muncii", "year": 2003},
        {"name": "Codul fiscal", "year": 2015},
    ]
    
    try:
        token, _ = get_cached_token()
        results = []
        
        for code in base_codes:
            try:
                body = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <Search xmlns="http://tempuri.org/">
      <SearchModel xmlns:a="http://schemas.datacontract.org/2004/07/FreeWebService">
        <a:NumarPagina>0</a:NumarPagina>
        <a:RezultatePagina>1</a:RezultatePagina>
        <a:SearchTitlu>{code['name']}</a:SearchTitlu>
        <a:SearchAn>{code['year']}</a:SearchAn>
      </SearchModel>
      <tokenKey>{token}</tokenKey>
    </Search>
  </soap:Body>
</soap:Envelope>'''
                
                headers = {
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
                }
                
                response = requests.post(SOAP_URL, headers=headers, data=body, timeout=180)
                
                if response.status_code == 200:
                    pattern = r'<a:Legi>(.*?)</a:Legi>'
                    matches = re.findall(pattern, response.text, re.DOTALL)
                    
                    if matches:
                        results.append({
                            "code_name": code["name"],
                            "details": format_lege_from_xml(matches[0])
                        })
            except Exception as e:
                logger.warning(f"Erreur pour {code['name']}: {e}")
        
        return jsonify({
            "success": True,
            "total": len(results),
            "codes": results
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/document/<doc_id>", methods=["GET"])
def get_document(doc_id):
    """Lien vers un document"""
    return jsonify({
        "success": True,
        "url": f"https://legislatie.just.ro/Public/DetaliiDocument/{doc_id}"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
