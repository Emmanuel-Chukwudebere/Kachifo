import os
import requests
import logging
import sys
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException
import re
from cachetools import cached, TTLCache
import spacy

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
TWITTER_API_KEY = get_env_var('TWITTER_API_KEY')
TWITTER_ACCESS_TOKEN = get_env_var('TWITTER_ACCESS_TOKEN')
REDDIT_CLIENT_ID = get_env_var('REDDIT_CLIENT_ID')
REDDIT_SECRET = get_env_var('REDDIT_SECRET')
REDDIT_USER_AGENT = get_env_var('REDDIT_USER_AGENT')
GOOGLE_CSE_ID = get_env_var('GOOGLE_CSE_ID')

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
    # Simple summarization: return first sentence as a summary
    return str(sentences[0]) if sentences else "No summary available."

# Error handling decorator for API requests
def handle_api_errors(func):
    """Decorator to handle exceptions for API calls."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RequestException as e:
            logging.error(f"API request error: {e}")
            return {'error': f"Failed to fetch data from API. Error: {str(e)}"}
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            return {'error': "An unexpected error occurred. Please try again later."}
    return wrapper

# Fetch and cache data from Reddit
@cached(cache)
@handle_api_errors
def fetch_reddit_data(query):
    """Fetch trending Reddit posts based on the sanitized query."""
    query = sanitize_input(query)
    reddit_auth_url = "https://www.reddit.com/api/v1/access_token"
    auth = HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
    data = {'grant_type': 'client_credentials'}
    headers = {'User-Agent': REDDIT_USER_AGENT}

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

        structured_results.append({
            'title': title,
            'url': url,
            'summary': summary
        })

    logging.info(f"Fetched Reddit data for query: {query}")
    return structured_results

# Fetch and cache data from Twitter
@cached(cache)
@handle_api_errors
def fetch_twitter_data(query):
    """Fetch trending tweets from Twitter based on the sanitized query."""
    query = sanitize_input(query)
    search_url = f"https://api.twitter.com/1.1/search/tweets.json?q={query}&count=10"
    headers = {
        'Authorization': f'Bearer {TWITTER_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }

    response = requests.get(search_url, headers=headers)
    response.raise_for_status()

    tweets = response.json().get('statuses', [])
    structured_results = []

    for tweet in tweets:
        text = tweet.get('text', 'No text available')
        tweet_url = f"https://twitter.com/user/status/{tweet.get('id_str', '')}"
        summary = summarize_text(text)

        structured_results.append({
            'tweet': text,
            'url': tweet_url,
            'summary': summary
        })

    logging.info(f"Fetched Twitter data for query: {query}")
    return structured_results

# Fetch and cache data from YouTube
@cached(cache)
@handle_api_errors
def fetch_youtube_data(query):
    """Fetch trending YouTube videos based on the sanitized query."""
    query = sanitize_input(query)
    youtube_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=10&q={query}&key={YOUTUBE_API_KEY}"
    
    response = requests.get(youtube_url)
    response.raise_for_status()

    videos = response.json().get('items', [])
    structured_results = []

    for video in videos:
        title = video['snippet'].get('title', 'No title')
        video_id = video['id'].get('videoId', '')
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        description = video['snippet'].get('description', '')
        summary = summarize_text(description)

        structured_results.append({
            'title': title,
            'url': video_url,
            'summary': summary
        })

    logging.info(f"Fetched YouTube data for query: {query}")
    return structured_results

# Fetch and cache data from NewsAPI
@cached(cache)
@handle_api_errors
def fetch_news_data(query):
    """Fetch trending news articles based on the sanitized query."""
    query = sanitize_input(query)
    news_url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}&pageSize=10"

    response = requests.get(news_url)
    response.raise_for_status()

    articles = response.json().get('articles', [])
    structured_results = []

    for article in articles:
        title = article.get('title', 'No title')
        article_url = article.get('url', '')
        content = article.get('content', '')
        summary = summarize_text(content)

        structured_results.append({
            'title': title,
            'url': article_url,
            'summary': summary
        })

    logging.info(f"Fetched NewsAPI data for query: {query}")
    return structured_results

# Main function to fetch trending topics from multiple sources
@handle_api_errors
def fetch_trending_topics(query):
    """Fetch trending topics from multiple APIs and aggregate the results."""
    logging.info(f"Fetching trending topics for query: {query}")

    reddit_results = fetch_reddit_data(query)
    twitter_results = fetch_twitter_data(query)
    youtube_results = fetch_youtube_data(query)
    news_results = fetch_news_data(query)

    combined_results = {
        'reddit': reddit_results,
        'twitter': twitter_results,
        'youtube': youtube_results,
        'news': news_results
    }

    logging.info(f"Fetched combined results for query: {query}")
    return combined_results