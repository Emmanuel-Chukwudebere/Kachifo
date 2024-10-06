import os
import logging
import json
import re
import random
import asyncio
import time
import threading
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException, BadRequest
from api_integrations import fetch_trending_topics, summarize_with_hf, extract_entities_with_hf, generate_conversational_response
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

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///production.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Caching configuration
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)

# Initialize Hugging Face Client for BlenderBot
inference_client = InferenceClient(token=os.getenv("HUGGINGFACE_API_KEY"))

# Models for Trends and User Queries
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

# Setup logging
def setup_logging():
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(logging.StreamHandler())

setup_logging()
logger = logging.getLogger(__name__)

# Loading messages pool
loading_messages = [
    "AI is fetching trends for you!",
    "Hold tight! We're gathering data...",
    "Did you know: The term ‘trending’ was popularized by social media?"
    "Did you know? Honey never spoils.",
    "Fact: Bananas are berries, but strawberries aren't!",
    "Fun fact: Octopuses have three hearts.",
    "A group of flamingos is called a 'flamboyance.'",
    "Cats have fewer toes on their back paws.",
    "Sharks existed before trees.",
    "A snail can sleep for three years.",
    "Wombat poop is cube-shaped.",
    "You can't hum while holding your nose closed.",
    "Bees can recognize human faces."
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

# Rate limiting middleware
def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = "global_rate_limit"
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            remaining_requests = 60
        elif remaining_requests <= 0:
            logger.warning("Rate limit exceeded")
            return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        response = func(*args, **kwargs)
        return response
    return wrapper

# Input sanitization and classification
def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input):
    query_pattern = re.compile(
        r'\b(search|find|look up|what is|tell me|trending|give me|show me)\b',
        re.IGNORECASE
    )
    if query_pattern.search(user_input):
        return 'query'
    return 'conversation'

# Asynchronous fetching of results
async def fetch_async(query):
    return fetch_trending_topics(query)

# Stream loading messages and final results
async def stream_with_loading_messages(query):
    global results
    results = await fetch_async(query)

    # Streaming loading messages until data is fetched
    while not results:
        yield f"data: {random.choice(loading_messages)}\n\n"
        await asyncio.sleep(2)

    if results:
        summaries = []
        individual_summaries = []
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
        yield f"data: {json.dumps(final_response)}\n\n"
    else:
        yield "data: {'error': 'No results found.'}\n\n"

# Stream BlenderBot responses
async def stream_blender_response(response_stream):
    try:
        async for token in response_stream:
            yield f"data: {token['choices'][0]['delta']['content']}\n\n"
    except Exception as e:
        logger.error(f"Error while streaming response: {str(e)}")
        yield "data: {'error': 'Failed to generate response.'}\n\n"

def async_to_sync(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.get_event_loop().run_until_complete(f(*args, **kwargs))
    return wrapper

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['GET', 'POST'])
@rate_limit
def interact():
    user_input = request.json.get('input') if request.method == 'POST' else request.args.get('input')
    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400

    input_type = classify_input_type(user_input)

    # Handle conversational input with BlenderBot
    if input_type == 'conversation':
        try:
            @async_to_sync
            async def generate_blender_response():
                response_stream = await inference_client.chat_completion(
                    messages=[{"role": "user", "content": user_input}],
                    stream=True
                )
                async for token in response_stream:
                    yield f"data: {token['choices'][0]['delta']['content']}\n\n"
            
            return Response(stream_with_context(generate_blender_response()), content_type='text/event-stream')
        except Exception as e:
            logger.error(f"Error with BlenderBot: {str(e)}", exc_info=True)
            return create_standard_response(None, 500, "An error occurred. Please try again later.")

    # Handle query-type input
    elif input_type == 'query':
        try:
            logger.info(f"Handling query: {user_input}")
            
            @async_to_sync
            async def generate_query_response():
                async for message in stream_with_loading_messages(user_input):
                    yield message

            return Response(stream_with_context(generate_query_response()), content_type='text/event-stream')
        except Exception as e:
            logger.error(f"Error streaming query: {str(e)}", exc_info=True)
            return create_standard_response(None, 500, "An error occurred while processing your request.")

    return jsonify({'error': 'Invalid input type.'}), 400

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    query = request.args.get('q') if request.method == 'GET' else request.json.get('q')
    if not query:
        return create_standard_response({'error': 'Query parameter "q" is required'}, 400, "Query parameter missing")
    
    query = sanitize_input(query)

    @async_to_sync
    async def generate_search_response():
        async for message in stream_with_loading_messages(query):
            yield message

    return Response(stream_with_context(generate_search_response()), content_type='text/event-stream')

@app.route('/process-query', methods=['POST'])
@rate_limit
def process_query():
    try:
        query = request.json.get('q') if request.is_json else request.form.get('q')
        if not query:
            logger.warning("Query is missing")
            return create_standard_response({'error': 'Query is required'}, 400, "Query is required")
        
        query = sanitize_input(query)

        @async_to_sync
        async def process_query_async():
            # Extract entities from query using Hugging Face API
            processed_query_data = await extract_entities_with_hf(query)
            
            # Store the query in the database
            new_query = UserQuery(query=query)
            new_query.set_hf_data(processed_query_data)
            db.session.add(new_query)
            db.session.commit()
            
            # Generate trending topics
            trends = await fetch_trending_topics(query)
            
            # Summarize trends
            summaries = []
            for trend in trends:
                title = trend.get('title', '')
                summary = trend.get('summary', '')
                full_summary = await summarize_with_hf(f"{title} {summary}")
                summaries.append(full_summary)
            
            # Generate a general summary
            general_summary = await generate_general_summary(summaries)
            
            # Prepare context for BlenderBot
            context = f"Query: {query}\nTrending topics: {general_summary}"
            
            # Generate conversational response using BlenderBot
            response_stream = await inference_client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are an AI assistant helping with trending topics."},
                    {"role": "user", "content": context}
                ],
                stream=True
            )
            
            # Stream the response
            async for token in response_stream:
                yield f"data: {token['choices'][0]['delta']['content']}\n\n"

        return Response(stream_with_context(process_query_async()), content_type='text/event-stream')
    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

@app.route('/recent_searches', methods=['GET'])
@rate_limit
def recent_searches():
    try:
        @async_to_sync
        async def fetch_recent_searches_async():
            # Fetch recent searches from the database asynchronously
            recent_queries = await fetch_recent_queries()
            for q in recent_queries:
                yield f"data: {q.query}\n\n"

        return Response(stream_with_context(fetch_recent_searches_async()), content_type='text/event-stream')
    except Exception as e:
        logger.error(f"Error fetching recent searches: {str(e)}", exc_info=True)
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