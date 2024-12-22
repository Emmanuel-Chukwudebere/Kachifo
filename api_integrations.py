import os
import logging
import asyncio
import aiohttp
from requests.exceptions import RequestException, Timeout
from cachetools import TTLCache
from functools import wraps
from typing import List, Dict, Any, Optional
from huggingface_hub import InferenceClient
import time
import re
from requests_oauthlib import OAuth1

# Initialize logging
logger = logging.getLogger(__name__)

# API Configuration
class APIConfig:
    """
    Centralized configuration management for API keys and endpoints.
    Loads configuration from environment variables with validation.
    """
    def __init__(self):
        self.keys = {
            'youtube': os.getenv("YOUTUBE_API_KEY"),
            'google': os.getenv("GOOGLE_API_KEY"),
            'google_cse': os.getenv("GOOGLE_CSE_ID"),
            'news': os.getenv("NEWSAPI_KEY"),
            'twitter': {
                'api_key': os.getenv("TWITTER_API_KEY"),
                'api_secret': os.getenv("TWITTER_API_SECRET_KEY"),
                'access_token': os.getenv("TWITTER_ACCESS_TOKEN"),
                'access_secret': os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
            },
            'huggingface': os.getenv('HUGGINGFACE_API_KEY')
        }
        
        self.models = {
            'summary': "facebook/bart-large-cnn",
            'ner': "dbmdz/bert-large-cased-finetuned-conll03-english",
            'conversation': "facebook/blenderbot-400M-distill"
        }
        
        self.validate_config()
    
    def validate_config(self):
        """Validates that all required API keys are present"""
        missing_keys = []
        for key, value in self.keys.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    if not subvalue:
                        missing_keys.append(f"{key}.{subkey}")
            elif not value:
                missing_keys.append(key)
        
        if missing_keys:
            logger.warning(f"Missing API keys: {', '.join(missing_keys)}")

# Initialize configuration
config = APIConfig()

# Initialize Hugging Face clients
inference_clients = {
    'summary': InferenceClient(model=config.models['summary'], token=config.keys['huggingface']),
    'ner': InferenceClient(model=config.models['ner'], token=config.keys['huggingface']),
    'conversation': InferenceClient(model=config.models['conversation'], token=config.keys['huggingface'])
}

# Cache configuration
cache = {
    'summary': TTLCache(maxsize=1000, ttl=3600),  # 1 hour cache
    'entity': TTLCache(maxsize=1000, ttl=3600),
    'api': TTLCache(maxsize=500, ttl=300)  # 5 minute cache for API responses
}

# Rate limiting decorator
def rate_limited(max_per_second: float):
    """
    Decorator to limit the rate of API calls.
    
    Args:
        max_per_second (float): Maximum number of calls allowed per second
    """
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

# Retry decorator with exponential backoff
def retry_with_backoff(exceptions, tries=3, delay=2, backoff=2):
    """
    Retry decorator with exponential backoff for failed API calls.
    
    Args:
        exceptions: Exception or tuple of exceptions to catch
        tries (int): Number of attempts to make
        delay (int): Initial delay between retries in seconds
        backoff (int): Multiplicative factor for subsequent delays
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    logger.warning(
                        f"{func.__name__} failed due to {str(e)}, "
                        f"retrying in {_delay} seconds..."
                    )
                    await asyncio.sleep(_delay)
                    _tries -= 1
                    _delay *= backoff
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# API Integration Functions
@rate_limited(1.0)
@retry_with_backoff((aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    """
    Fetches trending videos from YouTube API.
    
    Args:
        query (str): Search query
        
    Returns:
        List[Dict]: List of video information
    """
    cache_key = f"youtube_{query}"
    if cache_key in cache['api']:
        return cache['api'][cache_key]
        
    url = (
        "https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&q={query}&type=video&maxResults=3"
        f"&key={config.keys['youtube']}"
    )
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"YouTube API error: {await response.text()}")
                return []
                
            result = await response.json()
            videos = [{
                "title": item['snippet']['title'],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "summary": item['snippet']['description']
            } for item in result.get('items', [])]
            
            cache['api'][cache_key] = videos
            return videos

# Continue from previous code...

@rate_limited(1.0)
@retry_with_backoff((aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    """
    Fetches trending tweets from Twitter API v2.
    
    Args:
        query (str): Search query
        
    Returns:
        List[Dict]: List of tweet information with summaries
    """
    cache_key = f"twitter_{query}"
    if cache_key in cache['api']:
        return cache['api'][cache_key]
        
    url = f"https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": 3,
        "tweet.fields": "created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "username"
    }
    
    auth = OAuth1(
        config.keys['twitter']['api_key'],
        config.keys['twitter']['api_secret'],
        config.keys['twitter']['access_token'],
        config.keys['twitter']['access_secret']
    )
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, auth=auth) as response:
            if response.status != 200:
                logger.error(f"Twitter API error: {await response.text()}")
                return []
                
            result = await response.json()
            tweets = []
            
            # Process tweets with user information
            users = {user['id']: user for user in result.get('includes', {}).get('users', [])}
            
            for tweet in result.get('data', []):
                author = users.get(tweet['author_id'], {}).get('username', 'unknown')
                tweets.append({
                    "title": f"Tweet by @{author}",
                    "url": f"https://twitter.com/{author}/status/{tweet['id']}",
                    "summary": tweet['text'],
                    "metrics": tweet.get('public_metrics', {}),
                    "source": "twitter"
                })
            
            cache['api'][cache_key] = tweets
            return tweets

@rate_limited(1.0)
@retry_with_backoff((aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    """
    Fetches trending topics from Google Custom Search API.
    
    Args:
        query (str): Search query
        
    Returns:
        List[Dict]: List of search results with summaries
    """
    cache_key = f"google_{query}"
    if cache_key in cache['api']:
        return cache['api'][cache_key]
        
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "cx": config.keys['google_cse'],
        "key": config.keys['google'],
        "num": 3,
        "dateRestrict": "d1"  # Last 24 hours
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logger.error(f"Google API error: {await response.text()}")
                return []
                
            result = await response.json()
            search_results = [{
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "summary": item.get("snippet", ""),
                "source": "google",
                "metadata": {
                    "date_published": item.get("pagemap", {}).get("metatags", [{}])[0].get("article:published_time"),
                    "site_name": item.get("displayLink", "")
                }
            } for item in result.get('items', [])]
            
            cache['api'][cache_key] = search_results
            return search_results

@rate_limited(1.0)
@retry_with_backoff((aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_news_articles(query: str) -> List[Dict[str, Any]]:
    """
    Fetches news articles from NewsAPI.
    
    Args:
        query (str): Search query
        
    Returns:
        List[Dict]: List of news articles with summaries
    """
    cache_key = f"news_{query}"
    if cache_key in cache['api']:
        return cache['api'][cache_key]
        
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "apiKey": config.keys['news'],
        "pageSize": 3,
        "sortBy": "relevancy",
        "language": "en"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logger.error(f"NewsAPI error: {await response.text()}")
                return []
                
            result = await response.json()
            articles = [{
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "summary": article.get("description", ""),
                "source": "news",
                "metadata": {
                    "author": article.get("author"),
                    "source_name": article.get("source", {}).get("name"),
                    "published_at": article.get("publishedAt"),
                    "image_url": article.get("urlToImage")
                }
            } for article in result.get('articles', [])]
            
            cache['api'][cache_key] = articles
            return articles

class ResultProcessor:
    """
    Handles post-processing of API results including summarization,
    deduplication, and ranking.
    """
    def __init__(self, inference_client):
        self.inference_client = inference_client
        self.seen_urls = set()
    
    async def process_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process and enhance the combined results from all sources.
        
        Args:
            results (List[Dict]): Raw results from API calls
            
        Returns:
            List[Dict]: Processed and enhanced results
        """
        processed_results = []
        
        for result in results:
            # Skip if we've seen this URL before
            if result['url'] in self.seen_urls:
                continue
                
            self.seen_urls.add(result['url'])
            
            # Generate or fetch cached summary
            summary = await self._get_summary(result['summary'])
            
            # Enhance result with processed data
            enhanced_result = {
                **result,
                "summary": summary,
                "rank_score": await self._calculate_rank_score(result)
            }
            
            processed_results.append(enhanced_result)
        
        # Sort by rank score
        processed_results.sort(key=lambda x: x['rank_score'], reverse=True)
        
        return processed_results
    
    async def _get_summary(self, text: str) -> str:
        """Get or generate a summary for the given text."""
        cache_key = f"summary_{hash(text)}"
        
        if cache_key in cache['summary']:
            return cache['summary'][cache_key]
            
        try:
            summary = await self.inference_client.summarization(
                text,
                parameters={"max_length": 150, "min_length": 50, "do_sample": False}
            )
            
            cache['summary'][cache_key] = summary
            return summary
            
        except Exception as e:
            logger.error(f"Summarization error: {str(e)}")
            return text[:200] + "..."
    
    async def _calculate_rank_score(self, result: Dict[str, Any]) -> float:
        """Calculate a ranking score based on various factors."""
        score = 1.0
        
        # Factor in source credibility
        source_weights = {
            "news": 1.2,
            "twitter": 0.8,
            "google": 1.0,
            "youtube": 0.9
        }
        score *= source_weights.get(result.get('source', ''), 1.0)
        
        # Factor in social metrics if available
        metrics = result.get('metrics', {})
        if metrics:
            engagement = (
                metrics.get('like_count', 0) +
                metrics.get('retweet_count', 0) * 2 +
                metrics.get('reply_count', 0) * 1.5
            )
            score *= (1 + min(engagement / 1000, 1))
        
        return score

# Continuing from previous code...

@rate_limited(1.0)
@retry_with_backoff((aiohttp.ClientError, asyncio.TimeoutError))
async def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    """
    Fetches trending posts from Reddit's API using PRAW.
    
    Args:
        query (str): Search query to find relevant Reddit posts
        
    Returns:
        List[Dict]: List of Reddit posts with titles, URLs, and summaries
        
    Note:
        This implementation uses Reddit's API through PRAW for better rate limiting
        and authentication handling. Posts are sorted by relevance and filtered
        for quality engagement metrics.
    """
    cache_key = f"reddit_{query}"
    if cache_key in cache['api']:
        return cache['api'][cache_key]
    
    try:
        # Initialize Reddit client (moved to a separate function in production)
        reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_SECRET"),
            user_agent=os.getenv("REDDIT_USER_AGENT")
        )
        
        results = []
        # Search across all subreddits with quality filters
        for submission in reddit.subreddit("all").search(
            query,
            sort="relevance",
            time_filter="day",
            limit=5
        ):
            # Apply quality filters
            if submission.score < 10 or submission.upvote_ratio < 0.7:
                continue
                
            # Extract meaningful content
            content = submission.selftext if submission.selftext else submission.title
            
            results.append({
                "title": submission.title,
                "url": f"https://reddit.com{submission.permalink}",
                "summary": content[:500],  # Truncate long posts
                "source": "reddit",
                "metadata": {
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "num_comments": submission.num_comments,
                    "subreddit": str(submission.subreddit),
                    "created_utc": submission.created_utc
                }
            })
            
        cache['api'][cache_key] = results
        return results
        
    except Exception as e:
        logger.error(f"Reddit API error: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout))
async def summarize_with_hf(text: str) -> str:
    """
    Generates a concise summary of the input text using Hugging Face's summarization model.
    
    Args:
        text (str): Input text to summarize
        
    Returns:
        str: Generated summary of the input text
        
    Note:
        This function uses BART-large-CNN model which is particularly effective
        for news article summarization. The function includes caching to avoid
        redundant API calls for the same content.
    """
    if not text or len(text.strip()) < 50:
        return text
        
    cache_key = f"summary_{hash(text)}"
    if cache_key in cache['summary']:
        return cache['summary'][cache_key]
        
    try:
        # Truncate long texts to model's maximum input length
        max_length = 1024
        truncated_text = text[:max_length]
        
        response = await inference_clients['summary'].summarization(
            truncated_text,
            parameters={
                "max_length": 150,
                "min_length": 50,
                "do_sample": False,
                "temperature": 0.7,  # Balance between creativity and consistency
                "no_repeat_ngram_size": 3  # Avoid repetitive phrases
            }
        )
        
        summary = response.get('summary_text', '').strip()
        
        # Cache the result
        cache['summary'][cache_key] = summary
        return summary
        
    except Exception as e:
        logger.error(f"Summarization error: {str(e)}")
        return text[:200] + "..."  # Fallback to truncation

@rate_limited(1.0)
@retry_with_backoff((RequestException, Timeout))
async def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    """
    Extracts named entities from text using Hugging Face's NER model.
    
    Args:
        text (str): Input text to extract entities from
        
    Returns:
        Dict[str, List[str]]: Dictionary containing categorized named entities
        
    Note:
        This function uses BERT model fine-tuned on CoNLL-2003 dataset for named
        entity recognition. It categorizes entities into types like person,
        organization, location, etc. Results are cached to improve performance.
    """
    cache_key = f"entity_{hash(text)}"
    if cache_key in cache['entity']:
        return cache['entity'][cache_key]
        
    try:
        # Truncate text to model's maximum input length
        max_length = 512
        truncated_text = text[:max_length]
        
        response = await inference_clients['ner'].token_classification(truncated_text)
        
        # Process and categorize entities
        entities: Dict[str, List[str]] = {
            'PERSON': [],
            'ORG': [],
            'LOC': [],
            'MISC': []
        }
        
        current_entity = {'text': [], 'type': None}
        
        for token in response:
            # Handle B- (beginning) and I- (inside) prefixes
            entity_type = token['entity_group']
            if entity_type.startswith('B-'):
                if current_entity['text']:
                    entity_text = ' '.join(current_entity['text'])
                    entities[current_entity['type']].append(entity_text)
                current_entity = {
                    'text': [token['word']],
                    'type': entity_type[2:]
                }
            elif entity_type.startswith('I-') and current_entity['type'] == entity_type[2:]:
                current_entity['text'].append(token['word'])
            else:
                if current_entity['text']:
                    entity_text = ' '.join(current_entity['text'])
                    entities[current_entity['type']].append(entity_text)
                current_entity = {'text': [], 'type': None}
        
        # Add final entity if exists
        if current_entity['text']:
            entity_text = ' '.join(current_entity['text'])
            entities[current_entity['type']].append(entity_text)
        
        # Remove duplicates and normalize
        for entity_type in entities:
            entities[entity_type] = list(set(entities[entity_type]))
        
        # Cache results
        cache['entity'][cache_key] = entities
        return entities
        
    except Exception as e:
        logger.error(f"Entity extraction error: {str(e)}")
        return {'PERSON': [], 'ORG': [], 'LOC': [], 'MISC': []}

async def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """
    Orchestrates the fetching and processing of trending topics from multiple sources.
    
    Args:
        query (str): Search query to find trending topics
        
    Returns:
        List[Dict]: Combined and processed results from all sources
        
    Note:
        This function coordinates the parallel fetching of data from multiple APIs,
        processes the results, and combines them into a unified format. It includes
        deduplication, ranking, and enhanced metadata.
    """
    cache_key = f"trends_{query}"
    if cache_key in cache['api']:
        return cache['api'][cache_key]

    # Gather results from all sources concurrently
    tasks = [
        fetch_youtube_trends(query),
        fetch_twitter_trends(query),
        fetch_google_trends(query),
        fetch_news_articles(query),
        fetch_reddit_trends(query)
    ]
    
    try:
        # Execute all API calls concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        processor = ResultProcessor(inference_clients['summary'])
        
        # Combine valid results and handle errors
        combined_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                source = tasks[i].__name__.replace('fetch_', '')
                logger.error(f"{source} API fetch failed: {str(result)}")
                continue
            combined_results.extend(result)
        
        # Extract entities for the entire dataset
        all_text = " ".join(item.get('title', '') + " " + item.get('summary', '')
                           for item in combined_results)
        entities = await extract_entities_with_hf(all_text)
        
        # Process and enhance results
        processed_results = await processor.process_results(combined_results)
        
        # Add extracted entities to the result set
        final_results = {
            'results': processed_results,
            'entities': entities,
            'metadata': {
                'total_sources': len([r for r in results if not isinstance(r, Exception)]),
                'query_time': time.time(),
                'sources_distribution': {
                    item.get('source'): len([r for r in processed_results 
                                           if r.get('source') == item.get('source')])
                    for item in processed_results
                }
            }
        }
        
        # Cache the final results
        cache['api'][cache_key] = final_results
        return final_results
        
    except Exception as e:
        logger.error(f"Error in fetch_trending_topics: {str(e)}")
        return {'results': [], 'entities': {}, 'metadata': {}}

if __name__ == "__main__":
    async def main():
        query = input("What trends would you like to explore? ")
        results = await fetch_trending_topics(query)
        print(json.dumps(results, indent=2))
    
    asyncio.run(main())