import os
import logging
import re
import time
from flask import Flask, request, jsonify, render_template
from functools import wraps

# Flask Application Initialization
app = Flask(__name__)

# Security Headers
@app.after_request
def set_secure_headers(response):
    """Sets secure headers to prevent vulnerabilities."""
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

# Logging Configuration
def setup_logging():
    """Sets up application logging."""
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

setup_logging()
logger = logging.getLogger(__name__)

# Middleware: Rate Limiting
def rate_limit(func):
    """Limits the number of requests a user can make."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not hasattr(wrapper, 'request_count'):
            wrapper.request_count = 0
        if wrapper.request_count >= 60:  # Limit to 60 requests per hour
            return jsonify({'error': 'Rate limit exceeded. Try again later.'}), 429
        wrapper.request_count += 1
        return func(*args, **kwargs)
    return wrapper

# Input Sanitization
def sanitize_input(query):
    """Sanitizes user input to prevent injection attacks."""
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Simulated Data Fetch
def fetch_trending_topics(query):
    """Simulates an API call to fetch trending topics."""
    time.sleep(2)  # Simulate network delay
    return [
        {"title": "Trending Topic 1", "summary": "Summary of topic 1", "url": "https://example.com/topic1"},
        {"title": "Trending Topic 2", "summary": "Summary of topic 2", "url": "https://example.com/topic2"},
        {"title": "Trending Topic 3", "summary": "Summary of topic 3", "url": "https://example.com/topic3"}
    ]

# Routes
@app.route('/')
def home():
    """Renders the homepage for the Kachifo web app."""
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover Trends")

@app.route('/interact', methods=['POST'])
@rate_limit
def interact():
    """Handles user interactions and forwards input for processing."""
    user_input = request.json.get('input', '').strip()
    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400

    logger.info(f"Received user input: {user_input}")
    return jsonify({'message': 'Input received. Streaming handled client-side.'}), 200

@app.route('/search', methods=['GET'])
@rate_limit
def search_trends():
    """Fetches trending topics based on user query."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Query parameter "q" is required.'}), 400

    sanitized_query = sanitize_input(query)
    results = fetch_trending_topics(sanitized_query)
    return jsonify({"query": sanitized_query, "results": results}), 200

@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    """Processes user query and performs basic entity extraction."""
    try:
        query = request.json.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Query parameter "q" is required.'}), 400

        sanitized_query = sanitize_input(query)
        entities = ["Entity1", "Entity2"]  # Simulated entity extraction
        return jsonify({"query": sanitized_query, "entities": entities}), 200
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))