import re

import requests

WIKI_API = "https://blox-fruits.fandom.com/api.php"
PAGE_TITLE = 'Blox Fruits "Stock"'


def get_fruit_image_urls(fruit_names: list[str]) -> dict[str, str]:
    """Batch-fetch wiki image URLs for the given fruit names. Returns {name: url}."""
    if not fruit_names:
        return {}
    titles = "|".join(f"File:{name}_Fruit.png" for name in fruit_names)
    response = requests.get(
        WIKI_API,
        params={
            "action": "query",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json",
        },
        timeout=10,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})

    result: dict[str, str] = {}
    for page in pages.values():
        if page.get("ns") != 6 or "imageinfo" not in page:
            continue
        # MediaWiki normalizes underscores to spaces in titles
        title: str = page.get("title", "").replace(" ", "_")  # e.g. "File:Blade_Fruit.png"
        if title.startswith("File:") and title.endswith("_Fruit.png"):
            name = title[5:-10]                      # strip "File:" and "_Fruit.png"
            result[name] = page["imageinfo"][0]["url"]
    return result


def fetch_stock() -> dict[str, list[str]]:
    """Fetch the Blox Fruits stock page via MediaWiki API and return parsed stock data."""
    response = requests.get(
        WIKI_API,
        params={
            "action": "parse",
            "page": PAGE_TITLE,
            "prop": "wikitext",
            "format": "json",
        },
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()
    wikitext: str = data["parse"]["wikitext"]["*"]

    stock_main_match = re.search(
        r"\{\{Stock/Main(.*?)\}\}", wikitext, re.DOTALL | re.IGNORECASE
    )
    if not stock_main_match:
        raise ValueError("Template {{Stock/Main}} not found in page wikitext.")

    template_body = stock_main_match.group(1)

    result: dict[str, list[str]] = {}
    for param_match in re.finditer(r"\|\s*(\w+)\s*=\s*([^\|]+)", template_body):
        key = param_match.group(1).strip()
        raw_value = param_match.group(2).strip()
        fruits = [f.strip() for f in raw_value.split(",") if f.strip()]
        result[key] = fruits

    return result
