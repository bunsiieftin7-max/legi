"""
API REST pour accéder à legislatie.just.ro
Compatible avec n8n et déployable sur Render/Railway/Heroku
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from zeep import Client
from zeep.exceptions import Fault
import os
from datetime import datetime
import logging

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Permettre les requêtes cross-origin depuis n8n

# Configuration
WSDL_URL = 'http://legislatie.just.ro/apiws/FreeWebService.svc?wsdl'
TOKEN_CACHE = {'token': None, 'timestamp': None}
TOKEN_LIFETIME = 3600  # 1 heure


def get_soap_client():
    """Initialise le client SOAP"""
    try:
        return Client(WSDL_URL)
    except Exception as e:
        logger.error(f"Erreur création client SOAP: {e}")
        raise


def get_cached_token():
    """Obtient un token (avec cache)"""
    global TOKEN_CACHE
    
    # Vérifier si token en cache et toujours valide
    if TOKEN_CACHE['token'] and TOKEN_CACHE['timestamp']:
        age = (datetime.now() - TOKEN_CACHE['timestamp']).seconds
        if age < TOKEN_LIFETIME:
            logger.info("Utilisation token en cache")
            return TOKEN_CACHE['token']
    
    # Générer nouveau token
    try:
        client = get_soap_client()
        token = client.service.GetToken()
        TOKEN_CACHE = {
            'token': token,
            'timestamp': datetime.now()
        }
        logger.info("Nouveau token généré")
        return token
    except Exception as e:
        logger.error(f"Erreur GetToken: {e}")
        raise


def format_lege(lege):
    """Formate un objet Lege en dictionnaire"""
    return {
        'id': getattr(lege, 'Id', None),
        'title': getattr(lege, 'Titlu', ''),
        'number': getattr(lege, 'Numar', ''),
        'year': getattr(lege, 'An', None),
        'type': getattr(lege, 'TipAct', ''),
        'issuer': getattr(lege, 'Emitent', ''),
        'effective_date': str(getattr(lege, 'DataVigoare', '')),
        'publication': getattr(lege, 'Publicatie', ''),
        'text_preview': (getattr(lege, 'Text', '') or '')[:500],  # Aperçu 500 chars
        'text_full': getattr(lege, 'Text', ''),
        'url': f"https://legislatie.just.ro/Public/DetaliiDocument/{getattr(lege, 'Id', '')}"
    }


@app.route('/')
def index():
    """Page d'accueil avec documentation"""
    return jsonify({
        'service': 'Legislatie.just.ro API Proxy',
        'version': '1.0',
        'endpoints': {
            '/health': 'GET - Vérifier l\'état du service',
            '/token': 'GET - Obtenir un token (avec cache)',
            '/search': 'GET - Rechercher dans la législation',
            '/codes': 'GET - Obtenir les codes principaux'
        },
        'search_params': {
            'title': 'Titre de la loi (ex: Codul civil)',
            'year': 'Année (ex: 2009)',
            'number': 'Numéro (ex: 287)',
            'text': 'Texte à rechercher',
            'page': 'Numéro de page (défaut: 0)',
            'per_page': 'Résultats par page (défaut: 10, max: 100)'
        },
        'examples': {
            'search_civil_code': '/search?title=Codul civil',
            'search_by_year': '/search?year=2009&per_page=20',
            'search_penal': '/search?title=Codul penal&page=0'
        }
    })


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de santé pour monitoring"""
    try:
        # Tester la connexion SOAP
        client = get_soap_client()
        return jsonify({
            'status': 'healthy',
            'soap_service': 'connected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@app.route('/token', methods=['GET'])
def get_token():
    """Endpoint pour obtenir un token"""
    try:
        token = get_cached_token()
        return jsonify({
            'success': True,
            'token': token,
            'cached': TOKEN_CACHE['timestamp'] is not None
        })
    except Exception as e:
        logger.error(f"Erreur /token: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/search', methods=['GET'])
def search():
    """Endpoint principal de recherche"""
    try:
        # Obtenir le token
        token = get_cached_token()
        client = get_soap_client()
        
        # Préparer les paramètres de recherche
        page = int(request.args.get('page', 0))
        per_page = min(int(request.args.get('per_page', 10)), 100)  # Max 100
        
        # Créer le SearchModel
        factory = client.type_factory('ns0')
        search_model = factory.SearchModel()
        
        search_model.NumarPagina = page
        search_model.RezultatePagina = per_page
        
        # Paramètres optionnels
        if request.args.get('title'):
            search_model.SearchTitlu = request.args.get('title')
        
        if request.args.get('year'):
            search_model.SearchAn = int(request.args.get('year'))
        
        if request.args.get('number'):
            search_model.SearchNumar = request.args.get('number')
        
        if request.args.get('text'):
            search_model.SearchText = request.args.get('text')
        
        # Effectuer la recherche
        logger.info(f"Recherche avec: title={request.args.get('title')}, page={page}")
        response = client.service.Search(search_model, token)
        
        # Formater les résultats
        results = []
        if hasattr(response, 'Legi') and response.Legi:
            for lege in response.Legi:
                results.append(format_lege(lege))
        
        return jsonify({
            'success': True,
            'total': len(results),
            'page': page,
            'per_page': per_page,
            'query': {
                'title': request.args.get('title'),
                'year': request.args.get('year'),
                'number': request.args.get('number'),
                'text': request.args.get('text')
            },
            'results': results
        })
        
    except Fault as e:
        logger.error(f"SOAP Fault: {e}")
        return jsonify({
            'success': False,
            'error': 'SOAP Error',
            'detail': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Erreur /search: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/codes', methods=['GET'])
def get_main_codes():
    """Endpoint pour obtenir les codes juridiques principaux"""
    codes = [
        {'name': 'Codul civil', 'year': 2009, 'number': 287},
        {'name': 'Codul penal', 'year': 2009, 'number': 286},
        {'name': 'Codul de procedură civilă', 'year': 2010, 'number': 134},
        {'name': 'Codul de procedură penală', 'year': 2010, 'number': 135},
        {'name': 'Codul muncii', 'year': 2003, 'number': 53},
        {'name': 'Codul fiscal', 'year': 2015, 'number': 227},
        {'name': 'Constituția României', 'year': 1991, 'number': None},
    ]
    
    try:
        # Rechercher chaque code
        results = []
        token = get_cached_token()
        client = get_soap_client()
        
        for code in codes:
            factory = client.type_factory('ns0')
            search_model = factory.SearchModel()
            search_model.NumarPagina = 0
            search_model.RezultatePagina = 1
            search_model.SearchTitlu = code['name']
            if code['year']:
                search_model.SearchAn = code['year']
            
            try:
                response = client.service.Search(search_model, token)
                if hasattr(response, 'Legi') and response.Legi:
                    results.append({
                        'code_name': code['name'],
                        'details': format_lege(response.Legi[0])
                    })
            except Exception as e:
                logger.warning(f"Code {code['name']} non trouvé: {e}")
        
        return jsonify({
            'success': True,
            'total': len(results),
            'codes': results
        })
        
    except Exception as e:
        logger.error(f"Erreur /codes: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/document/<doc_id>', methods=['GET'])
def get_document(doc_id):
    """Endpoint pour obtenir un document spécifique par ID"""
    return jsonify({
        'success': True,
        'message': 'Feature coming soon',
        'url': f'https://legislatie.just.ro/Public/DetaliiDocument/{doc_id}',
        'note': 'Pour l\'instant, utilisez l\'URL directement'
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False') == 'True'
    app.run(host='0.0.0.0', port=port, debug=debug)
