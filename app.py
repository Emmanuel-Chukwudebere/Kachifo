import os
import logging
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from api_integrations import get_all_trends, get_chatgpt_response, cache
from models import db, Trend, UserQuery, DailyUsage
from datetime import date
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

# Initialize the Flask app
app = Flask(__name__)

# Load configuration from environment variables (ensure they are set in production)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'mysql+pymysql://ceo:CEOKachifo2024@kachifo.cteuykcg0zmb.eu-north-1.rds.amazonaws.com:3306/kachifo')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['CACHE_TYPE'] = 'simple'  # Simple cache, replace with Redis in production if needed

# Initialize the database and cache
db.init_app(app)
cache.init_app(app)

# Set up logging for production
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
file_handler = logging.FileHandler('kachifo.log')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
app.logger.addHandler(file_handler)

MAX_PROMPTS = int(os.getenv('MAX_PROMPTS', 50))

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
async def search_trends():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({"error": "Please provide a search query."}), 400

    # Log the user query
    user_query = UserQuery(query=query)
    db.session.add(user_query)
    db.session.commit()

    try:
        # Check the daily limit of prompts
        usage = get_prompt_count()
        if usage.count >= MAX_PROMPTS:
            app.logger.warning('Daily prompt limit reached')
            return jsonify({"error": "You've reached the maximum number of prompts for today. Please try again tomorrow."}), 429

        # Try getting trends from cache, if available
        cached_trends = cache.get(query)
        if cached_trends:
            app.logger.info(f"Cache hit for query: {query}")
            return jsonify({"response": cached_trends})

        # Get trends from external APIs
        trends = await get_all_trends(query)

        # Formulate structured prompt for ChatGPT
        chatgpt_prompt = f"""
        Summarize these trends for the user related to {query}. Provide brief descriptions for each and format the result clearly with links:
        {trends}
        """

        # Get response from ChatGPT
        chatgpt_response = await get_chatgpt_response(chatgpt_prompt)

        # Cache the result for future queries
        cache.set(query, chatgpt_response)

        # Update daily usage count
        usage.count += 1
        db.session.commit()

        app.logger.info(f"Trends retrieved successfully for query: {query}")
        return jsonify({"response": chatgpt_response})
    except Exception as e:
        app.logger.error(f"Error processing trends for query: {query}: {str(e)}")
        return jsonify({"error": "Something went wrong while retrieving trends. Please try again later."}), 500

@app.route('/categories')
def get_categories():
    try:
        # Cache categories to reduce database load
        categories = cache.get("categories")
        if not categories:
            categories = db.session.query(Trend.category).distinct().all()
            cache.set("categories", categories)
        app.logger.info('Categories retrieved successfully')
        return jsonify({"categories": [category[0] for category in categories]})
    except Exception as e:
        app.logger.error(f"Error retrieving categories: {str(e)}")
        return jsonify({"error": "Failed to retrieve categories. Please try again later."}), 500

# Error handling for 404 and 500 errors
@app.errorhandler(404)
def resource_not_found(e):
    app.logger.error(f"Resource not found: {str(e)}")
    return jsonify(error="The requested resource could not be found."), 404

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Internal server error: {str(e)}")
    return jsonify(error="Internal server error. Please try again later."), 500

@app.errorhandler(Exception)
def handle_generic_error(e):
    app.logger.error(f"An unexpected error occurred: {str(e)}")
    return jsonify(error="An unexpected error occurred. Please try again later."), 500

# Request logging
@app.before_request
def log_request_info():
    app.logger.info(f"Request: {request.method} {request.path}")

if __name__ == '__main__':
    # Production-ready server should use Gunicorn or similar WSGI server
    with app.app_context():
        app.logger.info("Creating all tables if they don't exist.")
        db.create_all()
    
    # For development only. In production, use Gunicorn or similar.
    # app.run(debug=False, host='0.0.0.0')