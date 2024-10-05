import os
import logging
import asyncio
import aiohttp
from requests.exceptions import RequestException, Timeout
from cachetools import TTLCache
from functools import wraps
from dotenv import load_dotenv
from typing import List, Dict, Any
from huggingface_hub import InferenceClient
import praw
import json
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

# Hugging Face API keys and models
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"
HF_API_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"
HF_API_BOT_MODEL = "facebook/blenderbot-400M-distill"

# Initialize the InferenceClient for summarization, NER, and BlenderBot
inference_summary = InferenceClient(model=HF_API_SUMMARY_MODEL, token=HF_API_KEY)
inference_ner = InferenceClient(model=HF_API_NER_MODEL, token=HF_API_KEY)
inference_bot = InferenceClient(model=HF_API_BOT_MODEL, token=HF_API_KEY)

# Cache setup for summaries and entities
summary_cache = TTLCache(maxsize=1000, ttl=3600)
entity_cache = TTLCache(maxsize=1000, ttl=3600)

# Rate limit configuration
def rate_limited(max_per_second: float):
    """Limits the number of API calls per second."""
    min_interval = 1.0 / max_per_second
    last_called = [0.0]

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            wait_time = min_interval - elapsed
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            last_called[0] = time.time()
            return await func(*args, **kwargs)
        return wrapper

    return decorator

# Retry logic with exponential backoff
def retry_with_backoff(exceptions, tries=3, delay=2, backoff=2):
    """Retry decorator for functions in case of failure."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    logger.warning(f"{func.__name__} failed due to {str(e)}, retrying in {_delay} seconds...")
                    await asyncio.sleep(_delay)
                    _tries -= 1
                    _delay *= backoff
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# General summary from individual summaries
async def generate_general_summary(individual_summaries: List[str]) -> str:
    """Generates a general summary using Hugging Face Hub API from individual summaries."""
    combined_text = " ".join(individual_summaries)  # Combine all individual summaries into one text
    try:
        logger.info("Calling Hugging Face Summarization API for general summary")
        response = await inference_summary.summarization(combined_text, parameters={"max_length": 200, "min_length": 100, "do_sample": False})
        general_summary = response.get('summary_text', "No summary available")
        return general_summary
    except Exception as e:
        logger.error(f"Error generating general summary: {str(e)}")
        return "Sorry, I couldn't generate a summary at the moment."

# Summarize with Hugging Face
@rate_limited(max_per_second=1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def summarize_with_hf(text: str) -> str:
    """Summarizes text using Hugging Face Hub API with caching and logging."""
    if text in summary_cache:
        logger.info(f"Cache hit for summarization: {text[:100]}...")
        return summary_cache[text]
    try:
        logger.info(f"Calling Hugging Face Summarization API for text: {text[:100]}...")
        max_input_length = 1024  # Adjust this value based on your model's requirements
        truncated_text = text[:max_input_length]
        response = await inference_summary.summarization(truncated_text, parameters={"max_length": 150, "min_length": 50, "do_sample": False})
        summary = response.get('summary_text', "No summary available")
        logger.info(f"Summary generated: {summary[:100]}...")
        summary_cache[text] = summary
        return summary
    except Exception as e:
        logger.error(f"Error calling Hugging Face Summarization API: {str(e)}")
        return "Sorry, summarization is unavailable at the moment."

# Extract named entities with Hugging Face
@rate_limited(max_per_second=1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    """Extracts named entities using Hugging Face Hub API with caching and logging."""
    if text in entity_cache:
        logger.info(f"Cache hit for NER: {text[:100]}...")
        return entity_cache[text]
    try:
        logger.info(f"Calling Hugging Face NER API for text: {text[:100]}...")
        max_input_length = 512  # Adjust this value based on your model's requirements
        truncated_text = text[:max_input_length]
        response = await inference_ner.token_classification(truncated_text)
        entities = [ent['word'] for ent in response if ent['entity_group'] in ['ORG', 'PER', 'LOC']]
        logger.info(f"Entities extracted: {entities}")
        entity_cache[text] = {"entities": entities}
        return {"entities": entities}
    except Exception as e:
        logger.error(f"Error calling Hugging Face NER API: {str(e)}")
        return {"entities": []}

# Generate a conversational response using BlenderBot with chat_completion()
@rate_limited(max_per_second=1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def generate_conversational_response(user_input: str) -> str:
    """Generate a conversational response using Hugging Face API."""
    try:
        logger.info(f"Generating conversational response for input: {user_input[:100]}...")
        response = await inference_bot.chat_completion(messages=[{"role": "user", "content": user_input}], stream=False)
        generated_response = response.get('choices', [{}])[0].get('message', {}).get('content', "No response available")
        logger.info(f"Conversational response generated: {generated_response[:100]}...")
        return generated_response
    except Exception as e:
        logger.error(f"Error generating conversational response: {str(e)}")
        return "I'm sorry, I couldn't respond to that."

# Fetch YouTube trends
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                return [{"title": item['snippet']['title'], "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}", "summary": await summarize_with_hf(item['snippet']['description'])} for item in result.get('items', [])]
    except Exception as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

# Fetch Twitter trends
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&max_results=3"
    auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET_KEY, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth) as response:
                result = await response.json()
                return [{"title": tweet.get('text'), "url": f"https://twitter.com/statuses/{tweet.get('id')}", "summary": await summarize_with_hf(tweet.get('text'))} for tweet in result.get('data', [])]
    except Exception as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []

# Fetch Google search results
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                return [{"title": item.get("title"), "url": item.get("link"), "summary": await summarize_with_hf(item.get("snippet", ""))} for item in result.get('items', [])]
    except Exception as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []

# Fetch Reddit trends
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    reddit = praw.Reddit(client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_SECRET, user_agent=REDDIT_USER_AGENT)
    try:
        results = []
        for submission in reddit.subreddit("all").search(query, sort="top", limit=3):
            post_title = submission.title
            post_url = submission.url
            post_content = submission.selftext[:500]
            summary = await summarize_with_hf(post_content)
            results.append({"title": post_title, "url": post_url, "summary": summary})
        return results
    except Exception as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

# Fetch News articles
@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout), tries=3)
async def fetch_news_articles(query: str) -> List[Dict[str, Any]]:
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                return [{"title": article.get("title"), "url": article.get("url"), "summary": await summarize_with_hf(article.get("description", ""))} for article in result.get('articles', [])]
    except Exception as e:
        logger.error(f"Error fetching news articles: {str(e)}")
        return []
        
# Fetch all trends from APIs (YouTube, Reddit, Twitter, Google, News)
async def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """Fetch trends from YouTube, Reddit, Google, Twitter, and News."""
    youtube_trends = fetch_youtube_trends(query)
    reddit_trends = fetch_reddit_trends(query)
    twitter_trends = fetch_twitter_trends(query)
    google_trends = fetch_google_trends(query)
    news_trends = fetch_news_articles(query)

    # Wait for all fetching to complete
    results = await asyncio.gather(youtube_trends, reddit_trends, twitter_trends, google_trends, news_trends)
    all_results = [trend for sublist in results for trend in sublist]  # Flatten the result
    return all_results

# Entry point for the script
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    print(trends)