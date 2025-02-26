import os
import logging
import time
import requests
from cachetools import TTLCache
from functools import wraps
from dotenv import load_dotenv
from typing import List, Dict, Any
import praw
import json
import re

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# In-memory caches for summaries and entities
summary_cache = TTLCache(maxsize=1000, ttl=3600)
entity_cache = TTLCache(maxsize=1000, ttl=3600)

# API keys and configuration variables
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

# Hugging Face API configuration and models
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"
HF_API_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"
HF_API_BOT_MODEL = "facebook/blenderbot-400M-distill"

# Use synchronous InferenceClient from huggingface_hub
from huggingface_hub import InferenceClient

inference_summary = InferenceClient(model=HF_API_SUMMARY_MODEL, token=HF_API_KEY)
inference_ner = InferenceClient(model=HF_API_NER_MODEL, token=HF_API_KEY)
inference_bot = InferenceClient(model=HF_API_BOT_MODEL, token=HF_API_KEY)

def rate_limited(max_per_second: float):
    min_interval = 1.0 / max_per_second
    def decorator(func):
        last_called = [0.0]
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

def retry_with_backoff(exceptions, tries=3, delay=2, backoff=2):
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

def generate_general_summary(individual_summaries: List[str]) -> str:
    combined_text = " ".join(individual_summaries)
    try:
        logger.info("Generating general summary via Hugging Face API")
        response = inference_summary.summarization(combined_text)
        return response.get('summary_text', "No summary available")
    except Exception as e:
        logger.error(f"Error generating general summary: {str(e)}")
        return "Sorry, I couldn't generate a summary at the moment."

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def summarize_with_hf(text: str) -> str:
    if text in summary_cache:
        logger.info(f"Cache hit for summarization: {text[:100]}...")
        return summary_cache[text]
    try:
        logger.info(f"Summarizing text: {text[:100]}...")
        max_input_length = 1024
        truncated_text = text[:max_input_length]
        response = inference_summary.summarization(truncated_text)
        summary = response.get('summary_text', "No summary available")
        summary_cache[text] = summary
        return summary
    except Exception as e:
        logger.error(f"Error in summarization: {str(e)}")
        return "Sorry, summarization is unavailable at the moment."

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    if text in entity_cache:
        logger.info(f"Cache hit for NER: {text[:100]}...")
        return entity_cache[text]
    try:
        logger.info(f"Extracting entities from text: {text[:100]}...")
        max_input_length = 512
        truncated_text = text[:max_input_length]
        response = inference_ner.token_classification(truncated_text)
        entities = [ent['word'] for ent in response if ent['entity_group'] in ['ORG', 'PER', 'LOC']]
        entity_cache[text] = {"entities": entities}
        return {"entities": entities}
    except Exception as e:
        logger.error(f"Error extracting entities: {str(e)}")
        return {"entities": []}

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def generate_conversational_response(user_input: str) -> str:
    try:
        logger.info(f"Generating conversational response for input: {user_input[:100]}...")
        response = inference_bot.chat_completion(messages=[{"role": "user", "content": user_input}], stream=False)
        content = response.get('choices', [{}])[0].get('message', {}).get('content', "")
        if not content:
            raise ValueError("Empty response")
        return content
    except Exception as e:
        logger.error(f"Error generating conversational response: {str(e)}")
        # Fallback for typical greeting queries
        if re.search(r'\bhow are you\b', user_input, re.IGNORECASE):
            return "I'm doing well, thank you! How can I assist you today?"
        return "I'm sorry, I'm experiencing some difficulties at the moment. How can I help you?"

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
    try:
        response = requests.get(url)
        result = response.json()
        items = result.get('items', [])
        return [{
            "title": item['snippet']['title'],
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            "summary": summarize_with_hf(item['snippet']['description'])
        } for item in items]
    except Exception as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}"
    try:
        response = requests.get(url)
        result = response.json()
        items = result.get('items', [])
        return [{
            "title": item.get("title"),
            "url": item.get("link"),
            "summary": summarize_with_hf(item.get("snippet", ""))
        } for item in items]
    except Exception as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    reddit = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT")
    )
    try:
        results = []
        for submission in reddit.subreddit("all").search(query, sort="top", limit=3):
            summary = summarize_with_hf(submission.selftext[:500])
            results.append({
                "title": submission.title,
                "url": submission.url,
                "summary": summary
            })
        return results
    except Exception as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_news_articles(query: str) -> List[Dict[str, Any]]:
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
    try:
        response = requests.get(url)
        result = response.json()
        articles = result.get('articles', [])
        return [{
            "title": article.get("title"),
            "url": article.get("url"),
            "summary": summarize_with_hf(article.get("description", ""))
        } for article in articles]
    except Exception as e:
        logger.error(f"Error fetching news articles: {str(e)}")
        return []

def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    logger.info(f"Fetching trending topics for query: {query}")
    youtube_trends = fetch_youtube_trends(query)
    reddit_trends = fetch_reddit_trends(query)
    google_trends = fetch_google_trends(query)
    news_trends = fetch_news_articles(query)
    return youtube_trends + reddit_trends + google_trends + news_trends

if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    print(json.dumps(trends, indent=2))