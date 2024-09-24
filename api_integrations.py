import os
import requests
import logging
import spacy
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException
from cachetools import cached, TTLCache
import re

# Initialize logging
logging.basicConfig(
    filename="Kachifo.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Initialize SpaCy NLP model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    from spacy.cli import download
    download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# Cache setup: 1-hour time-to-live, max 1000 items
cache = TTLCache(maxsize=1000, ttl=3600)

# API keys from environment variables
def get_env_var(key):
    value = os.getenv(key)
    if not value:
        logging.error(f"Environment variable {key} is missing.")
        raise ValueError(f"{key} is required but not set.")
    return value

YOUTUBE_API_KEY = get_env_var('YOUTUBE_API_KEY')
GOOGLE_API_KEY = get_env_var('GOOGLE_API_KEY')
NEWSAPI_KEY = get_env_var('NEWSAPI_KEY')
TWITTER_ACCESS_TOKEN = get_env_var('TWITTER_ACCESS_TOKEN')
REDDIT_CLIENT_ID = get_env_var('REDDIT_CLIENT_ID')
REDDIT_SECRET = get_env_var('REDDIT_SECRET')
REDDIT_USER_AGENT = get_env_var('REDDIT_USER_AGENT')

# Helper function for input sanitization
def sanitize_input(query):
    """Sanitize input to prevent injection attacks."""
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logging.info(f"Sanitized input: {sanitized}")
    return sanitized

# Helper function for summarizing text using SpaCy
def summarize_text(text):
    """Summarize text using SpaCy NLP."""
    doc = nlp(text)
    sentences = list(doc.sents)
    if not sentences:
        return "No content available."
    return str(sentences[0]) if sentences else "No summary available."

# Error handling decorator for API requests
def handle_api_errors(func):
    """Decorator to handle API errors gracefully."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RequestException as e:
            logging.error(f"API request failed: {str(e)}")
            return {'error': 'API request failed. Please try again later.'}
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return {'error': 'An unexpected error occurred. Please try again later.'}
    return wrapper

@handle_api_errors
@cached(cache)
def fetch_trending_topics(query):
    """Fetch trending topics from YouTube, Reddit, and Twitter based on a query."""
    logging.info(f"Fetching trending topics for query: {query}")
    
    sanitized_query = sanitize_input(query)
    
    # YouTube API
    youtube_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={sanitized_query}&type=video&key={YOUTUBE_API_KEY}"
    youtube_response = requests.get(youtube_url)
    youtube_data = youtube_response.json()

    # Reddit API
    reddit_url = f"https://www.reddit.com/search.json?q={sanitized_query}&sort=top&t=week"
    reddit_response = requests.get(reddit_url, headers={'User-Agent': REDDIT_USER_AGENT})
    reddit_data = reddit_response.json()

    # Twitter API (example only)
    twitter_url = f"https://api.twitter.com/2/tweets/search/recent?query={sanitized_query}&tweet.fields=created_at"
    twitter_response = requests.get(twitter_url, headers={'Authorization': f"Bearer {TWITTER_ACCESS_TOKEN}"})
    twitter_data = twitter_response.json()

    # Combine results from all APIs
    combined_results = []
    
    for item in youtube_data['items']:
        combined_results.append({
            'source': 'YouTube',
            'title': item['snippet']['title'],
            'summary': summarize_text(item['snippet']['description']),
            'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}"
        })
    
    for post in reddit_data['data']['children']:
        combined_results.append({
            'source': 'Reddit',
            'title': post['data']['title'],
            'summary': summarize_text(post['data']['selftext']),
            'url': f"https://www.reddit.com{post['data']['permalink']}"
        })
    
    for tweet in twitter_data['data']:
        combined_results.append({
            'source': 'Twitter',
            'title': tweet['text'],
            'summary': summarize_text(tweet['text']),
            'url': f"https://twitter.com/i/web/status/{tweet['id']}"
        })
    
    return combined_results
