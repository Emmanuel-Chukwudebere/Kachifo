import openai
from flask_caching import Cache

# Initialize cache
cache = Cache(config={'CACHE_TYPE': 'simple'})

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

def get_all_trends(query):
    """
    Fetch trends from various APIs and return as a structured format for ChatGPT
    to summarize. This can include news, Reddit, YouTube, Twitter, etc.
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
            if isinstance(trend, dict) and 'url' in trend:
                formatted_trends += f"- {trend['title']} (Source: {trend['url']})\n"
            else:
                formatted_trends += f"- {trend}\n"
    
    return formatted_trends
