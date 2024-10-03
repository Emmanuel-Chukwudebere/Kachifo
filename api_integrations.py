import os
import requests
import logging
from requests.exceptions import RequestException, Timeout
from cachetools import TTLCache
import time
from functools import wraps
from dotenv import load_dotenv
from typing import List, Dict, Any
from huggingface_hub import InferenceClient
import praw
import json
from functools import wraps
import re
from requests_oauthlib import OAuth1

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Cache setup: 1-hour time-to-live, max 1000 items
cache = TTLCache(maxsize=1000, ttl=3600)

# API keys from environment variables
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

# API keys and URLs
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"  # Summarization model
HF_API_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"  # NER model

# Initialize the InferenceClient for summarization
inference_summary = InferenceClient(model="facebook/bart-large-cnn", token=os.getenv('HUGGINGFACE_API_KEY'))

# Initialize the InferenceClient for NER
inference_ner = InferenceClient(model="dbmdz/bert-large-cased-finetuned-conll03-english", token=os.getenv('HUGGINGFACE_API_KEY'))

# Cache setup: 1-hour time-to-live, max 1000 items
summary_cache = TTLCache(maxsize=1000, ttl=3600)
entity_cache = TTLCache(maxsize=1000, ttl=3600)

# Rate limit configuration
def rate_limited(max_per_second: float):
    """Limits the number of API calls per second."""
    min_interval = 1.0 / max_per_second
    last_called = [0.0]

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            wait_time = min_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            last_called[0] = time.time()
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Retry logic with exponential backoff
def retry_with_backoff(exceptions, tries=3, delay=2, backoff=2):
    """Retry decorator for functions in case of failure."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    logger.warning(f"{func.__name__} failed due to {str(e)}, retrying in {_delay} seconds...")
                    time.sleep(_delay)
                    _tries -= 1
                    _delay *= backoff
            return func(*args, **kwargs)
        return wrapper
    return decorator

@rate_limited(max_per_second=1.0)  # Customize based on API rate limits
@retry_with_backoff((RequestException, Timeout), tries=3)
def summarize_with_hf(text: str) -> str:
    """Summarizes text using Hugging Face Hub API with caching and logging."""
    # Check if summarization result is already cached
    if text in summary_cache:
        logger.info(f"Cache hit for summarization: {text[:100]}...")  # Log part of the input for clarity
        return summary_cache[text]

    try:
        logger.info(f"Calling Hugging Face Summarization API for text: {text[:100]}...")  # Log partial input text
        response = inference_summary.summarization(text, parameters={"max_length": 150, "min_length": 50, "do_sample": False})
        summary = response.get('summary_text', "No summary available")

        # Log the result of the summarization
        logger.info(f"Summary generated: {summary[:100]}...")  # Log part of the output for clarity

        # Cache the result
        summary_cache[text] = summary
        return summary
    except Exception as e:
        logger.error(f"Error calling Hugging Face Summarization API: {str(e)}")
        return "Sorry, summarization is unavailable at the moment."

@rate_limited(max_per_second=1.0)  # Customize based on API rate limits
@retry_with_backoff((RequestException, Timeout), tries=3)
def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    """Extracts named entities using Hugging Face Hub API with caching and logging."""
    if text in entity_cache:
        logger.info(f"Cache hit for NER: {text[:100]}...")  # Log part of the input for clarity
        return entity_cache[text]

    try:
        logger.info(f"Calling Hugging Face NER API for text: {text[:100]}...")  # Log partial input text
        response = inference_ner.token_classification(text)
        entities = [ent['word'] for ent in response if ent['entity_group'] in ['ORG', 'PER', 'LOC']]

        # Log the result of the NER call
        logger.info(f"Entities extracted: {entities}")  # Log the extracted entities

        # Cache the result
        entity_cache[text] = {"entities": entities}
        return {"entities": entities}
    except Exception as e:
        logger.error(f"Error calling Hugging Face NER API: {str(e)}")
        return {"entities": []}

# Fetch trending topics (combined from multiple sources)
@retry_with_backoff((RequestException, Timeout), tries=3)
def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """Fetch all trends (YouTube, News, Google, Twitter, Reddit) for the given query."""
    trends = []
    try:
        # Call multiple external APIs to fetch trends (e.g., YouTube, Google, Twitter)
        trends.extend(fetch_youtube_trends(query))
        trends.extend(fetch_news_trends(query))
        trends.extend(fetch_google_trends(query))
        trends.extend(fetch_twitter_trends(query))
        trends.extend(fetch_reddit_trends(query))

        logger.info(f"Fetched total {len(trends)} trends from all sources.")
        return trends
    except Exception as e:
        logger.error(f"Error fetching trends: {str(e)}")
        return []
        
# General summary from individual summaries
def generate_general_summary(individual_summaries: List[str]) -> str:
    """Generates a general summary using Hugging Face Hub API from individual summaries."""
    combined_text = " ".join(individual_summaries)  # Combine all individual summaries into one text

    try:
        logger.info("Calling Hugging Face Summarization API for general summary")
        response = inference_summary.summarization(combined_text, parameters={"max_length": 200, "min_length": 100, "do_sample": False})
        general_summary = response.get('summary_text', "No summary available")
        return general_summary
    except Exception as e:
        logger.error(f"Error generating general summary: {str(e)}")
        return "Sorry, I couldn't generate a summary at the moment."

# Fetch YouTube trends (Limited to 3 results)
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending YouTube videos matching the query."""
    try:
        logger.info(f"Fetching YouTube trends for query: {query}")
        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['snippet']['title']
            description = item['snippet']['description']
            video_url = f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            summary = summarize_with_hf(description)

            if title and summary and video_url:
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

# Fetch News trends (Limited to 3 results)
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
def fetch_news_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending news articles matching the query."""
    try:
        logger.info(f"Fetching news trends for query: {query}")
        search_url = f"https://newsapi.org/v2/everything?q={query}&pageSize=3&apiKey={NEWSAPI_KEY}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for article in data['articles']:
            title = article['title']
            content = article['content'] or article['description']
            article_url = article['url']
            summary = summarize_with_hf(content)

            if title and summary and article_url:
                results.append({
                    'source': 'News Article',
                    'title': title,
                    'summary': summary,
                    'url': article_url
                })

        logger.info(f"Fetched {len(results)} news trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching news trends: {str(e)}")
        return []

# Fetch Google Search trends (Limited to 3 results)
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch Google Custom Search results matching the query."""
    try:
        logger.info(f"Fetching Google search trends for query: {query}")
        search_url = f"https://www.googleapis.com/customsearch/v1?q={query}&num=3&key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['title']
            snippet = item['snippet']
            link = item['link']
            summary = summarize_with_hf(snippet)

            if title and summary and link:
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

# Twitter API: Fetch trending tweets
@rate_limited(1.0)  # Limiting to 1 request per second
@retry_with_backoff((RequestException, Timeout), tries=3)
def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending tweets matching the query."""
    try:
        logger.info(f"Fetching Twitter trends for query: {query}")
        # Twitter uses OAuth1 authentication
        auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET_KEY, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET)
        search_url = f"https://api.twitter.com/1.1/search/tweets.json?q={query}&result_type=popular&count=3"
        
        response = requests.get(search_url, auth=auth, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for tweet in data['statuses']:
            tweet_text = tweet['text']
            user_name = tweet['user']['screen_name']
            tweet_url = f"https://twitter.com/{user_name}/status/{tweet['id_str']}"
            summary = summarize_with_hf(tweet_text)

            if tweet_text and summary and tweet_url:
                results.append({
                    'source': 'Twitter',
                    'title': f"Tweet by @{user_name}",
                    'summary': summary,
                    'url': tweet_url
                })

        logger.info(f"Fetched {len(results)} Twitter trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []
        
# Initialize Reddit API with PRAW
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_SECRET,
    user_agent=REDDIT_USER_AGENT
)
        
@rate_limited(1.0)  # Limiting to 1 request per second
@retry_with_backoff((RequestException, Timeout), tries=3)
def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending Reddit posts matching the query."""
    try:
        logger.info(f"Fetching Reddit trends for query: {query}")
        # Search for the query on Reddit
        results = []
        for submission in reddit.subreddit("all").search(query, sort="top", limit=3):
            post_title = submission.title
            post_url = submission.url
            post_content = submission.selftext[:500]  # Reddit posts can be long, truncate if necessary
            summary = summarize_with_hf(post_content)

            if post_title and summary and post_url:
                results.append({
                    'source': 'Reddit',
                    'title': post_title,
                    'summary': summary,
                    'url': post_url
                })

        logger.info(f"Fetched {len(results)} Reddit trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []
        

# Entry point for the script
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    print(trends)