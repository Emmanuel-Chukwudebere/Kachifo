# app.py
import os
import logging
import json
import re
from flask import Flask, request, jsonify, render_template, Response
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
from werkzeug.exceptions import HTTPException, BadRequest
from api_integrations import fetch_trending_topics, summarize_with_hf, extract_entities_with_hf, generate_conversational_response
from logging.handlers import RotatingFileHandler
from huggingface_hub import InferenceClient

# Initialize Flask app with enhanced security and performance configurations
app = Flask(__name__)

# Security: Use Flask-Talisman to enforce HTTPS and set secure headers
Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:', "'unsafe-inline'"],  # Allow inline scripts for streaming
    'style-src': ["'self'", 'https:', "'unsafe-inline'"],
    'img-src': ["'self'", 'data:', 'https:'],
    'connect-src': ["'self'", 'https:', 'wss:']  # Allow WebSocket connections
})

# Caching configuration - Using simple cache instead of database
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)

# Initialize Hugging Face Client
inference_client = InferenceClient(token=os.getenv("HUGGINGFACE_API_KEY"))

# Setup logging with enhanced error tracking
def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(logging.StreamHandler())

setup_logging()
logger = logging.getLogger(__name__)

# Helper function for standardized responses
def create_standard_response(data, status_code, message):
    """
    Creates a standardized JSON response format
    
    Args:
        data: The payload to be sent
        status_code (int): HTTP status code
        message (str): Response message
        
    Returns:
        tuple: JSON response and status code
    """
    response = {
        "data": data,
        "status": status_code,
        "message": message
    }
    return jsonify(response), status_code

# Rate limiting middleware
def rate_limit(func):
    """
    Decorator to implement rate limiting using cache
    Limits to 60 requests per hour per IP
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if request.headers.get('X-Real-IP'):
            key = f"rate_limit_{request.headers['X-Real-IP']}"
        else:
            key = f"rate_limit_{request.remote_addr}"
            
        remaining_requests = cache.get(key)
        
        if remaining_requests is None:
            remaining_requests = 60
        elif remaining_requests <= 0:
            logger.warning(f"Rate limit exceeded for IP: {key}")
            return create_standard_response(
                None, 
                429, 
                "Rate limit exceeded. Please try again later."
            )
            
        cache.set(key, remaining_requests - 1, timeout=3600)  # 1 hour timeout
        return func(*args, **kwargs)
    return wrapper

# Input sanitization and classification
def sanitize_input(query):
    """
    Sanitizes user input by removing special characters and excess whitespace
    
    Args:
        query (str): Raw user input
        
    Returns:
        str: Sanitized input
    """
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input):
    """
    Classifies input as either a query or conversation
    
    Args:
        user_input (str): User's input text
        
    Returns:
        str: 'query' or 'conversation'
    """
    query_pattern = re.compile(
        r'\b(search|find|look up|what is|tell me|trending|give me|show me)\b',
        re.IGNORECASE
    )
    return 'query' if query_pattern.search(user_input) else 'conversation'

# Routes
@app.route('/')
def home():
    """Renders the home page"""
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['POST'])
@rate_limit
def interact():
    """
    Main interaction endpoint handling both queries and conversations
    Returns complete response for frontend streaming
    """
    try:
        user_input = request.json.get('input')
        if not user_input:
            return create_standard_response(
                {'error': 'No input provided.'}, 
                400, 
                "Missing input"
            )

        input_type = classify_input_type(user_input)
        
        # Handle conversational input
        if input_type == 'conversation':
            response = generate_conversational_response(user_input)
            return jsonify({
                'type': 'conversation',
                'response': response
            })
            
        # Handle query input
        elif input_type == 'query':
            trends = fetch_trending_topics(user_input)
            processed_trends = []
            
            for trend in trends:
                summary = summarize_with_hf(
                    f"{trend.get('title', '')} {trend.get('description', '')}"
                )
                processed_trends.append({
                    'source': trend.get('source', ''),
                    'title': trend.get('title', ''),
                    'summary': summary,
                    'url': trend.get('url', '')
                })
                
            return jsonify({
                'type': 'query',
                'query': user_input,
                'results': processed_trends
            })
            
    except Exception as e:
        logger.error(f"Error in interact endpoint: {str(e)}", exc_info=True)
        return create_standard_response(
            None, 
            500, 
            "An unexpected error occurred. Please try again later."
        )

# Error handler for unhandled exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler for all unhandled exceptions"""
    if isinstance(e, HTTPException):
        return e
        
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return create_standard_response(
        None, 
        500, 
        "An unexpected error occurred. Please try again later."
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)