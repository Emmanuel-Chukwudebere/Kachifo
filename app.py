from flask import Flask, request, jsonify, render_template, g
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
import spacy
import logging
import os
import time
import re
from api_integrations import fetch_trending_topics  # Import API integration logic
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError

# Initialize Flask app
app = Flask(__name__)

# Security: Use Flask-Talisman to enforce HTTPS, set secure headers (Content Security Policy)
Talisman(app, content_security_policy={
    'default-src': ['\'self\'', 'https:'],
    'script-src': ['\'self\'', 'https:'],
    'style-src': ['\'self\'', 'https:']
})

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///default.db')  # Ensure environment variable is set for production
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Caching configuration
app.config['CACHE_TYPE'] = 'simple'  # Use Redis in production for better performance
app.config['CACHE_DEFAULT_TIMEOUT'] = 3600  # 1 hour
cache = Cache(app)

# Initialize database
db = SQLAlchemy(app)

# Initialize logging
if not app.debug:
    logging.basicConfig(
        filename='Kachifo.log',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(remote_addr)s] %(message)s'
    )

# Load SpaCy model
nlp = spacy.load("en_core_web_sm")  # Small model to save memory

# Rate limit setup (70 requests/day per IP)
LIMIT = 70
RATE_LIMIT_RESET = 24 * 60 * 60  # Reset after 24 hours
rate_limit_cache = {}

def rate_limiter():
    """Decorator to rate limit users based on their IP address."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_ip = request.remote_addr
            current_time = time.time()

            if user_ip in rate_limit_cache:
                requests_made, first_request_time = rate_limit_cache[user_ip]

                if requests_made >= LIMIT:
                    if current_time - first_request_time < RATE_LIMIT_RESET:
                        logging.warning(f"Rate limit exceeded for IP: {user_ip}")
                        return jsonify({"error": "Rate limit exceeded. Please wait before making more requests."}), 429
                    else:
                        # Reset the count after 24 hours
                        rate_limit_cache[user_ip] = (0, current_time)

            # Update rate limit cache
            if user_ip not in rate_limit_cache:
                rate_limit_cache[user_ip] = (1, current_time)
            else:
                rate_limit_cache[user_ip] = (rate_limit_cache[user_ip][0] + 1, rate_limit_cache[user_ip][1])

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def sanitize_input(input_data):
    """Sanitize input to prevent injection attacks."""
    sanitized = re.sub(r'[^\w\s]', '', input_data)
    logging.info(f"Sanitized input: {sanitized}")
    return sanitized

# SpaCy NLP processing function
def analyze_text(text):
    """Process text input using SpaCy for named entity recognition and keyword extraction."""
    doc = nlp(text)
    entities = [(ent.text, ent.label_) for ent in doc.ents]  # Extract entities
    tokens = [token.text for token in doc if token.is_alpha and not token.is_stop]  # Filter keywords
    return {
        "entities": entities,
        "keywords": tokens
    }

# Error handling
@app.errorhandler(HTTPException)
def handle_http_exception(e):
    """Handle general HTTP exceptions."""
    logging.error(f"HTTP error: {e.description}")
    return jsonify({"error": e.description}), e.code

@app.errorhandler(500)
def internal_server_error(error):
    """Handle internal server errors."""
    logging.error(f"Internal server error: {str(error)}")
    return jsonify({"error": "An internal error occurred. Please try again later."}), 500

# Centralized 404 handler for unknown routes
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    logging.warning(f"404 error: {request.url} not found")
    return jsonify({"error": "Endpoint not found."}), 404

# Route: Home
@app.route('/')
def home():
    """Render the homepage."""
    return render_template('index.html')  # Ensure index.html is in your templates folder

# Route: Search trends
@app.route('/search', methods=['GET'])
@rate_limiter()
@cache.cached(timeout=60 * 60, query_string=True)  # Cache for 1 hour based on query string
def search_trend():
    """Search for trends based on user query."""
    query = request.args.get('q')
    if not query:
        return jsonify({"error": "Query parameter 'q' is required."}), 400
    
    sanitized_query = sanitize_input(query)
    
    # Fetch trends from external APIs
    try:
        result = fetch_trending_topics (sanitized_query)
        if not result:
            logging.error(f"No trends found for query: {sanitized_query}")
            return jsonify({"error": "No trends found."}), 404
    except Exception as e:
        logging.error(f"Error fetching trends for query '{sanitized_query}': {str(e)}")
        return jsonify({"error": "Failed to fetch trends. Please try again."}), 500

    # Analyze text using SpaCy
    analysis = analyze_text(sanitized_query)

    logging.info(f"Fetched trends and analyzed text for query: {sanitized_query}")
    return jsonify({"data": result, "analysis": analysis})

# Database session handling
@app.teardown_appcontext
def shutdown_session(exception=None):
    """Ensure the database session is properly closed after each request."""
    try:
        db.session.remove()
    except SQLAlchemyError as e:
        logging.error(f"Error closing database session: {str(e)}")

# Run the app in production (Gunicorn will handle this in a proper setup)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Default to port 5000 if PORT is not set
    app.run(host="0.0.0.0", port=port)
