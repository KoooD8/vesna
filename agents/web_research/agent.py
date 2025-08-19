#!/usr/bin/env python3
"""
Простой Web Research Agent

ВНИМАНИЕ: experimental/legacy.
Этот модуль сохраняется для справки и может быть нестабилен:
- Содержит HTML-скрейпинг Google (хрупко, потенциально нарушает ToS).
- Логика дублируется с WorkingWebAgent и может расходиться.
Рекомендуется использовать WorkingWebAgent из agents.web_research.
"""

import requests
import json
from datetime import datetime
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

class WebResearchAgent:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def search_reddit(self, query):
        """Поиск на Reddit"""
        try:
            # Извлекаем ключевые слова из запроса
            keywords = self.extract_keywords(query)
            search_query = ' '.join(keywords)
            
            print(f"🔍 Поиск на Reddit: '{search_query}'")
            
            url = "https://www.reddit.com/search.json"
            params = {
                'q': search_query,
                'limit': 10,
                'sort': 'relevance',  # Изменено на relevance для более точных результатов
                't': 'month'  # Расширили до месяца
            }
            
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return [{'error': f'HTTP {response.status_code}: {response.text}'}]
            
            data = response.json()
            
            results = []
            for post in data.get('data', {}).get('children', []):
                post_data = post.get('data', {})
                title = post_data.get('title', '')
                selftext = post_data.get('selftext', '')
                
                # Фильтруем результаты по релевантности
                if self.is_relevant(title + ' ' + selftext, keywords):
                    results.append({
                        'title': title,
                        'subreddit': post_data.get('subreddit', ''),
                        'score': post_data.get('score', 0),
                        'url': f"https://reddit.com{post_data.get('permalink', '')}",
                        'author': post_data.get('author', ''),
                        'text': selftext[:300] if selftext else '',
                        'created': post_data.get('created_utc', 0)
                    })
            
            # Сортируем по релевантности и популярности
            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:5]  # Возвращаем топ-5
            
        except Exception as e:
            return [{'error': f'Ошибка поиска Reddit: {str(e)}'}]
    
    def extract_keywords(self, query):
        """Извлечение ключевых слов из запроса"""
        # Слова, которые нужно исключить
        stop_words = {
            'найди', 'найти', 'поиск', 'информация', 'информацию',
            'про', 'о', 'и', 'с', 'когда', 'как', 'что', 'там',
            'reddit', 'find', 'search', 'information', 'about', 'on', 'with'
        }
        
        # Очищаем и разбиваем на слова
        words = re.findall(r'\b\w+\b', query.lower())
        
        # Оставляем только значимые слова
        keywords = [word for word in words if len(word) > 2 and word not in stop_words]
        
        # Если не осталось ключевых слов, берем все
        if not keywords:
            keywords = [word for word in words if len(word) > 1]
        
        return keywords[:5]  # Максимум 5 ключевых слов
    
    def is_relevant(self, text, keywords):
        """Проверка релевантности текста"""
        if not keywords:
            return True
        
        text_lower = text.lower()
        matches = sum(1 for keyword in keywords if keyword in text_lower)
        
        # Считаем релевантным, если найдено хотя бы 30% ключевых слов
        return matches >= max(1, len(keywords) * 0.3)
    
    def search_general(self, query):
        """Общий поиск по разным субреддитам"""
        try:
            keywords = self.extract_keywords(query)
            search_query = ' '.join(keywords) if keywords else query
            
            print(f"🌐 Общий поиск: '{search_query}'")
            print(f"🔑 Ключевые слова: {keywords}")
            
            # Поиск в популярных субреддитах
            subreddits = ['OpenAI', 'MachineLearning', 'artificial', 'technology', 'singularity']
            all_results = []
            
            for subreddit in subreddits:
                print(f"🔍 Поиск в r/{subreddit}...")
                url = f"https://www.reddit.com/r/{subreddit}/search.json"
                params = {
                    'q': search_query,
                    'restrict_sr': 'true',
                    'limit': 5,
                    'sort': 'new',
                    't': 'month'
                }
                
                try:
                    response = self.session.get(url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        posts = data.get('data', {}).get('children', [])
                        print(f"  ℹ️ Найдено {len(posts)} постов в r/{subreddit}")
                        
                        for post in posts:
                            post_data = post.get('data', {})
                            title = post_data.get('title', '')
                            selftext = post_data.get('selftext', '')
                            
                            # Упростим проверку релевантности
                            all_results.append({
                                'title': title,
                                'subreddit': post_data.get('subreddit', ''),
                                'score': post_data.get('score', 0),
                                'url': f"https://reddit.com{post_data.get('permalink', '')}",
                                'author': post_data.get('author', ''),
                                'text': selftext[:300] if selftext else '',
                                'created': post_data.get('created_utc', 0)
                            })
                    else:
                        print(f"  ❌ Ошибка {response.status_code} для r/{subreddit}")
                except Exception as e:
                    print(f"  ❌ Исключение для r/{subreddit}: {e}")
                    continue
            
            print(f"📊 Всего найдено: {len(all_results)} результатов")
            
            # Сортируем по популярности
            all_results.sort(key=lambda x: x['score'], reverse=True)
            return all_results[:5]
            
        except Exception as e:
            return [{'error': f'Ошибка общего поиска: {str(e)}'}]
    
    def search_google(self, query):
        """Поиск в Google (отключено в experimental-версии).
        
        Причина:
        - HTML-скрейпинг результатов Google нестабилен и может нарушать условия использования.
        - Используйте WorkingWebAgent (DuckDuckGo + RSS) или внешние API (напр., SerpAPI/Tavily).
        """
        return [{'error': 'Google HTML scraping is disabled in experimental agent'}]
    
    def execute(self, task):
        """Выполнить поиск"""
        print(f"🔍 Выполняю поиск: {task}")
        
        results = []
        
        # Поиск в Reddit
        reddit_results = self.search_reddit(task)
        results.extend(reddit_results)

        # Общий поиск
        general_results = self.search_general(task)
        results.extend(general_results)

        # Поиск в Google
        google_results = self.search_google(task)
        results.extend(google_results)
        
        return {
            'agent': 'Web Research Agent',
            'task': task,
            'results': results,
            'count': len(results),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
