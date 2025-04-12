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
web_search_cache = TTLCache(maxsize=100, ttl=300)  # Cache web searches for 5 minutes
analysis_cache = TTLCache(maxsize=500, ttl=1800)  # Cache analyses for 30 minutes

# API keys loaded from environment variables
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
SERP_API_KEY = os.getenv("SERP_API_KEY")

# Hugging Face API configuration
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY')
HF_API_SUMMARY_MODEL = "facebook/bart-large-cnn"
HF_API_NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"
HF_API_BOT_MODEL = "mistralai/Mistral-7B-Instruct-v0.1"
HF_API_ANALYSIS_MODEL = "mistralai/Mistral-7B-Instruct-v0.1"  # Using Mistral for analysis too

# Initialize HuggingFace inference clients
def initialize_inference_clients():
    """Initialize HuggingFace inference clients with robust error handling."""
    global inference_summary, inference_ner, inference_bot
    
    try:
        from huggingface_hub import InferenceClient
        
        # Initialize the summary and NER models
        try:
            inference_summary = InferenceClient(model=HF_API_SUMMARY_MODEL, token=HF_API_KEY)
            logger.info(f"Successfully initialized summary model: {HF_API_SUMMARY_MODEL}")
        except Exception as sum_err:
            logger.error(f"Error initializing summary model: {str(sum_err)}")
            inference_summary = None
            
        try:
            inference_ner = InferenceClient(model=HF_API_NER_MODEL, token=HF_API_KEY)
            logger.info(f"Successfully initialized NER model: {HF_API_NER_MODEL}")
        except Exception as ner_err:
            logger.error(f"Error initializing NER model: {str(ner_err)}")
            inference_ner = None
        
        # Initialize Mistral with fallbacks
        mistral_models = [
            "mistralai/Mistral-7B-Instruct-v0.1",
            "mistralai/Mistral-7B-v0.1",
            "facebook/opt-350m",  # Small fallback if Mistral is unavailable
            "facebook/blenderbot-400M-distill"  # Last resort
        ]
        
        for model in mistral_models:
            try:
                logger.info(f"Attempting to initialize conversational model: {model}")
                inference_bot = InferenceClient(model=model, token=HF_API_KEY)
                
                # Test the model with a simple prompt
                test_prompt = "Hello, how are you?"
                if model.startswith("mistralai/Mistral"):
                    # Format specifically for Mistral
                    messages = [
                        {"role": "user", "content": test_prompt}
                    ]
                    test_response = inference_bot.chat_completion(messages=messages, max_tokens=10)
                else:
                    # Generic format for other models
                    test_response = inference_bot.text_generation(prompt=test_prompt, max_new_tokens=10)
                
                logger.info(f"Successfully initialized and tested model: {model}")
                # Update the global variable to reflect the actual model used
                global HF_API_BOT_MODEL
                HF_API_BOT_MODEL = model
                return True
            except Exception as model_err:
                logger.warning(f"Failed to initialize model {model}: {str(model_err)}")
                continue
                
        # If we get here, all models failed
        logger.error("All conversational models failed to initialize")
        inference_bot = None
        return False
        
    except Exception as e:
        logger.error(f"Critical error initializing HuggingFace clients: {str(e)}")
        inference_summary = None
        inference_ner = None
        inference_bot = None
        return False

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
def generate_conversational_response(user_input: str, conversation_history: List[Dict[str, str]] = None) -> str:
    """Generate a conversational response using Mistral or fallback models."""
    if not user_input:
        return "I didn't receive any input. How can I help you today?"
        
    try:
        logger.info(f"Generating conversational response for input: {user_input[:50]}...")
        
        if not inference_bot:
            return "Conversational service unavailable at the moment."
            
        # Use the conversation history if provided, or create a new conversation
        if not conversation_history:
            conversation_history = [
                {'role': 'system', 'content': 'You are Kachifo, a helpful AI assistant specialized in discovering and analyzing trends. Always refer to yourself as Kachifo.'},
                {'role': 'user', 'content': user_input}
            ]
        # If history exists but doesn't include the latest user input, add it
        elif conversation_history[-1]['role'] != 'user' or conversation_history[-1]['content'] != user_input:
            conversation_history.append({'role': 'user', 'content': user_input})
            
        # Format the prompt based on which model we're using
        if HF_API_BOT_MODEL.startswith("mistralai/Mistral"):
            # Mistral doesn't support system messages in the same way, so convert to a format it understands
            mistral_messages = []
            system_content = None
            
            # Extract system message if present
            for msg in conversation_history:
                if msg['role'] == 'system':
                    system_content = msg['content']
                else:
                    mistral_messages.append(msg)
                    
            # If there was a system message, prepend it to the first user message
            if system_content and mistral_messages and mistral_messages[0]['role'] == 'user':
                mistral_messages[0]['content'] = f"{system_content}\n\nUser: {mistral_messages[0]['content']}"
                
            try:
                # Use chat completion for Mistral
                response = inference_bot.chat_completion(
                    messages=mistral_messages, 
                    max_tokens=2000,
                    temperature=0.7
                )
                
                # Extract content based on response format
                if isinstance(response, dict):
                    if 'choices' in response:
                        # OpenAI-like format
                        content = response.get('choices', [{}])[0].get('message', {}).get('content', "")
                    elif 'generated_text' in response:
                        content = response.get('generated_text', "")
                    else:
                        content = str(response)
                else:
                    content = str(response)
                    
            except Exception as chat_err:
                logger.warning(f"Error using chat completion: {str(chat_err)}")
                # Fallback to simple text completion
                # Build input text from conversation history
                prompt_parts = []
                
                for i, msg in enumerate(mistral_messages):
                    if msg['role'] == 'user':
                        prompt_parts.append(f"{msg['content']}")
                    elif msg['role'] == 'assistant' and i > 0:
                        prompt_parts.append(f"{msg['content']}")
                
                prompt = "".join(prompt_parts)
                
                response = inference_bot.text_generation(
                    prompt=prompt, 
                    max_new_tokens=2000,
                    temperature=0.7
                )
                content = response.get('generated_text', str(response))
                # Remove the input prompt if it's included in the response
                if content.startswith(prompt):
                    content = content[len(prompt):].strip()
        else:
            # Generic format for other models
            # Convert the conversation history to a single text prompt
            prompt_parts = []
            
            for msg in conversation_history:
                if msg['role'] == 'system':
                    prompt_parts.append(f"System: {msg['content']}")
                elif msg['role'] == 'user':
                    prompt_parts.append(f"User: {msg['content']}")
                elif msg['role'] == 'assistant':
                    prompt_parts.append(f"Assistant: {msg['content']}")
            
            prompt_parts.append("Assistant:")
            prompt = "\n".join(prompt_parts)
            
            response = inference_bot.text_generation(
                prompt=prompt, 
                max_new_tokens=2000,
                temperature=0.7
            )
            
            if isinstance(response, dict) and 'generated_text' in response:
                content = response['generated_text']
                # Extract just the assistant's response
                if "Assistant:" in content:
                    content = content.split("Assistant:")[-1].strip()
            else:
                content = str(response)
        
        if not content:
            raise ValueError("Received empty response from the model")
            
        logger.info("Conversational response generated successfully")
        
        # Ensure Kachifo personality if not already included
        if "kachifo" not in content.lower() and not content.startswith("I am ") and not content.startswith("I'm "):
            content = f"As Kachifo, {content}"
            
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

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=2)
def perform_web_search(query: str) -> List[Dict[str, Any]]:
    """Perform a web search using Google Custom Search API."""
    # Check cache first
    cache_key = f"web:{query}"
    if cache_key in web_search_cache:
        logger.info(f"Cache hit for web search: {query}")
        return web_search_cache[cache_key]
    
    results = []
    
    # Use Google Custom Search API
    if GOOGLE_API_KEY and GOOGLE_CSE_ID:
        try:
            logger.info(f"Performing Google search for: {query}")
            url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={GOOGLE_CSE_ID}&key={GOOGLE_API_KEY}&num=5"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if "items" in data:
                for item in data["items"]:
                    results.append({
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": item.get("snippet", "")
                    })
        except Exception as e:
            logger.error(f"Google search failed: {str(e)}")
    else:
        logger.error("Google API key or CSE ID not configured for web search")
    
    # If no results, provide a fallback response
    if not results:
        logger.warning(f"No search results found for: {query}")
        results = [{
            "title": "No search results found",
            "link": "#",
            "snippet": f"Unable to find web search results for '{query}'. Please try a different query or check your Google API configuration."
        }]
    
    web_search_cache[cache_key] = results
    return results

@rate_limited(1.0)
@retry_with_backoff(Exception, tries=3)
def analyze_content(topic: str, content_list: List[str]) -> str:
    """Analyze a list of content pieces about a specific topic."""
    if not content_list:
        return f"I don't have any information to analyze about '{topic}'."
    
    # Check cache
    cache_key = f"analysis:{topic}:{hash(str(content_list))}"
    if cache_key in analysis_cache:
        logger.info(f"Cache hit for analysis: {topic}")
        return analysis_cache[cache_key]
    
    try:
        logger.info(f"Analyzing content about: {topic}")
        
        if not inference_bot:
            return f"Analysis service is unavailable at the moment. I can't provide an analysis for '{topic}'."
        
        # Prepare the content for analysis
        combined_content = "\n\n".join(content_list)
        # Truncate if too long
        if len(combined_content) > 4000:
            combined_content = combined_content[:4000] + "..."
        
        # Create prompt for the analysis
        prompt = f"""As Kachifo, analyze the following information about "{topic}" and provide a comprehensive analysis. 
        Include insights about key trends, patterns, significant factors, and potential implications.
        
        Here's the information to analyze:
        
        {combined_content}
        
        Provide a well-structured analysis with clear sections and insights.
        Remember to introduce yourself as Kachifo in your response. 
"""
        
        # Use text generation for analysis
        response = inference_bot.text_generation(
            prompt=prompt,
            max_new_tokens=800,  # Allow for longer analysis
            temperature=0.7,
            top_p=0.9
        )
        
        # Process the response
        if isinstance(response, dict) and 'generated_text' in response:
            analysis = response['generated_text']
            # Remove the prompt from the response if present
            if prompt in analysis:
                analysis = analysis[len(prompt):].strip()
        else:
            analysis = str(response)
        
        if not analysis:
            analysis = f"I couldn't generate a meaningful analysis about '{topic}' with the provided information."
        
        # Cache the result
        analysis_cache[cache_key] = analysis
        return analysis
        
    except Exception as e:
        logger.error(f"Error analyzing content: {str(e)}", exc_info=True)
        return f"I encountered an issue while analyzing information about '{topic}'. Please try again later."

# Call the initialization function after all functions are defined
initialize_inference_clients()

# For direct testing
if __name__ == "__main__":
    user_query = input("What trends would you like to explore today? ")
    trends = fetch_trending_topics(user_query)
    import json
    print(json.dumps(trends, indent=2))
