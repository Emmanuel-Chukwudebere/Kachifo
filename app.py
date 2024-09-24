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

# Caching configuration - Switch between 'redis' and 'simple' based on environment
if os.environ.get('REDIS_URL'):
    app.config['CACHE_TYPE'] = 'RedisCache'
    app.config['CACHE_REDIS_URL'] = os.environ['REDIS_URL']
else:
    app.config['CACHE_TYPE'] = 'SimpleCache'

cache = Cache(app)
db = SQLAlchemy(app)

# Trend and UserQuery Models
class Trend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.String(500), nullable=True)
    url = db.Column(db.String(255), nullable=False)

class UserQuery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())

# Advanced logging setup: Logs to file and console (stdout) for Render
LOG_FILE = "Kachifo.log"
logging.basicConfig(
    level=logging.DEBUG,  # Capture everything (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),       # Log to file
        logging.StreamHandler()              # Log to Render's stdout (console)
    ]
)

# Helper function to log request details
def log_request_details():
    logging.info(f"Request Method: {request.method}")
    logging.info(f"Request URL: {request.url}")
    logging.info(f"Request Headers: {request.headers}")
    if request.method == 'POST':
        logging.info(f"Request Body: {request.get_json()}")

# Simple rate-limiting decorator (e.g., 50 requests per day per user)
def rate_limit(func):
    """Decorator to limit number of API calls."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        user_ip = request.remote_addr
        key = f"rate_limit_{user_ip}"
        remaining_requests = cache.get(key)
        
        if remaining_requests is None:
            remaining_requests = 50
        elif remaining_requests <= 0:
            logging.warning(f"Rate limit exceeded for IP: {user_ip}")
            return jsonify({'error': 'Rate limit exceeded. Please try again tomorrow.'}), 429

        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        logging.info(f"Remaining requests for {user_ip}: {remaining_requests - 1}")
        return func(*args, **kwargs)

    return wrapper

# Sanitize input helper
def sanitize_input(query):
    """Sanitize input to prevent injection attacks."""
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logging.info(f"Sanitized input: {sanitized}")
    return sanitized

# Error handling for user-friendly responses
@app.errorhandler(HTTPException)
def handle_http_error(e):
    """Return user-friendly error messages."""
    logging.error(f"HTTP error occurred: {e.description} - Code: {e.code}")
    return jsonify({'error': e.description}), e.code

@app.errorhandler(SQLAlchemyError)
def handle_database_error(e):
    """Handle database errors gracefully."""
    logging.error(f"Database error: {str(e)}")
    return jsonify({'error': 'A database error occurred. Please try again later.'}), 500

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Handle unexpected errors gracefully."""
    logging.critical(f"Unexpected error: {str(e)}")
    return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# Routes
@app.route('/')
def home():
    """Home route."""
    logging.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    """Search for trending topics based on user input using both GET and POST."""
    log_request_details()  # Log request details for better traceability
    
    if request.method == 'GET':
        query = request.args.get('q', '')
    elif request.method == 'POST':
        data = request.get_json()
        if not data or 'q' not in data:
            logging.error("POST request missing 'q' in body")
            return jsonify({'error': 'Query parameter is required in body for POST'}), 400
        query = data['q']

    if not query:
        logging.warning("Search query is missing")
        return jsonify({'error': 'Query parameter is required'}), 400

    query = sanitize_input(query)
    
    try:
        results = fetch_trending_topics(query)
        logging.info(f"Search results for '{query}': {results}")
        
        # Store results in database
        for result in results:
            new_trend = Trend(
                query=query,
                source=result['source'],
                title=result['title'],
                summary=result['summary'],
                url=result['url']
            )
            db.session.add(new_trend)
        db.session.commit()

        return jsonify(results)
    except Exception as e:
        logging.error(f"Error while fetching trends: {str(e)}")
        return jsonify({'error': 'Failed to fetch trending topics. Please try again later.'}), 500

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)