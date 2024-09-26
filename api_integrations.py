import os
import requests
import logging
from requests.exceptions import RequestException
from cachetools import cached, TTLCache
import re
from dotenv import load_dotenv
import spacy
from typing import List, Dict, Any
import random

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
def get_env_var(key: str) -> str:
    value = os.getenv(key)
    if not value:
        logger.error(f"Environment variable {key} is missing.")
        raise ValueError(f"{key} is required but not set.")
    return value

YOUTUBE_API_KEY = get_env_var('YOUTUBE_API_KEY')
GOOGLE_API_KEY = get_env_var('GOOGLE_API_KEY')
NEWSAPI_KEY = get_env_var('NEWSAPI_KEY')
TWITTER_BEARER_TOKEN = get_env_var('TWITTER_BEARER_TOKEN')
REDDIT_CLIENT_ID = get_env_var('REDDIT_CLIENT_ID')
REDDIT_SECRET = get_env_var('REDDIT_SECRET')
REDDIT_USER_AGENT = get_env_var('REDDIT_USER_AGENT')

def process_user_input(user_input: str) -> str:
    """Process user input using spaCy NLP."""
    doc = nlp(user_input)
    entities = [ent.text for ent in doc.ents]
    keywords = [token.text for token in doc if token.pos_ in ['NOUN', 'PROPN', 'ADJ']]
    return ' '.join(set(entities + keywords))

def generate_dynamic_response(user_input: str, results: List[Dict[str, Any]]) -> str:
    """Generate a dynamic response using spaCy analysis of user input and results."""
    doc = nlp(user_input)
    
    # Extract key information from user input
    main_topic = next((token.text for token in doc if token.pos_ in ['NOUN', 'PROPN']), "this topic")
    sentiment = doc.sentiment
    
    # Generate introduction based on sentiment and main topic
    if sentiment > 0.5:
        intro = f"Great choice! I found some exciting trends about {main_topic}:"
    elif sentiment < -0.5:
        intro = f"I understand your concern about {main_topic}. Here's what's trending:"
    else:
        intro = f"Here's what I discovered about {main_topic}:"
    
    response = f"{intro}\n\n"
    
    for result in results:
        response += f"📌 {result['source']}: {result['title']}\n"
        response += f"   {result['summary']}\n"
        response += f"   More at: {result['url']}\n\n"
    
    # Generate conclusion based on results
    if len(results) > 5:
        conclusion = f"Wow, there's a lot of buzz around {main_topic}! Which aspect interests you most?"
    else:
        conclusion = f"These are the top trends for {main_topic}. Would you like to explore any specific area further?"
    
    response += conclusion
    
    return response

@cached(cache)
def fetch_trending_topics(user_input: str) -> str:
    try:
        logger.info(f"Processing user input: {user_input}")
        query = process_user_input(user_input)
        logger.info(f"Extracted query: {query}")
        
        results = []
        results.extend(fetch_youtube_trends(query))
        results.extend(fetch_news_trends(query))
        results.extend(fetch_twitter_trends(query))
        results.extend(fetch_reddit_trends(query))
        
        # Limit to first 10 results
        results = results[:10]
        
        if not results:
            return f"I couldn't find any relevant trends about {query} at the moment. Could you try rephrasing your query or exploring a different topic?"
        
        # Generate dynamic response
        return generate_dynamic_response(user_input, results)

    except Exception as e:
        logger.error(f"Error fetching trending topics: {str(e)}", exc_info=True)
        return f"I apologize, but I encountered an unexpected issue while fetching trends about {query}. Could we try again with a different query?"

# ... (keep existing YouTube, News, and Twitter API functions)

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
            
            summary = nlp(description).sents.__next__().text  # Get first sentence as summary
            
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
            
            summary = nlp(content).sents.__next__().text  # Get first sentence as summary
            
            results.append({
                'source': 'NewsAPI',
                'title': title,
                'summary': summary,
                'url': article_url
            })

        logger.info(f"Fetched {len(results)} news trends.")
        return results
    except RequestException as e:
        logger.error(f"Error fetching news trends: {str(e)}")
        return []

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
            
            summary = nlp(snippet).sents.__next__().text  # Get first sentence as summary
            
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

def fetch_twitter_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending tweets matching the query."""
    try:
        logger.info(f"Fetching Twitter trends for query: {query}")
        search_url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&tweet.fields=text,author_id,created_at&expansions=author_id&user.fields=username"
        headers = {
            "Authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
            "User-Agent": "v2RecentSearchPython"
        }
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for tweet in data.get('data', []):
            tweet_text = tweet['text']
            author = next((user for user in data['includes']['users'] if user['id'] == tweet['author_id']), None)
            username = author['username'] if author else 'Unknown'
            
            summary = nlp(tweet_text).sents.__next__().text  # Get first sentence as summary
            
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
            
            summary = nlp(selftext[:500]).sents.__next__().text if selftext else title  # Get first sentence of selftext or use title
            
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
    return fetch_trending_topics(sanitized_input)

if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = get_trends(user_query)
    print(trends)