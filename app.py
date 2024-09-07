import os
from flask import Flask, jsonify, render_template, request
import requests
import praw
import tweepy
from newsapi import NewsApiClient
from googleapiclient.discovery import build
from dotenv import load_dotenv
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Length
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()  # Load environment variables from .env file

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')  # Add this line for Flask-WTF

# Initialize APIs
google_service = build('customsearch', 'v1', developerKey=os.getenv('GOOGLE_API_KEY'))
youtube_service = build('youtube', 'v3', developerKey=os.getenv('YOUTUBE_API_KEY'))

reddit = praw.Reddit(client_id=os.getenv('REDDIT_CLIENT_ID'),
                     client_secret=os.getenv('REDDIT_SECRET'),
                     user_agent=os.getenv('REDDIT_USER_AGENT'))

auth = tweepy.OAuthHandler(os.getenv('TWITTER_API_KEY'), os.getenv('TWITTER_API_SECRET'))
auth.set_access_token(os.getenv('TWITTER_ACCESS_TOKEN'), os.getenv('TWITTER_ACCESS_SECRET'))
twitter_api = tweepy.API(auth)

news_api = NewsApiClient(api_key=os.getenv('NEWS_API_KEY'))

# Initialize rate limiter
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Form for input validation
class SearchForm(FlaskForm):
    query = StringField('Query', validators=[DataRequired(), Length(min=1, max=100)])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/google', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def google_search():
    form = SearchForm(request.args)
    if form.validate():
        query = form.query.data
        try:
            res = google_service.cse().list(q=query, cx=os.getenv('GOOGLE_CSE_ID')).execute()
            return jsonify(res)
        except Exception as e:
            app.logger.error(f"Error in Google search: {str(e)}")
            return jsonify({"error": "An error occurred processing your request"}), 500
    else:
        return jsonify({"error": "Invalid input"}), 400

@app.route('/youtube', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def youtube_search():
    form = SearchForm(request.args)
    if form.validate():
        query = form.query.data
        try:
            res = youtube_service.search().list(q=query, part='snippet', maxResults=5).execute()
            return jsonify(res)
        except Exception as e:
            app.logger.error(f"Error in YouTube search: {str(e)}")
            return jsonify({"error": "An error occurred processing your request"}), 500
    else:
        return jsonify({"error": "Invalid input"}), 400

@app.route('/reddit', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def reddit_search():
    form = SearchForm(request.args)
    if form.validate():
        query = form.query.data
        try:
            submissions = []
            for submission in reddit.subreddit(query).hot(limit=5):
                submissions.append({'title': submission.title, 'score': submission.score})
            return jsonify(submissions)
        except Exception as e:
            app.logger.error(f"Error in Reddit search: {str(e)}")
            return jsonify({"error": "An error occurred processing your request"}), 500
    else:
        return jsonify({"error": "Invalid input"}), 400

@app.route('/twitter', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def twitter_search():
    form = SearchForm(request.args)
    if form.validate():
        query = form.query.data
        try:
            tweets = []
            for tweet in tweepy.Cursor(twitter_api.search_tweets, q=query, lang='en').items(5):
                tweets.append({'text': tweet.text, 'user': tweet.user.screen_name})
            return jsonify(tweets)
        except Exception as e:
            app.logger.error(f"Error in Twitter search: {str(e)}")
            return jsonify({"error": "An error occurred processing your request"}), 500
    else:
        return jsonify({"error": "Invalid input"}), 400

@app.route('/news', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def news_search():
    form = SearchForm(request.args)
    if form.validate():
        query = form.query.data
        try:
            top_headlines = news_api.get_top_headlines(q=query)
            return jsonify(top_headlines)
        except Exception as e:
            app.logger.error(f"Error in News search: {str(e)}")
            return jsonify({"error": "An error occurred processing your request"}), 500
    else:
        return jsonify({"error": "Invalid input"}), 400

if __name__ == '__main__':
    app.run(debug=True)