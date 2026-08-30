import re
import requests
from urllib.parse import unquote
from logger import log

def scrape_ddg_lite(query: str, max_results: int = 4) -> str:
  log.info(f"Scraping DDG Lite for: '{query}'")
  url = "https://lite.duckduckgo.com/lite/"
  headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
  }
  data = {"q": query}
  
  try:
    r = requests.post(url, data=data, headers=headers, timeout=10)
    if r.status_code != 200:
      log.warning(f"DDG Lite returned status code {r.status_code}")
      return ""
      
    html = r.text
    # Find links: <a rel="nofollow" href="..." class='result-link'>...</a>
    links = re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]+class=['\"]result-link['\"][^>]*>(.*?)</a>", html, re.DOTALL)
    
    # Find snippets: <td class='result-snippet'>...</td>
    snippets = re.findall(r"<td class=['\"]result-snippet['\"][^>]*>(.*?)</td>", html, re.DOTALL)
    
    if not links:
      log.warning("No links parsed from DDG Lite HTML.")
      return ""
      
    results = []
    limit = min(len(links), len(snippets), max_results)
    for idx in range(limit):
      link, title = links[idx]
      snippet = snippets[idx].strip()
      
      # Clean snippet HTML
      snippet = re.sub(r"<[^>]+>", "", snippet)
      snippet = re.sub(r"\s+", " ", snippet)
      
      # Clean title HTML
      title = re.sub(r"<[^>]+>", "", title).strip()
      
      # Decode redirect links
      if "/l/?uddg=" in link:
        match = re.search(r"uddg=([^&]+)", link)
        if match:
          link = unquote(match.group(1))
      elif link.startswith("/"):
        link = "https://duckduckgo.com" + link
        
      results.append(f"Result {idx+1}:\nTitle: {title}\nURL: {link}\nSnippet: {snippet}\n")
      
    return "\n".join(results)
  except Exception as e:
    log.error(f"DDG Lite scraping failed: {e}")
    return ""

def search_wikipedia(query: str, max_results: int = 3) -> str:
  log.info(f"Attempting Wikipedia search fallback for: '{query}'")
  url = "https://en.wikipedia.org/w/api.php"
  params = {
    "action": "query",
    "format": "json",
    "list": "search",
    "srsearch": query,
    "utf8": 1,
    "formatversion": 2
  }
  try:
    r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
    if r.status_code == 200:
      data = r.json()
      search_results = data.get("query", {}).get("search", [])
      if search_results:
        formatted = []
        for idx, item in enumerate(search_results[:max_results]):
          title = item.get("title")
          snippet = item.get("snippet")
          # Clean HTML tags
          snippet = re.sub(r"<[^>]+>", "", snippet)
          link = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
          formatted.append(f"Result {idx+1} (Wikipedia):\nTitle: {title}\nURL: {link}\nSnippet: {snippet}\n")
        return "\n".join(formatted)
  except Exception as e:
    log.error(f"Wikipedia search failed: {e}")
  return ""

def search_web(query: str, max_results: int = 4) -> str:
  # 1. Try Lite Scraper
  res = scrape_ddg_lite(query, max_results)
  if res:
    return res
    
  # 2. Fallback to DDG API library
  log.info(f"Falling back to duckduckgo_search API for: '{query}'")
  try:
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
      results = [r for r in ddgs.text(query, max_results=max_results)]
      if results:
        formatted = []
        for idx, r in enumerate(results):
          title = r.get('title', 'N/A')
          link = r.get('href', 'N/A')
          body = r.get('body', 'N/A')
          formatted.append(f"Result {idx+1}:\nTitle: {title}\nURL: {link}\nSnippet: {body}\n")
        return "\n".join(formatted)
  except Exception as e:
    log.error(f"DuckDuckGo search fallback failed: {e}")
    
  # 3. Fallback to Wikipedia API
  wiki_res = search_wikipedia(query, max_results=3)
  if wiki_res:
    return wiki_res
    
  return "No web or knowledge base results found."
