#!/usr/bin/env python3
"""
Тест поиска Reddit
"""

import requests

def test_reddit_search():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })
    
    print("🔍 Тестируем поиск Reddit...")
    
    # Простой тест поиска
    url = "https://www.reddit.com/r/OpenAI/search.json"
    params = {
        'q': 'GPT-5',
        'restrict_sr': 'true',
        'limit': 5,
        'sort': 'new',
        't': 'month'
    }
    
    try:
        response = session.get(url, params=params, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            posts = data.get('data', {}).get('children', [])
            print(f"Найдено постов: {len(posts)}")
            
            for i, post in enumerate(posts[:3], 1):
                post_data = post.get('data', {})
                print(f"\n{i}. {post_data.get('title', 'Без названия')}")
                print(f"   Субреддит: r/{post_data.get('subreddit', 'unknown')}")
                print(f"   Автор: u/{post_data.get('author', 'unknown')}")
                print(f"   Очки: {post_data.get('score', 0)}")
        else:
            print(f"Ошибка: {response.text}")
            
    except Exception as e:
        print(f"Исключение: {e}")

if __name__ == "__main__":
    test_reddit_search()
