import os
import logging
import json
import re
import random
import time  # For simulating delays in the streaming example
from flask import Flask, request, jsonify, render_template, Response, stream_with_context, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException, BadRequest
from api_integrations import fetch_trending_topics, summarize_with_hf, extract_entities_with_hf, generate_general_summary
from logging.handlers import RotatingFileHandler
from huggingface_hub import InferenceClient  # Import for Hugging Face API interaction

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

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_size': 10, 'pool_timeout': 30, 'max_overflow': 5}
db = SQLAlchemy(app)

# Caching configuration
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)

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
    entities = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=db.func.now())

    def set_hf_data(self, processed_data):
        self.entities = json.dumps(processed_data.get('entities', []))

    def get_hf_data(self):
        return {'entities': json.loads(self.entities) if self.entities else []}

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

setup_logging()
logger = logging.getLogger(__name__)

# Loading messages pool
loading_messages = [
    "Did you know AI can predict trends 10x faster than humans?",
    "Tip: Try searching for trending news about technology.",
    "Here’s a fun fact: The first tweet was posted in 2006 by Twitter's founder.",
    "Hold tight! We’re fetching the latest news from the web for you!",
    "Fun fact: The term ‘trending’ was popularized by social media platforms.",
    "Did you know that over 3.6 billion people use social media worldwide?",
    "Tip: Ask about the latest trends in your favorite topics!",
    "Here's a trivia: The word 'hashtag' was first used in 2007.",
    "Did you know: Google processes over 3.5 billion searches per day?",
    "Fun fact: The first ever online sale was made in 1994."
]

# Helper function for standardized responses
def create_standard_response(data, status_code, message):
    response = {
        "data": data,
        "status": status_code,
        "message": message
    }
    return response, status_code

# Middleware for logging requests and responses
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
        key = "global_rate_limit"
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            remaining_requests = 60
        elif remaining_requests <= 0:
            logger.warning("Global rate limit exceeded")
            return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        logger.info(f"Remaining global requests: {remaining_requests - 1}")
        response = func(*args, **kwargs)
        if isinstance(response, tuple):
            data, status_code = response
            response = make_response(jsonify(data), status_code)
        elif not isinstance(response, Response):
            response = make_response(jsonify(response), 200)
        response.headers['X-RateLimit-Remaining'] = str(remaining_requests - 1)
        response.headers['X-RateLimit-Limit'] = '60'
        return response
    return wrapper

# Input sanitization and classification
def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input):
    # Define a comprehensive regex pattern for query-type inputs
    query_pattern = re.compile(
        r'\b(search|find|look up|what is|tell me|trending|give me|show me|search for|what\'s new|help me|ask about|info on|tell me about|what are|who is|where can|when is|how to|latest|news|updates|discover|check out|any news on)\b',
        re.IGNORECASE
    )
    
    # Check if the input matches the query pattern
    if query_pattern.search(user_input):
        return 'query'
    else:
        return 'conversation'

# Streaming generator function to yield results in real-time
def stream_with_loading_messages(query):
    try:
        # Sending loading messages
        for _ in range(5):  # Adjust the number of loading messages as needed
            yield f"data: {random.choice(loading_messages)}\n\n"
            time.sleep(2)  # Wait before sending the next loading message
        
        # Now fetch the results after the loading messages
        results = fetch_trending_topics(query)  # Replace with the actual query passed by the user
        summaries = []
        individual_summaries = []  # For storing individual summaries
        
        for result in results:
            summary = summarize_with_hf(f"{result.get('title', '')} {result.get('summary', '')}")
            individual_summaries.append(summary)
            summaries.append({
                'source': result.get('source', ''),
                'title': result.get('title', ''),
                'summary': summary,
                'url': result.get('url', '')
            })
        
        # Generate a general summary from all individual summaries
        general_summary = generate_general_summary(individual_summaries)
        
        # Construct the prompt for BlenderBot
        bot_prompt = (
            f"User asked about trends in {query}. Here are the results:\n\n"
            f"General Summary: {general_summary}\n\n"
            f"Individual Results:\n" + "\n".join([f"- {s['title']}: {s['summary']}" for s in summaries])
        )

        # Get a conversational response from BlenderBot
        conversational_response = generate_conversational_response(bot_prompt)
        
        final_response = {
            'query': query,
            'results': summaries,
            'general_summary': general_summary,
            'dynamic_response': conversational_response  # Updated to use BlenderBot's response
        }
        
        # Send final combined result
        yield f"data: {json.dumps(final_response)}\n\n"
        logger.info(f"Streaming completed for '{query}'")
    except Exception as e:
        logger.error(f"Error while processing search: {str(e)}", exc_info=True)
        yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

# Generate conversational response using BlenderBot
def generate_conversational_response(user_input):
    # Replace with your Hugging Face API call to BlenderBot
    inference_client = InferenceClient(repo_id="facebook/blenderbot-400M-distill")  # Adjust based on your model
    response = inference_client.chat(user_input)  # Call the chat method to get a response
    return response['generated_text']  # Adjust according to the response format

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

# Route for interacting with the model
@app.route('/interact', methods=['GET', 'POST'])
def interact():
    if request.method == 'POST':
        user_input = request.json.get('input')
    else:
        # For GET requests, you may want to retrieve the input from query parameters
        user_input = request.args.get('input')

    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400  # Return error if no input is given

    # Determine if input is conversational or query-related
    input_type = classify_input_type(user_input)
    
    if input_type == 'conversation':
        # Use BlenderBot to respond to conversational queries
        response = generate_conversational_response(user_input)
    elif input_type == 'query':
        # Use streaming with loading messages for data fetching
        return Response(stream_with_context(stream_with_loading_messages(user_input)), content_type='text/event-stream')
    else:
        return jsonify({'error': 'Invalid input type.'}), 400  # Handle invalid input type

    return jsonify({'response': response})

# Routes for searching trends with streaming response
@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    try:
        if request.method == 'GET':
            query = request.args.get('q')
        elif request.method == 'POST':
            query = request.json.get('q') if request.is_json else request.form.get('q')
        else:
            raise BadRequest("Unsupported HTTP method")

        if not query:
            logger.warning(f"Search query is missing. Method: {request.method}, Headers: {request.headers}")
            return create_standard_response({'error': 'Query parameter "q" is required'}, 400, "Query parameter missing")

        query = sanitize_input(query)
        return Response(stream_with_context(stream_with_loading_messages(query)), content_type='text/event-stream')
    except BadRequest as e:
        logger.error(f"Bad request: {str(e)}")
        return create_standard_response(None, 400, str(e))
    except Exception as e:
        logger.error(f"Error while processing search: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

# Route for recent searches with streaming
@app.route('/recent_searches', methods=['GET'])
@rate_limit
def recent_searches():
    try:
        return Response(stream_with_context(stream_recent_searches()), content_type='text/event-stream')
    except Exception as e:
        logger.error(f"Error fetching recent searches: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

# Process query with streaming
@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    try:
        if request.is_json:
            query = request.json.get('q')
        else:
            query = request.form.get('q')
        if not query:
            logger.warning("Query is missing")
            return create_standard_response({'error': 'Query is required'}, 400, "Query is required")

        query = sanitize_input(query)
        # Extract entities from query using Hugging Face API
        processed_query_data = extract_entities_with_hf(query)
        # Store the query in the database
        new_query = UserQuery(query=query)
        new_query.set_hf_data(processed_query_data)
        db.session.add(new_query)
        db.session.commit()
        logger.info("Query stored in the database")
        return Response(stream_with_context(stream_with_loading_messages(query)), content_type='text/event-stream')
    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

# Error handler for unhandled exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

# Initialize the database
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Initialize the database
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))