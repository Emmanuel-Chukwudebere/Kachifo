from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from api_integrations import get_all_trends, get_chatgpt_response, cache
from models import db, Trend, UserQuery

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://ceo:CEOKachifo@2024@localhost/kachifo_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
cache.init_app(app)

@app.route('/')
def home():
    return jsonify({"message": "Welcome to Kachifo - Discover trending topics!"})

@app.route('/search', methods=['POST'])
def search_trends():
    query = request.json.get('query')
    
    # Log user query
    user_query = UserQuery(query=query)
    db.session.add(user_query)
    db.session.commit()

    trends = get_all_trends(query)

    # Store trends in database
    for category, trend_list in trends.items():
        for trend in trend_list:
            new_trend = Trend(query=query, category=category, title=trend)
            db.session.add(new_trend)
    db.session.commit()

    return jsonify(trends)

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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)