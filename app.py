import os
import logging
import re
from flask import Flask, request, jsonify, render_template
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
from werkzeug.exceptions import HTTPException

from api_integrations import (
    fetch_trending_topics,
    summarize_with_hf,
    extract_entities_with_hf,
    generate_conversational_response,
    generate_general_summary
)

# Initialize Flask app
app = Flask(__name__)

# Enable HTTPS with secure headers
Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:', "'unsafe-inline'"],  # Allow inline JS for animations
    'style-src': ["'self'", 'https:', "'unsafe-inline'"],   # Allow inline CSS
    'img-src': ["'self'", 'data:', 'https:'],
    'connect-src': ["'self'", 'https:'],
    'font-src': ["'self'", 'https:', 'data:']
})

# Configure in-memory caching
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes
cache = Cache(app)

def setup_logging():
    """Configure application logging."""
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    
    # Create formatter for consistent log format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Setup file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    # Setup console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

setup_logging()
logger = logging.getLogger(__name__)

def create_response(data, status_code=200, message="Success"):
    """Standard response format for API endpoints."""
    return jsonify({"data": data, "status": status_code, "message": message}), status_code

@app.before_request
def log_request_info():
    """Log information about incoming requests."""
    logger.info(f'Request: {request.method} {request.url}')
    
    # Only log detailed info for non-production environments
    if os.environ.get('FLASK_ENV') != 'production':
        logger.debug(f'Headers: {request.headers}')
        if request.method in ['POST', 'PUT'] and request.is_json:
            logger.debug(f'Body: {request.get_json()}')

@app.after_request
def log_response_info(response):
    """Log information about outgoing responses."""
    logger.info(f'Response: {response.status}')
    return response

def rate_limit(func):
    """Rate limiting decorator for API endpoints."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get client IP for more granular rate limiting
        client_ip = request.remote_addr
        key = f"rate_limit:{client_ip}"
        
        # Check remaining requests
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            # Initialize with 60 requests per hour
            remaining_requests = 60
            cache.set(key, remaining_requests, timeout=3600)  # 1 hour
        elif remaining_requests <= 0:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        
        # Decrement remaining requests
        cache.set(key, remaining_requests - 1, timeout=3600)
        return func(*args, **kwargs)
    return wrapper

def sanitize_input(query):
    """Sanitize user input to prevent injection attacks."""
    if not query:
        return ""
    # Remove special characters, keep alphanumeric and spaces
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input):
    """Determine if the input is a search query or conversational."""
    if not user_input:
        return 'conversation'
        
    # Patterns suggesting a search or query intention
    query_pattern = re.compile(
        r'\b(search|find|look up|what is|tell me about|trending|give me|show me)\b', 
        re.IGNORECASE
    )
    
    if query_pattern.search(user_input):
        return 'query'
    return 'conversation'

@app.route('/')
def home():
    """Serve the main application page."""
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['POST'])
@rate_limit
def interact():
    """Main interaction endpoint for handling both queries and conversations."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    user_input = data.get('input', '').strip()
    if not user_input:
        return jsonify({'error': 'No input provided'}), 400

    # Classify the input type
    input_type = classify_input_type(user_input)
    
    try:
        if input_type == 'conversation':
            # Handle conversational input
            response_text = generate_conversational_response(user_input)
            logger.info("Conversational response generated")
            return jsonify({'response': response_text})
        else:
            # Handle search query
            logger.info(f"Processing search query: {user_input}")
            return process_search_query(user_input)
    except Exception as e:
        logger.error(f"Error in /interact: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500

def process_search_query(query):
    """Process a search query and return results with summaries."""
    results = fetch_trending_topics(query)
    
    # Process results and generate summaries
    individual_summaries = []
    processed_results = []
    
    for result in results:
        title = result.get('title', '')
        summary = result.get('summary', '')
        
        # Create individual summary
        full_summary = summarize_with_hf(f"{title} {summary}")
        individual_summaries.append(full_summary)
        
        # Add to processed results
        processed_results.append({
            'source': result.get('source', ''),
            'title': title,
            'summary': full_summary,
            'url': result.get('url', '')
        })
    
    # Generate overall summary
    general_summary = generate_general_summary(individual_summaries)
    
    # Prepare response
    final_response = {
        'query': query,
        'results': processed_results,
        'general_summary': general_summary
    }
    
    return jsonify(final_response)

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    """API endpoint for searching trends."""
    # Handle both GET and POST requests
    if request.method == 'GET':
        query = request.args.get('q', '')
    else:
        data = request.get_json()
        query = data.get('q', '') if data else ''
    
    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400
    
    # Sanitize input and process query
    query = sanitize_input(query)
    return process_search_query(query)

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler for all routes."""
    if isinstance(e, HTTPException):
        return e
    
    # Log unexpected errors
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    
    # Return user-friendly error
    return jsonify({
        'error': 'An unexpected error occurred. Please try again later.'
    }), 500

if __name__ == '__main__':
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    # Run app
    app.run(host='0.0.0.0', port=port, debug=debug)
