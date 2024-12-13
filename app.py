import os
import logging
from flask import Flask, request, jsonify, render_template
import time
import re
from functools import wraps

# Initialize Flask app
app = Flask(__name__)

# Security: Use secure headers
@app.after_request
def set_secure_headers(response):
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

# Setup logging
def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

setup_logging()
logger = logging.getLogger(__name__)

# Middleware for rate limiting
def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Implement a simple in-memory rate limiting
        key = 'global_rate_limit'
        if not hasattr(wrapper, 'requests'):  # Initialize request count
            wrapper.requests = 0
        if wrapper.requests >= 60:  # Limit to 60 requests/hour
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        wrapper.requests += 1
        return func(*args, **kwargs)
    return wrapper

# Helper function for input sanitization
def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Simulated synchronous API fetch
def fetch_trending_topics(query):
    time.sleep(2)  # Simulate network delay
    return [
        {"title": "Trending Topic 1", "summary": "Summary of topic 1", "url": "https://example.com/topic1"},
        {"title": "Trending Topic 2", "summary": "Summary of topic 2", "url": "https://example.com/topic2"},
        {"title": "Trending Topic 3", "summary": "Summary of topic 3", "url": "https://example.com/topic3"}
    ]

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to the Refactored App")

@app.route('/interact', methods=['POST'])
@rate_limit
def interact():
    user_input = request.json.get('input', '').strip()
    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400

    logger.info(f"Received user input: {user_input}")
    return jsonify({'message': 'Input received. Streaming is client-side now.'}), 200

@app.route('/search', methods=['GET'])
@rate_limit
def search_trends():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Query parameter \"q\" is required.'}), 400

    sanitized_query = sanitize_input(query)
    results = fetch_trending_topics(sanitized_query)
    return jsonify({"query": sanitized_query, "results": results}), 200

@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    try:
        query = request.json.get('q', '').strip()
        if not query:
            return jsonify({'error': 'Query parameter \"q\" is required.'}), 400

        sanitized_query = sanitize_input(query)
        entities = ["Entity1", "Entity2"]  # Simulated entity extraction
        return jsonify({"query": sanitized_query, "entities": entities}), 200
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
