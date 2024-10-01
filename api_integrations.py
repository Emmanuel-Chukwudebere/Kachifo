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
    Limits text length to avoid memory overload.
    """
    text = text[:1000]  # Limit the text length to 1000 characters
    original_length = len(text)
    doc = nlp(text)
    
    # Filter out tokens that are too short, punctuation, or whitespace
    meaningful_tokens = [token.text for token in doc if len(token.text.strip()) > 1 and not token.is_punct]

    logger.info(f"Original text length: {original_length}, Number of meaningful tokens: {len(meaningful_tokens)}")
    
    if not meaningful_tokens:
        return ""
    
    # Join the first 30 meaningful tokens to create a summary
    summary = " ".join(meaningful_tokens[:30])
    
    return summary if summary.strip() else "No meaningful summary generated."

# Generate a dynamic response
def generate_dynamic_response(user_input: str, results: List[Dict[str, Any]]) -> str:
    doc = nlp(user_input)
    main_topic = next((token.text for token in doc if token.pos_ in ['NOUN', 'PROPN']), "this topic")
    
    response = f"I've found some interesting information about {main_topic}. "
    response += "Here's a quick overview of what I discovered:\n\n"
    
    for result in results[:5]:  # Limit to top 5 results for brevity
        response += f"- {result['title']}\n"
    
    response += f"\nWould you like me to elaborate on any specific aspect of {main_topic}?"
    return response

def generate_general_summary(summaries: List[str]) -> str:
    if not summaries:
        return "I couldn't find any relevant trends for your query. Can you try rephrasing or asking about a different topic?"

    combined_text = " ".join(summaries)
    combined_doc = nlp(combined_text)

    key_phrases = list(dict.fromkeys([chunk.text for chunk in combined_doc.noun_chunks if len(chunk) > 1]))[:5]
    key_entities = list(dict.fromkeys([ent.text for ent in combined_doc.ents if ent.label_ in ['PERSON', 'ORG', 'GPE', 'EVENT']]))[:5]

    summary = f"Based on the latest trends, {', '.join(key_phrases)} seem to be hot topics. "
    if key_entities:
        summary += f"Key names that come up include {', '.join(key_entities)}. "
    summary += "Let me know if you want to dive deeper into any of these areas!"

    return summary

# Cache API results
@cached(cache)
@rate_limited(1.0)
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

        if not valid_results:
            logger.warning("No valid results were found after filtering.")
            return json.dumps({"error": "No relevant trends found for the query. Please try again with a different topic."})

        # Generate summaries for valid results
        individual_summaries = [result['summary'] for result in valid_results]

        # Generate the general summary from individual summaries
        general_summary = generate_general_summary(individual_summaries)

        # Generate dynamic response with individual results
        dynamic_response = generate_dynamic_response(user_input, valid_results)

        # Combine the general summary with the dynamic response and individual results
        response = {
            "general_summary": general_summary,
            "dynamic_response": dynamic_response,
            "results": valid_results[:5]  # Limit to top 5 results
        }

        return json.dumps(response)
    except Exception as e:
        logger.error(f"Unexpected error during processing: {str(e)}", exc_info=True)
        return json.dumps({"error": "An unexpected error occurred. Please try again later."})

# Fetch YouTube trends (Limited to 5 results)
@rate_limited(1.0)
def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending YouTube videos matching the query."""
    try:
        logger.info(f"Fetching YouTube trends for query: {query}")
        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=5&key={YOUTUBE_API_KEY}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['snippet']['title']
            description = item['snippet']['description']
            video_url = f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            summary = process_text_with_spacy(description)

            if title and summary and video_url:
                results.append({
                    'source': 'YouTube',
                    'title': title,
                    'summary': summary,
                    'url': video_url,
                })

        logger.info(f"Fetched {len(results)} YouTube trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

# Fetch News trends (Limited to 5 results)
@rate_limited(1.0)
def fetch_news_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending news articles matching the query."""
    try:
        logger.info(f"Fetching news trends for query: {query}")
        search_url = f"https://newsapi.org/v2/everything?q={query}&pageSize=5&apiKey={NEWSAPI_KEY}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for article in data['articles']:
            title = article['title']
            content = article['content'] or article['description']
            article_url = article['url']
            summary = process_text_with_spacy(content)

            if title and summary and article_url:
                results.append({
                    'source': 'News Article',
                    'title': title,
                    'summary': summary,
                    'url': article_url,
                })

        logger.info(f"Fetched {len(results)} news trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching news trends: {str(e)}")
        return []

# Fetch Google Search trends (Limited to 5 results)
@rate_limited(1.0)
def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch Google Custom Search results matching the query."""
    try:
        logger.info(f"Fetching Google search trends for query: {query}")
        search_url = f"https://www.googleapis.com/customsearch/v1?q={query}&num=5&key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            title = item['title']
            snippet = item['snippet']
            link = item['link']
            summary = process_text_with_spacy(snippet)

            if title and summary and link:
                results.append({
                    'source': 'Google',
                    'title': title,
                    'summary': summary,
                    'url': link,
                })

        logger.info(f"Fetched {len(results)} Google trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []

# Fetch Twitter trends (Limited to 5 results)
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
            'user.fields': 'username',
            'max_results': 5  # Limiting results to 5
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

        logger.info(f"Fetched {len(results)} Twitter trends.")
        return results

    except RequestException as e:
        logger.error(f"Error fetching Twitter trends: {str(e)}")
        return []

# Fetch Reddit trends (Limited to 5 results)
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
        search_url = f"https://oauth.reddit.com/r/all/search?q={query}&sort=relevance&t=week&limit=5"  # Limiting results to 5
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