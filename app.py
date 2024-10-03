import os
import requests
import logging
from flask import Flask, request, jsonify, render_template, Response, make_response, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
import json
from werkzeug.exceptions import HTTPException, BadRequest
from api_integrations import fetch_trending_topics, summarize_with_hf, extract_entities_with_hf

# Initialize Flask app
app = Flask(__name__)

# Security: Use Flask-Talisman to enforce HTTPS and set secure headers
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
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_size': 10, 'pool_timeout': 30, 'max_overflow': 5}
db = SQLAlchemy(app)

# Caching configuration
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)

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
    timestamp = db.Column(db.DateTime, default=db.func.now())

    def set_hf_data(self, processed_data):
        self.entities = json.dumps(processed_data.get('entities', []))

    def get_hf_data(self):
        return {'entities': json.loads(self.entities) if self.entities else []}

# Advanced logging setup
def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    max_log_size = 10 * 1024 * 1024  # 10 MB
    backup_count = 5

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=max_log_size, backupCount=backup_count)
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

# Helper function for standardized responses
def create_standard_response(data, status_code, message):
    response = {
        "data": data,
        "status": status_code,
        "message": message
    }
    return response, status_code

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
            remaining_requests = 60
        elif remaining_requests <= 0:
            logger.warning("Global rate limit exceeded")
            return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        logger.info(f"Remaining global requests: {remaining_requests - 1}")

        response = func(*args, **kwargs)
        if isinstance(response, tuple):
            data, status_code = response
            response = make_response(jsonify(data), status_code)
        elif not isinstance(response, Response):
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
            query = request.json.get('q') if request.is_json else request.form.get('q')
        else:
            raise BadRequest("Unsupported HTTP method")

        if not query:
            current_app.logger.warning(f"Search query is missing. Method: {request.method}, Headers: {request.headers}, Data: {request.data}")
            return create_standard_response({'error': 'Query parameter "q" is required'}, 400, "Query parameter missing")

        query = sanitize_input(query)
        current_app.logger.info(f"Processing search query: {query}")

        # Process the user's search query with Hugging Face (entity extraction)
        processed_query_data = extract_entities_with_hf(query)

        # Fetch trending topics (results from external APIs)
        results = fetch_trending_topics(query)

        current_app.logger.info(f"Search results for '{query}': {len(results)} items found")

        # Summarize results
        summaries = []
        for result in results:
            summary = summarize_with_hf(f"{result.get('title', '')} {result.get('summary', '')}")
            summaries.append({
                'source': result.get('source', ''),
                'title': result.get('title', ''),
                'summary': summary,
                'url': result.get('url', '')
            })

        # Generate a conversational response
        friendly_response = f"Here's what I found about {query}. Let me know if you want to know more about any specific topic!"
        return create_standard_response({
            'query': query,
            'processed_query': processed_query_data,
            'results': summaries,
            'dynamic_response': friendly_response
        }, 200, "Search query processed successfully")

    except BadRequest as e:
        logger.error(f"Bad request: {str(e)}")
        return create_standard_response(None, 400, str(e))
    except Exception as e:
        logger.error(f"Error while processing search: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

@app.route('/recent_searches', methods=['GET'])
@rate_limit
def recent_searches():
    try:
        recent_queries = UserQuery.query.order_by(UserQuery.timestamp.desc()).limit(10).all()
        recent_searches_processed = []

        for query in recent_queries:
            recent_searches_processed.append({
                'query': query.query,
                'timestamp': query.timestamp.isoformat(),
                'processed_data': query.get_hf_data()
            })

        logger.info(f"Fetched {len(recent_searches_processed)} recent searches")
        return create_standard_response(recent_searches_processed, 200, "Recent searches retrieved successfully")

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching recent searches: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "A database error occurred while fetching recent searches")
    except Exception as e:
        logger.error(f"Unexpected error while fetching recent searches: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred while fetching recent searches")

@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    try:
        if request.is_json:
            query = request.json.get('q')
        else:
            query = request.form.get('q')

        if not query:
            logger.warning("Query is missing")
            return create_standard_response({'error': 'Query is required'}, 400, "Query is required")

        query = sanitize_input(query)
        logger.debug(f"Sanitized query: {query}")

        # Extract entities from query using Hugging Face API
        processed_query_data = extract_entities_with_hf(query)

        # Store the query in the database
        new_query = UserQuery(query=query)
        new_query.set_hf_data(processed_query_data)
        db.session.add(new_query)
        db.session.commit()

        logger.info("Query stored in the database")

        # Fetch results from external APIs (YouTube, Google, News, etc.)
        results = fetch_trending_topics(query)
        logger.info("Sending response with the search results")

        return create_standard_response(results, 200, "Query processed successfully")

    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

@app.errorhandler(Exception)
def handle_exception(e):
    # Handle HTTP errors
    if isinstance(e, HTTPException):
        return e

    # Log non-HTTP exceptions
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Initialize the database
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))