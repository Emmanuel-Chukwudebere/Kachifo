import os

class Config:
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', 'AIzaSyAVJ_sMioOjuSdj7eJSZOKJnZM_8hEGvmo')
    YOUTUBE_API_KEY = os.getenv('AIzaSyAVJ_sMioOjuSdj7eJSZOKJnZM_8hEGvmo')
    REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID', 'zskm6kxen7LUioIZo7c7Lw')
    REDDIT_SECRET = os.getenv('REDDIT_SECRET', 'your-reddit-secret')
    REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', '	yvd-36fJeq4ka6-BxsPrb8tfWJFcqw')
    TWITTER_API_KEY = os.getenv('TWITTER_API_KEY', 'MAEUjU5lhp5B8WrllG4TGsEx0')
    TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET', 'eLGaex9yWbEU3PJZaRw3BBt4Qw0soT25rUyOMJPzAbqSdSYoVv')
    TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN', '1523964160291319810-QJztiYubF5DFjBZKGhzRMir5on6WgV')
    TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET', 'lblsG10CQJQcxw3EJH3lNOojpBKB7poFbJC5PVG5zKijM')
    NEWS_API_KEY = os.getenv('cf11bdce87ea4180879a7d8290e342e5')
