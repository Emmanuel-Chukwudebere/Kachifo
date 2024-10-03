import os
import requests
import logging
from requests.exceptions import RequestException, Timeout
from cachetools import TTLCache
from functools import wraps
from dotenv import load_dotenv
from typing import List, Dict, Any
from huggingface_hub import InferenceApi

# Load environment variables
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API keys and URLs
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"  # Summarization model
HF_API_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"  # NER model

# Initialize the Hugging Face Hub Inference API
inference_summary = InferenceApi(repo_id=HF_API_SUMMARY_MODEL, token=HF_API_KEY)
inference_ner = InferenceApi(repo_id=HF_API_NER_MODEL, token=HF_API_KEY)

# Cache setup: 1-hour time-to-live, max 1000 items
summary_cache = TTLCache(maxsize=1000, ttl=3600)
entity_cache = TTLCache(maxsize=1000, ttl=3600)

# Retry logic with exponential backoff
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

# Hugging Face Summarization API with caching
@retry_with_backoff((RequestException, Timeout), tries=3)
def summarize_with_hf(text: str) -> str:
    """Summarizes text using Hugging Face Hub API."""
    # Check if summarization result is already cached
    if text in summary_cache:
        return summary_cache[text]
    
    try:
        logger.info("Calling Hugging Face Summarization API")
        response = inference_summary(inputs=text, parameters={"max_length": 150, "min_length": 50, "do_sample": False})
        summary = response.get('summary_text', "No summary available")
        
        # Cache the result
        summary_cache[text] = summary
        return summary
    except (RequestException, Timeout) as e:
        logger.error(f"Error calling Hugging Face Summarization API: {str(e)}")
        return "Sorry, summarization is unavailable at the moment."

# Hugging Face NER API with caching
@retry_with_backoff((RequestException, Timeout), tries=3)
def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    """Extracts named entities using Hugging Face Hub API."""
    # Check if NER result is already cached
    if text in entity_cache:
        return entity_cache[text]

    try:
        logger.info("Calling Hugging Face NER API")
        response = inference_ner(inputs=text)
        entities = [ent['word'] for ent in response if ent['entity_group'] in ['ORG', 'PER', 'LOC']]
        
        # Cache the result
        entity_cache[text] = {"entities": entities}
        return {"entities": entities}
    except (RequestException, Timeout) as e:
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