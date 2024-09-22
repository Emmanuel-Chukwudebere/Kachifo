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

# Load configuration from environment variables
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL', 'mysql+pymysql://ceo:CEOKachifo2024@kachifo.cteuykcg0zmb.eu-north-1.rds.amazonaws.com:3306/kachifo'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['CACHE_TYPE'] = 'simple'

# Initialize the database and cache
db.init_app(app)
cache.init_app(app)

# Set up logging for production
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ---------------------------- ROUTES ---------------------------- #

@app.route('/')
def home():
    """Render the homepage."""
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    """Search for trends based on user input."""
    query = request.form.get('query')
    
    if not query:
        return jsonify({'error': 'Query is required'}), 400

    # Universal prompt limit check
    today = date.today()
    daily_usage = DailyUsage.query.filter_by(date=today).first()
    
    if daily_usage and daily_usage.usage_count >= 70:
        return jsonify({'error': 'Daily limit of 70 prompts reached. Try again tomorrow.'}), 403

    # Try to retrieve cached result
    cached_result = cache.get(query.lower())
    if cached_result:
        return jsonify({'result': cached_result})

    # Log the user query to the database
    try:
        user_query = UserQuery(query=query.lower())
        db.session.add(user_query)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Database error: {str(e)}")

    # Fetch trends asynchronously
    try:
        trends = asyncio.run(get_all_trends(query))
        # Cache the result for future queries
        cache.set(query.lower(), trends)
    except Exception as e:
        logging.error(f"Error fetching trends: {str(e)}")
        trends = "Sorry, we couldn't fetch trends at this time."

    return jsonify({'result': trends})

@app.route('/chat', methods=['POST'])
async def chat():
    """Get response from ChatGPT based on the user's prompt."""
    prompt = request.form.get('prompt')
    
    if not prompt:
        return jsonify({'error': 'Prompt is required'}), 400

    # Universal prompt limit check
    today = date.today()
    daily_usage = DailyUsage.query.filter_by(date=today).first()
    
    if daily_usage and daily_usage.usage_count >= 70:
        return jsonify({'error': 'Daily limit of 70 prompts reached. Try again tomorrow.'}), 403

    # Fetch the ChatGPT response asynchronously
    response = await get_chatgpt_response(prompt)
    return jsonify({'response': response})

@app.route('/categories', methods=['GET'])
def categories():
    """Return available categories for trends (this route can be customized further)."""
    categories = ["Tech", "Design", "Software", "Medicine", "Finance"]
    return jsonify({'categories': categories})

@app.route('/trend_details/<int:trend_id>', methods=['GET'])
def trend_details(trend_id):
    """Fetch details of a specific trend by ID."""
    trend = Trend.query.get(trend_id)
    if trend:
        return jsonify({
            'id': trend.id,
            'name': trend.name,
            'description': trend.description,
            'source': trend.source
        })
    return jsonify({'error': 'Trend not found'}), 404

# ---------------------- DATABASE INIT ---------------------- #

@app.before_first_request
def initialize_database():
    """Create all database tables."""
    with app.app_context():
        db.create_all()

# ------------------------ DAILY USAGE TRACKING ------------------------ #

@app.before_request
def track_daily_usage():
    """Track the number of daily prompts for all users."""
    # Get today's date
    today = date.today()

    # Check if there is an entry for today's usage
    daily_usage = DailyUsage.query.filter_by(date=today).first()

    if not daily_usage:
        # If no entry, create a new one
        daily_usage = DailyUsage(date=today, usage_count=0)
        db.session.add(daily_usage)

    # Increment usage count
    daily_usage.usage_count += 1
    db.session.commit()

# ------------------------- RUN APP ------------------------- #

if __name__ == '__main__':
    app.run(debug=True)