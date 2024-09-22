import os
import asyncio
import logging
from functools import wraps
import time
import aiohttp
import openai
from flask_caching import Cache
from pytrends.request import TrendReq

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize cache
cache = Cache(config={'CACHE_TYPE': 'simple'})

# Environment variables for API keys
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.getenv('REDDIT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

openai.api_key = OPENAI_API_KEY

# Rate limiting decorator
def rate_limited(max_calls, time_frame):
    def decorator(func):
        calls = []
        @wraps(func)
        async def wrapper(*args, **kwargs):
            now = time.time()
            calls[:] = [c for c in calls if c > now - time_frame]
            if len(calls) >= max_calls:
                raise Exception("Rate limit exceeded")
            calls.append(now)
            return await func(*args, **kwargs)
        return wrapper
    return decorator

@rate_limited(max_calls=5, time_frame=60)
async def get_chatgpt_response(prompt):
    try:
        response = await openai.Completion.acreate(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=250,
            temperature=0.7
        )
        return response.choices[0].text.strip()
    except Exception as e:
        logger.error(f"OpenAI API error: {str(e)}")  # Log the complete error
        return "Sorry, I couldn't generate a response at this time."

async def get_news_trends(session, query):
    try:
        url = f'https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                articles = data.get('articles', [])
                return [f"{article['title']} - {article['url']}" for article in articles[:5]]
            else:
                logger.warning(f"News API returned status code {response.status}")
                return ["No news trends found."]
    except Exception as e:
        logger.error(f"Error fetching news trends: {e}")
        return ["Error fetching news trends."]

async def get_reddit_trends(session, query):
    try:
        headers = {"User-Agent": REDDIT_USER_AGENT}
        auth = aiohttp.BasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
        data = {'grant_type': 'client_credentials'}
        async with session.post('https://www.reddit.com/api/v1/access_token', auth=auth, data=data, headers=headers) as token_response:
            if token_response.status == 200:
                token_data = await token_response.json()
                access_token = token_data['access_token']
                headers['Authorization'] = f'bearer {access_token}'
                search_url = f"https://oauth.reddit.com/search?q={query}&sort=top&limit=5"
                async with session.get(search_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        posts = data['data']['children']
                        return [f"{post['data']['title']} - {post['data']['url']}" for post in posts]
            else:
                logger.warning(f"Reddit API returned status code {token_response.status}")
        return ["No Reddit trends found."]
    except Exception as e:
        logger.error(f"Error fetching Reddit trends: {e}")
        return ["Error fetching Reddit trends."]

async def get_youtube_trends(session, query):
    try:
        url = f'https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&key={YOUTUBE_API_KEY}&maxResults=5'
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                videos = data.get('items', [])
                return [f"{video['snippet']['title']} - https://www.youtube.com/watch?v={video['id']['videoId']}" for video in videos]
            else:
                logger.warning(f"YouTube API returned status code {response.status}")
                return ["No YouTube trends found."]
    except Exception as e:
        logger.error(f"Error fetching YouTube trends: {e}")
        return ["Error fetching YouTube trends."]

async def get_twitter_trends(session, query):
    try:
        headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
        url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&tweet.fields=created_at&max_results=5"
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                tweets = data['data']
                return [f"{tweet['text']} - Tweet ID: {tweet['id']}" for tweet in tweets]
            else:
                logger.warning(f"Twitter API returned status code {response.status}")
                return ["No Twitter trends found."]
    except Exception as e:
        logger.error(f"Error fetching Twitter trends: {e}")
        return ["Error fetching Twitter trends."]

@cache.memoize(timeout=3600)
def get_google_trends(query):
    try:
        pytrends = TrendReq()
        pytrends.build_payload([query], cat=0, timeframe='today 12-m', geo='', gprop='')
        related_queries = pytrends.related_queries()

        if query in related_queries and 'top' in related_queries[query] and related_queries[query]['top'] is not None:
            top_related = related_queries[query]['top']
            if top_related.empty:
                logger.warning(f"No Google trends found for query: {query}")
                return ["No Google trends found for this query."]
            return [f"{row['query']}" for index, row in top_related.iterrows()]
        else:
            logger.warning(f"No top related Google trends found for query: {query}")
            return ["No Google trends found for this query."]
    except Exception as e:
        logger.error(f"Error fetching Google trends: {e}")
        return ["Error fetching Google trends."]

async def get_all_trends(query):
    async with aiohttp.ClientSession() as session:
        tasks = [
            get_news_trends(session, query),
            get_reddit_trends(session, query),
            get_youtube_trends(session, query),
            get_twitter_trends(session, query)
        ]
        results = await asyncio.gather(*tasks)
        google_trends = await asyncio.to_thread(get_google_trends, query)  # Run synchronous function in a separate thread

    trends = {
        'news': results[0],
        'reddit': results[1],
        'youtube': results[2],
        'twitter': results[3],
        'google': google_trends,
    }

    formatted_trends = ""
    for category, trend_list in trends.items():
        formatted_trends += f"\n{category.capitalize()} trends:\n"
        for trend in trend_list:
            formatted_trends += f"- {trend}\n"
    
    return formatted_trends