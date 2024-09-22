from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from transformers import pipeline
from functools import wraps
import logging
import os
import time
import re

# Initialize Flask app and database
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
db = SQLAlchemy(app)

# Initialize logging
logging.basicConfig(filename='Kachifo.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

# Initialize the Hugging Face transformers model (text generation)
model = pipeline('text-generation', model='gpt2')

# Rate limit setup (70 requests/day globally)
LIMIT = 70
RATE_LIMIT_RESET = 24 * 60 * 60  # Reset after 24 hours
rate_limit_cache = {}

def rate_limiter():
    """Decorator to rate limit users based on their IP"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_ip = request.remote_addr
            current_time = time.time()

            if user_ip in rate_limit_cache:
                requests_made, first_request_time = rate_limit_cache[user_ip]
                
                if requests_made >= LIMIT:
                    if current_time - first_request_time < RATE_LIMIT_RESET:
                        return jsonify({"error": "Rate limit exceeded. Please wait before making more requests."}), 429
                    else:
                        # Reset the count after 24 hours
                        rate_limit_cache[user_ip] = (0, current_time)

            # Update rate limit cache
            if user_ip not in rate_limit_cache:
                rate_limit_cache[user_ip] = (1, current_time)
            else:
                rate_limit_cache[user_ip] = (rate_limit_cache[user_ip][0] + 1, first_request_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def sanitize_input(input_data):
    """Sanitize input to prevent injection and other vulnerabilities."""
    return re.sub(r'[^\w\s]', '', input_data)

# Routes
@app.route('/')
def home():
    return "Welcome to Kachifo - Discover Trends."

@app.route('/search', methods=['GET'])
@rate_limiter()
def search_trend():
    query = request.args.get('q')
    if not query:
        return jsonify({"error": "Query parameter 'q' is required."}), 400
    
    sanitized_query = sanitize_input(query)
    
    # Call external API integrations (YouTube, Reddit, etc.) with sanitized query
    result = fetch_trends_from_apis(sanitized_query)
    
    if result is None:
        logging.error(f"Error fetching trends for query: {sanitized_query}")
        return jsonify({"error": "Failed to fetch trends. Please try again."}), 500
    
    return jsonify({"data": result})

@app.route('/generate', methods=['POST'])
@rate_limiter()
def generate_text():
    input_data = request.json.get('input')
    if not input_data:
        return jsonify({"error": "Input text is required."}), 400

    sanitized_input = sanitize_input(input_data)

    try:
        output = model(sanitized_input, max_length=50, num_return_sequences=1)
        return jsonify({"generated_text": output[0]['generated_text']})
    except Exception as e:
        logging.error(f"Error generating text: {str(e)}")
        return jsonify({"error": "Failed to generate text."}), 500

if __name__ == '__main__':
    app.run(debug=False)  # Ensure debug=False in production