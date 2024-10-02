import os
import requests
import logging
from requests.exceptions import RequestException, Timeout
from requests_oauthlib import OAuth1
from cachetools import cached, TTLCache
from dotenv import load_dotenv
from typing import List, Dict, Any
import time
import praw
import json
from functools import wraps
import re
from nltk.tokenize import sent_tokenize
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import nltk

# Download necessary NLTK data
nltk.download('punkt')
nltk.download('stopwords')

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

# Hugging Face API URLs and Key
HF_API_URL_SUMMARY = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
HF_API_URL_NER = "https://api-inference.huggingface.co/models/dbmdz/bert-large-cased-finetuned-conll03-english"
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')

# Rate limit configuration
last_called = 0  # Initialize as global

def rate_limited(max_per_second: float):
    """Rate limit decorator."""
    min_interval = 1.0 / max_per_second
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            global last_called
            elapsed = time.time() - last_called
            wait_time = min_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            last_called = time.time()
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Retry logic decorator with exponential backoff
def retry_with_backoff(exceptions, tries=3, delay=1, backoff=2):
    """Retry decorator with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    logger.warning(f"{func.__name__} failed. Retrying in {mdelay} seconds... Error: {str(e)}")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Fallback summarization function using NLTK
def fallback_summarize(text: str, num_sentences: int = 3) -> str:
    sentences = sent_tokenize(text)
    stop_words = set(stopwords.words('english'))
    word_frequencies = {}
    
    for sentence in sentences:
        for word in word_tokenize(sentence.lower()):
            if word not in stop_words:
                if word not in word_frequencies:
                    word_frequencies[word] = 1
                else:
                    word_frequencies[word] += 1

    max_frequency = max(word_frequencies.values())
    for word in word_frequencies.keys():
        word_frequencies[word] = (word_frequencies[word] / max_frequency)

    sentence_scores = {}
    for sentence in sentences:
        for word in word_tokenize(sentence.lower()):
            if word in word_frequencies:
                if len(sentence.split(' ')) < 30:
                    if sentence not in sentence_scores:
                        sentence_scores[sentence] = word_frequencies[word]
                    else:
                        sentence_scores[sentence] += word_frequencies[word]

    summary_sentences = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[:num_sentences]
    summary = ' '.join(summary_sentences)
    return summary

# Fallback NER function
def fallback_ner(text: str) -> Dict[str, List[str]]:
    words = word_tokenize(text)
    named_entities = []
    for word in words:
        if word[0].isupper():
            named_entities.append(word)
    return {"entities": named_entities}

@retry_with_backoff((RequestException, Timeout), tries=3)
def summarize_with_hf(text):
    """Summarizes text using Hugging Face's BART model with fallback."""
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {
        "inputs": text,
        "parameters": {"max_length": 150, "min_length": 50, "do_sample": False}
    }
    try:
        response = requests.post(HF_API_URL_SUMMARY, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result[0].get('summary_text', "No summary available")
    except (RequestException, Timeout) as e:
        logger.error(f"Summarization HF API error: {str(e)}")
        return fallback_summarize(text)

@retry_with_backoff((RequestException, Timeout), tries=3)
def extract_entities_with_hf(text):
    """Extracts entities from text using Hugging Face's NER model with fallback."""
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {"inputs": text}
    try:
        response = requests.post(HF_API_URL_NER, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return {"entities": [ent['word'] for ent in result if ent['entity_group'] in ['ORG', 'PER', 'LOC']]}
    except (RequestException, Timeout) as e:
        logger.error(f"NER HF API error: {str(e)}")
        return fallback_ner(text)

# Fetch YouTube trends (Limited to 3 results)
@rate_limited(1.0)
@retry((RequestException, Timeout), tries=3)
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
@retry((RequestException, Timeout), tries=3)
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
@retry((RequestException, Timeout), tries=3)
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
@retry((RequestException, Timeout), tries=3)
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
@retry((RequestException, Timeout), tries=3)
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
        
def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """Fetch all trends (YouTube, News, Google, Twitter, Reddit) for the given query."""
    trends = []
    try:
        # Fetch from all platforms
        trends.extend(fetch_youtube_trends(query))
        trends.extend(fetch_news_trends(query))
        trends.extend(fetch_google_trends(query))
        trends.extend(fetch_twitter_trends(query))
        trends.extend(fetch_reddit_trends(query))
        logger.info(f"Fetched total {len(trends)} trends from all sources.")
        return trends
    except Exception as e:
        logger.error(f"Error fetching all trends: {str(e)}")
        return []

# Entry point for the script
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    print(trends)