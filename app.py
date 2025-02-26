import os
import logging
import json
import re
import random
import time

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

app = Flask(__name__)

Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:'],
    'style-src': ["'self'", 'https:'],
    'img-src': ["'self'", 'data:'],
    'connect-src': ["'self'", 'https:']
})

app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)

def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(logging.StreamHandler())

setup_logging()
logger = logging.getLogger(__name__)

def create_standard_response(data, status_code, message):
    response = {"data": data, "status": status_code, "message": message}
    return response, status_code

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

def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = "global_rate_limit"
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            remaining_requests = 60
        elif remaining_requests <= 0:
            logger.warning("Rate limit exceeded")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        return func(*args, **kwargs)
    return wrapper

def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input):
    query_pattern = re.compile(r'\b(search|find|look up|what is|tell me|trending|give me|show me)\b', re.IGNORECASE)
    if query_pattern.search(user_input):
        return 'query'
    return 'conversation'

@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['POST'])
@rate_limit
def interact():
    user_input = request.json.get('input')
    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400

    input_type = classify_input_type(user_input)
    
    if input_type == 'conversation':
        try:
            response_text = generate_conversational_response(user_input)
            logger.info("Conversational response generated.")
            return jsonify({'response': response_text})
        except Exception as e:
            logger.error(f"Error generating conversational response: {str(e)}", exc_info=True)
            return jsonify({'error': 'An error occurred. Please try again later.'}), 500

    elif input_type == 'query':
        try:
            logger.info(f"Handling query: {user_input}")
            results = fetch_trending_topics(user_input)
            individual_summaries = []
            summaries = []
            for result in results:
                title = result.get('title', '')
                summary = result.get('summary', '')
                full_summary = summarize_with_hf(f"{title} {summary}")
                individual_summaries.append(full_summary)
                summaries.append({
                    'source': result.get('source', ''),
                    'title': title,
                    'summary': full_summary,
                    'url': result.get('url', '')
                })
            general_summary = generate_general_summary(individual_summaries)
            final_response = {
                'query': user_input,
                'results': summaries,
                'general_summary': general_summary
            }
            return jsonify(final_response)
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return jsonify({'error': 'An error occurred while processing your request.'}), 500
    else:
        return jsonify({'error': 'Invalid input type.'}), 400

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    query = request.args.get('q') if request.method == 'GET' else request.json.get('q')
    if not query:
        return jsonify({'error': 'Query parameter "q" is required.'}), 400

    query = sanitize_input(query)
    try:
        results = fetch_trending_topics(query)
        individual_summaries = []
        summaries = []
        for result in results:
            title = result.get('title', '')
            summary = result.get('summary', '')
            full_summary = summarize_with_hf(f"{title} {summary}")
            individual_summaries.append(full_summary)
            summaries.append({
                'source': result.get('source', ''),
                'title': title,
                'summary': full_summary,
                'url': result.get('url', '')
            })
        general_summary = generate_general_summary(individual_summaries)
        final_response = {
            'query': query,
            'results': summaries,
            'general_summary': general_summary
        }
        return jsonify(final_response)
    except Exception as e:
        logger.error(f"Error searching trends: {str(e)}", exc_info=True)
        return jsonify({'error': 'An error occurred while fetching trends.'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))