#!/usr/bin/env python3
"""
Рабочий Web Research Agent с реальным поиском
"""

import os
import requests
import json
from datetime import datetime
import time
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, List, Optional

try:
    import requests_cache  # type: ignore
except Exception:  # optional
    requests_cache = None

logger = logging.getLogger(__name__)

def _normalize_result(title: str, url: str, snippet: str = "", source: str = "Unknown", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "title": title or "Без названия",
        "url": url or "",
        "snippet": (snippet or "")[:500],
        "source": source,
        "metadata": metadata or {}
    }

class RateLimiter:
    def __init__(self, min_interval: float = 0.5):
        self.min_interval = float(min_interval)
        self._last: Dict[str, float] = {}

    def wait(self, key: str) -> None:
        now = time.time()
        last = self._last.get(key, 0.0)
        delta = now - last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last[key] = time.time()

class WorkingWebAgent:
    def __init__(self, timeout: float = 10.0, max_results: int = 5, retries: int = 2, backoff: float = 0.5, verbose: bool = False):
        self.timeout = timeout
        self.max_results = max_results

        level = logging.DEBUG if verbose else logging.INFO
        if os.environ.get("AI_STACK_JSON_LOGS", "0") == "1":
            from logging_setup import setup_json_logger
            setup_json_logger(level)
        else:
            logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

        # Caching (optional)
        if requests_cache is not None and os.environ.get("AI_STACK_HTTP_CACHE", "0") == "1":
            requests_cache.install_cache("web_cache", expire_after=int(os.environ.get("AI_STACK_HTTP_CACHE_TTL", "300")))

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # Minimal retry/backoff
        retry_cfg = Retry(
            total=retries,
            backoff_factor=backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_cfg)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        logger.debug("Session initialized with retries=%s backoff=%s timeout=%s", retries, backoff, timeout)

        # Simple rate limiter
        self.ratelimiter = RateLimiter(min_interval=float(os.environ.get("AI_STACK_RATE_INTERVAL", "0.5")))

        # Optional API keys
        self.serpapi_key = os.environ.get("SERPAPI_KEY")
        self.tavily_key = os.environ.get("TAVILY_API_KEY")
        self.reddit_client_id = os.environ.get("REDDIT_CLIENT_ID")
        self.reddit_client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    
    def search_duckduckgo(self, query: str) -> List[Dict[str, Any]]:
        """Поиск: при наличии SERPAPI_KEY используем SerpAPI; иначе DDG с fallback."""
        try:
            if self.serpapi_key:
                logger.info("SerpAPI search: %s", query)
                self.ratelimiter.wait("serpapi")
                resp = self.session.get(
                    "https://serpapi.com/search.json",
                    params={"engine": "duckduckgo", "q": query, "api_key": self.serpapi_key},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    organic = data.get("organic_results") or []
                    out: List[Dict[str, Any]] = []
                    for r in organic[: self.max_results]:
                        out.append(_normalize_result(title=r.get("title"), url=r.get("link"), snippet=r.get("snippet", ""), source="DuckDuckGo"))
                    return out
                logger.warning("SerpAPI HTTP %s", resp.status_code)
            logger.info("DDG search: %s", query)
            # 1) Получаем токен/страницу
            self.ratelimiter.wait("duckduckgo.com")
            url = "https://duckduckgo.com/"
            response = self.session.get(url, timeout=self.timeout)
            logger.debug("DDG home status=%s", response.status_code)

            # 2) Ищем vqd токен
            vqd_match = re.search(r'vqd=([0-9-]+)', response.text) or re.search(r'"vqd":"([^"]+)"', response.text)
            if not vqd_match:
                logger.warning("DDG vqd token not found, fallback to html SERP")
                # Fallback: парс HTML выдачи
                self.ratelimiter.wait("duckduckgo.com/html")
                serp = self.session.get(f"https://duckduckgo.com/html/?q={quote_plus(query)}", timeout=self.timeout)
                if serp.status_code != 200:
                    return [{'error': f'DDG HTML fallback HTTP {serp.status_code}'}]
                soup = BeautifulSoup(serp.text, 'html.parser')
                results = []
                for a in soup.select('.result__a')[: self.max_results]:
                    title = a.get_text(strip=True)
                    href = a.get('href', '')
                    # filter out internal duckduckgo redirects/ads
                    if href and href.startswith('http') and 'duckduckgo.com' not in href:
                        results.append(_normalize_result(title=title, url=href, source="DuckDuckGo"))
                logger.info("DDG HTML fallback results=%d", len(results))
                return results

            vqd = vqd_match.group(1)
            logger.debug("DDG vqd=%s", vqd)

            # 3) Выполняем поиск через d.js
            search_url = "https://links.duckduckgo.com/d.js"
            params = {
                'q': query,
                'vqd': vqd,
                'l': 'us-en',
                'p': '',
                's': '0',
                'df': '',
                'ex': '-1'
            }
            self.ratelimiter.wait("links.duckduckgo.com")
            response = self.session.get(search_url, params=params, timeout=self.timeout)
            logger.debug("DDG d.js status=%s len=%s", response.status_code, len(response.text or ""))

            if response.status_code == 200:
                text = response.text
                if text.startswith('DDG.pageLayout.load('):
                    json_str = text[len('DDG.pageLayout.load('):-2]
                    data = json.loads(json_str)
                    items = data.get('results', [])[: self.max_results]
                    results = []
                    for result in items:
                        results.append(_normalize_result(
                            title=result.get('t', 'Без названия'),
                            url=result.get('u', ''),
                            snippet=result.get('a', ''),
                            source="DuckDuckGo"
                        ))
                    logger.info("DDG results=%d", len(results))
                    return results

            logger.error("DDG d.js unexpected status=%s", response.status_code)
            return [{'error': f'DuckDuckGo HTTP {response.status_code}'}]
        except Exception as e:
            logger.exception("DDG search error: %s", e)
            return [{'error': f'Ошибка поиска DuckDuckGo: {str(e)}'}]
    
    def _reddit_bearer(self) -> Optional[str]:
        if not (self.reddit_client_id and self.reddit_client_secret):
            return None
        try:
            auth = requests.auth.HTTPBasicAuth(self.reddit_client_id, self.reddit_client_secret)  # type: ignore
            self.ratelimiter.wait("reddit_token")
            resp = self.session.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"}, auth=auth, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json().get("access_token")
        except Exception:
            return None
        return None

    def search_reddit_simple(self, query: str) -> List[Dict[str, Any]]:
        """Поиск Reddit: используем OAuth при наличии кредов, иначе публичный JSON."""
        try:
            logger.info("Reddit search: %s", query)
            bearer = self._reddit_bearer()
            headers = {"User-Agent": self.session.headers.get("User-Agent", "")}
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
                base = "https://oauth.reddit.com"
            else:
                base = "https://www.reddit.com"
            queries_to_try = [query]
            all_results: List[Dict[str, Any]] = []

            for search_query in queries_to_try:
                url = f"{base}/search.json"
                params = {
                    'q': search_query,
                    'limit': self.max_results,
                    'sort': 'new',
                    't': 'all'
                }
                try:
                    self.ratelimiter.wait("reddit")
                    resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                    logger.debug("Reddit status=%s for q='%s'", resp.status_code, search_query)
                    if resp.status_code == 200:
                        data = resp.json()
                        posts = data.get('data', {}).get('children', [])
                        logger.debug("Reddit posts=%d", len(posts))
                        for post in posts[: self.max_results]:
                            pd = post.get('data', {})
                            all_results.append(_normalize_result(
                                title=pd.get('title', ''),
                                url=f"https://reddit.com{pd.get('permalink', '')}",
                                snippet=(pd.get('selftext', '') or '')[:300],
                                source="Reddit",
                                metadata={
                                    "subreddit": pd.get('subreddit', ''),
                                    "score": pd.get('score', 0),
                                    "author": pd.get('author', '')
                                }
                            ))
                    elif resp.status_code in (429, 403):
                        logger.warning("Reddit rate/forbidden status=%s", resp.status_code)
                        continue
                except Exception as e:
                    logger.debug("Reddit attempt failed for q='%s': %s", search_query, e)
                    continue

            logger.info("Reddit results=%d", len(all_results))
            return all_results[: self.max_results]
        except Exception as e:
            logger.exception("Reddit search error: %s", e)
            return [{'error': f'Ошибка поиска Reddit: {str(e)}'}]
    
    def search_news_sites(self, query: str) -> List[Dict[str, Any]]:
        """Поиск по новостным сайтам"""
        try:
            logger.info("News search: %s", query)
            search_query = quote_plus(query)
            url = f"https://news.google.com/rss/search?q={search_query}&hl=en-US&gl=US&ceid=US:en"
            self.ratelimiter.wait("news.google.com")
            resp = self.session.get(url, timeout=self.timeout)
            logger.debug("News RSS status=%s", resp.status_code)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'xml')
                items = soup.find_all('item')[: self.max_results]
                results: List[Dict[str, Any]] = []
                for item in items:
                    title = item.find('title').text if item.find('title') else 'Без названия'
                    link = item.find('link').text if item.find('link') else ''
                    description = item.find('description').text if item.find('description') else ''
                    pub_date = item.find('pubDate').text if item.find('pubDate') else ''
                    results.append(_normalize_result(
                        title=title,
                        url=link,
                        snippet=description,
                        source="Google News",
                        metadata={"date": pub_date}
                    ))
                logger.info("News results=%d", len(results))
                return results
            logger.error("News RSS unexpected status=%s", resp.status_code)
            return []
        except Exception as e:
            logger.exception("News search error: %s", e)
            return []
    
    def execute(self, task: str) -> Dict[str, Any]:
        """Выполнить комплексный поиск"""
        logger.info("Execute task: %s", task)
        all_results: List[Dict[str, Any]] = []

        # 1) DuckDuckGo / SerpAPI
        ddg = self.search_duckduckgo(task)
        all_results.extend([r for r in ddg if 'error' not in r])

        # 2) Reddit
        red = self.search_reddit_simple(task)
        all_results.extend([r for r in red if 'error' not in r])

        # 3) News
        news = self.search_news_sites(task)
        all_results.extend([r for r in news if 'error' not in r])

        logger.info("Total results=%d", len(all_results))
        return {
            'agent': 'Working Web Research Agent',
            'task': task,
            'results': all_results,
            'count': len(all_results),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
