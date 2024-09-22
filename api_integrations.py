import requests
import os
import logging
from requests.auth import HTTPBasicAuth

# API keys are pulled from Render environment variables
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.getenv('REDDIT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')

logging.basicConfig(filename='Kachifo.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s %(message)s')

def fetch_trends_from_apis(query):
    """Fetch trends and relevant links from multiple APIs."""
    results = {}

    # YouTube API Integration
    youtube_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&key={YOUTUBE_API_KEY}"
    youtube_response = requests.get(youtube_url)
    if youtube_response.status_code == 200:
        youtube_results = youtube_response.json().get('items', [])
        youtube_data = []
        for item in youtube_results:
            video_id = item['id'].get('videoId')
            video_title = item['snippet'].get('title')
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            youtube_data.append({'title': video_title, 'url': video_url})
        results['youtube'] = youtube_data
    else:
        logging.error(f"YouTube API failed: {youtube_response.status_code}")

    # NewsAPI Integration
    news_url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
    news_response = requests.get(news_url)
    if news_response.status_code == 200:
        news_articles = news_response.json().get('articles', [])
        news_data = [{'title': article.get('title'), 'url': article.get('url')} for article in news_articles]
        results['news'] = news_data
    else:
        logging.error(f"NewsAPI failed: {news_response.status_code}")

    # Reddit API Integration
    reddit_auth_url = "https://www.reddit.com/api/v1/access_token"
    reddit_auth = HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
    
    auth_data = {'grant_type': 'client_credentials'}
    headers = {'User-Agent': REDDIT_USER_AGENT}

    auth_response = requests.post(reddit_auth_url, auth=reddit_auth, data=auth_data, headers=headers)
    
    if auth_response.status_code == 200:
        reddit_access_token = auth_response.json().get('access_token')
        
        # Use access token to make authenticated requests to Reddit API
        headers['Authorization'] = f'bearer {reddit_access_token}'
        reddit_search_url = f"https://oauth.reddit.com/search?q={query}"
        reddit_search_response = requests.get(reddit_search_url, headers=headers)
        
        if reddit_search_response.status_code == 200:
            reddit_posts = reddit_search_response.json().get('data', {}).get('children', [])
            reddit_data = [
                {
                    'title': post['data'].get('title'),
                    'url': f"https://www.reddit.com{post['data'].get('permalink')}"
                }
                for post in reddit_posts
            ]
            return reddit_data
        else:
            logging.error(f"Reddit search failed: {reddit_search_response.status_code}")
    else:
        logging.error(f"Reddit OAuth failed: {auth_response.status_code}")

    # Twitter API Integration
    twitter_url = "https://api.twitter.com/2/tweets/search/recent"
    twitter_params = {'query': query}
    twitter_headers = {
        'Authorization': f"Bearer {TWITTER_ACCESS_TOKEN}"
    }
    twitter_response = requests.get(twitter_url, headers=twitter_headers, params=twitter_params)
    
    if twitter_response.status_code == 200:
        twitter_data = twitter_response.json().get('data', [])
        twitter_trends = [{'text': tweet['text'], 'url': f"https://twitter.com/i/web/status/{tweet['id']}"} for tweet in twitter_data]
        results['twitter'] = twitter_trends
    else:
        logging.error(f"Twitter API failed: {twitter_response.status_code}")

    return results if results else None