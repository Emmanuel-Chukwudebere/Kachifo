import os
import requests
import logging
import sys
from requests.auth import HTTPBasicAuth
import re
from datetime import datetime, timedelta
from cachetools import cached, TTLCache
import spacy

# Logging setup
logging.basicConfig(
    stream=sys.stdout,  # Output logs to stdout instead of a file
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"

# Initialize SpaCy NLP model
try:
    # Load the language model
    nlp = spacy.load("en_core_web_sm")
except OSError:
    # If the model is not installed, install it programmatically
    from spacy.cli import download
    download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# Cache setup: 1 hour time-to-live, max 1000 items
# cache = TTLCache(maxsize=1000, ttl=3600)

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
TWITTER_API_KEY = get_env_var('TWITTER_API_KEY')
TWITTER_ACCESS_TOKEN = get_env_var('TWITTER_ACCESS_TOKEN')
REDDIT_CLIENT_ID = get_env_var('REDDIT_CLIENT_ID')
REDDIT_SECRET = get_env_var('REDDIT_SECRET')
REDDIT_USER_AGENT = get_env_var('REDDIT_USER_AGENT')
GOOGLE_CSE_ID = get_env_var('GOOGLE_CSE_ID')

# Helper function for input sanitization
def sanitize_input(query):
    """Sanitize input to prevent SQL injection and other attacks."""
    return re.sub(r"[^\w\s]", "", query).strip()

# Decorator for rate limiting (custom implementation or using a package like `ratelimit`)
def rate_limited(func):
    def wrapper(*args, **kwargs):
        # Add rate-limiting logic here if needed
        return func(*args, **kwargs)
    return wrapper

# Summarize text using SpaCy
def summarize_text(text):
    """Summarize text using SpaCy."""
    doc = nlp(text)
    sentences = list(doc.sents)
    if not sentences:
        return "No content available."
    
    # Simple summarization: return first sentence as summary
    return str(sentences[0]) if sentences else "No summary available."

# Fetch and cache data from Reddit
@cached(cache)
@rate_limited
def fetch_reddit_data(query):
    """Fetch trending Reddit posts based on query."""
    query = sanitize_input(query)
    reddit_auth_url = "https://www.reddit.com/api/v1/access_token"
    auth = HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
    data = {'grant_type': 'client_credentials'}
    headers = {'User-Agent': REDDIT_USER_AGENT}

    try:
        # Obtain OAuth token
        auth_response = requests.post(reddit_auth_url, auth=auth, data=data, headers=headers)
        auth_response.raise_for_status()
        access_token = auth_response.json().get('access_token')
        headers['Authorization'] = f'bearer {access_token}'
        
        # Make search request to Reddit
        search_url = f"https://oauth.reddit.com/search?q={query}&limit=10"
        search_response = requests.get(search_url, headers=headers)
        search_response.raise_for_status()

        reddit_posts = search_response.json().get('data', {}).get('children', [])
        structured_results = []
        
        for post in reddit_posts:
            data = post['data']
            title = data.get('title', 'No title')
            url = f"https://www.reddit.com{data.get('permalink', '')}"
            body = data.get('selftext', '')
            summary = summarize_text(body)
            
            structured_results.append({'title': title, 'url': url, 'summary': summary})
        
        logging.info(f"Fetched Reddit data for query: {query}")
        return structured_results

    except requests.RequestException as e:
        logging.error(f"Reddit API error: {e}")
        return [{'error': 'Failed to fetch data from Reddit. Please try again later.'}]

# Fetch and cache data from Twitter
@cached(cache)
@rate_limited
def fetch_twitter_data(query):
    """Fetch trending Twitter tweets based on query."""
    query = sanitize_input(query)
    search_url = f"https://api.twitter.com/1.1/search/tweets.json?q={query}&count=10"
    headers = {
        'Authorization': f'Bearer {TWITTER_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        tweets = response.json().get('statuses', [])
        structured_results = []
        
        for tweet in tweets:
            text = tweet.get('text', 'No text available')
            tweet_url = f"https://twitter.com/user/status/{tweet.get('id_str', '')}"
            summary = summarize_text(text)
            
            structured_results.append({'tweet': text, 'url': tweet_url, 'summary': summary})
        
        logging.info(f"Fetched Twitter data for query: {query}")
        return structured_results

    except requests.RequestException as e:
        logging.error(f"Twitter API error: {e}")
        return [{'error': 'Failed to fetch data from Twitter. Please try again later.'}]

# Fetch and cache data from YouTube
@cached(cache)
@rate_limited
def fetch_youtube_data(query):
    """Fetch trending YouTube videos based on query."""
    query = sanitize_input(query)
    youtube_search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=10&q={query}&key={YOUTUBE_API_KEY}"
    
    try:
        response = requests.get(youtube_search_url)
        response.raise_for_status()
        videos = response.json().get('items', [])
        structured_results = []

        for video in videos:
            title = video['snippet'].get('title', 'No title')
            video_id = video['id'].get('videoId', '')
            url = f"https://www.youtube.com/watch?v={video_id}"

            structured_results.append({'title': title, 'url': url, 'summary': 'No summary available for videos.'})

        logging.info(f"Fetched YouTube data for query: {query}")
        return structured_results

    except requests.RequestException as e:
        logging.error(f"YouTube API error: {e}")
        return [{'error': 'Failed to fetch data from YouTube. Please try again later.'}]

# Fetch and cache data from Google News
@cached(cache)
@rate_limited
def fetch_google_news(query):
    """Fetch trending news from Google based on query."""
    query = sanitize_input(query)
    google_search_url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}"
    
    try:
        response = requests.get(google_search_url)
        response.raise_for_status()
        news_items = response.json().get('items', [])
        structured_results = []

        for item in news_items:
            title = item.get('title', 'No title')
            url = item.get('link', 'No link')
            snippet = item.get('snippet', 'No snippet available')

            structured_results.append({'title': title, 'url': url, 'summary': snippet})

        logging.info(f"Fetched Google News data for query: {query}")
        return structured_results

    except requests.RequestException as e:
        logging.error(f"Google News API error: {e}")
        return [{'error': 'Failed to fetch data from Google News. Please try again later.'}]

# Main function to fetch all data from multiple sources
def fetch_trending_topics(query):
    """Fetch trending topics from all integrated sources."""
    logging.info(f"Fetching trending topics for query: {query}")

    return {
        'reddit': fetch_reddit_data(query),
        'twitter': fetch_twitter_data(query),
        'youtube': fetch_youtube_data(query),
        'google_news': fetch_google_news(query)
    }
