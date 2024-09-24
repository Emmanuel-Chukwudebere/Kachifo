import os
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
import time
import re
from api_integrations import fetch_trending_topics
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError

# Initialize Flask app
app = Flask(__name__)

# Load configuration from environment variables
# app.config.from_object('config.ProductionConfig')

# Security: Use Flask-Talisman to enforce HTTPS, set secure headers (Content Security Policy)
Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:'],
    'style-src': ["'self'", 'https:']
})

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Caching configuration
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
    timestamp = db.Column(db.DateTime, default=db.func.now())

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
    
    # Set Flask and SQLAlchemy loggers to use the same handlers
    for logger_name in ('werkzeug', 'sqlalchemy.engine'):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(log_level)

setup_logging()
logger = logging.getLogger(__name__)

# Request logging middleware
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
        user_ip = request.remote_addr
        key = f"rate_limit_{user_ip}"
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            remaining_requests = 50
        elif remaining_requests <= 0:
            logger.warning(f"Rate limit exceeded for IP: {user_ip}")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        logger.info(f"Remaining requests for {user_ip}: {remaining_requests - 1}")
        return func(*args, **kwargs)
    return wrapper

# Input sanitization
def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Error handlers
@app.errorhandler(HTTPException)
def handle_http_error(e):
    logger.error(f"HTTP error occurred: {e.description} - Code: {e.code}")
    return jsonify({'error': e.description}), e.code

@app.errorhandler(SQLAlchemyError)
def handle_database_error(e):
    logger.error(f"Database error: {str(e)}")
    return jsonify({'error': 'A database error occurred. Please try again later.'}), 500

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.critical(f"Unexpected error: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

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
            return jsonify({'error': 'Query parameter "q" is required'}), 400

        query = sanitize_input(query)
        current_app.logger.info(f"Processing search query: {query}")

        results = fetch_trending_topics(query)
        current_app.logger.info(f"Search results for '{query}': {len(results)} items found")

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

        # Store user query
        new_query = UserQuery(query=query)
        db.session.add(new_query)
        db.session.commit()

        return jsonify(results)

    except BadRequest as e:
        current_app.logger.error(f"Bad request: {str(e)}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error while processing search: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@app.route('/recent_searches', methods=['GET'])
def recent_searches():
    try:
        recent_queries = UserQuery.query.order_by(UserQuery.timestamp.desc()).limit(10).all()
        return jsonify([query.query for query in recent_queries])
    except Exception as e:
        logger.error(f"Error fetching recent searches: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to fetch recent searches. Please try again later.'}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))