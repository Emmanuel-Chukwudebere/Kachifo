import os
import requests
import logging
from requests.exceptions import RequestException
from requests_oauthlib import OAuth1
from cachetools import cached, TTLCache
from dotenv import load_dotenv
import spacy
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

# Initialize SpaCy NLP model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    logger.info("Downloading SpaCy model...")
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

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

# Process user input with SpaCy
def process_user_input(user_input: str) -> str:
    """Extract relevant keywords and entities from user input using SpaCy."""
    doc = nlp(user_input)

    # Convert to basic types (strings and lists)
    entities = [ent.text for ent in doc.ents]  # list of strings
    keywords = [token.text for token in doc if token.pos_ in ['NOUN', 'PROPN', 'ADJ']]  # list of strings

    return ' '.join(set(entities + keywords))  # return as string, which is JSON-serializable

# Process text with SpaCy to create a meaningful summary
def process_text_with_spacy(text: str) -> str:
    """
    Processes text with SpaCy to filter tokens, returning a summary made of the first 30 meaningful tokens.
    """
    original_length = len(text)
    doc = nlp(text)
    
    # Filter out single characters or whitespace tokens
    meaningful_tokens = [token.text for token in doc if len(token.text) > 1]
    
    # Log the original length and number of meaningful tokens
    logger.info(f"Original text length: {original_length}, Number of meaningful tokens: {len(meaningful_tokens)}")
    
    # Join the first 30 meaningful tokens to create a summary
    summary = " ".join(meaningful_tokens[:30])
    
    logger.info(f"Generated summary: {summary}")
    return summary

# Generate a dynamic response
def generate_dynamic_response(user_input: str, results: List[Dict[str, Any]]) -> str:
    """Generate a dynamic response using SpaCy analysis of user input and API results."""
    doc = nlp(user_input)
    main_topic = next((token.text for token in doc if token.pos_ in ['NOUN', 'PROPN']), "this topic")
    
    # Generate introduction
    intro = f"Here's what I discovered about {main_topic}:\n\n" if not doc.sentiment else f"Great choice! I found some exciting trends about {main_topic}:\n\n"

    response = f"{intro}"

    for result in results:
        response += f"📌 {result['source']}: {result['title']}\n"
        response += f"   {result['summary']}\n"
        response += f"   More at: {result['url']}\n\n"

    # Generate a conclusion
    if len(results) > 5:
        conclusion = f"Wow, there's a lot of buzz around {main_topic}! Which aspect interests you most?"
    else:
        conclusion = f"These are the top trends for {main_topic}. Would you like to explore any specific area further?"

    response += conclusion
    return response

# Cache API results
@cached(cache)
@rate_limited(1.0)  # Rate limit to 1 request per second
def fetch_trending_topics(user_input: str) -> str:
    try:
        logger.info(f"Processing user input: {user_input}")
        query = process_user_input(user_input)
        logger.info(f"Extracted query: {query}")
        
        # Fetch results from each API
        results = (
            fetch_youtube_trends(query) +
            fetch_news_trends(query) +
            fetch_twitter_trends(query) +
            fetch_reddit_trends(query) +
            fetch_google_trends(query)
        )
        
        # Filter valid results using list comprehension
        valid_results = [result for result in results if isinstance(result, dict) and result.get('title') and result.get('summary')]
        
        # Limit to the first 10 valid results
        valid_results = valid_results[:10]
        
        if not valid_results:
            return f"I couldn't find any relevant trends about {query} at the moment. Could you try rephrasing your query or exploring a different topic?"
        
        # Generate dynamic response
        return generate_dynamic_response(user_input, valid_results)
    except RequestException as e:
        logger.error(f"Error fetching trending topics: {str(e)}", exc_info=True)
        return f"I apologize, but I encountered an unexpected issue while fetching trends about {query}. Could we try again with a different query?"

# Fetch YouTube trends
@rate_limited(1.0)
def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending YouTube videos matching the query."""
    try:
        logger.info(f"Fetching YouTube trends for query: {query}")
        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&key={YOUTUBE_API_KEY}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['snippet']['title']
            description = item['snippet']['description']
            video_url = f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            summary = process_text_with_spacy(description)  # Use the new processing function

            if title and summary and video_url:
                results.append({
                    'source': 'YouTube',
                    'title': title,
                    'summary': summary,
                    'url': video_url,
                })
            else:
                logger.warning(f"Skipped YouTube result due to missing data: {repr(item)}")

        logger.info(f"Fetched {len(results)} YouTube trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

# Fetch News trends
@rate_limited(1.0)
def fetch_news_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending news articles matching the query."""
    try:
        logger.info(f"Fetching news trends for query: {query}")
        search_url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for article in data['articles']:
            title = article['title']
            content = article['content'] or article['description']
            article_url = article['url']
            summary = process_text_with_spacy(content)  # Use the new processing function

            if title and summary and article_url:
                results.append({
                    'source': 'NewsAPI',
                    'title': title,
                    'summary': summary,
                    'url': article_url,
                })
            else:
                logger.warning(f"Skipped NewsAPI result due to missing data: {repr(article)}")

        logger.info(f"Fetched {len(results)} news trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching news trends: {str(e)}")
        return []

# Fetch Google Search trends
@rate_limited(1.0)
def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch Google Custom Search results matching the query."""
    try:
        logger.info(f"Fetching Google search trends for query: {query}")
        search_url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['title']
            snippet = item['snippet']
            link = item['link']
            summary = process_text_with_spacy(snippet)  # Use the new processing function

            if title and summary and link:
                results.append({
                    'source': 'Google',
                    'title': title,
                    'summary': summary,
                    'url': link,
                })
            else:
                logger.warning(f"Skipped Google result due to missing data: {repr(item)}")

        logger.info(f"Fetched {len(results)} Google trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []

# Fetch Twitter trends using OAuth1.0a for authentication
@rate_limited(1.0)
def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending tweets matching the query using OAuth1."""
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
            'user.fields': 'username'
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
            summary = process_text_with_spacy(tweet_text) if len(tweet_text) > 100 else tweet_text

            if username and summary and tweet['id']:
                results.append({
                    'source': 'Twitter',
                    'title': f"Tweet by @{username}",
                    'summary': summary,
                    'url': f"https://twitter.com/{username}/status/{tweet['id']}"
                })
            else:
                logger.warning(f"Skipped Twitter result due to missing data: {repr(tweet)}")

        logger.info(f"Fetched {len(results)} Twitter trends.")
        return results

    except RequestException as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []

# Fetch Reddit trends
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
        search_url = f"https://oauth.reddit.com/r/all/search?q={query}&sort=relevance&t=week"
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        posts = response.json()['data']['children']

        results = []
        for post in posts:
            title = post['data']['title']
            selftext = post['data']['selftext']
            url = f"https://www.reddit.com{post['data']['permalink']}"
            summary = process_text_with_spacy(selftext) if selftext else title

            if title and summary and url:
                results.append({
                    'source': 'Reddit',
                    'title': title,
                    'summary': summary,
                    'url': url
                })
            else:
                logger.warning(f"Skipped Reddit result due to missing data: {repr(post)}")

        logger.info(f"Fetched {len(results)} Reddit trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

# Main function to handle user queries
def get_trends(user_input: str) -> str:
    sanitized_input = re.sub(r"[^\w\s]", "", user_input).strip()
    logger.info(f"Sanitized input: {sanitized_input}")
    return json.dumps(fetch_trending_topics(sanitized_input))

# Entry point for the script
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = get_trends(user_query)
    print(trends)
