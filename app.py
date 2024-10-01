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
import json

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

    def set_spacy_data(self, processed_data):
        self.entities = json.dumps(processed_data['entities'])
        self.verbs = json.dumps(processed_data['verbs'])
        self.nouns = json.dumps(processed_data['nouns'])

    def get_spacy_data(self):
        return {
            'entities': json.loads(self.entities) if self.entities else [],
            'verbs': json.loads(self.verbs) if self.verbs else [],
            'nouns': json.loads(self.nouns) if self.nouns else []
        }

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

# Helper function for standardized response and ensure create_standard_response always returns a tuple
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

        # Execute the original function
        response = func(*args, **kwargs)
        
        # Handle different response types
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
            return create_standard_response({'error': 'Query parameter "q" is required'}, 400, "Query parameter missing")

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
            else:
                # Ensure non-dictionary results are serialized appropriately
                processed_results.append({
                    'text': str(result)  # Ensure it's serialized as a string
                })

        # Log processed results to debug serialization issues
        logger.info(f"Processed search results: {processed_results}")

        # Return JSON-serializable response
        return create_standard_response({
            'query': query,
            'processed_query': processed_query_data,
            'results': processed_results
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
        # Fetch the 10 most recent queries
        recent_queries = UserQuery.query.order_by(UserQuery.timestamp.desc()).limit(10).all()
        
        recent_searches_processed = []
        for query in recent_queries:
            # Process each recent query text with spaCy
            processed_query_data = process_query_with_spacy(query.query)
            
            # Parse the stored string representations back into lists
            entities = json.loads(query.entities.replace("'", '"'))
            verbs = json.loads(query.verbs.replace("'", '"'))
            nouns = json.loads(query.nouns.replace("'", '"'))
            
            recent_searches_processed.append({
                'query': query.query,
                'timestamp': query.timestamp.isoformat(),
                'entities': entities,
                'verbs': verbs,
                'nouns': nouns,
                'processed_data': processed_query_data  # Include the freshly processed data
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
        logger.debug("Received request to /process-query")
        
        # Extract the query from the request (JSON or form)
        if request.is_json:
            query = request.json.get('q')
        else:
            query = request.form.get('q')

        logger.info(f"Processing query: {query}")
        
        # Ensure query is provided
        if not query:
            logger.warning("Query is missing")
            return create_standard_response({'error': 'Query is required'}, 400, "Query is required")
        
        # Sanitize the input query
        query = sanitize_input(query)
        logger.debug(f"Sanitized query: {query}")
        
        # Process the user's search query with spaCy
        processed_query_data = process_query_with_spacy(query)
        logger.debug(f"Processed query data: {processed_query_data}")
        
        # Store the user's query with spaCy data in the database
        new_query = UserQuery(query=query)
        new_query.set_spacy_data(processed_query_data)
        db.session.add(new_query)
        db.session.commit()
        logger.info("Query stored in database")
        
        # Fetch trending topics or perform search
        results = fetch_trending_topics(query)
        
        # Log the complete set of results as a string (use repr to show structure)
        logger.debug(f"Fetched results (full): {repr(results)}")
        logger.debug(f"Number of results fetched: {len(results)}")
        
        processed_results = []
        for result in results:
            if isinstance(result, dict):
                # Process dictionary results as usual
                result_text = f"{result.get('title', '')} {result.get('summary', '')}"
                processed_result_data = process_query_with_spacy(result_text)
                
                processed_result = {
                    'source': result.get('source', 'Unknown'),
                    'title': result.get('title', 'No Title'),
                    'summary': result.get('summary', 'No Summary'),
                    'url': result.get('url', None),
                    'entities': processed_result_data['entities'],
                    'verbs': processed_result_data['verbs'],
                    'nouns': processed_result_data['nouns']
                }
                processed_results.append(processed_result)
                
                # Log important fields for each dictionary result
                logger.info(f"Processed result: Source: {processed_result['source']}, Title: {processed_result['title']}, URL: {processed_result['url'] or 'No URL'}")
            else:
                # Convert non-dict result to a dictionary with placeholders
                logger.warning(f"Non-dict result encountered: {repr(result)}")
                processed_result = {
                    'source': 'Unknown',  # Placeholder source
                    'title': 'No Title',  # Placeholder title
                    'summary': str(result),  # Use the non-dict result as the summary
                    'url': None,  # No URL available for non-dict results
                    'entities': [],  # No entities available
                    'verbs': [],
                    'nouns': []
                }
                processed_results.append(processed_result)
                # Log the newly converted result
                logger.info(f"Converted non-dict result: {processed_result}")

        logger.debug(f"Processed {len(processed_results)} results")
        
        # Log sample data from the first result, if available
        if processed_results:
            first_result = processed_results[0]
            logger.info(f"Sample Result - Source: {first_result.get('source', 'Unknown')}, Title: {first_result.get('title', 'No Title')}, URL: {first_result.get('url') if first_result.get('url') else 'No URL'}")
        else:
            logger.info("No results to process")
        
        # Prepare response data
        response_data = {
            'query': processed_query_data,
            'results': processed_results
        }

        logger.info("Sending response")
        return create_standard_response(response_data, 200, "Query processed successfully")
    
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))