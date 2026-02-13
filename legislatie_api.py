"""
API REST pour legislatie.just.ro
Version 8.0 - CORRECTION BUG OFFICIEL

BUG OFFICIEL CONFIRMÉ DE L'API legislatie.just.ro:
- SearchAn SEUL fonctionne ✅
- SearchTitlu SEUL fonctionne ✅
- SearchTitlu + SearchAn = SearchAn IGNORÉ ❌

SOLUTION: Filtrer côté serveur les résultats par année
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
import re
from datetime import datetime, timedelta
import threading
import requests
from xml.sax.saxutils import escape as xml_escape

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legislatie_api")

app = Flask(__name__)
CORS(app)

SOAP_URL = "https://legislatie.just.ro/apiws/FreeWebService.svc/SOAP"
TOKEN_LIFETIME = int(os.environ.get("TOKEN_LIFETIME", "3600"))

_token_cache = {"token": None, "expires_at": None}
_token_lock = threading.Lock()


def get_new_token():
    """Obtient un nouveau token"""
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/GetToken"
    }
    
    body = '<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><GetToken xmlns="http://tempuri.org/"/></soap:Body></soap:Envelope>'
    
    logger.info("🔑 Demande d'un nouveau token...")
    response = requests.post(SOAP_URL, headers=headers, data=body.encode('utf-8'), timeout=30)
    
    if response.status_code != 200:
        raise Exception(f"Erreur GetToken: {response.status_code}")
    
    match = re.search(r'<GetTokenResult>([^<]+)</GetTokenResult>', response.text)
    if not match:
        raise Exception("Token non trouvé")
    
    token = match.group(1).strip()
    
    with _token_lock:
        _token_cache["token"] = token
        _token_cache["expires_at"] = datetime.utcnow() + timedelta(seconds=TOKEN_LIFETIME)
    
    logger.info(f"✅ Token obtenu: {token[:25]}...")
    return token


def get_cached_token():
    """Token en cache ou nouveau"""
    with _token_lock:
        token = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at")
        
        if token and expires_at and expires_at > datetime.utcnow():
            return token, True
    
    return get_new_token(), False


def invalidate_token():
    """Invalide le cache"""
    with _token_lock:
        _token_cache["token"] = None
        _token_cache["expires_at"] = None
    logger.info("🗑️ Token invalidé")


def extract_tag(xml, tag):
    """Extrait le contenu d'un tag XML"""
    pattern = rf'<a:{tag}>(.*?)</a:{tag}>'
    match = re.search(pattern, xml, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    pattern = rf'<{tag}>(.*?)</{tag}>'
    match = re.search(pattern, xml, re.DOTALL)
    return match.group(1).strip() if match else ""


def format_lege(xml_content):
    """Formate un résultat Legi"""
    link = extract_tag(xml_content, 'LinkHtml')
    text = extract_tag(xml_content, 'Text')
    
    return {
        "id": link.split('/')[-1] if link else "",
        "title": extract_tag(xml_content, 'Titlu'),
        "number": extract_tag(xml_content, 'Numar'),
        "type": extract_tag(xml_content, 'TipAct'),
        "issuer": extract_tag(xml_content, 'Emitent'),
        "effective_date": extract_tag(xml_content, 'DataVigoare'),
        "publication": extract_tag(xml_content, 'Publicatie'),
        "text_preview": text[:500] if text else "",
        "text_full": text,
        "url": link
    }


def build_search_body(token, page, per_page, title=None, year=None, number=None, text=None):
    """
    Construit le body SOAP selon le WSDL officiel
    Seuls 4 filtres sont officiels: SearchAn, SearchNumar, SearchText, SearchTitlu
    """
    
    params = [
        f'<a:NumarPagina>{page}</a:NumarPagina>',
        f'<a:RezultatePagina>{per_page}</a:RezultatePagina>',
    ]
    
    # Filtres officiels selon WSDL
    if year:
        try:
            params.append(f'<a:SearchAn>{int(year)}</a:SearchAn>')
        except ValueError:
            params.append('<a:SearchAn i:nil="true" />')
    else:
        params.append('<a:SearchAn i:nil="true" />')
    
    if number:
        params.append(f'<a:SearchNumar>{xml_escape(str(number))}</a:SearchNumar>')
    else:
        params.append('<a:SearchNumar i:nil="true" />')
    
    if text:
        params.append(f'<a:SearchText>{xml_escape(str(text))}</a:SearchText>')
    else:
        params.append('<a:SearchText i:nil="true" />')
    
    if title:
        params.append(f'<a:SearchTitlu>{xml_escape(str(title))}</a:SearchTitlu>')
    else:
        params.append('<a:SearchTitlu i:nil="true" />')
    
    params_str = '\n        '.join(params)
    
    body = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <Search xmlns="http://tempuri.org/">
      <SearchModel xmlns:a="http://schemas.datacontract.org/2004/07/FreeWebService" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
        {params_str}
      </SearchModel>
      <tokenKey>{token}</tokenKey>
    </Search>
  </soap:Body>
</soap:Envelope>'''
    
    return body


def do_search(token, page, per_page, title=None, year=None, number=None, text=None):
    """Effectue la recherche SOAP"""
    
    body = build_search_body(token, page, per_page, title, year, number, text)
    
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/IFreeWebService/Search"
    }
    
    filters_used = {k: v for k, v in {
        'title': title, 'year': year, 'number': number, 'text': text
    }.items() if v}
    logger.info(f"🔍 Recherche: page={page}, per_page={per_page}, filters={filters_used}")
    
    response = requests.post(SOAP_URL, headers=headers, data=body.encode('utf-8'), timeout=180)
    
    logger.info(f"📡 Réponse: HTTP {response.status_code}")
    
    return response, body


@app.route("/")
def index():
    """Documentation de l'API"""
    return jsonify({
        "service": "Legislatie.just.ro API Proxy",
        "version": "8.0 - CORRECTION BUG OFFICIEL",
        "soap_endpoint": SOAP_URL,
        "bug_known": {
            "description": "L'API SOAP legislatie.just.ro ignore SearchAn quand SearchTitlu est présent",
            "workaround": "Filtrage côté serveur des résultats par année"
        },
        "filters_official": {
            "title": "SearchTitlu - Recherche dans le titre",
            "text": "SearchText - Recherche dans le texte complet",
            "year": "SearchAn - Année (filtrage côté serveur si title présent)",
            "number": "SearchNumar - Numéro de l'acte"
        },
        "endpoints": {
            "GET /": "Cette documentation",
            "GET /health": "Health check",
            "GET /token": "Obtenir un token",
            "GET /search": "Rechercher des actes législatifs"
        },
        "examples": [
            "/search?title=medici&year=2014",
            "/search?text=codul%20penal",
            "/search?year=2024&per_page=20",
            "/search?number=100"
        ]
    })


@app.route("/health")
def health():
    """Health check"""
    try:
        token, cached = get_cached_token()
        return jsonify({
            "status": "healthy",
            "token_valid": True,
            "token_cached": cached,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@app.route("/token")
def token_endpoint():
    """Obtenir un token"""
    try:
        token, cached = get_cached_token()
        with _token_lock:
            expires_in = (_token_cache["expires_at"] - datetime.utcnow()).seconds if cached else TOKEN_LIFETIME
        
        return jsonify({
            "success": True,
            "token": token,
            "cached": cached,
            "expires_in_seconds": expires_in
        })
    except Exception as e:
        logger.exception("Erreur /token")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/search")
def search():
    """
    Recherche d'actes législatifs
    
    NOTE: Bug officiel de l'API SOAP - SearchAn ignoré si SearchTitlu présent
    SOLUTION: Filtrage côté serveur par année
    """
    try:
        # Pagination
        page = int(request.args.get("page", 0))
        per_page = min(int(request.args.get("per_page", 10)), 100)
        
        # Filtres officiels
        title = request.args.get("title")
        year = request.args.get("year")
        number = request.args.get("number")
        text = request.args.get("text")
        
        # Log
        logger.info(f"📥 Requête: page={page}, title={title}, year={year}, number={number}, text={text[:30] if text else None}...")
        
        # Avertir si filtres non supportés
        ignored_params = [p for p in ['tip_act', 'issuer', 'publication', 'date'] if request.args.get(p)]
        if ignored_params:
            logger.warning(f"⚠️ Paramètres ignorés (non supportés par le WSDL): {ignored_params}")
        
        # Recherche
        token, was_cached = get_cached_token()
        response, soap_body = do_search(token, page, per_page, title, year, number, text)
        
        # Retry si token expiré
        if response.status_code == 500 and was_cached:
            logger.warning("⚠️ Token expiré, retry...")
            invalidate_token()
            token, _ = get_cached_token()
            response, soap_body = do_search(token, page, per_page, title, year, number, text)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Erreur SOAP: {response.status_code}",
                "details": response.text[:500]
            }), 500
        
        # Parser les résultats
        results = []
        for match in re.finditer(r'<a:Legi>(.*?)</a:Legi>', response.text, re.DOTALL):
            try:
                results.append(format_lege(match.group(1)))
            except Exception as e:
                logger.warning(f"⚠️ Erreur parsing: {e}")
        
        # CORRECTION BUG: Filtrer par année côté serveur si title ET year sont présents
        # Car l'API SOAP ignore year quand title est présent
        if title and year:
            year_str = str(year)
            original_count = len(results)
            results = [r for r in results if r.get('effective_date', '').startswith(year_str)]
            logger.info(f"🔧 Filtrage année {year}: {original_count} → {len(results)} résultats")
        
        logger.info(f"✅ {len(results)} résultats")
        
        return jsonify({
            "success": True,
            "total": len(results),
            "page": page,
            "per_page": per_page,
            "filters_applied": {
                "title": title,
                "year": year,
                "number": number,
                "text": text[:50] + "..." if text and len(text) > 50 else text
            },
            "filters_ignored": ignored_params if ignored_params else None,
            "server_side_filtering": {
                "enabled": bool(title and year),
                "reason": "Bug officiel API SOAP: SearchAn ignoré si SearchTitlu présent"
            } if title and year else None,
            "results": results
        })
        
    except Exception as e:
        logger.exception("❌ Erreur /search")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Démarrage API v8.0 sur le port {port}")
    logger.info("📋 Filtres officiels (WSDL): title, text, year, number")
    logger.info("🔧 CORRECTION: Filtrage année côté serveur si title+year")
    app.run(host="0.0.0.0", port=port, debug=True)
