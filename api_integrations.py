import os
import requests
import logging
from requests.exceptions import RequestException
from cachetools import cached, TTLCache
import re
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import html2text
import spacy

# Load environment variables
load_dotenv()

# Initialize logging
logger = logging.getLogger(__name__)

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
TWITTER_ACCESS_TOKEN = get_env_var('TWITTER_ACCESS_TOKEN')
REDDIT_CLIENT_ID = get_env_var('REDDIT_CLIENT_ID')
REDDIT_SECRET = get_env_var('REDDIT_SECRET')
REDDIT_USER_AGENT = get_env_var('REDDIT_USER_AGENT')

# Helper function for input sanitization
def sanitize_input(query):
    """Sanitize input to prevent injection attacks."""
    sanitized = re.sub(r"[^\w\s]", "", query).strip()
    logger.info(f"Sanitized input: {sanitized}")
    return sanitized

# Helper function for summarizing text using SpaCy
def summarize_text(text, max_sentences=3):
    """Summarize text using SpaCy NLP."""
    doc = nlp(text)
    sentences = list(doc.sents)
    if not sentences:
        return "No content available."
    return " ".join(str(sent) for sent in sentences[:max_sentences])

# Helper function to fetch and parse webpage content
def fetch_webpage_content(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        h = html2text.HTML2Text()
        h.ignore_links = True
        text_content = h.handle(soup.get_text())
        return summarize_text(text_content)
    except Exception as e:
        logger.error(f"Error fetching webpage content: {str(e)}")
        return "Unable to fetch content."

# Error handling decorator for API requests
def handle_api_errors(func):
    """Decorator to handle API errors gracefully."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RequestException as e:
            logger.error(f"API request failed: {str(e)}", exc_info=True)
            return {'error': 'API request failed. Please try again later.'}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return {'error': 'An unexpected error occurred. Please try again later.'}
    return wrapper

@handle_api_errors
@cached(cache)
def fetch_trending_topics(query):
    """Fetch trending topics from YouTube, Reddit, and Twitter based on a query."""
    logger.info(f"Fetching trending topics for query: {query}")
    sanitized_query = sanitize_input(query)
    combined_results = []
    
    # YouTube API
    youtube_results = fetch_youtube_trends(sanitized_query)
    combined_results.extend(youtube_results)
    
    # Reddit API
    reddit_results = fetch_reddit_trends(sanitized_query)
    combined_results.extend(reddit_results)
    
    # Twitter API
    twitter_results = fetch_twitter_trends(sanitized_query)
    combined_results.extend(twitter_results)
    
    logger.info(f"Total results fetched: {len(combined_results)}")
    return combined_results

@handle_api_errors
def fetch_youtube_trends(query):
    youtube_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&key={YOUTUBE_API_KEY}"
    youtube_response = requests.get(youtube_url, timeout=10)
    youtube_data = youtube_response.json()
    results = []
    for item in youtube_data.get('items', []):
        video_id = item['id']['videoId']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        results.append({
            'source': 'YouTube',
            'title': item['snippet']['title'],
            'summary': summarize_text(item['snippet']['description']),
            'url': video_url
        })
    logger.info(f"YouTube results fetched: {len(results)}")
    return results

@handle_api_errors
def fetch_reddit_trends(query):
    reddit_url = f"https://www.reddit.com/search.json?q={query}&sort=top&t=week"
    reddit_response = requests.get(reddit_url, headers={'User-Agent': REDDIT_USER_AGENT}, timeout=10)
    reddit_data = reddit_response.json()
    results = []
    for post in reddit_data.get('data', {}).get('children', []):
        post_url = f"https://www.reddit.com{post['data']['permalink']}"
        summary = summarize_text(post['data'].get('selftext', '')) if post['data'].get('selftext') else fetch_webpage_content(post_url)
        results.append({
            'source': 'Reddit',
            'title': post['data']['title'],
            'summary': summary,
            'url': post_url
        })
    logger.info(f"Reddit results fetched: {len(results)}")
    return results

@handle_api_errors
def fetch_twitter_trends(query):
    twitter_url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&tweet.fields=created_at,entities"
    twitter_response = requests.get(twitter_url, headers={'Authorization': f"access {TWITTER_ACCESS_TOKEN}"}, timeout=10)
    twitter_data = twitter_response.json()
    results = []
    for tweet in twitter_data.get('data', []):
        tweet_url = f"https://twitter.com/i/web/status/{tweet['id']}"
        summary = summarize_text(tweet['text'])
        if 'entities' in tweet and 'urls' in tweet['entities']:
            for url in tweet['entities']['urls']:
                expanded_url = url['expanded_url']
                if expanded_url != tweet_url:
                    summary += " " + fetch_webpage_content(expanded_url)
        results.append({
            'source': 'Twitter',
            'title': tweet['text'][:100] + "...",  # Use first 100 characters as title
            'summary': summary,
            'url': tweet_url
        })
    logger.info(f"Twitter results fetched: {len(results)}")
    return results

if __name__ == "__main__":
    # Test the function
    test_query = "artificial intelligence"
    results = fetch_trending_topics(test_query)
    print(f"Results for '{test_query}':")
    for result in results:
        print(f"- {result['source']}: {result['title']}")
        print(f"  Summary: {result['summary']}")
        print(f"  URL: {result['url']}")
    print()