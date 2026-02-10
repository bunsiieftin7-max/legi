"""
API REST pour accéder à legislatie.just.ro
Features:
 - Conversion SOAP -> REST
 - Cache de tokens automatique (TTL configurable)
 - Endpoints documentés
 - Compatible n8n / Make / Zapier (CORS + JSON)
 - Déployable en un clic (Procfile: gunicorn legislatie_api:app)
Configuration via env:
 - WSDL_URL (default fourni)
 - TOKEN_LIFETIME (seconds, default 3600)
 - DEBUG (True/False)
"""
# Fix pour Python 3.13+ (module cgi supprimé mais requis par zeep)
import sys
if sys.version_info >= (3, 13):
    import html
    sys.modules['cgi'] = type(sys)('cgi')
    sys.modules['cgi'].escape = html.escape
 """
 
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
from datetime import datetime, timedelta
import threading

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("legislatie_api")

# App
app = Flask(__name__)
CORS(app)

# Configuration (env overrides)
WSDL_URL = os.environ.get("WSDL_URL", "http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl")
TOKEN_LIFETIME = int(os.environ.get("TOKEN_LIFETIME", str(3600)))  # seconds
DEBUG = os.environ.get("DEBUG", "False").lower() in ("1", "true", "yes")

# Token cache structure (process-local)
_token_cache = {
    "token": None,
    "expires_at": None
}
_token_lock = threading.Lock()


def _import_zeep_client():
    """
    Import zeep lazily so the app can start even when zeep is missing (useful for debugging).
    Raises ImportError if zeep not installed.
    """
    try:
        from zeep import Client
        from zeep.exceptions import Fault
        return Client, Fault
    except ImportError as e:
        logger.error("Zeep is not installed: %s", e)
        raise


def get_soap_client():
    """Initialise et retourne un client zeep SOAP. Lève ImportError si zeep absent."""
    Client, _ = _import_zeep_client()
    try:
        client = Client(WSDL_URL)
        return client
    except Exception as e:
        logger.error("Erreur création client SOAP: %s", e)
        raise


def _now():
    return datetime.utcnow()


def get_cached_token():
    """
    Retourne un token valide en cache ou demande un nouveau token au service SOAP.
    Thread-safe via _token_lock.
    """
    # Quick check without lock
    token = _token_cache.get("token")
    expires_at = _token_cache.get("expires_at")
    if token and expires_at and expires_at > _now():
        logger.debug("Token utilisé depuis le cache, expires_at=%s", expires_at.isoformat())
        return token, True

    with _token_lock:
        # Re-check after acquiring lock
        token = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at")
        if token and expires_at and expires_at > _now():
            logger.debug("Token trouvé dans cache après verrou")
            return token, True

        # Need to fetch a new token
        try:
            client = get_soap_client()
            token = client.service.GetToken()
            expires_at = _now() + timedelta(seconds=TOKEN_LIFETIME)
            _token_cache["token"] = token
            _token_cache["expires_at"] = expires_at
            logger.info("Nouveau token obtenu et mis en cache (expires_at=%s)", expires_at.isoformat())
            return token, False
        except Exception as e:
            logger.error("Erreur lors de l'obtention du token: %s", e)
            raise


def format_lege(lege):
    """Formate un objet Lege (résultat SOAP) en dict JSON-friendly."""
    # Using getattr to be resilient to missing attributes
    return {
        "id": getattr(lege, "Id", None),
        "title": getattr(lege, "Titlu", "") or "",
        "number": getattr(lege, "Numar", "") or "",
        "year": getattr(lege, "An", None),
        "type": getattr(lege, "TipAct", "") or "",
        "issuer": getattr(lege, "Emitent", "") or "",
        "effective_date": str(getattr(lege, "DataVigoare", "") or ""),
        "publication": getattr(lege, "Publicatie", "") or "",
        "text_preview": (getattr(lege, "Text", "") or "")[:500],
        "text_full": getattr(lege, "Text", "") or "",
        "url": f"https://legislatie.just.ro/Public/DetaliiDocument/{getattr(lege, 'Id', '')}"
    }


@app.route("/", methods=["GET"])
def index():
    """Documentation minimaliste pour usage par n8n / scripts"""
    return jsonify({
        "service": "Legislatie.just.ro API Proxy",
        "version": "2.0",
        "description": "Proxy REST light pour le service SOAP legislatie.just.ro — friendly for n8n/Make/Zapier",
        "endpoints": {
            "GET /health": "Check service health",
            "GET /token": "Get current token (cached)",
            "GET /search": "Search legislation — params: title, year, number, text, page, per_page",
            "GET /codes": "Get main legal codes (predefined list)",
            "GET /document/<id>": "Link to the official document by id"
        },
        "example": {
            "search_code_civil": "/search?title=Codul%20civil&per_page=5",
            "curl": "curl 'https://<your-service>/search?title=Codul%20civil'"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    """Health endpoint. Tests basic SOAP connectivity (non-blocking if zeep absent)."""
    try:
        # Try to import zeep and create client to check WSDL reachability
        Client, _ = _import_zeep_client()
        # Attempt to create client — network errors will be raised here
        client = Client(WSDL_URL)
        return jsonify({
            "status": "healthy",
            "soap_wsdl": WSDL_URL,
            "timestamp": _now().isoformat()
        })
    except ImportError:
        return jsonify({
            "status": "degraded",
            "reason": "zeep library not installed",
            "timestamp": _now().isoformat()
        }), 200
    except Exception as e:
        logger.warning("Healthcheck SOAP failure: %s", e)
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _now().isoformat()
        }), 500


@app.route("/token", methods=["GET"])
def token_endpoint():
    """Return cached token (and whether it was cached)."""
    try:
        token, cached = get_cached_token()
        return jsonify({
            "success": True,
            "token": token,
            "cached": cached,
            "expires_at": _token_cache.get("expires_at").isoformat() if _token_cache.get("expires_at") else None
        })
    except Exception as e:
        logger.exception("Erreur /token")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/search", methods=["GET"])
def search():
    """
    Main search endpoint.
    Query params (all optional):
     - title, year, number, text, page (int, default 0), per_page (int default 10, max 100)
    """
    try:
        # Acquire token (will refresh if expired)
        token, _ = get_cached_token()

        # Build SOAP client and SearchModel
        client = get_soap_client()
        factory = client.type_factory("ns0")
        search_model = factory.SearchModel()

        page = int(request.args.get("page", 0))
        per_page = min(int(request.args.get("per_page", 10)), 100)

        search_model.NumarPagina = page
        search_model.RezultatePagina = per_page

        if request.args.get("title"):
            search_model.SearchTitlu = request.args.get("title")
        if request.args.get("year"):
            try:
                search_model.SearchAn = int(request.args.get("year"))
            except ValueError:
                pass
        if request.args.get("number"):
            search_model.SearchNumar = request.args.get("number")
        if request.args.get("text"):
            search_model.SearchText = request.args.get("text")

        logger.info("Executing search: title=%s page=%d per_page=%d",
                    request.args.get("title"), page, per_page)

        response = client.service.Search(search_model, token)

        results = []
        # 'Legi' may be None or list-like
        if hasattr(response, "Legi") and response.Legi:
            for lege in response.Legi:
                results.append(format_lege(lege))

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
        # If SOAP Fault exists, zeep raises a Fault — let it surface as detail
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/codes", methods=["GET"])
def get_main_codes():
    """Return a curated list of main codes with their best-match result (1 per code)."""
    base_codes = [
        {"name": "Codul civil", "year": 2009, "number": 287},
        {"name": "Codul penal", "year": 2009, "number": 286},
        {"name": "Codul de procedură civilă", "year": 2010, "number": 134},
        {"name": "Codul de procedură penală", "year": 2010, "number": 135},
        {"name": "Codul muncii", "year": 2003, "number": 53},
        {"name": "Codul fiscal", "year": 2015, "number": 227},
        {"name": "Constituția României", "year": 1991, "number": None}
    ]

    try:
        token, _ = get_cached_token()
        client = get_soap_client()
        factory = client.type_factory("ns0")

        results = []
        for code in base_codes:
            try:
                search_model = factory.SearchModel()
                search_model.NumarPagina = 0
                search_model.RezultatePagina = 1
                search_model.SearchTitlu = code["name"]
                if code["year"]:
                    search_model.SearchAn = code["year"]

                resp = client.service.Search(search_model, token)
                if hasattr(resp, "Legi") and resp.Legi:
                    results.append({
                        "code_name": code["name"],
                        "details": format_lege(resp.Legi[0])
                    })
            except Exception as e:
                logger.warning("Erreur pour code %s : %s", code["name"], e)
                # continue to next code

        return jsonify({
            "success": True,
            "total": len(results),
            "codes": results
        })
    except Exception as e:
        logger.exception("Erreur /codes")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/document/<doc_id>", methods=["GET"])
def get_document(doc_id):
    """Return a friendly link and metadata for a given document id."""
    return jsonify({
        "success": True,
        "url": f"https://legislatie.just.ro/Public/DetaliiDocument/{doc_id}",
        "note": "Direct link to the official site. Full text retrieval may be added later."
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_env = os.environ.get("DEBUG", "False").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug_env)
