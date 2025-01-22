# api_integrations.py
import os
import logging
import requests
import json
from typing import List, Dict, Any, Optional
from functools import lru_cache
from requests.exceptions import RequestException, Timeout
from requests_oauthlib import OAuth1
from huggingface_hub import InferenceClient
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
class APIConfig:
    """Configuration class for API credentials and settings"""
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
    HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
    
    # API endpoints
    YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"
    TWITTER_API_URL = "https://api.twitter.com/2/tweets/search/recent"
    GOOGLE_API_URL = "https://www.googleapis.com/customsearch/v1"
    NEWSAPI_URL = "https://newsapi.org/v2/everything"
    
    # HuggingFace models
    HF_SUMMARY_MODEL = "facebook/bart-large-cnn"
    HF_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"
    HF_BOT_MODEL = "facebook/blenderbot-400M-distill"

# Initialize HuggingFace clients
class HuggingFaceClients:
    """Singleton class for HuggingFace API clients"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.summary_client = InferenceClient(
                model=APIConfig.HF_SUMMARY_MODEL,
                token=APIConfig.HF_API_KEY
            )
            cls._instance.ner_client = InferenceClient(
                model=APIConfig.HF_NER_MODEL,
                token=APIConfig.HF_API_KEY
            )
            cls._instance.bot_client = InferenceClient(
                model=APIConfig.HF_BOT_MODEL,
                token=APIConfig.HF_API_KEY
            )
        return cls._instance

# Initialize clients
hf_clients = HuggingFaceClients()

# Caching decorator with TTL
def ttl_cache(ttl_seconds: int = 3600):
    """
    Custom TTL cache decorator
    
    Args:
        ttl_seconds (int): Time to live in seconds
    """
    def decorator(func):
        cache = {}
        
        def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)
            if key in cache:
                result, timestamp = cache[key]
                if datetime.now() - timestamp < timedelta(seconds=ttl_seconds):
                    return result
                
            result = func(*args, **kwargs)
            cache[key] = (result, datetime.now())
            return result
            
        return wrapper
    return decorator

# Error handling decorator
def api_error_handler(func):
    """Decorator for handling API errors consistently"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Timeout:
            logger.error(f"Timeout error in {func.__name__}")
            return []
        except RequestException as e:
            logger.error(f"Request error in {func.__name__}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            return []
    return wrapper

# API Integration Classes
class YouTubeAPI:
    """YouTube API integration"""
    @api_error_handler
    @ttl_cache(3600)
    def fetch_trends(self, query: str) -> List[Dict[str, Any]]:
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'maxResults': 3,
            'key': APIConfig.YOUTUBE_API_KEY
        }
        
        response = requests.get(APIConfig.YOUTUBE_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        return [{
            'title': item['snippet']['title'],
            'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            'description': item['snippet']['description'],
            'source': 'YouTube'
        } for item in data.get('items', [])]

class TwitterAPI:
    """Twitter API integration"""
    @api_error_handler
    @ttl_cache(3600)
    def fetch_trends(self, query: str) -> List[Dict[str, Any]]:
        auth = OAuth1(
            APIConfig.TWITTER_API_KEY,
            APIConfig.TWITTER_API_SECRET_KEY,
            APIConfig.TWITTER_ACCESS_TOKEN,
            APIConfig.TWITTER_ACCESS_TOKEN_SECRET
        )
        
        params = {
            'query': query,
            'max_results': 3
        }
        
        response = requests.get(APIConfig.TWITTER_API_URL, auth=auth, params=params)
        response.raise_for_status()
        data = response.json()
        
        return [{
            'title': tweet['text'],
            'url': f"https://twitter.com/statuses/{tweet['id']}",
            'description': tweet['text'],
            'source': 'Twitter'
        } for tweet in data.get('data', [])]

class GoogleAPI:
    """Google Custom Search API integration"""
    @api_error_handler
    @ttl_cache(3600)
    def fetch_trends(self, query: str) -> List[Dict[str, Any]]:
        params = {
            'q': query,
            'cx': APIConfig.GOOGLE_CSE_ID,
            'key': APIConfig.GOOGLE_API_KEY
        }
        
        response = requests.get(APIConfig.GOOGLE_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        return [{
            'title': item['title'],
            'url': item['link'],
            'description': item.get('snippet', ''),
            'source': 'Google'
        } for item in data.get('items', [])]

class NewsAPI:
    """NewsAPI integration"""
    @api_error_handler
    @ttl_cache(3600)
    def fetch_trends(self, query: str) -> List[Dict[str, Any]]:
        params = {
            'q': query,
            'apiKey': APIConfig.NEWSAPI_KEY,
            'pageSize': 3
        }
        
        response = requests.get(APIConfig.NEWSAPI_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        return [{
            'title': article['title'],
            'url': article['url'],
            'description': article.get('description', ''),
            'source': 'NewsAPI'
        } for article in data.get('articles', [])]
        
class RedditAPI:
    """RedditAPI Integration"""
    @api_error_handler
    @ttl_cache(3600)
    def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending posts from Reddit"""
    try:
        results = []
        for submission in reddit.subreddit("all").search(query, sort="top", limit=3):
            results.append({
                "title": submission.title,
                "url": submission.url,
                "summary": submission.selftext[:200] if submission.selftext else submission.title
            })
        return results
    except Exception as e:
        logger.error(f"Reddit API error: {str(e)}")
        return []

# Main functions for external use
def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """
    Fetch trends from all sources concurrently
    
    Args:
        query (str): Search query
        
    Returns:
        List[Dict[str, Any]]: Combined results from all sources
    """
    apis = [
        YouTubeAPI(),
        TwitterAPI(),
        GoogleAPI(),
        NewsAPI(),
        RedditAPI()
    ]
    
    with ThreadPoolExecutor(max_workers=len(apis)) as executor:
        results = list(executor.map(
            lambda api: api.fetch_trends(query),
            apis
        ))
    
    # Flatten results and remove duplicates
    all_results = []
    seen_urls = set()
    
    for result_list in results:
        for item in result_list:
            if item['url'] not in seen_urls:
                seen_urls.add(item['url'])
                all_results.append(item)
    
    return all_results

@ttl_cache(3600)
def summarize_with_hf(text: str) -> str:
    """
    Summarize text using HuggingFace API
    
    Args:
        text (str): Text to summarize
        
    Returns:
        str: Summarized text
    """
    try:
        max_length = min(len(text.split()), 1024)
        response = hf_clients.summary_client.summarization(
            text,
            parameters={
                "max_length": max_length,
                "min_length": max(50, max_length // 4),
                "do_sample": False
            }
        )
        return response.get('summary_text', "No summary available")
    except Exception as e:
        logger.error(f"Error in summarization: {str(e)}")
        return text[:200] + "..."

def generate_conversational_response(user_input: str) -> str:
    """
    Generate conversational response using BlenderBot
    
    Args:
        user_input (str): User's input text
        
    Returns:
        str: Generated response
    """
    try:
        response = hf_clients.bot_client.chat_completion(
            messages=[{"role": "user", "content": user_input}],
            stream=False
        )
        return response.get('choices', [{}])[0].get('message', {}).get('content', 
            "I'm sorry, I couldn't process that request."
        )
    except Exception as e:
        logger.error(f"Error in conversation generation: {str(e)}")
        return "I'm sorry, I'm having trouble processing that right now."

def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    """
    Extract named entities from text
    
    Args:
        text (str): Input text
        
    Returns:
        Dict[str, List[str]]: Dictionary of extracted entities
    """
    try:
        response = hf_clients.ner_client.token_classification(text)
        entities = [ent['word'] for ent in response if ent['entity_group'] in ['ORG', 'PER', 'LOC']]
        return {"entities": list(set(entities))}
    except Exception as e:
        logger.error(f"Error in entity extraction: {str(e)}")
        return {"entities": []}