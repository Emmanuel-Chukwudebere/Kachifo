import openai
import requests
from flask_caching import Cache
import os

# Initialize cache
cache = Cache(config={'CACHE_TYPE': 'simple'})

# Environment variables for API keys
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_SECRET = os.getenv('REDDIT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN')

def get_chatgpt_response(prompt):
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=250,
            temperature=0.7
        )
        return response.choices[0].text.strip()
    except openai.error.OpenAIError as e:
        print(f"Error getting ChatGPT response: {e}")
        return "Sorry, I couldn't generate a response at this time."

### NEWS API CALL ###
def get_news_trends(query):
    """
    Fetch news trends from NewsAPI based on the query.
    """
    try:
        url = f'https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}'
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            return [f"{article['title']} - {article['url']}" for article in articles]  # Return titles and URLs
        else:
            return ["No news trends found."]
    except Exception as e:
        print(f"Error fetching news trends: {e}")
        return ["Error fetching news trends."]

### REDDIT API CALL ###
def get_reddit_trends(query):
    """
    Fetch Reddit trends using Reddit API (PRAW or Requests).
    Requires valid Reddit app credentials.
    """
    try:
        headers = {"User-Agent": REDDIT_USER_AGENT}
        auth = requests.auth.HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_SECRET)
        data = {'grant_type': 'client_credentials'}
        token = requests.post('https://www.reddit.com/api/v1/access_token', auth=auth, data=data, headers=headers)
        if token.status_code == 200:
            access_token = token.json()['access_token']
            headers['Authorization'] = f'bearer {access_token}'
            search_url = f"https://oauth.reddit.com/search?q={query}&sort=top&limit=5"
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                posts = response.json()['data']['children']
                return [f"{post['data']['title']} - {post['data']['url']}" for post in posts]  # Title and URL
        return ["No Reddit trends found."]
    except Exception as e:
        print(f"Error fetching Reddit trends: {e}")
        return ["Error fetching Reddit trends."]

### YOUTUBE API CALL ###
def get_youtube_trends(query):
    """
    Fetch YouTube video trends using YouTube API.
    """
    try:
        url = f'https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&key={YOUTUBE_API_KEY}&maxResults=5'
        response = requests.get(url)
        if response.status_code == 200:
            videos = response.json().get('items', [])
            return [f"{video['snippet']['title']} - https://www.youtube.com/watch?v={video['id']['videoId']}" for video in videos]
        else:
            return ["No YouTube trends found."]
    except Exception as e:
        print(f"Error fetching YouTube trends: {e}")
        return ["Error fetching YouTube trends."]

### TWITTER API CALL ###
def get_twitter_trends(query):
    """
    Fetch Twitter trends using the Twitter API.
    """
    try:
        headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
        url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&tweet.fields=created_at&max_results=5"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            tweets = response.json()['data']
            return [f"{tweet['text']} - Tweet ID: {tweet['id']}" for tweet in tweets]
        else:
            return ["No Twitter trends found."]
    except Exception as e:
        print(f"Error fetching Twitter trends: {e}")
        return ["Error fetching Twitter trends."]

### GOOGLE TRENDS API CALL ###
def get_google_trends(query):
    """
    Fetch Google trends (simplified using pytrends).
    """
    from pytrends.request import TrendReq
    try:
        pytrends = TrendReq()
        pytrends.build_payload([query], cat=0, timeframe='today 12-m', geo='', gprop='')
        related_queries = pytrends.related_queries()
        top_related = related_queries[query]['top']
        return [f"{row['query']}" for index, row in top_related.iterrows()]
    except Exception as e:
        print(f"Error fetching Google trends: {e}")
        return ["Error fetching Google trends."]

### GET ALL TRENDS ###
def get_all_trends(query):
    """
    Fetch trends from various APIs and return as a structured format for ChatGPT
    to summarize. This can include news, Reddit, YouTube, Twitter, Google, etc.
    """
    trends = {
        'news': get_news_trends(query),
        'reddit': get_reddit_trends(query),
        'youtube': get_youtube_trends(query),
        'twitter': get_twitter_trends(query),
        'google': get_google_trends(query),
    }

    formatted_trends = ""
    for category, trend_list in trends.items():
        formatted_trends += f"\n{category.capitalize()} trends:\n"
        for trend in trend_list:
            formatted_trends += f"- {trend}\n"
    
    return formatted_trends
