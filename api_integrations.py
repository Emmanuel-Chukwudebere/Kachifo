import os
import requests
import logging
from requests.exceptions import RequestException
from requests_oauthlib import OAuth1
from cachetools import cached, TTLCache
from dotenv import load_dotenv
from typing import List, Dict, Any
import re
import json
import time
from functools import wraps

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
            global last_called  # Use global variable
            elapsed = time.time() - last_called
            wait_time = min_interval - elapsed
            
            if wait_time > 0:
                time.sleep(wait_time)
            last_called = time.time()  # Update the last called time
            return func(*args, **kwargs)
        
        return wrapper
    return decorator

# Hugging Face: Summarization
def summarize_with_hf(text):
    """Summarizes text using Hugging Face's BART model."""
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {
        "inputs": text,
        "parameters": {"max_length": 150, "min_length": 50, "do_sample": False}
    }
    response = requests.post(HF_API_URL_SUMMARY, headers=headers, json=payload)
    
    if response.status_code != 200:
        logger.error(f"Summarization HF API error: {response.status_code}")
        return "Sorry, I couldn't summarize the text."

    result = response.json()
    return result[0]['summary_text']

# Hugging Face: Entity Extraction (NER)
def extract_entities_with_hf(text):
    """Extracts entities from text using Hugging Face's NER model."""
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {"inputs": text}
    response = requests.post(HF_API_URL_NER, headers=headers, json=payload)

    if response.status_code != 200:
        logger.error(f"NER HF API error: {response.status_code}")
        return {"entities": []}

    result = response.json()
    return {"entities": [ent['word'] for ent in result if ent['entity_group'] in ['ORG', 'PER', 'LOC']]}

# Fetch YouTube trends (Limited to 3 results)
@rate_limited(1.0)
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

# Fetch Twitter trends (Limited to 3 results)
@rate_limited(1.0)
def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending tweets matching the query."""
    try:
        logger.info(f"Fetching Twitter trends for query: {query}")
        
        search_url = "https://api.twitter.com/2/tweets/search/recent"
        auth = OAuth1(
            client_key=TWITTER_API_KEY,
            client_secret=TWITTER_API_SECRET_KEY,
            resource_owner_key=TWITTER_ACCESS_TOKEN,
            resource_owner_secret=TWITTER_ACCESS_TOKEN_SECRET
        )

        params = {
            'query': query,
            'tweet.fields': 'text,author_id,created_at',
            'expansions': 'author_id',
            'user.fields': 'username',
            'max_results': 3
        }
        
        response = requests.get(search_url, params=params, auth=auth)
        response.raise_for_status()

        data = response.json()

        results = []
        for tweet in data.get('data', []):
            tweet_text = tweet['text']
            author_id = tweet['author_id']
            author = next((user for user in data.get('includes', {}).get('users', []) if user['id'] == author_id), None)
            username = author['username'] if author else "Unknown"
            summary = summarize_with_hf(tweet_text)

            if username and summary and tweet['id']:
                results.append({
                    'source': 'Twitter',
                    'title': f"Tweet by @{username}",
                    'summary': summary,
                    'url': f"https://twitter.com/{username}/status/{tweet['id']}"
                })

        logger.info(f"Fetched {len(results)} Twitter trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []

# Fetch Reddit trends (Limited to 3 results)
@rate_limited(1.0)
def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending Reddit posts matching the query."""
    try:
        logger.info(f"Fetching Reddit trends for query: {query}")
        auth = requests.auth.HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
        headers = {'User-Agent': REDDIT_USER_AGENT}
        
        # Get token
        response = requests.post('https://www.reddit.com/api/v1/access_token', 
                                 auth=auth, 
                                 data={'grant_type': 'client_credentials'},
                                 headers=headers)
        response.raise_for_status()
        token = response.json()['access_token']
        
        # Use token to get trends
        headers['Authorization'] = f'bearer {token}'
        search_url = f"https://oauth.reddit.com/r/all/search?q={query}&sort=relevance&t=week&limit=3"

        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        posts = response.json()['data']['children']

        results = []
        for post in posts:
            title = post['data']['title']
            selftext = post['data']['selftext']
            url = f"https://www.reddit.com{post['data']['permalink']}"
            summary = summarize_with_hf(selftext) if selftext else title

            if title and summary and url:
                results.append({
                    'source': 'Reddit',
                    'title': title,
                    'summary': summary,
                    'url': url
                })

        logger.info(f"Fetched {len(results)} Reddit trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

# Fetch trending topics from all sources, combining results
def fetch_trending_topics(user_input: str) -> Dict[str, Any]:
    sanitized_input = re.sub(r"[^\w\s]", "", user_input).strip()
    logger.info(f"Sanitized input: {sanitized_input}")
    
    # Combine results from different sources
    all_results = []
    all_results.extend(fetch_youtube_trends(sanitized_input))
    all_results.extend(fetch_news_trends(sanitized_input))
    all_results.extend(fetch_google_trends(sanitized_input))
    all_results.extend(fetch_twitter_trends(sanitized_input))
    all_results.extend(fetch_reddit_trends(sanitized_input))

    # Limit total results to a maximum of 15 (3 from each API)
    limited_results = all_results[:15]

    logger.info(f"Total combined results: {len(limited_results)}")

    # Generate a summary if there are results
    general_summary = "Here are the top trends related to your query." if limited_results else "No trends found for your query."

    return {
        'general_summary': general_summary,
        'dynamic_response': "These are the latest trends:",
        'results': limited_results
    }

# Entry point for the script
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    print(trends)
