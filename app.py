import os
import re
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

FEED_URL = "https://docs.cloud.google.com/feeds/bigquery-release-notes.xml"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")


def strip_html_tags(html_str):
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r'<[^>]+>', '', html_str)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_release_notes():
    """Fetch the Atom feed from Google, parse entries into structured dicts."""
    try:
        req = urllib.request.Request(
            FEED_URL,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                )
            }
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        parsed_entries = []

        for entry in root.findall('atom:entry', ns):
            title_elem = entry.find('atom:title', ns)
            date_str = title_elem.text.strip() if title_elem is not None and title_elem.text else "Unknown"
            updated_elem = entry.find('atom:updated', ns)
            updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""

            link_elem = entry.find("atom:link[@rel='alternate']", ns)
            link = link_elem.attrib.get('href', '') if link_elem is not None else ""
            if not link and date_str:
                anchor_id = date_str.replace(" ", "_").replace(",", "")
                link = f"https://docs.cloud.google.com/bigquery/docs/release-notes#{anchor_id}"

            content_elem = entry.find('atom:content', ns)
            content_html = content_elem.text if content_elem is not None and content_elem.text else ""

            # Split content by <h3> headings into sections
            pattern = re.compile(
                r'<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|$)', re.DOTALL | re.IGNORECASE
            )
            matches = pattern.findall(content_html)

            sections = []
            if matches:
                for idx, (category, body) in enumerate(matches):
                    category_clean = strip_html_tags(category.strip())
                    body_clean = body.strip()
                    plain_text = strip_html_tags(body_clean)
                    sections.append({
                        "id": f"{date_str.replace(' ', '_').replace(',', '')}_{idx}",
                        "category": category_clean,
                        "body_html": body_clean,
                        "plain_text": plain_text,
                    })
            else:
                plain_text = strip_html_tags(content_html)
                sections.append({
                    "id": f"{date_str.replace(' ', '_').replace(',', '')}_0",
                    "category": "Update",
                    "body_html": content_html.strip(),
                    "plain_text": plain_text,
                })

            parsed_entries.append({
                "date": date_str,
                "updated": updated,
                "link": link,
                "sections": sections,
            })

        # Write to local cache
        with open(CACHE_FILE, 'w') as f:
            json.dump(parsed_entries, f, indent=2)

        return parsed_entries, None

    except Exception as e:
        print(f"Error fetching/parsing feed: {e}")
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    cached_data = json.load(f)
                return cached_data, f"Offline mode — using cached data (Error: {e})"
            except Exception as cache_err:
                return [], f"Cache unreadable: {cache_err}"
        return [], f"Feed unavailable and no cache: {e}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/release-notes')
def get_release_notes():
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'

    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
            return jsonify({"success": True, "data": data, "source": "cache"})
        except Exception:
            pass  # fall through to live fetch

    data, error = parse_release_notes()
    if error and not data:
        return jsonify({"success": False, "error": error}), 500

    return jsonify({
        "success": True,
        "data": data,
        "source": "live",
        "warning": error,
    })


@app.route('/api/tweet-url')
def tweet_url():
    """Build a Twitter/X intent URL for a given text + optional URL."""
    text = request.args.get('text', '')
    url = request.args.get('url', '')
    hashtags = request.args.get('hashtags', 'BigQuery,GoogleCloud')

    params = {'text': text}
    if url:
        params['url'] = url
    if hashtags:
        params['hashtags'] = hashtags

    intent = "https://twitter.com/intent/tweet?" + urllib.parse.urlencode(params)
    return jsonify({"intent_url": intent})


if __name__ == '__main__':
    if not os.path.exists(CACHE_FILE):
        print("Pre-fetching release notes on startup …")
        parse_release_notes()
    app.run(debug=True, host='0.0.0.0', port=5001)
