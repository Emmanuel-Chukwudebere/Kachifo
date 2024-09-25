import os
import requests
import logging
from requests.exceptions import RequestException
from cachetools import cached, TTLCache
import re
from dotenv import load_dotenv
import spacy

# Load environment variables
load_dotenv()

# Initialize logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize SpaCy NLP model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    logger.info("Downloading SpaCy model...")
    from spacy.cli import download
    download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# Cache setup: 1-hour time-to-live, max 1000 items
cache = TTLCache(maxsize=1000, ttl=3600)

# API keys from environment variables
def get_env_var(key):
    value = os.getenv(key)
    if not value:
        logger.error(f"Environment variable {key} is missing.")
        raise ValueError(f"{key} is required but not set.")
    return value

YOUTUBE_API_KEY = get_env_var('YOUTUBE_API_KEY')
GOOGLE_API_KEY = get_env_var('GOOGLE_API_KEY')
NEWSAPI_KEY = get_env_var('NEWSAPI_KEY')
TWITTER_BEARER_TOKEN = get_env_var('TWITTER_BEARER_TOKEN')
REDDIT_CLIENT_ID = get_env_var('REDDIT_CLIENT_ID')
REDDIT_SECRET = get_env_var('REDDIT_SECRET')
REDDIT_USER_AGENT = get_env_var('REDDIT_USER_AGENT')

# Helper function for input sanitization
def sanitize_input(query):
    """Sanitize input to prevent injection attacks."""
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Use SpaCy to summarize text
def summarize_text(text):
    """Summarize the provided text using NLP."""
    doc = nlp(text)
    sentences = list(doc.sents)
    summary = " ".join(str(sent) for sent in sentences[:3])  # Use first 3 sentences
    logger.info(f"Generated summary: {summary}")
    return summary

# Fetch trending topics from different sources
@cached(cache)
def fetch_trending_topics(query):
    try:
        logger.info(f"Fetching trends for query: {query}")
        
        # Fetch from multiple sources
        youtube_results = fetch_youtube_trends(query)
        reddit_results = fetch_reddit_trends(query)
        news_results = fetch_news_trends(query)
        twitter_results = fetch_twitter_trends(query)
        google_results = fetch_google_trends(query)
        
        results = youtube_results + reddit_results + news_results + twitter_results + google_results
        
        # Limit to first 10 results
        return results[:10]

    except Exception as e:
        logger.error(f"Error fetching trending topics: {str(e)}", exc_info=True)
        return []

# API integration functions
def fetch_youtube_trends(query):
    """Fetch trending YouTube videos matching the query."""
    try:
        logger.info(f"Fetching YouTube trends for query: {query}")
        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&key={YOUTUBE_API_KEY}"
        response = requests.get(search_url)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['snippet']['title']
            description = item['snippet']['description']
            video_url = f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            
            # Summarize description using SpaCy
            summary = summarize_text(description)
            
            results.append({
                'source': 'YouTube',
                'title': title,
                'summary': summary,
                'url': video_url
            })
        
        logger.info(f"Fetched {len(results)} YouTube trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

def fetch_reddit_trends(query):
    """Fetch trending Reddit posts matching the query."""
    try:
        logger.info(f"Fetching Reddit trends for query: {query}")
        reddit_auth = requests.auth.HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
        reddit_headers = {
            'User-Agent': REDDIT_USER_AGENT
        }
        reddit_data = {
            'grant_type': 'client_credentials'
        }
        
        token_response = requests.post('https://www.reddit.com/api/v1/bearer_token', auth=reddit_auth, data=reddit_data, headers=reddit_headers)
        token_response.raise_for_status()
        token = token_response.json()['bearer_token']
        
        headers = {
            'Authorization': f'Bearer {token}',
            'User-Agent': REDDIT_USER_AGENT
        }
        
        search_url = f"https://oauth.reddit.com/r/all/search?q={query}&limit=10"
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data['data']['children']:
            title = item['data']['title']
            selftext = item['data']['selftext']
            post_url = f"https://reddit.com{item['data']['permalink']}"
            
            # Summarize post text using SpaCy
            summary = summarize_text(selftext)
            
            results.append({
                'source': 'Reddit',
                'title': title,
                'summary': summary,
                'url': post_url
            })

        logger.info(f"Fetched {len(results)} Reddit trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

def fetch_news_trends(query):
    """Fetch trending news articles matching the query."""
    try:
        logger.info(f"Fetching news trends for query: {query}")
        search_url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
        response = requests.get(search_url)
        response.raise_for_status()
        data = response.json()

        results = []
        for article in data['articles']:
            title = article['title']
            content = article['content'] or article['description']
            article_url = article['url']
            
            # Summarize content using SpaCy
            summary = summarize_text(content)
            
            results.append({
                'source': 'NewsAPI',
                'title': title,
                'summary': summary,
                'url': article_url
            })

        logger.info(f"Fetched {len(results)} news trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching news trends: {str(e)}")
        return []

def fetch_twitter_trends(query):
    """Fetch trending tweets matching the query."""
    try:
        logger.info(f"Fetching Twitter trends for query: {query}")
        search_url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&tweet.fields=text"
        headers = {
            "Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"
        }
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        data = response.json()

        results = []
        for tweet in data.get('data', []):
            tweet_text = tweet['text']
            
            # Summarize tweet text using SpaCy
            summary = summarize_text(tweet_text)
            
            results.append({
                'source': 'Twitter',
                'title': "Tweet",
                'summary': summary,
                'url': f"https://twitter.com/twitter/status/{tweet['id']}"
            })

        logger.info(f"Fetched {len(results)} Twitter trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []

def fetch_google_trends(query):
    """Fetch Google Custom Search results matching the query."""
    try:
        logger.info(f"Fetching Google search trends for query: {query}")
        search_url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={GOOGLE_API_KEY}&cx={os.getenv('GOOGLE_CSE_ID')}"
        response = requests.get(search_url)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['title']
            snippet = item['snippet']
            link = item['link']
            
            # Summarize snippet using SpaCy
            summary = summarize_text(snippet)
            
            results.append({
                'source': 'Google',
                'title': title,
                'summary': summary,
                'url': link
            })

        logger.info(f"Fetched {len(results)} Google trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []