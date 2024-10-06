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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from marshmallow import Schema, fields, validate

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
    "Did you know: The term ‘trending’ was popularized by social media?",
    "Did you know? Honey never spoils.",
    "Fact: Bananas are berries, but strawberries aren't!",
    "Fun fact: Octopuses have three hearts.",
    "A group of flamingos is called a 'flamboyance.'",
    "Cats have fewer toes on their back paws.",
    "Sharks existed before trees.",
    "A snail can sleep for three years.",
    "Wombat poop is cube-shaped.",
    "You can't hum while holding your nose closed.",
    "Bees can recognize human faces.",
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
        key = f"global_rate_limit:{request.remote_addr}"
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            remaining_requests = 60
        elif remaining_requests <= 0:
            logger.warning(f"Rate limit exceeded for IP: {request.remote_addr}")
            return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")
        cache.set(key, remaining_requests - 1, timeout=24 * 3600)
        return func(*args, **kwargs)
    return wrapper

# request validation
class InteractSchema(Schema):
    input = fields.Str(required=True, validate=validate.Length(min=1, max=1000))

class SearchSchema(Schema):
    q = fields.Str(required=True, validate=validate.Length(min=1, max=200))

class ProcessQuerySchema(Schema):
    q = fields.Str(required=True, validate=validate.Length(min=1, max=200))

def validate_request(schema_class):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            schema = schema_class()
            if request.method == 'GET':
                errors = schema.validate(request.args)
            else:
                if request.is_json:
                    errors = schema.validate(request.json)
                else:
                    errors = schema.validate(request.form)
            
            if errors:
                return create_standard_response({'errors': errors}, 400, "Invalid request parameters")
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# rate limit per ip
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100 per day", "30 per hour"]
)

# Then attach it to the app
limiter.init_app(app)

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

# Helper for async handling in synchronous context
def async_to_sync(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))  # Create and run a new event loop
    return wrapper

# Stream BlenderBot responses
async def stream_blender_response(user_input, response_started):
    try:
        response_stream = await inference_client.chat_completion(messages=[{"role": "user", "content": user_input}], stream=True)
        response_started.set()  # Signal that the response has started
        async for token in response_stream:
            yield f"data: {token['choices'][0]['delta']['content']}\n\n"
    except Exception as e:
        response_started.set()
        logger.error(f"Error with BlenderBot: {str(e)}", exc_info=True)
        yield "data: {'error': 'Failed to generate response.'}\n\n"

# Stream loading messages until the response starts
async def send_loading_messages(response_started):
    while not response_started.is_set():
        loading_message = random.choice(loading_messages)
        yield f"data: {loading_message}\n\n"
        await asyncio.sleep(2)
        
# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
@validate_request(InteractSchema)
def interact():
    user_input = request.json.get('input') if request.method == 'POST' else request.args.get('input')
    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400

    input_type = classify_input_type(user_input)

    @async_to_sync
    async def generate_response():
        response_started = asyncio.Event()

        async def send_loading_messages():
            while not response_started.is_set():
                loading_message = random.choice(loading_messages)
                yield f"data: {loading_message}\n\n"
                await asyncio.sleep(2)

        async def process_input():
            try:
                if input_type == 'conversation':
                    response_stream = await inference_client.chat_completion(
                        messages=[{"role": "user", "content": user_input}],
                        stream=True
                    )
                    response_started.set()
                    async for token in response_stream:
                        yield f"data: {token['choices'][0]['delta']['content']}\n\n"
                else:  # query
                    trends = await fetch_trending_topics(user_input)
                    summaries = []
                    for trend in trends:
                        summary = await summarize_with_hf(f"{trend['title']} {trend['summary']}")
                        summaries.append({
                            'source': trend['source'],
                            'title': trend['title'],
                            'summary': summary,
                            'url': trend['url']
                        })
                    response_started.set()
                    yield f"data: {json.dumps({'query': user_input, 'results': summaries})}\n\n"
            except Exception as e:
                response_started.set()
                logger.error(f"Error processing input: {str(e)}", exc_info=True)
                yield f"data: {{'error': 'An error occurred. Please try again later.'}}\n\n"

        async def merged_stream():
            loading_task = asyncio.create_task(send_loading_messages().__anext__())
            process_task = asyncio.create_task(process_input().__anext__())
            while True:
                done, pending = await asyncio.wait(
                    [loading_task, process_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if loading_task in done:
                    try:
                        loading_message = loading_task.result()
                        yield loading_message
                        if not response_started.is_set():
                            loading_task = asyncio.create_task(send_loading_messages().__anext__())
                    except StopAsyncIteration:
                        pass
                if process_task in done:
                    try:
                        response_message = process_task.result()
                        yield response_message
                        process_task = asyncio.create_task(process_input().__anext__())
                    except StopAsyncIteration:
                        break

        return Response(stream_with_context(merged_stream()), content_type='text/event-stream')

    return generate_response()

# Route to search trends
@app.route('/search', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
@validate_request(SearchSchema)
def search_trends():
    query = request.args.get('q') if request.method == 'GET' else request.json.get('q')
    if not query:
        return create_standard_response({'error': 'Query parameter "q" is required'}, 400, "Query parameter missing")

    query = sanitize_input(query)

    @async_to_sync
    async def generate_search_response():
        try:
            results = await fetch_trending_topics(query)
            if not results:
                yield "data: {'error': 'No results found.'}\n\n"
                return

            summaries = []
            individual_summaries = []
            for result in results:
                title = result.get('title', '')
                summary = result.get('summary', '')
                full_summary = await summarize_with_hf(f"{title} {summary}")
                individual_summaries.append(full_summary)
                summaries.append({
                    'source': result.get('source', ''),
                    'title': title,
                    'summary': full_summary,
                    'url': result.get('url', '')
                })

            general_summary = await generate_general_summary(individual_summaries)
            final_response = {'query': query, 'results': summaries, 'general_summary': general_summary}
            yield f"data: {json.dumps(final_response)}\n\n"
        except Exception as e:
            logger.error(f"Error in search_trends: {str(e)}", exc_info=True)
            yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

    return Response(stream_with_context(generate_search_response()), content_type='text/event-stream')

@app.route('/process-query', methods=['POST'])
@limiter.limit("10 per minute")
@validate_request(ProcessQuerySchema)
def process_query():
    try:
        query = request.json.get('q') if request.is_json else request.form.get('q')
        if not query:
            logger.warning("Query is missing")
            return create_standard_response({'error': 'Query is required'}, 400, "Query is required")
        
        query = sanitize_input(query)

        @async_to_sync
        async def process_query_async():
            response_started = asyncio.Event()

            # Function to yield loading messages
            async def send_loading_messages():
                while not response_started.is_set():
                    loading_message = random.choice(loading_messages)
                    yield f"data: {loading_message}\n\n"
                    await asyncio.sleep(2)

            # Function to process the query and stream the response
            async def process_and_respond():
                try:
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
                    response_started.set()
                    async for token in response_stream:
                        yield f"data: {token['choices'][0]['delta']['content']}\n\n"
                except Exception as e:
                    response_started.set()
                    logger.error(f"Error processing query: {str(e)}", exc_info=True)
                    yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

            # Merge the loading messages and the response
            async def merged_stream():
                loading_task = asyncio.create_task(send_loading_messages().__anext__())
                response_task = asyncio.create_task(process_and_respond().__anext__())

                while True:
                    done, pending = await asyncio.wait(
                        [loading_task, response_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if loading_task in done:
                        try:
                            loading_message = loading_task.result()
                            yield loading_message
                            if not response_started.is_set():
                                loading_task = asyncio.create_task(send_loading_messages().__anext__())
                        except StopAsyncIteration:
                            pass  # No more loading messages

                    if response_task in done:
                        try:
                            response_message = response_task.result()
                            yield response_message
                            response_task = asyncio.create_task(process_and_respond().__anext__())
                        except StopAsyncIteration:
                            break  # Response fully streamed

            return Response(stream_with_context(merged_stream()), content_type='text/event-stream')

        return process_query_async()

    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")
        
# Route to fetch recent searches
@app.route('/recent_searches', methods=['GET'])
@limiter.limit("30 per minute")
def recent_searches():
    try:
        @async_to_sync
        async def fetch_recent_searches_async():
            try:
                recent_queries = UserQuery.query.order_by(UserQuery.timestamp.desc()).limit(10).all()
                for q in recent_queries:
                    yield f"data: {json.dumps({'query': q.query, 'timestamp': q.timestamp.isoformat()})}\n\n"
            except SQLAlchemyError as e:
                logger.error(f"Database error in recent_searches: {str(e)}", exc_info=True)
                yield f"data: {{'error': 'A database error occurred. Please try again later.'}}\n\n"
            except Exception as e:
                logger.error(f"Unexpected error in recent_searches: {str(e)}", exc_info=True)
                yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

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

# Error handler for rate limiting
@app.errorhandler(429)
def ratelimit_handler(e):
    return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")

# Initialize the database
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Initialize the database
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))