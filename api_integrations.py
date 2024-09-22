import os
import requests
import logging
from requests.auth import HTTPBasicAuth
from transformers import pipeline
import re
from datetime import datetime

# Logging setup
logging.basicConfig(filename="Kachifo.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Initialize Hugging Face summarization and text generation pipelines
hugging_face_summarizer = pipeline('summarization')
hugging_face_generator = pipeline('text-generation', model='gpt2')

# API keys from environment variables
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.getenv('REDDIT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')

# Helper function for input sanitization
def sanitize_input(query):
    # Basic sanitization to prevent SQL injection and other attacks
    return re.sub(r"[;--]", "", query)

# Reddit Integration
def fetch_reddit_data(query):
    query = sanitize_input(query)
    reddit_auth_url = "https://www.reddit.com/api/v1/access_token"
    auth = HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
    data = {'grant_type': 'client_credentials'}
    headers = {'User-Agent': REDDIT_USER_AGENT}
    
    try:
        auth_response = requests.post(reddit_auth_url, auth=auth, data=data, headers=headers)
        auth_response.raise_for_status()
        access_token = auth_response.json().get('access_token')

        headers['Authorization'] = f'bearer {access_token}'
        search_url = f"https://oauth.reddit.com/search?q={query}&limit=10"
        search_response = requests.get(search_url, headers=headers)
        search_response.raise_for_status()
        
        reddit_posts = search_response.json().get('data', {}).get('children', [])
        structured_results = []

        for post in reddit_posts:
            title = post['data'].get('title', 'No title')
            url = f"https://www.reddit.com{post['data'].get('permalink', '')}"
            body = post['data'].get('selftext', '')
            
            # Summarize post body
            if body:
                summary = hugging_face_summarizer(body, max_length=50, min_length=25, do_sample=False)[0]['summary_text']
            else:
                summary = "No content available."
            
            structured_results.append({'title': title, 'url': url, 'summary': summary})
        
        return structured_results
    except Exception as e:
        logging.error(f"Reddit API failed: {str(e)}")
        return [{'error': 'Failed to fetch data from Reddit. Please try again later.'}]

# Twitter Integration
def fetch_twitter_data(query):
    query = sanitize_input(query)
    search_url = f"https://api.twitter.com/1.1/search/tweets.json?q={query}&count=10"
    headers = {
        'Authorization': f'Bearer {TWITTER_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        tweets = response.json().get('statuses', [])
        structured_results = []

        for tweet in tweets:
            text = tweet.get('text', 'No text available')
            tweet_url = f"https://twitter.com/user/status/{tweet.get('id_str', '')}"
            
            # Summarize tweet
            summary = hugging_face_summarizer(text, max_length=30, min_length=10, do_sample=False)[0]['summary_text']
            
            structured_results.append({'tweet': text, 'url': tweet_url, 'summary': summary})
        
        return structured_results
    except Exception as e:
        logging.error(f"Twitter API failed: {str(e)}")
        return [{'error': 'Failed to fetch data from Twitter. Please try again later.'}]

# YouTube Integration
def fetch_youtube_data(query):
    query = sanitize_input(query)
    youtube_search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=10&q={query}&key={YOUTUBE_API_KEY}"
    
    try:
        response = requests.get(youtube_search_url)
        response.raise_for_status()
        videos = response.json().get('items', [])
        structured_results = []

        for video in videos:
            title = video['snippet'].get('title', 'No title')
            video_id = video['id'].get('videoId', '')
            url = f"https://www.youtube.com/watch?v={video_id}"

            structured_results.append({'title': title, 'url': url, 'summary': 'No summary available for videos.'})
        
        return structured_results
    except Exception as e:
        logging.error(f"YouTube API failed: {str(e)}")
        return [{'error': 'Failed to fetch data from YouTube. Please try again later.'}]

# Google News Integration
def fetch_google_news(query):
    query = sanitize_input(query)
    google_search_url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={os.getenv('GOOGLE_CSE_ID')}&key={GOOGLE_API_KEY}"
    
    try:
        response = requests.get(google_search_url)
        response.raise_for_status()
        news_items = response.json().get('items', [])
        structured_results = []

        for item in news_items:
            title = item.get('title', 'No title')
            url = item.get('link', 'No link')
            snippet = item.get('snippet', 'No snippet available')

            structured_results.append({'title': title, 'url': url, 'summary': snippet})
        
        return structured_results
    except Exception as e:
        logging.error(f"Google News API failed: {str(e)}")
        return [{'error': 'Failed to fetch data from Google News. Please try again later.'}]

# Main function to fetch all data
def fetch_trending_topics(query):
    """Fetch trending topics from all sources."""
    logging.info(f"Fetching trending topics for query: {query}")

    reddit_data = fetch_reddit_data(query)
    twitter_data = fetch_twitter_data(query)
    youtube_data = fetch_youtube_data(query)
    google_news_data = fetch_google_news(query)

    return {
        'reddit': reddit_data,
        'twitter': twitter_data,
        'youtube': youtube_data,
        'google_news': google_news_data
    }