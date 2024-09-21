import os
import logging
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from api_integrations import get_all_trends, get_chatgpt_response, cache
from models import db, Trend, UserQuery, DailyUsage
from datetime import date

app = Flask(__name__)

# Database (MariaDB) configuration using environment variable
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'mysql+pymysql://username:password@localhost/kachifo')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database and cache
db.init_app(app)
cache.init_app(app)

# Set up logging to stdout (Render logs automatically capture these)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Optionally, if you still want to log to a file (not recommended for Render):
file_handler = logging.FileHandler('kachifo.log')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))

# Add the file handler to the logger (if needed)
logging.getLogger().addHandler(file_handler)


MAX_PROMPTS = 50

# Utility function to track daily prompt usage
def get_prompt_count():
    today = date.today()
    usage = DailyUsage.query.filter_by(date=today).first()
    if not usage:
        usage = DailyUsage(date=today, count=0)
        db.session.add(usage)
        db.session.commit()
    return usage

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search_trends():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({"error": "Please provide a search query."}), 400

    user_query = UserQuery(query=query)
    db.session.add(user_query)
    db.session.commit()

    try:
        # Check the daily limit of prompts
        usage = get_prompt_count()
        if usage.count >= MAX_PROMPTS:
            logging.warning('Daily prompt limit reached')
            return jsonify({"error": "You've reached the maximum number of prompts for today. Please try again tomorrow."}), 429

        # Try getting trends from cache, if available
        cached_trends = cache.get(query)
        if cached_trends:
            logging.info(f"Cache hit for query: {query}")
            return jsonify({"response": cached_trends})

        # Get trends from external APIs
        trends = get_all_trends(query)

        # Formulate structured prompt for ChatGPT
        chatgpt_prompt = f"""
        Summarize these trends for the user related to {query}. Provide brief descriptions for each and format the result clearly with links:
        {trends}
        """

        # Get response from ChatGPT
        chatgpt_response = get_chatgpt_response(chatgpt_prompt)

        # Cache the result for future queries
        cache.set(query, chatgpt_response)

        # Update daily usage count
        usage.count += 1
        db.session.commit()

        logging.info(f"Trends retrieved successfully for query: {query}")
        return jsonify({"response": chatgpt_response})

    except Exception as e:
        logging.error(f"Error processing trends for query: {query}: {str(e)}")
        return jsonify({"error": "Something went wrong while retrieving trends. Please try again later."}), 500

@app.route('/categories')
def get_categories():
    try:
        # Cache categories to reduce database load
        categories = cache.get("categories")
        if not categories:
            categories = db.session.query(Trend.category).distinct().all()
            cache.set("categories", categories)
        logging.info('Categories retrieved successfully')
        return jsonify({"categories": [category[0] for category in categories]})
    except Exception as e:
        logging.error(f"Error retrieving categories: {str(e)}")
        return jsonify({"error": "Failed to retrieve categories. Please try again later."}), 500

# Error handling for 404 and 500 errors
@app.errorhandler(404)
def resource_not_found(e):
    logging.error(f"Resource not found: {str(e)}")
    return jsonify(error="The requested resource could not be found."), 404

@app.errorhandler(500)
def internal_server_error(e):
    logging.error(f"Internal server error: {str(e)}")
    return jsonify(error="Internal server error. Please try again later."), 500

@app.errorhandler(Exception)
def handle_generic_error(e):
    logging.error(f"An unexpected error occurred: {str(e)}")
    return jsonify(error="An unexpected error occurred. Please try again later."), 500

# Request logging
@app.before_request
def log_request_info():
    logging.info(f"Request: {request.method} {request.path}")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
