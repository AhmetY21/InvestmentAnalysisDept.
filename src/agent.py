import os
import json
import httpx
import re
import random
import time
import asyncio
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel
from datetime import datetime
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pytrends.request import TrendReq

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

class NewsItem(BaseModel):
    title: str
    source: Optional[str] = None
    url: Optional[str] = None

class InvestmentResult(BaseModel):
    symbol: str
    current_price: str
    price_source: str
    market_outlook: str
    summary: str
    top_news: List[NewsItem]
    full_date: str
    trends_info: str

class InvestmentAgent:
    def __init__(self):
        self.serper_api_key = os.getenv("SERPER_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        if self.gemini_api_key:
            self.client = genai.Client(api_key=self.gemini_api_key)
        else:
            self.client = None

        self.http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self.pytrends = TrendReq(hl='en-US', tz=360)

    async def _search_serper(self, query: str) -> List[Dict[str, Any]]:
        # Fallback search if Google Finance fails
        if not self.serper_api_key:
            return []

        url = "https://google.serper.dev/search"
        payload = json.dumps({ "q": query, "num": 5 })
        headers = { 'X-API-KEY': self.serper_api_key, 'Content-Type': 'application/json' }
        
        try:
            resp = await self.http_client.post(url, headers=headers, data=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("organic", [])
        except Exception as e:
            print(f"Serper API Error: {e}")
            return []

    async def _scrape_google_finance(self, ticker: str) -> Dict[str, Any]:
        """
        Scrapes Google Finance for Price and News.
        URL: https://www.google.com/finance/quote/{ticker}?hl=en
        """
        url = f"https://www.google.com/finance/quote/{ticker}?hl=en"
        print(f"Scraping Google Finance: {url}")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            resp = await self.http_client.get(url, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            data = {
                "price": None,
                "news": []
            }
            
            # 1. Extract Price
            # Class varies, but usually: <div class="YMlKec fxKbKc">
            price_div = soup.find("div", class_="YMlKec fxKbKc")
            if price_div:
                data["price"] = price_div.get_text().strip()
            
            # 2. Extract News
            # News items are often in: <div class="yY3Lee"> containing links
            # Or simplified: look for specific Google Finance news structure
            # Let's try to find the 'News' section. 
            # Often inside <div class="v5kQ8e"> or similar containers.
            # Robust strategy: Find all links that look like news (external or internal with titles)
            
            # Google Finance News usually has a specific structure.
            # We look for the main news container or just parse typical news cards.
            # Classes: Yfwt5 (title), sfyJob (source) - might change.
            # Let's target the structure seen in previous steps or general density.
            
            # Search for the "News" header maybe?
            # Let's grab specific div containers that hold news items.
            # Based on standard Google Finance layout:
            news_items = soup.find_all("div", class_="Yfwt5") # Title class often
            
            if not news_items:
               # Fallback: finding elements with large text inside common containers
               # Attempt generic extraction if class names change
               pass

            # Since classes are obfuscated/dynamic, we might rely on text density or siblings of "News".
            # However, simpler: find the section titled "News" or similar.
            
            # Let's try a broader search for links with news-like attributes
            # Or iterate over main content area.
            
            # RE-STRATEGY based on known google finance html classes (often):
            # Price: YMlKec fxKbKc (Confirmed in many scraps)
            # News Title: Yfwt5
            # News Source: sfyJob
            
            found_news = []
            
            # Attempt 1: Specific Classes
            articles = soup.find_all("div", class_="yY3Lee") # Container for news item
            for article in articles:
                if len(found_news) >= 5: break
                
                title_div = article.find("div", class_="Yfwt5")
                source_div = article.find("div", class_="sfyJob")
                link_a = article.find("a", href=True) # The container itself might be a link or contain one
                
                # Sometimes the structure is deep.
                # Let's try finding 'a' tags directly that have news context.
                pass
            
            # Attempt 2: Finding by text "News" and siblings? No, hard in Soup.
            
            # Attempt 3: Just grab all reasonable links in the "latest news" area
            # Often <div id="news-main"> or similar? No.
            
            # Let's try the classes observed in common scraps:
            # News Container: .yY3Lee
            # Title: .Yfwt5
            # Source: .sfyJob
            
            potential_news = soup.select('.yY3Lee')
            for item in potential_news:
                try:
                    title_el = item.select_one('.Yfwt5')
                    source_el = item.select_one('.sfyJob')
                    link_el = item.find('a', href=True) or item.find_parent('a', href=True)
                    
                    if title_el and link_el:
                         found_news.append({
                             "title": title_el.get_text().strip(),
                             "source": source_el.get_text().strip() if source_el else "Unknown",
                             "url": link_el['href']
                         })
                except: continue
            
            data["news"] = found_news[:5]
            return data

        except Exception as e:
            print(f"Google Finance Scrape Error: {e}")
            return {"price": None, "news": []}

    async def _get_trends_data(self, keyword: str) -> str:
        # 1. Try PyTrends
        for attempt in range(2):
            try:
                self.pytrends.build_payload([keyword], timeframe='now 7-d')
                df = self.pytrends.interest_over_time()
                if df.empty: return "Google Trends: No data."
                
                # Simple analysis
                slope = df[keyword][-1] - df[keyword][0]
                trend = "Rising" if slope > 5 else "Falling" if slope < -5 else "Stable"
                return f"Google Trends: {trend} (7-day change)"
            except Exception as e:
                if "429" in str(e): time.sleep(2)
                else: break
        
        # 2. Fallback Serper
        fallback_query = f"{keyword} investment market trend analysis"
        results = await self._search_serper(fallback_query)
        if not results: return "Trends: Unavailable"
        snippets = [r.get('snippet', '') for r in results[:2]]
        return f"Trend Context via Search: {' '.join(snippets)}"

    async def analyze_investment(self, investment_name: str, ticker_id: str = None) -> Optional[InvestmentResult]:
        print(f"Analyzing {investment_name} ({ticker_id})...")
        
        google_data = {"price": None, "news": []}
        
        # 1. Scrape Google Finance
        if ticker_id:
            google_data = await self._scrape_google_finance(ticker_id)
        
        current_price = google_data.get("price")
        price_source = "Google Finance" if current_price else "Serper/Unknown"
        
        news_items = [NewsItem(title=n['title'], source=n['source'], url=n['url']) for n in google_data.get("news", [])]
        
        # 2. Fallback Price/News if Google Finance failed
        serper_results = []
        if not current_price or not news_items:
            print("Google Finance data incomplete. Using Serper fallback.")
            serper_results = await self._search_serper(f"{investment_name} investment news price")
            
            # Fallback Price
            if not current_price and serper_results:
                 # Try to extract from first snippet
                 # Very rudimentary extraction
                 pass 
            
            # Fallback News
            if not news_items:
                for r in serper_results[:5]:
                    news_items.append(NewsItem(title=r['title'], source=r['source'], url=r['link']))
        
        # 3. Trends
        trends_info = await self._get_trends_data(investment_name)

        # 4. LLM Summary
        if not self.client:
             return InvestmentResult(
                symbol=investment_name,
                current_price=current_price or "Unknown",
                price_source=price_source,
                market_outlook="Unknown",
                summary="No LLM Key.",
                top_news=news_items,
                full_date=datetime.now().strftime("%Y-%m-%d"),
                trends_info=trends_info
            )
            
        # Compose Context
        # We only pass titles and sources to the LLM, plus extracted price and trends
        context_text = f"Investment: {investment_name}\n"
        context_text += f"Current Price: {current_price}\n"
        context_text += f"Trends Info: {trends_info}\n"
        context_text += "Latest News Headlines:\n"
        for n in news_items:
            context_text += f"- {n.title} (Source: {n.source})\n"
            
        prompt = f"""
        You are an elite Investment Analyst. 
        Based ONLY on the provided verified data below, write an Executive Summary and determine the Market Outlook.
        
        Data:
        {context_text}
        
        Tasks:
        1. Market Outlook (Bullish/Bearish/Neutral) - base on price trend or news sentiment.
        2. Executive Summary - 2-3 sentences summarizing the situation. Do not halluciation facts not in headlines.

        Return JSON:
        {{
            "market_outlook": "...",
            "summary": "..."
        }}
        """

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            data = json.loads(response.text)
            
            return InvestmentResult(
                symbol=investment_name,
                current_price=current_price or "Unknown",
                price_source=price_source,
                market_outlook=data.get("market_outlook", "Neutral"),
                summary=data.get("summary", "No summary."),
                top_news=news_items, # Verified links
                full_date=datetime.now().strftime("%Y-%m-%d"),
                trends_info=trends_info
            )
            
        except Exception as e:
            print(f"Gemini Error: {e}")
            return None
