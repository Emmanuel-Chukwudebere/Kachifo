from dotenv import load_dotenv
import os

load_dotenv('.env')

class Config:
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', 'AIzaSyAVJ_sMio0juSdj7eJSZOKJnZM_8hEGvmo')
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', 'AIzaSyAVJ_sMio0juSdj7eJSZOKJnZM_8hEGvmo')
    REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID', 'zskm6kxen7LUioIZo7c7Lw')
    REDDIT_SECRET = os.getenv('REDDIT_SECRET', 'yvd-36fJeq4ka6-BxsPrb8tfWJFcqw')
    REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', 'python:com.kachifo.chatbot:v1.0 (by /u/e_chukwudebere)')
    TWITTER_API_KEY = os.getenv('TWITTER_API_KEY', 'zvC2Csz3jp8DKzz095ma6IiqB')
    TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET', '4gtQTvRqCcwvBia8baGVAOtVeNGSdglrtJovkWR53C9aQ3cWh4')
    TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN', '1523964160291319810-6CHoh87JPqwxlmJ8H2paosNy8RAYSh')
    TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET', 'fj4t9Nt8tx6ZxH0csliGKbpBbIXRr5eZkp8sYfJecztSS')
    NEWS_API_KEY = os.getenv('NEWS_API_KEY', 'cf11bdce87ea4180879a7d8290e342e5')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'sk-proj-qyDWWUgXN4v8qvNVqgEgRT4KqzVFLt6RdPH2BOMzBdj-H06pMGIVdC4ufaq1qNgWTOebjcRnxT3BIbkFJU4g-u2GRzr_Ah1U5jAeEhqK5Q1YVIHfTf5YZIRYksgIQNhJ_EgePq2dG3BkwArGLxniNVyOJOA')