import os
import logging
import time
import requests
from cachetools import TTLCache
from dotenv import load_dotenv
from requests.exceptions import RequestException, Timeout
from requests_oauthlib import OAuth1
import praw

# Load environment variables
load_dotenv()

# Initialize Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Cache setup: 1-hour time-to-live, max 1000 items
cache = TTLCache(maxsize=1000, ttl=3600)

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET_KEY = os.getenv("TWITTER_API_SECRET_KEY")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT")

# Hugging Face API keys and models
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"

# Initialize Reddit client
reddit_client = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# Twitter OAuth1 Session
twitter_auth = OAuth1(
    TWITTER_API_KEY,
    TWITTER_API_SECRET_KEY,
    TWITTER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET
)

# Retry logic with exponential backoff
def retry_with_backoff(func, *args, retries=3, delay=2, backoff=2, **kwargs):
    """Retry a function with exponential backoff."""
    _retries, _delay = retries, delay
    while _retries > 0:
        try:
            return func(*args, **kwargs)
        except (RequestException, Timeout) as e:
            _retries -= 1
            if _retries == 0:
                logger.error(f"All retries failed: {e}")
                raise
            logger.warning(f"Retrying in {_delay} seconds due to error: {e}")
            time.sleep(_delay)
            _delay *= backoff

# Summarize text
def summarize_text(text):
    """Summarizes text using Hugging Face Summarization API."""
    if text in cache:
        logger.info("Cache hit for summarization.")
        return cache[text]

    try:
        logger.info("Calling Hugging Face Summarization API.")
        response = requests.post(
            f"https://api-inference.huggingface.co/models/{HF_API_SUMMARY_MODEL}",
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json={"inputs": text[:1024]}
        )
        response.raise_for_status()
        summary = response.json().get('summary_text', "No summary available")
        cache[text] = summary
        return summary
    except Exception as e:
        logger.error(f"Error during summarization: {e}")
        return "Summarization unavailable."

# Fetch YouTube trends
def fetch_youtube_trends(query):
    """Fetch trends from YouTube based on a query."""
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
    try:
        response = retry_with_backoff(requests.get, url)
        results = response.json().get('items', [])
        return [
            {
                "title": item['snippet']['title'],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "summary": summarize_text(item['snippet']['description'])
            } for item in results
        ]
    except Exception as e:
        logger.error(f"Error fetching YouTube trends: {e}")
        return []

# Fetch Twitter trends
def fetch_twitter_trends(query):
    """Fetch recent tweets based on a query."""
    url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&max_results=3"
    try:
        response = retry_with_backoff(requests.get, url, auth=twitter_auth)
        tweets = response.json().get('data', [])
        return [
            {
                "text": tweet['text'],
                "url": f"https://twitter.com/i/web/status/{tweet['id']}",
                "summary": summarize_text(tweet['text'])
            } for tweet in tweets
        ]
    except Exception as e:
        logger.error(f"Error fetching Twitter trends: {e}")
        return []

# Fetch Google trends
def fetch_google_trends(query):
    """Fetch search results from Google using CSE."""
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}"
    try:
        response = retry_with_backoff(requests.get, url)
        items = response.json().get('items', [])
        return [
            {
                "title": item['title'],
                "url": item['link'],
                "summary": summarize_text(item.get('snippet', ''))
            } for item in items
        ]
    except Exception as e:
        logger.error(f"Error fetching Google trends: {e}")
        return []

# Fetch Reddit trends
def fetch_reddit_trends(query):
    """Fetch top Reddit posts based on a query."""
    try:
        results = []
        for submission in reddit_client.subreddit("all").search(query, sort="top", limit=3):
            results.append({
                "title": submission.title,
                "url": submission.url,
                "summary": summarize_text(submission.selftext[:500])
            })
        return results
    except Exception as e:
        logger.error(f"Error fetching Reddit trends: {e}")
        return []

# Fetch news articles
def fetch_news_articles(query):
    """Fetch news articles from NewsAPI."""
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
    try:
        response = retry_with_backoff(requests.get, url)
        articles = response.json().get('articles', [])
        return [
            {
                "title": article['title'],
                "url": article['url'],
                "summary": summarize_text(article.get('description', ''))
            } for article in articles
        ]
    except Exception as e:
        logger.error(f"Error fetching news articles: {e}")
        return []

# Fetch all trends
def fetch_trending_topics(query):
    """Fetch trends from YouTube, Reddit, Google, Twitter, and News."""
    youtube_trends = fetch_youtube_trends(query)
    reddit_trends = fetch_reddit_trends(query)
    twitter_trends = fetch_twitter_trends(query)
    google_trends = fetch_google_trends(query)
    news_trends = fetch_news_articles(query)

    return {
        "youtube": youtube_trends,
        "reddit": reddit_trends,
        "twitter": twitter_trends,
        "google": google_trends,
        "news": news_trends
    }

if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    print(trends)
