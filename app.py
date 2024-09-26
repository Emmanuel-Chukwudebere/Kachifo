import os
from flask import Flask, request, jsonify, render_template, current_app, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
import re
from api_integrations import fetch_trending_topics
from werkzeug.exceptions import HTTPException, BadRequest
from sqlalchemy.exc import SQLAlchemyError
import spacy

# Initialize spaCy model
nlp = spacy.load('en_core_web_sm')

# Initialize Flask app
app = Flask(__name__)

# Security: Use Flask-Talisman to enforce HTTPS, set secure headers
Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:'],
    'style-src': ["'self'", 'https:'],
    'img-src': ["'self'", 'data:'],
    'connect-src': ["'self'", 'https:']
})

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_timeout': 30,
    'max_overflow': 5
}

# Caching configuration
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)
db = SQLAlchemy(app)

# Models
class Trend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(255), nullable=False)

class UserQuery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    entities = db.Column(db.Text, nullable=True)
    verbs = db.Column(db.Text, nullable=True)
    nouns = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=db.func.now())

# Advanced logging setup
def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    max_log_size = 10 * 1024 * 1024  # 10 MB
    backup_count = 5
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    file_handler = RotatingFileHandler(log_file, maxBytes=max_log_size, backupCount=backup_count)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    for logger_name in ('werkzeug', 'sqlalchemy.engine'):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(log_level)

setup_logging()
logger = logging.getLogger(__name__)

# Request logging middleware
@app.before_request
def log_request_info():
    logger.info(f'Request: {request.method} {request.url}')
    logger.debug(f'Headers: {request.headers}')
    logger.debug(f'Body: {request.get_data()}')

@app.after_request
def log_response_info(response):
    logger.info(f'Response: {response.status}')
    logger.debug(f'Headers: {response.headers}')
    return response

# Rate limiting
def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = "global_rate_limit"
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            remaining_requests = 60  # Set a higher limit for global usage
        elif remaining_requests <= 0:
            logger.warning("Global rate limit exceeded")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        
        logger.info(f"Remaining global requests: {remaining_requests - 1}")
        response = func(*args, **kwargs)
        
        if isinstance(response, tuple):
            data, status_code = response
        elif isinstance(response, Response):
            return response  # If it's already a Response object, return it as is
        else:
            data, status_code = response, 200
        
        if not isinstance(data, (str, bytes)):
            data = json.dumps(data)  # Ensure data is a JSON string
        
        response = make_response(data, status_code)
        response.headers['Content-Type'] = 'application/json'
        response.headers['X-RateLimit-Remaining'] = remaining_requests - 1
        response.headers['X-RateLimit-Limit'] = 60
        return response
    return wrapper

# Input sanitization
def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Extract useful information from spaCy
def process_query_with_spacy(query):
    doc = nlp(query)
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    nouns = [chunk.text for chunk in doc.noun_chunks]
    verbs = [token.lemma_ for token in doc if token.pos_ == 'VERB']
    return {
        'entities': entities,
        'nouns': nouns,
        'verbs': verbs
    }

# Error handlers
@app.errorhandler(HTTPException)
def handle_http_error(e):
    logger.error(f"HTTP error occurred: {e.description} - Code: {e.code}")
    return jsonify({'error': 'Something went wrong! Please check your request and try again.'}), e.code

@app.errorhandler(SQLAlchemyError)
def handle_database_error(e):
    logger.error(f"Database error: {str(e)}")
    return jsonify({'error': 'Database error occurred. Please try again later.'}), 500

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.critical(f"Unexpected error: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    try:
        if request.method == 'GET':
            query = request.args.get('q')
        elif request.method == 'POST':
            if request.is_json:
                query = request.json.get('q')
            else:
                query = request.form.get('q')
        else:
            raise BadRequest("Unsupported HTTP method")

        if not query:
            current_app.logger.warning(f"Search query is missing. Method: {request.method}, Headers: {request.headers}, Data: {request.data}")
            return jsonify({'error': 'Query parameter "q" is required'}), 400

        query = sanitize_input(query)
        current_app.logger.info(f"Processing search query: {query}")

        # Process the user's search query with spaCy
        processed_query_data = process_query_with_spacy(query)

        # Fetch trending topics (results from external APIs)
        results = fetch_trending_topics(query)
        current_app.logger.info(f"Search results for '{query}': {len(results)} items found")

        # Process the fetched results with spaCy
        processed_results = []
        for result in results:
            if isinstance(result, dict):
                result_text = f"{result.get('title', '')} {result.get('summary', '')}"
                processed_result_data = process_query_with_spacy(result_text)
                processed_results.append({
                    'source': result.get('source', ''),
                    'title': result.get('title', ''),
                    'summary': result.get('summary', ''),
                    'url': result.get('url', ''),
                    'entities': processed_result_data['entities'],
                    'verbs': processed_result_data['verbs'],
                    'nouns': processed_result_data['nouns']
                })

                # Store the result in the database
                new_trend = Trend(
                    query=query,
                    source=result.get('source', ''),
                    title=result.get('title', ''),
                    summary=result.get('summary', ''),
                    url=result.get('url', '')
                )
                db.session.add(new_trend)

        # Store the user's query along with spaCy-extracted data
        new_query = UserQuery(
            query=query,
            entities=str(processed_query_data['entities']),
            verbs=str(processed_query_data['verbs']),
            nouns=str(processed_query_data['nouns'])
        )
        db.session.add(new_query)
        db.session.commit()

        return jsonify(processed_results)
    except BadRequest as e:
        current_app.logger.error(f"Bad request: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error while processing search: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@app.route('/recent_searches', methods=['GET'])
def recent_searches():
    try:
        recent_queries = UserQuery.query.order_by(UserQuery.timestamp.desc()).limit(10).all()
        recent_searches_processed = []
        for query in recent_queries:
            # Process each recent query text with spaCy
            processed_query_data = process_query_with_spacy(query.query)
            recent_searches_processed.append({
                'query': query.query,
                'entities': processed_query_data['entities'],
                'verbs': processed_query_data['verbs'],
                'nouns': processed_query_data['nouns']
            })
        return jsonify(recent_searches_processed)
    except Exception as e:
        current_app.logger.error(f"Error fetching recent searches: {str(e)}", exc_info=True)
        return jsonify({'error': 'An error occurred while fetching recent searches'}), 500

@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    try:
        if request.is_json:
            query = request.json.get('q')
        else:
            query = request.form.get('q')

        if not query:
            current_app.logger.warning(f"Query is missing. Headers: {request.headers}, Data: {request.data}")
            return jsonify({'error': 'Query is required'}), 400

        query = sanitize_input(query)
        current_app.logger.info(f"Processing query: {query}")

        # Process the user's search query with spaCy
        processed_query_data = process_query_with_spacy(query)

        # Store the user's query with spaCy data
        new_query = UserQuery(
            query=query,
            entities=str(processed_query_data['entities']),
            verbs=str(processed_query_data['verbs']),
            nouns=str(processed_query_data['nouns'])
        )
        db.session.add(new_query)
        db.session.commit()

        # Fetch trending topics or perform search
        results = fetch_trending_topics(query)
        processed_results = []
        for result in results:
            if isinstance(result, dict):
                result_text = f"{result.get('title', '')} {result.get('summary', '')}"
                processed_result_data = process_query_with_spacy(result_text)
                processed_results.append({
                    'source': result.get('source', ''),
                    'title': result.get('title', ''),
                    'summary': result.get('summary', ''),
                    'url': result.get('url', ''),
                    'entities': processed_result_data['entities'],
                    'verbs': processed_result_data['verbs'],
                    'nouns': processed_result_data['nouns']
                })

        return jsonify({
            'query': processed_query_data,
            'results': processed_results
        })
    except Exception as e:
        current_app.logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# Start the app
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))