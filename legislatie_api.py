"""
API REST pour legislatie.just.ro
Version 4.2 - Correction GetToken (erreur 405)
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

# Configuration
SOAP_URL = os.environ.get("SOAP_URL", "https://legislatie.just.ro/apiws")
TOKEN_LIFETIME = int(os.environ.get("TOKEN_LIFETIME", "3600"))

_token_cache = {"token": None, "expires_at": None}
_token_lock = threading.Lock()

def get_new_token():
    """Obtient un nouveau token via GetToken - Version corrigée"""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
    }
    
    # Format simplifié sans le header Action (cause possible de l'erreur 405)
    body = '''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetToken xmlns="http://tempuri.org/" />
  </soap:Body>
</soap:Envelope>'''
    
    try:
        logger.info("📡 Envoi requête GetToken...")
        response = requests.post(
            SOAP_URL, 
            headers=headers, 
            data=body.encode('utf-8'),
            timeout=30, 
            verify=True
        )
        
        logger.info(f"📥 Statut: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Réponse: {response.text[:200]}")
            raise Exception(f"Erreur GetToken: {response.status_code}")
        
        # Extraction plus robuste du token
        token_match = re.search(r'<GetTokenResult[^>]*>(.*?)</GetTokenResult>', response.text, re.DOTALL)
        if not token_match:
            raise Exception("Token non trouvé dans la réponse")
        
        token = token_match.group(1).strip()
        
        with _token_lock:
            _token_cache["token"] = token
            _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=TOKEN_LIFETIME)
        
        logger.info(f"✅ Token obtenu: {token[:20]}...")
        return token
        
    except Exception as e:
        logger.error(f"❌ Erreur: {str(e)}")
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
    """Construit la requête SOAP Search"""
    
    search_params = f"""
        <a:NumarPagina>{page}</a:NumarPagina>
        <a:RezultatePagina>{per_page}</a:RezultatePagina>
    """
    
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
    
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
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
    
    link = extract('LinkHtml')
    doc_id = link.split('/')[-1] if link else ""
    
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
    """Exécute une recherche SOAP"""
    
    xml_template = build_search_xml(page, per_page, title, year, number, text)
    xml_body = xml_template.replace('{{token}}', token)
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
    }
    
    logger.info(f"📡 Recherche - Page: {page}, Title: {title}, Year: {year}")
    
    response = requests.post(
        SOAP_URL, 
        headers=headers, 
        data=xml_body.encode('utf-8'), 
        timeout=60, 
        verify=True
    )
    
    if response.status_code != 200:
        raise Exception(f"Erreur SOAP Search: {response.status_code}")
    
    return response.text

@app.route("/")
def index():
    return jsonify({
        "name": "Legislatie.just.ro API Proxy",
        "version": "4.2",
        "endpoints": {
            "GET /health": "Health check",
            "GET /token": "Get token",
            "GET /search": "Search"
        }
    })

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "soap_url": SOAP_URL
    })

@app.route("/token")
def token_endpoint():
    try:
        token, cached = get_cached_token()
        return jsonify({
            "success": True,
            "token": token,
            "cached": cached
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/search")
def search_endpoint():
    try:
        page = int(request.args.get("page", 0))
        per_page = min(int(request.args.get("per_page", 10)), 100)
        title = request.args.get("title")
        year = request.args.get("year")
        number = request.args.get("number")
        text = request.args.get("text")
        
        token, was_cached = get_cached_token()
        
        try:
            soap_response = do_search(token, page, per_page, title, year, number, text)
        except Exception as e:
            if was_cached:
                logger.warning("Token expiré, régénération...")
                token = get_new_token()
                soap_response = do_search(token, page, per_page, title, year, number, text)
            else:
                raise
        
        results = []
        legi_pattern = r'<a:Legi>(.*?)</a:Legi>'
        
        for match in re.finditer(legi_pattern, soap_response, re.DOTALL):
            try:
                lege = parse_lege(match.group(1))
                if lege["title"]:
                    results.append(lege)
            except:
                continue
        
        return jsonify({
            "success": True,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "results": results
        })
        
    except Exception as e:
        logger.exception("Erreur search")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
