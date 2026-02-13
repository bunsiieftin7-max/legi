"""
API REST pour legislatie.just.ro
Version 4.3 - Stable - Gestion token inchangée + Support complet des filtres
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
    """Obtient un nouveau token - Version stable (inchangée)"""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
    }
    
    # Body SIMPLE sans Header (comme dans la version qui fonctionnait)
    body = '<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><GetToken xmlns="http://tempuri.org/" /></soap:Body></soap:Envelope>'
    
    try:
        logger.info("📡 Envoi requête GetToken...")
        response = requests.post(SOAP_URL, headers=headers, data=body, timeout=30, verify=True)
        
        if response.status_code != 200:
            raise Exception(f"Erreur GetToken: {response.status_code}")
        
        # Regex simple comme avant
        match = re.search(r'<GetTokenResult>([^<]+)</GetTokenResult>', response.text)
        if not match:
            raise Exception("Token non trouvé")
        
        token = match.group(1).strip()
        
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


def invalidate_token():
    """Invalide le token en cache"""
    with _token_lock:
        _token_cache["token"] = None
        _token_cache["expires_at"] = None
    logger.info("Token invalidé")


def extract_tag(xml, tag):
    """Extrait un tag XML"""
    pattern = rf'<a:{tag}>(.*?)</a:{tag}>'
    match = re.search(pattern, xml, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def format_lege(xml_content):
    """Formate un élément Legi en JSON"""
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


def do_search(token, page, per_page, title=None, year=None, number=None, text=None, tip_act=None):
    """Effectue une recherche avec tous les filtres"""
    
    # Construction des paramètres de recherche
    search_params = f"<a:NumarPagina>{page}</a:NumarPagina><a:RezultatePagina>{per_page}</a:RezultatePagina>"
    
    if title:
        search_params += f"<a:SearchTitlu>{title}</a:SearchTitlu>"
    if year:
        search_params += f"<a:SearchAn>{year}</a:SearchAn>"
    if number:
        search_params += f"<a:SearchNumar>{number}</a:SearchNumar>"
    if text:
        search_params += f"<a:SearchText>{text}</a:SearchText>"
    if tip_act:
        search_params += f"<a:SearchTipAct>{tip_act}</a:SearchTipAct>"
    
    # Construction de la requête SOAP
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
    
    logger.info(f"🔍 Recherche: page={page}, title={title}, year={year}, tip_act={tip_act}")
    
    response = requests.post(SOAP_URL, headers=headers, data=body, timeout=180, verify=True)
    return response


@app.route("/")
def index():
    return jsonify({
        "service": "Legislatie.just.ro API Proxy",
        "version": "4.3 - Stable",
        "endpoints": {
            "GET /health": "Health check",
            "GET /token": "Get token",
            "GET /search": "Search legislation"
        },
        "filters_supported": ["title", "text", "year", "number", "tip_act", "page", "per_page"]
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
        return jsonify({"success": True, "token": token, "cached": cached})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/search")
def search():
    """Recherche avec support de tous les filtres"""
    try:
        # Récupération de tous les paramètres
        page = int(request.args.get("page", 0))
        per_page = min(int(request.args.get("per_page", 10)), 100)
        title = request.args.get("title")
        year = request.args.get("year")
        number = request.args.get("number")
        text = request.args.get("text")
        tip_act = request.args.get("tip_act")  # NOUVEAU: filtre par type d'acte
        
        logger.info(f"📥 Requête reçue: page={page}, title={title}, year={year}, tip_act={tip_act}")
        
        # Premier essai avec token en cache
        token, was_cached = get_cached_token()
        response = do_search(token, page, per_page, title, year, number, text, tip_act)
        
        # Si erreur 500 et token était en cache, réessayer avec nouveau token
        if response.status_code == 500 and was_cached:
            logger.warning("⚠️ Token expiré, régénération...")
            invalidate_token()
            token, _ = get_cached_token()
            response = do_search(token, page, per_page, title, year, number, text, tip_act)
        
        if response.status_code != 200:
            return jsonify({
                "success": False, 
                "error": f"Erreur SOAP Search: {response.status_code}"
            }), 500
        
        # Extraction des résultats
        results = []
        for match in re.findall(r'<a:Legi>(.*?)</a:Legi>', response.text, re.DOTALL):
            results.append(format_lege(match))
        
        logger.info(f"✅ {len(results)} résultats trouvés")
        
        return jsonify({
            "success": True,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "filters_applied": {
                "title": title,
                "text": text[:50] + "..." if text and len(text) > 50 else text,
                "year": year,
                "number": number,
                "tip_act": tip_act
            },
            "results": results
        })
        
    except Exception as e:
        logger.exception("❌ Erreur /search")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    
    logger.info(f"🚀 Démarrage API sur le port {port}")
    logger.info(f"🔌 URL SOAP: {SOAP_URL}")
    app.run(host="0.0.0.0", port=port, debug=debug)
