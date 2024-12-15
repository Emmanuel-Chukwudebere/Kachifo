import os
import logging
import time
from requests.exceptions import RequestException
from cachetools import TTLCache
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from huggingface_hub import InferenceClient
from dotenv import load_dotenv
import praw
import requests
from requests_oauthlib import OAuth1

# Load Environment Variables
load_dotenv()
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET_KEY = os.getenv('TWITTER_API_SECRET_KEY')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_TOKEN_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.getenv('REDDIT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
HF_SUMMARY_MODEL = "facebook/bart-large-cnn"
HF_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"
HF_BOT_MODEL = "facebook/blenderbot-400M-distill"
HF_QA_MODEL = "deepset/roberta-base-squad2"
HF_SENTIMENT_MODEL = "cardiffnlp/twitter-roberta-base-sentiment"

# Initialize Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Cache
cache = TTLCache(maxsize=1000, ttl=3600)

# Hugging Face API Clients
summary_client = InferenceClient(model=HF_SUMMARY_MODEL, token=HF_API_KEY)
ner_client = InferenceClient(model=HF_NER_MODEL, token=HF_API_KEY)
bot_client = InferenceClient(model=HF_BOT_MODEL, token=HF_API_KEY)
qa_client = InferenceClient(model=HF_QA_MODEL, token=HF_API_KEY)
sentiment_client = InferenceClient(model=HF_SENTIMENT_MODEL, token=HF_API_KEY)

# Google API Client
google_client = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)

# Reddit Client
reddit_client = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

# Twitter OAuth1 Session
twitter_auth = OAuth1(
    TWITTER_API_KEY, TWITTER_API_SECRET_KEY,
    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
)

# Utility Function: Retry with Exponential Backoff
def retry_with_backoff(func, retries=3, delay=2):
    """Retries a function with exponential backoff."""
    for attempt in range(retries):
        try:
            return func()
        except RequestException as e:
            if attempt < retries - 1:
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(delay * (2 ** attempt))
            else:
                logger.error(f"All attempts failed: {e}")
                raise

# Hugging Face Integrations
def summarize_text(text):
    """Summarizes text using Hugging Face API."""
    if text in cache:
        logger.info("Cache hit for summarization.")
        return cache[text]

    try:
        logger.info("Calling Hugging Face Summarization API.")
        response = summary_client.summarization(text, parameters={"max_length": 150, "min_length": 50})
        summary = response.get('summary_text', "No summary available")
        cache[text] = summary
        return summary
    except Exception as e:
        logger.error(f"Error during summarization: {e}")
        return "Summarization unavailable."

# Additional Integrations
def fetch_google_results(query):
    """Fetches search results from Google."""
    try:
        logger.info(f"Fetching Google results for query: {query}")
        response = google_client.cse().list(q=query, cx="your_cse_id", num=5).execute()
        return response.get('items', [])
    except Exception as e:
        logger.error(f"Error during Google search: {e}")
        return []

def fetch_youtube_results(query):
    """Fetches YouTube videos for a query."""
    try:
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
        response = requests.get(url).json()
        return [
            {
                "title": item['snippet']['title'],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "summary": summarize_text(item['snippet']['description'])
            }
            for item in response.get('items', [])
        ]
    except Exception as e:
        logger.error(f"Error fetching YouTube data: {e}")
        return []

def fetch_reddit_results(query):
    """Fetches top Reddit posts for a query."""
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
        logger.error(f"Error fetching Reddit data: {e}")
        return []

def fetch_twitter_results(query):
    """Fetches recent tweets for a query."""
    try:
        url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&max_results=3"
        response = requests.get(url, auth=twitter_auth).json()
        return [
            {
                "text": tweet['text'],
                "url": f"https://twitter.com/i/web/status/{tweet['id']}"
            }
            for tweet in response.get('data', [])
        ]
    except Exception as e:
        logger.error(f"Error fetching Twitter data: {e}")
        return []

def fetch_trending_topics(query):
    """Aggregates trends from multiple sources."""
    google_results = fetch_google_results(query)
    youtube_results = fetch_youtube_results(query)
    reddit_results = fetch_reddit_results(query)
    twitter_results = fetch_twitter_results(query)

    return {
        "google": google_results,
        "youtube": youtube_results,
        "reddit": reddit_results,
        "twitter": twitter_results
    }

if __name__ == "__main__":
    query = "Artificial Intelligence"
    trends = fetch_trending_topics(query)
    print(trends)
