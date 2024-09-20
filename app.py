from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from api_integrations import get_all_trends, get_chatgpt_response, cache
from models import db, Trend, UserQuery, DailyUsage
from datetime import date
import logging

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://ceo:CEOKachifo%402024@localhost/kachifo_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
cache.init_app(app)

# Set up logging
logging.basicConfig(filename='kachifo.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')

MAX_PROMPTS = 50

# Utility function to track daily prompt usage
def get_prompt_count():
    today = date.today()
    usage = DailyUsage.query.filter_by(date=today).first()
    if not usage:
        # New day, reset the counter
        usage = DailyUsage(date=today, count=0)
        db.session.add(usage)
        db.session.commit()
    return usage

@app.route('/')
def home():
    return jsonify({"message": "Welcome to Kachifo - Discover trending topics!"})

@app.route('/search', methods=['POST'])
def search_trends():
    # Check the daily limit
    usage = get_prompt_count()
    if usage.count >= MAX_PROMPTS:
        return jsonify({"error": "Daily prompt limit reached"}), 429

    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({"error": "Query is required"}), 400

    # Log user query
    user_query = UserQuery(query=query)
    db.session.add(user_query)
    db.session.commit()

    try:
        # Get trends from APIs
        trends = get_all_trends(query)

        # Store trends in the database
        for category, trend_list in trends.items():
            for trend in trend_list:
                new_trend = Trend(query=query, category=category, title=trend)
                db.session.add(new_trend)
        db.session.commit()

        # Update prompt count
        usage.count += 1
        db.session.commit()

        return jsonify(trends)

    except Exception as e:
        logging.error(f"Error processing trends: {str(e)}")
        return jsonify({"error": "Failed to retrieve trends"}), 500


@app.route('/trend/<trend_id>')
def get_trend_details(trend_id):
    trend = Trend.query.get(trend_id)
    if trend:
        details = get_chatgpt_response(f"Tell me about the trend: {trend.title}")
        return jsonify({"trend": trend.title, "details": details})
    else:
        return jsonify({"error": "Trend not found"}), 404


@app.route('/categories')
def get_categories():
    categories = db.session.query(Trend.category).distinct().all()
    return jsonify({"categories": [category[0] for category in categories]})


# Error handling
@app.errorhandler(404)
def resource_not_found(e):
    return jsonify(error=str(e)), 404


@app.errorhandler(500)
def internal_server_error(e):
    return jsonify(error="Internal server error"), 500


@app.errorhandler(Exception)
def handle_generic_error(e):
    logging.error(f"An error occurred: {str(e)}")
    return jsonify(error="An unexpected error occurred"), 500


# Request logging
@app.before_request
def log_request_info():
    logging.info(f"Request: {request.method} {request.path}")


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
