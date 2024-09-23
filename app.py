from flask import Flask, request, jsonify, render_template, g
from flask_sqlalchemy import SQLAlchemy
from transformers import pipeline
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
import logging
import os
import time
import re
from api_integrations import fetch_trends_from_apis  # Import API integration logic
from werkzeug.exceptions import HTTPException

# Initialize Flask app
app = Flask(__name__)

# Security: Use Flask-Talisman to enforce HTTPS, set secure headers (Content Security Policy)
talisman = Talisman(app)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///default.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Caching configuration
app.config['CACHE_TYPE'] = 'simple'  # Can be upgraded to 'redis' or other caching backends in production
cache = Cache(app)

# Initialize database
db = SQLAlchemy(app)

# Initialize logging
logging.basicConfig(
    filename='Kachifo.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(remote_addr)s] %(message)s'
)

# Lazy model loading for better resource usage in production
huggingface_model = None
def load_huggingface_model():
    global huggingface_model
    if huggingface_model is None:
        huggingface_model = pipeline('text-generation', model='distilgpt2', framework="pt")
    return huggingface_model

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

# Lazy load model and cache it to avoid resource overuse
@app.before_request
def before_request():
    g.model = load_huggingface_model()  # Lazy load and attach to request context

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
        result = fetch_trends_from_apis(sanitized_query)
        if not result:
            logging.error(f"No trends found for query: {sanitized_query}")
            return jsonify({"error": "No trends found."}), 404
    except Exception as e:
        logging.error(f"Error fetching trends for query '{sanitized_query}': {str(e)}")
        return jsonify({"error": "Failed to fetch trends. Please try again."}), 500

    logging.info(f"Fetched trends for query: {sanitized_query}")
    return jsonify({"data": result})

# Route: Generate text using Hugging Face model
@app.route('/generate', methods=['POST'])
@rate_limiter()
def generate_text():
    """Generate text using the Hugging Face model."""
    input_data = request.json.get('input')
    if not input_data:
        return jsonify({"error": "Input text is required."}), 400

    sanitized_input = sanitize_input(input_data)

    try:
        output = g.model(sanitized_input, max_length=50, num_return_sequences=1)
        logging.info(f"Generated text for input: {sanitized_input}")
        return jsonify({"generated_text": output[0]['generated_text']})
    except Exception as e:
        logging.error(f"Error generating text: {str(e)}")
        return jsonify({"error": "Failed to generate text."}), 500

# Database session handling
@app.teardown_appcontext
def shutdown_session(exception=None):
    """Ensure the database session is properly closed after each request."""
    db.session.remove()

# Run the app in production (Gunicorn will handle this in a proper setup)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Default to port 5000 if PORT is not set
    app.run(host="0.0.0.0", port=port)  # Ensure debug=False in production