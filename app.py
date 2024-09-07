from flask import Flask, jsonify, render_template, request
import requests
import praw
import tweepy
from newsapi_python import NewsApiClient
from googleapiclient.discovery import build
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Initialize APIs
google_service = build('customsearch', 'v1', developerKey=app.config['GOOGLE_API_KEY'])
youtube_service = build('youtube', 'v3', developerKey=app.config['YOUTUBE_API_KEY'])

reddit = praw.Reddit(client_id=app.config['REDDIT_CLIENT_ID'],
                     client_secret=app.config['REDDIT_SECRET'],
                     user_agent=app.config['REDDIT_USER_AGENT'])

auth = tweepy.OAuthHandler(app.config['TWITTER_API_KEY'], app.config['TWITTER_API_SECRET'])
auth.set_access_token(app.config['TWITTER_ACCESS_TOKEN'], app.config['TWITTER_ACCESS_SECRET'])
twitter_api = tweepy.API(auth)

news_api = NewsApiClient(api_key=app.config['NEWS_API_KEY'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/google')
def google_search():
    query = request.args.get('query', 'Python programming')  # Default query if none provided
    res = google_service.cse().list(q=query, cx='your_search_engine_id').execute()
    return jsonify(res)

@app.route('/youtube')
def youtube_search():
    query = request.args.get('query', 'Python tutorials')  # Default query if none provided
    res = youtube_service.search().list(q=query, part='snippet', maxResults=5).execute()
    return jsonify(res)

@app.route('/reddit')
def reddit_search():
    query = request.args.get('query', 'learnpython')  # Default subreddit if none provided
    submissions = []
    for submission in reddit.subreddit(query).hot(limit=5):
        submissions.append({'title': submission.title, 'score': submission.score})
    return jsonify(submissions)

@app.route('/twitter')
def twitter_search():
    query = request.args.get('query', 'Python')  # Default query if none provided
    tweets = []
    for tweet in tweepy.Cursor(twitter_api.search, q=query, lang='en').items(5):
        tweets.append({'text': tweet.text, 'user': tweet.user.screen_name})
    return jsonify(tweets)

@app.route('/news')
def news_search():
    query = request.args.get('query', 'Python')  # Default query if none provided
    top_headlines = news_api.get_top_headlines(q=query)
    return jsonify(top_headlines)

if __name__ == '__main__':
    app.run(debug=True)
