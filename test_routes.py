import requests

BASE_URL = 'http://localhost:5000'

def test_home():
    response = requests.get(f'{BASE_URL}/')
    print(f"Home: {response.json()}")

def test_search():
    response = requests.post(f'{BASE_URL}/search', json={"query": "AI trends"})
    print(f"Search: {response.json()}")

def test_trend_details():
    response = requests.get(f'{BASE_URL}/trend/123')
    print(f"Trend Details: {response.json()}")

def test_categories():
    response = requests.get(f'{BASE_URL}/categories')
    print(f"Categories: {response.json()}")

if __name__ == '__main__':
    test_home()
    test_search()
    test_trend_details()
    test_categories()