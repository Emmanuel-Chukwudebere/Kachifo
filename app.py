import os
from flask import Flask, request, jsonify, render_template, Response, make_response, current_app
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

# Helper function for standardized response
def create_standard_response(data, status_code, message):
    response = {
        "data": data,
        "status": status_code,
        "message": message
    }
    return jsonify(response), status_code

# Middleware for logging requests and responses
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
            return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")

        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        logger.info(f"Remaining global requests: {remaining_requests - 1}")

        response = func(*args, **kwargs)

        if isinstance(response, tuple):
            data, status_code = response
            response = make_response(jsonify(data), status_code)
        elif isinstance(response, Response):
            # It's already a Response object, so return it directly
            return response
        else:
            response = make_response(jsonify(response), 200)

        response.headers['X-RateLimit-Remaining'] = str(remaining_requests - 1)
        response.headers['X-RateLimit-Limit'] = '60'
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
    return create_standard_response(None, e.code, "Something went wrong! Please check your request and try again.")

@app.errorhandler(SQLAlchemyError)
def handle_database_error(e):
    logger.error(f"Database error: {str(e)}")
    return create_standard_response(None, 500, "Database error occurred. Please try again later.")

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.critical(f"Unexpected error: {str(e)}", exc_info=True)
    return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    try:
        query = request.args.get('q') if request.method == 'GET' else request.form.get('q')
        if not query:
            raise BadRequest("Query parameter 'q' is required")

        query = sanitize_input(query)
        logger.info(f"Processing search query: {query}")

        # Fetch trending topics (results from external APIs)
        results = fetch_trending_topics(query)

        # Process the fetched results with spaCy
        processed_results = []
        for result in results:
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

        return create_standard_response({'query': query, 'results': processed_results}, 200, "Query processed successfully")
    except BadRequest as e:
        logger.error(f"Bad request: {str(e)}")
        return create_standard_response(None, 400, str(e))
    except Exception as e:
        logger.error(f"Error while processing search: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

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
        return create_standard_response(recent_searches_processed, 200, "Recent searches retrieved successfully")
    except Exception as e:
        logger.error(f"Error fetching recent searches: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An error occurred while fetching recent searches")
        
@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    try:
        query = request.json.get('q') if request.is_json else request.form.get('q')

        if not query:
            logger.warning(f"Query is missing. Headers: {request.headers}, Data: {request.get_data()}")
            return create_standard_response(None, 400, "Query is required")

        query = sanitize_input(query)
        logger.info(f"Processing query: {query}")

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

        return create_standard_response({
            'query': processed_query_data,
            'results': processed_results
        }, 200, "Query processed successfully")
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))