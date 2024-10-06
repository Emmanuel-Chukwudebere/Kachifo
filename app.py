import os
import logging
import json
import re
import random
import asyncio
import time
from quart import Quart, request, jsonify, render_template, Response, stream_with_context
from quart_sqlalchemy import SQLAlchemy
from quart_limiter import Limiter
from quart_limiter.util import get_remote_address
from quart_caching import Cache
from quart_talisman import Talisman
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException
from logging.handlers import RotatingFileHandler
from api_integrations import fetch_trending_topics, summarize_with_hf, extract_entities_with_hf, generate_conversational_response
from huggingface_hub import InferenceClient
from marshmallow import Schema, fields, validate
import threading

app = Quart(__name__)

# Security headers using Talisman
Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:'],
    'style-src': ["'self'", 'https:'],
    'img-src': ["'self'", 'data:'],
    'connect-src': ["'self'", 'https:']
})

# Database Configuration for PostgreSQL on Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql+psycopg2://kachifodb_user:bmSBnUVP4UEFw6B5dYLgoCu3Xi3uDF4I@dpg-cs1bci3tq21c73envab0-a/kachifodb')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Caching Configuration
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300
cache = Cache(app)

# Rate Limiting Configuration
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["100 per day", "30 per hour"]
)

# Initialize Hugging Face Client
inference_client = InferenceClient(token=os.getenv("HUGGINGFACE_API_KEY"))

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

# Define Models
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

@app.before_serving
async def log_request_info():
    logger.info(f'Request: {request.method} {request.url}')
    logger.debug(f'Headers: {request.headers}')
    logger.debug(f'Body: {await request.get_data()}')

@app.after_serving
async def log_response_info(response):
    logger.info(f'Response: {response.status}')
    logger.debug(f'Headers: {response.headers}')
    return response

# Helper function for standardized responses
def create_standard_response(data, status_code, message):
    response = {
        "data": data,
        "status": status_code,
        "message": message
    }
    return response, status_code

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

class InteractSchema(Schema):
    input = fields.Str(required=True, validate=validate.Length(min=1, max=1000))

class SearchSchema(Schema):
    q = fields.Str(required=True, validate=validate.Length(min=1, max=200))

class ProcessQuerySchema(Schema):
    q = fields.Str(required=True, validate=validate.Length(min=1, max=200))

def validate_request(schema_class):
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            schema = schema_class()
            errors = {}

            # Validate based on request method
            if request.method == 'GET':
                try:
                    schema.load(request.args)
                except ValidationError as err:
                    errors = err.messages
            else:
                if request.is_json:
                    try:
                        schema.load(await request.get_json())
                    except ValidationError as err:
                        errors = err.messages
                else:
                    try:
                        schema.load(await request.form)
                    except ValidationError as err:
                        errors = err.messages
            
            if errors:
                return create_standard_response({'errors': errors}, 400, "Invalid request parameters")
            return await f(*args, **kwargs)  # Ensure the function is awaited
        return decorated_function
    return decorator

# Input sanitization
def sanitize_input(query):
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Classify input type as 'query' or 'conversation'
def classify_input_type(user_input):
    query_pattern = re.compile(
        r'\b(search|find|look up|what is|tell me|trending|give me|show me)\b',
        re.IGNORECASE
    )
    if query_pattern.search(user_input):
        return 'query'
    return 'conversation'

# Stream BlenderBot responses
async def stream_blender_response(user_input, response_started):
    try:
        response_stream = await inference_client.chat_completion(
            messages=[{"role": "user", "content": user_input}], stream=True
        )
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

# Merged stream for loading and response
async def merged_stream(user_input):
    response_started = asyncio.Event()  # Moved here to ensure it's created for each request
    loading_task = asyncio.create_task(send_loading_messages(response_started))
    process_task = asyncio.create_task(stream_blender_response(user_input, response_started))
    
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
                    loading_task = asyncio.create_task(send_loading_messages(response_started))
            except StopAsyncIteration:
                pass
        if process_task in done:
            try:
                response_message = process_task.result()
                yield response_message
                break
            except StopAsyncIteration:
                break
                
@app.route('/')
async def home():
    logger.info("Home page accessed")
    return await render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
@validate_request(InteractSchema)
async def interact():
    user_input = (await request.json).get('input') if request.method == 'POST' else request.args.get('input')
    if not user_input:
        return jsonify({'error': 'No input provided.'}), 400

    input_type = classify_input_type(user_input)
    
    # Use merged_stream to handle loading and response streaming
    response_started = asyncio.Event()  # Track if the response has started

    async def merged_stream():
        loading_task = asyncio.create_task(send_loading_messages(response_started))
        
        # Define response generation based on input type
        async def generate_response():
            try:
                if input_type == 'conversation':
                    async for token in stream_blender_response(user_input, response_started):
                        yield token
                else:  # Handle trending topics
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
                    response_started.set()  # Signal that response has started
                    yield f"data: {json.dumps({'query': user_input, 'results': summaries})}\n\n"
            except Exception as e:
                response_started.set()
                logger.error(f"Error generating response: {str(e)}", exc_info=True)
                yield "data: {'error': 'An error occurred while generating the response.'}\n\n"

        response_task = asyncio.create_task(generate_response())
        
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
                        loading_task = asyncio.create_task(send_loading_messages(response_started))
                except StopAsyncIteration:
                    pass
            if response_task in done:
                try:
                    response_message = response_task.result()
                    yield response_message
                    break
                except StopAsyncIteration:
                    break

    return Response(stream_with_context(merged_stream()), content_type='text/event-stream')

@app.route('/search', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
@validate_request(InteractSchema)
async def search_trends():
    query = request.args.get('q') if request.method == 'GET' else (await request.json).get('q')
    if not query:
        return create_standard_response({'error': 'Query parameter "q" is required'}, 400, "Query parameter missing")

    query = sanitize_input(query)

    # Start the response tracking
    response_started = asyncio.Event()  

    async def generate_search_response():
        try:
            # Fetch trending topics asynchronously
            results = await fetch_trending_topics(query)
            if not results:
                yield "data: {'error': 'No results found.'}\n\n"
                return

            summaries = []
            for result in results:
                title = result.get('title', '')
                summary = result.get('summary', '')
                full_summary = await summarize_with_hf(f"{title} {summary}")
                summaries.append({
                    'source': result.get('source', ''),
                    'title': title,
                    'summary': full_summary,
                    'url': result.get('url', '')
                })

            # Generate a general summary from the individual summaries
            general_summary = await generate_general_summary([s['summary'] for s in summaries])
            final_response = {'query': query, 'results': summaries, 'general_summary': general_summary}
            yield f"data: {json.dumps(final_response)}\n\n"
        except Exception as e:
            logger.error(f"Error in search_trends: {str(e)}", exc_info=True)
            yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

    async def merged_stream():
        loading_task = asyncio.create_task(send_loading_messages(response_started))
        response_task = asyncio.create_task(generate_search_response())

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
                        loading_task = asyncio.create_task(send_loading_messages(response_started))
                except StopAsyncIteration:
                    pass
            if response_task in done:
                try:
                    response_message = response_task.result()
                    yield response_message
                    break
                except StopAsyncIteration:
                    break

    return Response(stream_with_context(merged_stream()), content_type='text/event-stream')

@app.route('/process-query', methods=['POST'])
@limiter.limit("10 per minute")
@validate_request(InteractSchema)
async def process_query():
    try:
        query = (await request.json).get('q') if request.is_json else (await request.form).get('q')
        if not query:
            logger.warning("Query is missing")
            return create_standard_response({'error': 'Query is required'}, 400, "Query is required")

        query = sanitize_input(query)
        response_started = asyncio.Event()  # Track if the response has started

        async def send_loading_messages():
            while not response_started.is_set():
                loading_message = random.choice(loading_messages)
                yield f"data: {loading_message}\n\n"
                await asyncio.sleep(2)

        async def process_and_respond():
            try:
                # Extract entities using Hugging Face
                processed_query_data = await extract_entities_with_hf(query)

                # Store query in the database
                new_query = UserQuery(query=query)
                new_query.set_hf_data(processed_query_data)
                db.session.add(new_query)
                db.session.commit()

                # Fetch trending topics
                trends = await fetch_trending_topics(query)

                # Summarize the trends
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
                response_started.set()  # Signal that the response has started
                async for token in response_stream:
                    yield f"data: {token['choices'][0]['delta']['content']}\n\n"
            except Exception as e:
                response_started.set()
                logger.error(f"Error processing query: {str(e)}", exc_info=True)
                yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

        # Merged stream for loading and response
        async def merged_stream():
            loading_task = asyncio.create_task(send_loading_messages())
            response_task = asyncio.create_task(process_and_respond())

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
                            loading_task = asyncio.create_task(send_loading_messages())
                    except StopAsyncIteration:
                        pass
                if response_task in done:
                    try:
                        response_message = response_task.result()
                        yield response_message
                        break
                    except StopAsyncIteration:
                        break

        return Response(stream_with_context(merged_stream()), content_type='text/event-stream')

    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "A database error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

# Route to fetch recent searches
@app.route('/recent_searches', methods=['GET'])
@limiter.limit("30 per minute")
async def recent_searches():
    try:
        # Create an event to signal when the response has started
        response_started = asyncio.Event()

        async def fetch_recent_searches():
            try:
                # Fetch recent queries from the database
                recent_queries = UserQuery.query.order_by(UserQuery.timestamp.desc()).limit(10).all()
                for q in recent_queries:
                    yield f"data: {json.dumps({'query': q.query, 'timestamp': q.timestamp.isoformat()})}\n\n"
            except SQLAlchemyError as e:
                logger.error(f"Database error in recent_searches: {str(e)}", exc_info=True)
                yield f"data: {{'error': 'A database error occurred. Please try again later.'}}\n\n"
            except Exception as e:
                logger.error(f"Unexpected error in recent_searches: {str(e)}", exc_info=True)
                yield f"data: {{'error': 'An unexpected error occurred. Please try again later.'}}\n\n"

        async def merged_stream():
            loading_task = asyncio.create_task(send_loading_messages(response_started))
            response_task = asyncio.create_task(fetch_recent_searches())

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
                            loading_task = asyncio.create_task(send_loading_messages(response_started))
                    except StopAsyncIteration:
                        pass
                if response_task in done:
                    try:
                        response_message = response_task.result()
                        yield response_message
                        break
                    except StopAsyncIteration:
                        break

        return Response(stream_with_context(merged_stream()), content_type='text/event-stream')
    except Exception as e:
        logger.error(f"Error fetching recent searches: {str(e)}", exc_info=True)
        return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

@app.errorhandler(Exception)
async def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return create_standard_response(None, 500, "An unexpected error occurred. Please try again later.")

@app.errorhandler(429)
async def ratelimit_handler(e):
    return create_standard_response(None, 429, "Rate limit exceeded. Please try again later.")

# Initialize the database
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Initialize the database
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), use_reloader=False)