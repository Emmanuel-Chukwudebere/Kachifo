import os
import logging
import json
import re
from flask import Flask, request, jsonify, render_template
from flask_talisman import Talisman
from functools import wraps
from werkzeug.exceptions import HTTPException
from api_integrations import fetch_trending_topics, summarize_with_hf, extract_entities_with_hf
from logging.handlers import RotatingFileHandler
from huggingface_hub import InferenceClient

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

# Initialize Hugging Face Client
inference_client = InferenceClient(token=os.getenv("HUGGINGFACE_API_KEY"))

# Setup logging
def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10 * 1024 * 1024,
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
    Creates a standardized API response format.
    
    Args:
        data: The payload to be returned to the client
        status_code (int): HTTP status code
        message (str): Human-readable message describing the response
        
    Returns:
        tuple: (response_dict, status_code)
    """
    response = {
        "data": data,
        "status": status_code,
        "message": message
    }
    return response, status_code

# Rate limiting using in-memory storage
class RateLimit:
    """
    Simple in-memory rate limiting implementation.
    For production, consider using Redis or a similar distributed cache.
    """
    def __init__(self, requests_per_minute=60):
        self.requests = {}
        self.limit = requests_per_minute
        self.cleanup_counter = 0
    
    def is_allowed(self, ip):
        current_time = time.time()
        self.cleanup_counter += 1
        
        # Cleanup old entries every 100 requests
        if self.cleanup_counter >= 100:
            self._cleanup(current_time)
            self.cleanup_counter = 0
        
        # Initialize or get existing window
        if ip not in self.requests:
            self.requests[ip] = []
        
        # Remove requests older than 1 minute
        self.requests[ip] = [t for t in self.requests[ip] 
                           if current_time - t < 60]
        
        # Check if limit is exceeded
        if len(self.requests[ip]) >= self.limit:
            return False
        
        # Add new request
        self.requests[ip].append(current_time)
        return True
    
    def _cleanup(self, current_time):
        """Remove entries older than 1 minute to prevent memory growth"""
        for ip in list(self.requests.keys()):
            if all(current_time - t >= 60 for t in self.requests[ip]):
                del self.requests[ip]

rate_limiter = RateLimit()

# Rate limiting middleware
def rate_limit(func):
    """
    Decorator to apply rate limiting to routes.
    Uses client IP address for tracking request frequency.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        client_ip = request.remote_addr
        
        if not rate_limiter.is_allowed(client_ip):
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            return create_standard_response(
                None, 
                429, 
                "Rate limit exceeded. Please try again later."
            )
            
        return func(*args, **kwargs)
    return wrapper

# Input processing
def sanitize_input(query):
    """
    Sanitizes user input by removing special characters and excess whitespace.
    
    Args:
        query (str): Raw user input
        
    Returns:
        str: Sanitized input string
    """
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input):
    """
    Determines whether the input is a search query or conversational.
    
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

# Request logging middleware
@app.before_request
def log_request_info():
    """Logs incoming request details for monitoring and debugging"""
    logger.info(f'Request: {request.method} {request.url}')
    logger.debug(f'Headers: {request.headers}')
    if request.is_json:
        logger.debug(f'Body: {request.get_json()}')

@app.after_request
def log_response_info(response):
    """Logs response details and adds security headers"""
    logger.info(f'Response: {response.status}')
    logger.debug(f'Headers: {response.headers}')
    
    # Add security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response

# Routes
@app.route('/')
def home():
    """Serves the main application page"""
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['GET', 'POST'])
@rate_limit
async def interact():
    """
    Main interaction endpoint handling both query and conversational inputs.
    
    Returns:
        JSON response containing either search results or conversational response
    """
    try:
        user_input = request.json.get('input') if request.method == 'POST' else request.args.get('input')
        
        if not user_input:
            return create_standard_response(
                {'error': 'No input provided.'}, 
                400, 
                "Missing input parameter"
            )

        input_type = classify_input_type(user_input)
        sanitized_input = sanitize_input(user_input)

        if input_type == 'conversation':
            # Handle conversational input with HuggingFace
            response = await inference_client.chat_completion(
                messages=[{"role": "user", "content": sanitized_input}],
                model="facebook/blenderbot-400M-distill"
            )
            return create_standard_response(
                response.get('choices', [{}])[0].get('message', {}).get('content'),
                200,
                "Conversation response generated successfully"
            )
            
        else:  # Handle query-type input
            results = await fetch_trending_topics(sanitized_input)
            
            # Process and summarize results
            processed_results = []
            for result in results:
                summary = await summarize_with_hf(
                    f"{result.get('title', '')} {result.get('summary', '')}"
                )
                processed_results.append({
                    'source': result.get('source', ''),
                    'title': result.get('title', ''),
                    'summary': summary,
                    'url': result.get('url', '')
                })

            return create_standard_response(
                {
                    'query': sanitized_input,
                    'results': processed_results
                },
                200,
                "Search results generated successfully"
            )

    except Exception as e:
        logger.error(f"Error in interact endpoint: {str(e)}", exc_info=True)
        return create_standard_response(
            None,
            500,
            "An unexpected error occurred. Please try again later."
        )

# Error handling
@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler for all unhandled exceptions"""
    if isinstance(e, HTTPException):
        return create_standard_response(None, e.code, str(e))
        
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return create_standard_response(
        None,
        500,
        "An unexpected error occurred. Please try again later."
    )

if __name__ == '__main__':
    # Initialize the application
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting application on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)