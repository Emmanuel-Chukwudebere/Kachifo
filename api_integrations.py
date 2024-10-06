import os
import logging
import asyncio
import aiohttp
from aiohttp import ClientError, ClientTimeout
from aiocache import cached, Cache
from aiocache.serializers import PickleSerializer
from functools import wraps
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
from huggingface_hub import InferenceClient
import asyncpraw
import time
from requests_oauthlib import OAuth1
from requests.exceptions import RequestException, Timeout

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# Initialize aiocache
cache = Cache(Cache.MEMORY, serializer=PickleSerializer())

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
@cached(ttl=3600, key_builder=lambda *args, **kwargs: f"general_summary:{args[0]}")
async def generate_general_summary(individual_summaries: List[str]) -> str:
    """Generates a general summary using Hugging Face Hub API from individual summaries."""
    combined_text = " ".join(individual_summaries)
    try:
        logger.info("Calling Hugging Face Summarization API for general summary")
        response = await inference_summary.summarization(combined_text,
                                                         parameters={"max_length": 200, "min_length": 100, "do_sample": False})
        general_summary = response.get('summary_text', "No summary available")
        return general_summary
    except Exception as e:
        logger.error(f"Error generating general summary: {str(e)}")
        return "Sorry, I couldn't generate a summary at the moment."

# Summarize with Hugging Face
@rate_limited(max_per_second=1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=3600, key_builder=lambda *args, **kwargs: f"summary:{args[0][:100]}")
async def summarize_with_hf(text: str) -> str:
    """Summarizes text using Hugging Face Hub API with caching and logging."""
    try:
        logger.info(f"Calling Hugging Face Summarization API for text: {text[:100]}...")
        max_input_length = 1024  # Adjust this value based on your model's requirements
        truncated_text = text[:max_input_length]
        response = await inference_summary.summarization(truncated_text,
                                                         parameters={"max_length": 150, "min_length": 50, "do_sample": False})
        summary = response.get('summary_text', "No summary available")
        logger.info(f"Summary generated: {summary[:100]}...")
        return summary
    except Exception as e:
        logger.error(f"Error calling Hugging Face Summarization API: {str(e)}")
        return "Sorry, summarization is unavailable at the moment."

# Extract named entities with Hugging Face
@rate_limited(max_per_second=1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=3600, key_builder=lambda *args, **kwargs: f"ner:{args[0][:100]}")
async def extract_entities_with_hf(text: str) -> Dict[str, Any]:
    """Extracts named entities using Hugging Face Hub API with caching and logging."""
    try:
        logger.info(f"Calling Hugging Face NER API for text: {text[:100]}...")
        max_input_length = 512  # Adjust this value based on your model's requirements
        truncated_text = text[:max_input_length]
        response = await inference_ner.token_classification(truncated_text)
        entities = [ent['word'] for ent in response if ent['entity_group'] in ['ORG', 'PER', 'LOC']]
        logger.info(f"Entities extracted: {entities}")
        return {"entities": entities}
    except Exception as e:
        logger.error(f"Error calling Hugging Face NER API: {str(e)}")
        return {"entities": []}

# Generate a conversational response using BlenderBot
@rate_limited(max_per_second=1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
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
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=600, key_builder=lambda *args, **kwargs: f"youtube:{args[0]}")
async def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=ClientTimeout(total=10)) as response:
                response.raise_for_status()
                result = await response.json()
                return [
                    {
                        "source": "YouTube",
                        "title": item['snippet']['title'],
                        "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                        "summary": await summarize_with_hf(item['snippet']['description'])
                    }
                    for item in result.get('items', [])
                ]
    except Exception as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

# Fetch Twitter trends
@rate_limited(1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=600, key_builder=lambda *args, **kwargs: f"twitter:{args[0]}")
async def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&max_results=3"
    auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET_KEY, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth, timeout=ClientTimeout(total=10)) as response:
                response.raise_for_status()
                result = await response.json()
                return [
                    {
                        "source": "Twitter",
                        "title": tweet.get('text'),
                        "url": f"https://twitter.com/statuses/{tweet.get('id')}",
                        "summary": await summarize_with_hf(tweet.get('text'))
                    }
                    for tweet in result.get('data', [])
                ]
    except Exception as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []

# Fetch Google search results
@rate_limited(1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=600, key_builder=lambda *args, **kwargs: f"google:{args[0]}")
async def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=ClientTimeout(total=10)) as response:
                response.raise_for_status()
                result = await response.json()
                return [
                    {
                        "source": "Google",
                        "title": item.get("title"),
                        "url": item.get("link"),
                        "summary": await summarize_with_hf(item.get("snippet", ""))
                    }
                    for item in result.get('items', [])
                ]
    except Exception as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []

# Fetch Reddit trends
@rate_limited(1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=600, key_builder=lambda *args, **kwargs: f"reddit:{args[0]}")
async def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    try:
        async with asyncpraw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_SECRET,
            user_agent=REDDIT_USER_AGENT
        ) as reddit:
            results = []
            subreddit = await reddit.subreddit("all")
            async for submission in subreddit.search(query, sort="top", limit=3):
                post_title = submission.title
                post_url = submission.url
                post_content = submission.selftext[:500]
                summary = await summarize_with_hf(post_content)
                results.append({
                    "source": "Reddit",
                    "title": post_title,
                    "url": post_url,
                    "summary": summary
                })
            return results
    except Exception as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

# Fetch News articles
@rate_limited(1.0)
@retry_with_backoff((ClientError, asyncio.TimeoutError), tries=3)
@cached(ttl=600, key_builder=lambda *args, **kwargs: f"news:{args[0]}")
async def fetch_news_articles(query: str) -> List[Dict[str, Any]]:
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=ClientTimeout(total=10)) as response:
                response.raise_for_status()
                result = await response.json()
                return [
                    {
                        "source": "News API",
                        "title": article.get("title"),
                        "url": article.get("url"),
                        "summary": await summarize_with_hf(article.get("description", ""))
                    }
                    for article in result.get('articles', [])[:3]  # Limit to top 3 articles
                ]
    except Exception as e:
        logger.error(f"Error fetching news articles: {str(e)}")
        return []

# Fetch all trends from APIs (YouTube, Reddit, Twitter, Google, News)
async def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """Fetch trends from YouTube, Reddit, Google, Twitter, and News."""
    tasks = [
        fetch_youtube_trends(query),
        fetch_reddit_trends(query),
        fetch_twitter_trends(query),
        fetch_google_trends(query),
        fetch_news_articles(query)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_results = []
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"An API request failed: {str(result)}")
        elif isinstance(result, list):
            all_results.extend(result)
    
    return all_results

# Utility function to clean and validate query
def clean_query(query: str) -> str:
    """Clean and validate the query string."""
    # Remove any non-alphanumeric characters except spaces
    cleaned_query = re.sub(r'[^\w\s]', '', query)
    # Trim leading/trailing whitespace and convert to lowercase
    cleaned_query = cleaned_query.strip().lower()
    # Ensure the query is not empty and not too long
    if not cleaned_query:
        raise ValueError("Query cannot be empty")
    if len(cleaned_query) > 100:
        cleaned_query = cleaned_query[:100]
    return cleaned_query

# Error handling decorator
def handle_errors(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except aiohttp.ClientError as e:
            logger.error(f"Network error in {func.__name__}: {str(e)}")
            return []
        except asyncio.TimeoutError:
            logger.error(f"Timeout error in {func.__name__}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            return []
    return wrapper

# Apply error handling to all API fetch functions
fetch_youtube_trends = handle_errors(fetch_youtube_trends)
fetch_reddit_trends = handle_errors(fetch_reddit_trends)
fetch_twitter_trends = handle_errors(fetch_twitter_trends)
fetch_google_trends = handle_errors(fetch_google_trends)
fetch_news_articles = handle_errors(fetch_news_articles)

# Main function to get trending topics
async def get_trending_topics(query: str) -> Dict[str, Any]:
    """Main function to get trending topics from all sources."""
    try:
        cleaned_query = clean_query(query)
    except ValueError as e:
        logger.error(f"Invalid query: {str(e)}")
        return {"error": str(e)}

    trends = await fetch_trending_topics(cleaned_query)
    
    if not trends:
        return {"error": "No trends found or all API requests failed"}

    # Generate a general summary of all trends
    all_summaries = [trend['summary'] for trend in trends if trend.get('summary')]
    general_summary = await generate_general_summary(all_summaries)

    return {
        "query": cleaned_query,
        "trends": trends,
        "general_summary": general_summary
    }

# Asynchronous context manager for aiohttp ClientSession
@asynccontextmanager
async def get_session():
    session = aiohttp.ClientSession()
    try:
        yield session
    finally:
        await session.close()

# Initialize cache
async def init_cache():
    global cache
    cache = Cache(Cache.MEMORY, serializer=PickleSerializer())
    await cache.init()

# Shutdown function to clean up resources
async def shutdown():
    await cache.close()
    # Add any other cleanup tasks here

# Health check function
async def health_check() -> Dict[str, str]:
    """Perform a health check on all API integrations."""
    health_status = {}
    apis = [
        ("YouTube", fetch_youtube_trends),
        ("Reddit", fetch_reddit_trends),
        ("Twitter", fetch_twitter_trends),
        ("Google", fetch_google_trends),
        ("NewsAPI", fetch_news_articles)
    ]

    for api_name, api_func in apis:
        try:
            result = await api_func("test")
            health_status[api_name] = "OK" if result else "No data returned"
        except Exception as e:
            health_status[api_name] = f"Error: {str(e)}"

    return health_status

if __name__ == "__main__":
    async def main():
        await init_cache()
        query = input("Enter a query to search for trending topics: ")
        result = await get_trending_topics(query)
        print(json.dumps(result, indent=2))
        await shutdown()

    asyncio.run(main())