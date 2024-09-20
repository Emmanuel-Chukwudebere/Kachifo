import os
import requests
from dotenv import load_dotenv
import praw
from googleapiclient.discovery import build
from twitter import *
import openai
from flask_caching import Cache
from ratelimit import limits, sleep_and_retry

load_dotenv()

# API keys and configurations
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Initialize API clients
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

twitter = Twitter(
    auth=OAuth(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET,
               TWITTER_API_KEY, TWITTER_API_SECRET)
)

google_search = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)

openai.api_key = OPENAI_API_KEY

# Initialize cache
cache = Cache(config={'CACHE_TYPE': 'simple'})

# Rate limiting decorators
@sleep_and_retry
@limits(calls=1, period=1)  # 1 call per second
def rate_limited_api_call(func):
    return func()

@cache.memoize(timeout=300)  # Cache for 5 minutes
def get_news_trends(query):
    try:
        url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWSAPI_KEY}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching news trends: {e}")
        return []

@cache.memoize(timeout=300)
def get_reddit_trends(subreddit_name):
    try:
        subreddit = reddit.subreddit(subreddit_name)
        return [post.title for post in subreddit.hot(limit=10)]
    except praw.exceptions.PRAWException as e:
        print(f"Error fetching Reddit trends: {e}")
        return []

@cache.memoize(timeout=300)
def get_youtube_trends(region_code='US'):
    try:
        request = youtube.videos().list(
            part="snippet",
            chart="mostPopular",
            regionCode=region_code,
            maxResults=10
        )
        response = request.execute()
        return [item['snippet']['title'] for item in response['items']]
    except Exception as e:
        print(f"Error fetching YouTube trends: {e}")
        return []

@cache.memoize(timeout=300)
def get_twitter_trends(woeid=1):
    try:
        trends = twitter.trends.place(_id=woeid)
        return [trend['name'] for trend in trends[0]['trends']]
    except TwitterHTTPError as e:
        print(f"Error fetching Twitter trends: {e}")
        return []

@cache.memoize(timeout=300)
def get_google_trends(query):
    try:
        res = google_search.cse().list(q=query, cx=GOOGLE_CSE_ID).execute()
        return [item['title'] for item in res['items']]
    except Exception as e:
        print(f"Error fetching Google trends: {e}")
        return []

@cache.memoize(timeout=60)  # Cache ChatGPT responses for 1 minute
def get_chatgpt_response(prompt):
    try:
        response = openai.Completion.create(
            engine="text-davinci-002",
            prompt=prompt,
            max_tokens=150
        )
        return response.choices[0].text.strip()
    except openai.error.OpenAIError as e:
        print(f"Error getting ChatGPT response: {e}")
        return "Sorry, I couldn't generate a response at this time."

def get_all_trends(query):
    trends = {
        'news': rate_limited_api_call(lambda: get_news_trends(query)),
        'reddit': rate_limited_api_call(lambda: get_reddit_trends('all')),
        'youtube': rate_limited_api_call(lambda: get_youtube_trends()),
        'twitter': rate_limited_api_call(lambda: get_twitter_trends()),
        'google': rate_limited_api_call(lambda: get_google_trends(query))
    }
    return trends