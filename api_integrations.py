import os
import logging
import time
import requests
from cachetools import TTLCache
from functools import wraps
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import praw

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# In-memory caches with TTL (Time-To-Live)
summary_cache = TTLCache(maxsize=1000, ttl=3600)  # Cache summaries for 1 hour
entity_cache = TTLCache(maxsize=1000, ttl=3600)   # Cache entities for 1 hour

# API keys loaded from environment variables
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

# Hugging Face API configuration
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"
HF_API_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"
HF_API_BOT_MODEL = "microsoft/phi-4/v1"

# Initialize HuggingFace inference clients
try:
    from huggingface_hub import InferenceClient
    inference_summary = InferenceClient(model=HF_API_SUMMARY_MODEL, token=HF_API_KEY)
    inference_ner = InferenceClient(model=HF_API_NER_MODEL, token=HF_API_KEY)
    inference_bot = InferenceClient(model=HF_API_BOT_MODEL, token=HF_API_KEY)
    logger.info("Successfully initialized HuggingFace inference clients")
except Exception as e:
    logger.error(f"Error initializing HuggingFace clients: {str(e)}")
    inference_summary = None
    inference_ner = None
    inference_bot = None

def rate_limited(max_per_second: float):
    """Decorator to limit the rate at which a function can be called."""
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
    """Retry calling the decorated function with exponential backoff."""
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
    """Generate a comprehensive summary from multiple individual summaries."""
    if not individual_summaries:
        return "No information available to summarize."
        
    combined_text = " ".join(individual_summaries)
    try:
        logger.info("Generating general summary via Hugging Face API")
        if not inference_summary:
            return "Summary service unavailable at the moment."
            
        response = inference_summary.summarization(combined_text)
        
        # Handle different response formats
        if isinstance(response, str):
            return response
        elif isinstance(response, dict):
            return response.get('summary_text', "No summary available")
        else:
            return str(response) if response else "No summary available"
    except Exception as e:
        logger.error(f"Error generating general summary: {str(e)}")
        return "Sorry, I couldn't generate a summary at the moment."

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def summarize_with_hf(text: str) -> str:
    """Summarize text using Hugging Face API with caching."""
    if not text:
        return "No content to summarize."
        
    # Check cache first
    if text in summary_cache:
        logger.info(f"Cache hit for summarization: {text[:50]}...")
        return summary_cache[text]
    
    try:
        logger.info(f"Summarizing text: {text[:50]}...")
        max_input_length = 1024
        truncated_text = text[:max_input_length]
        
        if not inference_summary:
            return "Summarization service unavailable at the moment."
            
        # Make the API call
        response = inference_summary.summarization(truncated_text)
        
        # Process the response based on its type
        if isinstance(response, str):
            summary = response
        elif isinstance(response, dict):
            summary = response.get('summary_text', "No summary available")
        else:
            logger.warning(f"Unexpected response format: {type(response)}")
            summary = str(response) if response else "No summary available"
            
        # Cache and return the summary
        summary_cache[text] = summary
        return summary
    except Exception as e:
        logger.error(f"Error in summarization: {str(e)}")
        return "Sorry, summarization is unavailable at the moment."

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def extract_entities_with_hf(text: str) -> Dict[str, List[str]]:
    """Extract named entities from text using Hugging Face API with caching."""
    if not text:
        return {"entities": []}
        
    # Check cache first
    if text in entity_cache:
        logger.info(f"Cache hit for NER: {text[:50]}...")
        return entity_cache[text]
    
    try:
        logger.info(f"Extracting entities from text: {text[:50]}...")
        max_input_length = 512
        truncated_text = text[:max_input_length]
        
        if not inference_ner:
            return {"entities": []}
            
        response = inference_ner.token_classification(truncated_text)
        
        # Ensure response is a list of dictionaries
        if not isinstance(response, list):
            logger.warning(f"Unexpected NER response format: {type(response)}")
            entities = []
        else:
            # Filter entities by type
            entities = [ent['word'] for ent in response if 'entity_group' in ent and 'word' in ent and ent['entity_group'] in ['ORG', 'PER', 'LOC']]
        
        result = {"entities": entities}
        entity_cache[text] = result
        return result
    except Exception as e:
        logger.error(f"Error extracting entities: {str(e)}")
        return {"entities": []}

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def generate_conversational_response(user_input: str) -> str:
    """Generate a conversational response using Microsoft phi-4."""
    if not user_input:
        return "I didn't receive any input. How can I help you today?"
        
    try:
        logger.info(f"Generating conversational response for input: {user_input[:50]}...")
        
        if not inference_bot:
            return "Conversational service unavailable at the moment."
            
        messages = [
            {
                "role": "system",
                "content": "You are a helpful, engaging, and knowledgeable AI assistant. Respond naturally and conversationally."
            },
            {
                "role": "user",
                "content": user_input
            }
        ]
        
        # Use the proper API format
        try:
            # First try the chat completions format
            response = inference_bot.chat_completion(messages=messages, max_tokens=150)
            
            # Handle response formats
            if isinstance(response, dict) and 'choices' in response:
                # OpenAI-like format
                content = response.get('choices', [{}])[0].get('message', {}).get('content', "")
            elif isinstance(response, dict) and 'generated_text' in response:
                # HF text generation format
                content = response.get('generated_text', "")
            elif isinstance(response, dict):
                # Other dictionary format
                content = str(response)
            elif isinstance(response, str):
                # Direct string response
                content = response
            else:
                content = str(response) if response else ""
                
        except Exception as chat_err:
            logger.warning(f"Chat completion failed, trying text generation: {str(chat_err)}")
            # Fallback to text generation
            prompt = f"System: You are a helpful assistant.\nUser: {user_input}\nAssistant:"
            response = inference_bot.text_generation(prompt=prompt, max_new_tokens=150)
            
            if isinstance(response, dict) and 'generated_text' in response:
                content = response['generated_text'].split('Assistant:')[-1].strip()
            elif isinstance(response, str):
                content = response.split('Assistant:')[-1].strip()
            else:
                content = str(response) if response else ""
        
        if not content:
            raise ValueError("Received empty response from the chat model.")
            
        logger.info("Conversational response generated successfully.")
        return content
    except Exception as e:
        logger.error(f"Error generating conversational response: {str(e)}", exc_info=True)
        return "I'm having trouble generating a response right now. Please try again later."

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_youtube_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending videos from YouTube related to the query."""
    if not YOUTUBE_API_KEY:
        logger.error("YouTube API key not configured")
        return []
        
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=3&key={YOUTUBE_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        result = response.json()
        items = result.get('items', [])
        
        return [{
            "title": item['snippet']['title'],
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            "summary": summarize_with_hf(item['snippet']['description']),
            "source": "YouTube"
        } for item in items]
    except Exception as e:
        logger.error(f"Error fetching YouTube trends: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_google_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending search results from Google related to the query."""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logger.error("Google API key or CSE ID not configured")
        return []
        
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        items = result.get('items', [])
        
        return [{
            "title": item.get("title", "No title available"),
            "url": item.get("link", "#"),
            "summary": summarize_with_hf(item.get("snippet", "")),
            "source": "Google"
        } for item in items]
    except Exception as e:
        logger.error(f"Error fetching Google trends: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_reddit_trends(query: str) -> List[Dict[str, Any]]:
    """Fetch trending posts from Reddit related to the query."""
    reddit_client_id = os.getenv("REDDIT_CLIENT_ID")
    reddit_secret = os.getenv("REDDIT_SECRET")
    reddit_user_agent = os.getenv("REDDIT_USER_AGENT")
    
    if not reddit_client_id or not reddit_secret or not reddit_user_agent:
        logger.error("Reddit API credentials not configured")
        return []
    
    try:
        reddit = praw.Reddit(
            client_id=reddit_client_id,
            client_secret=reddit_secret,
            user_agent=reddit_user_agent
        )
        
        results = []
        for submission in reddit.subreddit("all").search(query, sort="top", limit=3):
            content = submission.selftext[:500] if submission.selftext else "No content available"
            summary = summarize_with_hf(content)
            results.append({
                "title": submission.title,
                "url": submission.url,
                "summary": summary,
                "source": "Reddit"
            })
        return results
    except Exception as e:
        logger.error(f"Error fetching Reddit trends: {str(e)}")
        return []

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def fetch_news_articles(query: str) -> List[Dict[str, Any]]:
    """Fetch news articles related to the query using NewsAPI."""
    if not NEWSAPI_KEY:
        logger.error("NewsAPI key not configured")
        return []
        
    url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        articles = result.get('articles', [])[:3]  # Limit to 3 articles
        
        return [{
            "title": article.get("title", "No title available"),
            "url": article.get("url", "#"),
            "summary": summarize_with_hf(article.get("description", "")),
            "source": "NewsAPI"
        } for article in articles]
    except Exception as e:
        logger.error(f"Error fetching news articles: {str(e)}")
        return []

def fetch_trending_topics(query: str) -> List[Dict[str, Any]]:
    """
    Aggregate trending topics from multiple sources.
    Returns a combined list of trending topics.
    """
    if not query:
        return []
        
    logger.info(f"Fetching trending topics for query: {query}")
    
    # Fetch trends from each source in parallel (future enhancement)
    youtube_trends = fetch_youtube_trends(query)
    reddit_trends = fetch_reddit_trends(query)
    google_trends = fetch_google_trends(query)
    news_trends = fetch_news_articles(query)
    
    # Combine results
    all_trends = []
    all_trends.extend(youtube_trends)
    all_trends.extend(reddit_trends)
    all_trends.extend(google_trends)
    all_trends.extend(news_trends)
    
    return all_trends

# For direct testing
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    import json
    print(json.dumps(trends, indent=2))
