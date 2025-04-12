import os
import logging
import re
import uuid
import time
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session
from flask_caching import Cache
from flask_talisman import Talisman
from functools import wraps
from werkzeug.exceptions import HTTPException

from api_integrations import (
    fetch_trending_topics,
    summarize_with_hf,
    extract_entities_with_hf,
    generate_conversational_response,
    generate_general_summary,
    initialize_inference_clients,
    perform_web_search,
    analyze_content
)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# Enable HTTPS with secure headers
Talisman(app, content_security_policy={
    'default-src': ["'self'", 'https:'],
    'script-src': ["'self'", 'https:', "'unsafe-inline'"],  # Allow inline JS for animations
    'style-src': ["'self'", 'https:', "'unsafe-inline'"],   # Allow inline CSS
    'img-src': ["'self'", 'data:', 'https:'],
    'connect-src': ["'self'", 'https:'],
    'font-src': ["'self'", 'https:', 'data:']
})

# Configure in-memory caching
app.config['CACHE_TYPE'] = 'simple'
app.config['CACHE_DEFAULT_TIMEOUT'] = 3600  # 1 hour
cache = Cache(app)

# Initialize usage statistics
daily_usage_count = 0

# Conversation history storage
conversation_store = {}

def setup_logging():
    """Configure application logging."""
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_file = os.environ.get('LOG_FILE', 'kachifo.log')
    
    # Create formatter for consistent log format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Setup file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    # Setup console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

setup_logging()
logger = logging.getLogger(__name__)

def create_response(data, status_code=200, message="Success"):
    """Standard response format for API endpoints."""
    return jsonify({"data": data, "status": status_code, "message": message}), status_code

@app.before_request
def log_request_info():
    """Log information about incoming requests."""
    logger.info(f'Request: {request.method} {request.url}')
    
    # Only log detailed info for non-production environments
    if os.environ.get('FLASK_ENV') != 'production':
        logger.debug(f'Headers: {request.headers}')
        if request.method in ['POST', 'PUT'] and request.is_json:
            logger.debug(f'Body: {request.get_json()}')

@app.after_request
def log_response_info(response):
    """Log information about outgoing responses."""
    logger.info(f'Response: {response.status}')
    return response

def rate_limit(func):
    """Rate limiting decorator for API endpoints."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get client IP for more granular rate limiting
        client_ip = request.remote_addr
        key = f"rate_limit:{client_ip}"
        
        # Check remaining requests
        remaining_requests = cache.get(key)
        if remaining_requests is None:
            # Initialize with 60 requests per hour
            remaining_requests = 60
            cache.set(key, remaining_requests, timeout=3600)  # 1 hour
        elif remaining_requests <= 0:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
        
        # Decrement remaining requests
        cache.set(key, remaining_requests - 1, timeout=3600)
        return func(*args, **kwargs)
    return wrapper

def sanitize_input(query):
    """Sanitize user input to prevent injection attacks."""
    if not query:
        return ""
    # Remove special characters, keep alphanumeric and spaces
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

def classify_input_type(user_input, conversation_history=None):
    """Determine if the input is a search query, analysis request, or conversational."""
    if not user_input:
        return 'conversation'
    
    # Check for follow-up questions if we have conversation history
    if conversation_history and len(conversation_history) > 1:
        prev_query = conversation_history[-2].get('content', '')
        prev_response = conversation_history[-1].get('content', '')
        
        # Common follow-up patterns
        followup_patterns = [
            r'\b(more|tell me more|continue|elaborate|explain further|can you explain|what about)\b',
            r'\b(why|how|what|when|where|who)\b',
            r'\b(thanks|thank you|got it)\b',
            r'\b(and|also|additionally|moreover|furthermore|besides)\b',
            r'\b(details|specifics|examples|instances|cases)\b',
            r'\b(compared to|versus|vs|difference between)\b'
        ]
        
        for pattern in followup_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                if 'query' in prev_query.lower() or 'search' in prev_query.lower():
                    return 'query'
                elif 'analyze' in prev_query.lower() or 'analysis' in prev_query.lower():
                    return 'analysis'
                elif 'web' in prev_query.lower() or 'internet' in prev_query.lower() or 'online' in prev_query.lower():
                    return 'web_search'
        
    # Patterns suggesting a search query intention
    query_pattern = re.compile(
        r'\b(search|find|look up|what is|tell me about|trending|give me|show me|discover|explore|list|popular|top|best)\b', 
        re.IGNORECASE
    )
    
    # Patterns suggesting an analysis request
    analysis_pattern = re.compile(
        r'\b(analyze|analysis|evaluate|review|compare|summarize|insights|opinion|thoughts on|perspective|breakdown|assessment|critique|examine|study)\b',
        re.IGNORECASE
    )
    
    # Web search pattern
    web_search_pattern = re.compile(
        r'\b(web search|google|search online|current|latest|today|live|news|recent|internet|web|online|right now|up to date|real time)\b',
        re.IGNORECASE
    )
    
    # Topic-specific patterns that could indicate domain-specific searches
    topic_patterns = {
        'tech': re.compile(r'\b(technology|tech|AI|artificial intelligence|programming|software|hardware|digital|computer|app|application)\b', re.IGNORECASE),
        'business': re.compile(r'\b(business|finance|company|market|stock|investment|economy|industry|startup|entrepreneur)\b', re.IGNORECASE),
        'health': re.compile(r'\b(health|medical|wellness|nutrition|fitness|diet|exercise|doctor|hospital|treatment|therapy)\b', re.IGNORECASE),
        'entertainment': re.compile(r'\b(movie|film|tv|television|show|series|music|song|artist|celebrity|entertainment)\b', re.IGNORECASE)
    }
    
    # Check for topic-specific patterns first
    for topic, pattern in topic_patterns.items():
        if pattern.search(user_input):
            # More likely to be a query if a specific topic is mentioned
            return 'query'
    
    # Then check for general search patterns
    if web_search_pattern.search(user_input):
        return 'web_search'
    elif analysis_pattern.search(user_input):
        return 'analysis'
    elif query_pattern.search(user_input):
        return 'query'
    
    # If no patterns match, it's likely a conversation
    return 'conversation'

def get_conversation_history(session_id):
    """Retrieve conversation history for a session."""
    # Clean up old conversations (older than 24 hours)
    current_time = time.time()
    expired_keys = []
    
    for key, data in conversation_store.items():
        if current_time - data.get('last_updated', 0) > 86400:  # 24 hours
            expired_keys.append(key)
    
    for key in expired_keys:
        conversation_store.pop(key, None)
    
    # Get or create conversation history
    if session_id not in conversation_store:
        conversation_store[session_id] = {
            'history': [
                {'role': 'system', 'content': 'You are Kachifo, a helpful AI assistant specialized in discovering and analyzing trends. Always refer to yourself as Kachifo.'}
            ],
            'last_updated': current_time
        }
    else:
        conversation_store[session_id]['last_updated'] = current_time
        
    return conversation_store[session_id]['history']

def update_conversation_history(session_id, role, content):
    """Add a message to the conversation history."""
    history = get_conversation_history(session_id)
    history.append({'role': role, 'content': content})
    
    # Keep only the last 10 messages to prevent the history from growing too large
    if len(history) > 11:  # 1 system + 10 messages
        history.pop(1)  # Remove the oldest message (but keep the system message)
    
    conversation_store[session_id]['last_updated'] = time.time()
    return history

@app.route('/')
def home():
    """Serve the main application page."""
    logger.info("Home page accessed")
    
    # Generate a session ID if not present
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    return render_template('index.html', message="Welcome to Kachifo - Discover trends")

@app.route('/interact', methods=['POST'])
@rate_limit
def interact():
    """Main interaction endpoint for handling queries, analysis, and conversations."""
    global daily_usage_count
    daily_usage_count += 1
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    user_input = data.get('input', '').strip()
    if not user_input:
        return jsonify({'error': 'No input provided'}), 400
    
    # Get or create session ID
    client_session_id = data.get('session_id')
    
    # If client provided a session ID and it's valid (exists in our store)
    if client_session_id and client_session_id in conversation_store:
        session_id = client_session_id
    else:
        # Generate a new session ID if none provided or invalid
        session_id = str(uuid.uuid4())
        
    # If it's a new session, store it in the server session too
    if 'session_id' not in session:
        session['session_id'] = session_id
    
    # Get conversation history
    conversation_history = get_conversation_history(session_id)
    
    # Add user message to history
    update_conversation_history(session_id, 'user', user_input)
    
    # Classify the input type using conversation context
    input_type = classify_input_type(user_input, conversation_history)
    
    try:
        if input_type == 'web_search':
            # Handle web search request
            logger.info(f"Processing web search: {user_input}")
            response = process_web_search(user_input, session_id)
            
        elif input_type == 'analysis':
            # Handle analysis request
            logger.info(f"Processing analysis: {user_input}")
            response = process_analysis(user_input, session_id)
            
        elif input_type == 'query':
            # Handle search query
            logger.info(f"Processing search query: {user_input}")
            response = process_search_query(user_input, session_id)
            
        else:
            # Handle conversational input
            logger.info(f"Processing conversation: {user_input}")
            response_text = generate_conversational_response(user_input, conversation_history)
            
            # Add assistant response to history
            update_conversation_history(session_id, 'assistant', response_text)
            
            response = jsonify({
                'response': response_text,
                'session_id': session_id,
                'type': 'conversation'
            })
        
        return response
        
    except Exception as e:
        logger.error(f"Error in /interact: {str(e)}", exc_info=True)
        
        # Handle different types of errors gracefully
        error_message = "I'm sorry, I encountered an issue processing your request."
        
        if "API" in str(e) or "timeout" in str(e).lower():
            error_message = "I'm having trouble connecting to one of my sources. Please try again in a moment."
        elif "model" in str(e).lower():
            error_message = "I'm having trouble with my thinking process. Let me try a different approach next time."
        
        # Add error response to conversation history
        update_conversation_history(session_id, 'assistant', error_message)
        
        return jsonify({
            'response': error_message,
            'error': str(e),
            'session_id': session_id,
            'type': 'error'
        }), 500

def process_web_search(query, session_id=None):
    """Process a web search query and return real-time results."""
    # Try to get from cache first (with short expiration)
    cache_key = f"web_search:{query}"
    cached_results = cache.get(cache_key)
    
    if cached_results:
        logger.info(f"Cache hit for web search: {query}")
        
        # Add response to conversation history if session exists
        if session_id:
            update_conversation_history(session_id, 'assistant', cached_results['summary'])
            
        return jsonify(cached_results)
    
    # If not in cache, perform web search
    try:
        search_results = perform_web_search(query)
        
        # Create a summary from the search results
        result_texts = [result.get('snippet', '') for result in search_results]
        summary = generate_general_summary(result_texts)
        
        # Format for a user-friendly response
        formatted_results = []
        for result in search_results:
            formatted_results.append({
                'title': result.get('title', 'No title'),
                'url': result.get('link', '#'),
                'snippet': result.get('snippet', 'No description available')
            })
        
        response_text = f"Here's what I found online about '{query}':\n\n{summary}\n\n"
        
        final_response = {
            'query': query,
            'results': formatted_results, 
            'summary': response_text,
            'session_id': session_id,
            'type': 'web_search'
        }
        
        # Cache for a short time (5 minutes)
        cache.set(cache_key, final_response, timeout=300)
        
        # Add response to conversation history if session exists
        if session_id:
            update_conversation_history(session_id, 'assistant', response_text)
        
        return jsonify(final_response)
        
    except Exception as e:
        logger.error(f"Error in web search: {str(e)}", exc_info=True)
        error_message = f"I had trouble searching the web for '{query}'. Please try a different query or try again later."
        
        if session_id:
            update_conversation_history(session_id, 'assistant', error_message)
            
        return jsonify({
            'error': error_message,
            'session_id': session_id,
            'type': 'error'
        }), 500

def process_analysis(query, session_id=None):
    """Process an analysis request on a topic."""
    # Try cache first
    cache_key = f"analysis:{query}"
    cached_results = cache.get(cache_key)
    
    if cached_results:
        logger.info(f"Cache hit for analysis: {query}")
        
        # Add response to conversation history if session exists
        if session_id:
            update_conversation_history(session_id, 'assistant', cached_results['analysis'])
            
        return jsonify(cached_results)
    
    # First get trend data
    trend_data = fetch_trending_topics(query)
    
    # If we have no trend data, try a web search
    if not trend_data:
        logger.info(f"No trend data found, attempting web search for: {query}")
        search_results = perform_web_search(query)
        
        if search_results:
            # Extract snippets to analyze
            snippets = [result.get('snippet', '') for result in search_results]
            analysis_text = analyze_content(query, snippets)
        else:
            analysis_text = f"I couldn't find any recent information to analyze about '{query}'."
    else:
        # Prepare content for analysis from trend data
        content_to_analyze = []
        for item in trend_data:
            title = item.get('title', '')
            summary = item.get('summary', '')
            content_to_analyze.append(f"{title}: {summary}")
        
        # Perform analysis
        analysis_text = analyze_content(query, content_to_analyze)
    
    # Create response format
    response_data = {
        'query': query,
        'analysis': analysis_text,
        'timestamp': datetime.now().isoformat(),
        'session_id': session_id,
        'type': 'analysis'
    }
    
    # Cache the results
    cache.set(cache_key, response_data, timeout=1800)  # Cache for 30 minutes
    
    # Add to conversation history if session exists
    if session_id:
        update_conversation_history(session_id, 'assistant', analysis_text)
    
    return jsonify(response_data)

def process_search_query(query, session_id=None):
    """Process a search query and return results with summaries."""
    # Try to get from cache first
    cache_key = f"search_query:{query}"
    cached_results = cache.get(cache_key)
    
    if cached_results:
        logger.info(f"Cache hit for query: {query}")
        
        # Add to conversation history if session exists
        if session_id and 'general_summary' in cached_results:
            update_conversation_history(session_id, 'assistant', 
                f"Here's what I found about '{query}':\n\n{cached_results['general_summary']}")
            
        return jsonify(cached_results)
    
    # If not in cache, fetch new results
    results = fetch_trending_topics(query)
    
    # Process results and generate summaries
    individual_summaries = []
    processed_results = []
    
    for result in results:
        title = result.get('title', '')
        summary = result.get('summary', '')
        
        # Create individual summary
        full_summary = summarize_with_hf(f"{title} {summary}")
        individual_summaries.append(full_summary)
        
        # Add to processed results
        processed_results.append({
            'source': result.get('source', ''),
            'title': title,
            'summary': full_summary,
            'url': result.get('url', '')
        })
    
    # Generate overall summary
    general_summary = generate_general_summary(individual_summaries)
    
    # Add Kachifo personality to the summary
    personalized_summary = f"Here's what I found about '{query}':\n\n{general_summary}"
    
    # Prepare response
    final_response = {
        'query': query,
        'results': processed_results,
        'general_summary': personalized_summary,
        'session_id': session_id,
        'type': 'query'
    }
    
    # Cache the results
    cache.set(cache_key, final_response, timeout=1800)  # Cache for 30 minutes
    
    # Add to conversation history if session exists
    if session_id:
        update_conversation_history(session_id, 'assistant', personalized_summary)
    
    return jsonify(final_response)

@app.route('/search', methods=['GET', 'POST'])
@rate_limit
def search_trends():
    """API endpoint for searching trends."""
    # Handle both GET and POST requests
    if request.method == 'GET':
        query = request.args.get('q', '')
        session_id = request.args.get('session_id', None)
    else:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        query = data.get('q', '')
        session_id = data.get('session_id', None)
    
    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400
    
    # Sanitize input and process query
    query = sanitize_input(query)
    return process_search_query(query, session_id)

@app.route('/analyze', methods=['GET', 'POST'])
@rate_limit
def analyze_trends():
    """API endpoint for analyzing trends."""
    # Handle both GET and POST requests
    if request.method == 'GET':
        query = request.args.get('q', '')
        session_id = request.args.get('session_id', None)
    else:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        query = data.get('q', '')
        session_id = data.get('session_id', None)
    
    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400
    
    # Sanitize input and process for analysis
    query = sanitize_input(query)
    return process_analysis(query, session_id)

@app.route('/web-search', methods=['GET', 'POST'])
@rate_limit
def web_search():
    """API endpoint for web search."""
    # Handle both GET and POST requests
    if request.method == 'GET':
        query = request.args.get('q', '')
        session_id = request.args.get('session_id', None)
    else:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        query = data.get('q', '')
        session_id = data.get('session_id', None)
    
    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400
    
    # Sanitize input and process web search
    query = sanitize_input(query)
    return process_web_search(query, session_id)

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get basic usage statistics."""
    return jsonify({
        'daily_usage': daily_usage_count,
        'active_conversations': len(conversation_store)
    })

@app.route('/clear-history', methods=['POST'])
def clear_history():
    """Clear conversation history for a session."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    session_id = data.get('session_id', session.get('session_id'))
    
    if not session_id or session_id not in conversation_store:
        return jsonify({'success': True, 'message': 'No active session found'})
    
    # Clear history but keep system message
    system_message = conversation_store[session_id]['history'][0]
    conversation_store[session_id]['history'] = [system_message]
    conversation_store[session_id]['last_updated'] = time.time()
    
    return jsonify({'success': True, 'message': 'Conversation history cleared'})

@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler for all routes."""
    if isinstance(e, HTTPException):
        return e
    
    # Log unexpected errors
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    
    # Return user-friendly error with Kachifo personality
    return jsonify({
        'error': "I'm sorry, I ran into an unexpected issue. Please try again in a moment.",
        'type': 'error'
    }), 500

# Initialize HuggingFace clients
if not initialize_inference_clients():
    logger.warning("Failed to initialize some or all HuggingFace models. Some features may be limited.")

if __name__ == '__main__':
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    # Run app
    app.run(host='0.0.0.0', port=port, debug=debug)