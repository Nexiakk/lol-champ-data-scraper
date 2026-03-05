"""
Investigation script to find where lolalytics counter data is stored.
Searches for JSON data, script tags, and data attributes.
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import os
from datetime import datetime

TEST_URL = "https://lolalytics.com/pl/lol/diana/build/?tier=d2_plus"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

def log(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")

def investigate_page():
    log("=" * 80)
    log("INVESTIGATING LOLALYTICS DATA STRUCTURE")
    log("=" * 80)
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    log(f"Fetching {TEST_URL}")
    response = session.get(TEST_URL, timeout=15)
    html = response.text
    soup = BeautifulSoup(html, 'html.parser')
    
    log(f"Page size: {len(html)} characters")
    
    # 1. Search for script tags with JSON data
    log("\n=== Searching for JSON in script tags ===")
    scripts = soup.find_all('script')
    log(f"Found {len(scripts)} script tags")
    
    json_data_found = []
    for i, script in enumerate(scripts):
        if script.string:
            # Look for JSON patterns
            if 'window.__' in script.string or 'JSON.parse' in script.string:
                log(f"  Script {i}: Contains potential data")
                # Extract first 500 chars
                preview = script.string[:500].replace('\n', ' ')
                log(f"    Preview: {preview}...")
            
            # Try to find any JSON objects
            try:
                # Look for JSON in the script
                json_matches = re.findall(r'\{[\s\S]*?\}', script.string)
                for match in json_matches[:3]:  # Limit to first 3
                    if 'win' in match.lower() or 'rate' in match.lower() or 'delta' in match.lower():
                        log(f"  Script {i}: Found potential stats JSON")
                        break
            except:
                pass
    
    # 2. Search for data attributes
    log("\n=== Searching for data attributes ===")
    elements_with_data = soup.find_all(attrs={"data": True})
    log(f"Found {len(elements_with_data)} elements with data attributes")
    
    # 3. Look for specific counter container and analyze its structure
    log("\n=== Analyzing counter container structure ===")
    counter_container = soup.find('div', class_=re.compile(r'flex h-\[146px\] mb-2 border'))
    
    if counter_container:
        log("✓ Found counter container")
        
        # Get all child divs
        all_divs = counter_container.find_all('div', recursive=True)
        log(f"  Container has {len(all_divs)} nested divs")
        
        # Look for the flex container with matchups
        flex_containers = counter_container.find_all('div', class_=re.compile(r'flex gap-\[6px\]'))
        log(f"  Found {len(flex_containers)} flex gap-[6px] containers")
        
        # Check for q: attributes (Qwik framework)
        q_elements = counter_container.find_all(attrs={"q:id": True})
        log(f"  Found {len(q_elements)} elements with q:id attributes")
        
        # Look for any text content that looks like stats
        text_content = counter_container.get_text()
        win_rate_matches = re.findall(r'\d+\.\d+%', text_content)
        log(f"  Win rate patterns found: {win_rate_matches[:10]}")
        
        # Print the actual HTML structure (first 2000 chars)
        container_html = str(counter_container)
        log(f"\n  Container HTML (first 2000 chars):")
        log(f"  {container_html[:2000]}")
    else:
        log("✗ Counter container not found")
    
    # 4. Search for all /vs/ links and their parent structure
    log("\n=== Analyzing /vs/ link structure ===")
    vs_links = soup.find_all('a', href=re.compile(r'/vs/'))
    log(f"Found {len(vs_links)} /vs/ links total")
    
    # Analyze first few links
    for i, link in enumerate(vs_links[:3]):
        log(f"\n  Link {i+1}: {link.get('href', 'N/A')}")
        
        # Get parent structure
        parent = link.find_parent()
        grandparent = parent.find_parent() if parent else None
        
        log(f"    Parent tag: {parent.name if parent else 'N/A'}")
        log(f"    Parent classes: {parent.get('class', []) if parent else 'N/A'}")
        
        if grandparent:
            log(f"    Grandparent tag: {grandparent.name}")
            log(f"    Grandparent classes: {grandparent.get('class', [])}")
        
        # Get all text in the grandparent
        if grandparent:
            texts = [t.strip() for t in grandparent.stripped_strings if t.strip()]
            log(f"    Texts in grandparent: {texts[:10]}")
    
    # 5. Look for JSON-LD or structured data
    log("\n=== Searching for structured data ===")
    jsonld_scripts = soup.find_all('script', type='application/ld+json')
    log(f"Found {len(jsonld_scripts)} JSON-LD scripts")
    
    # 6. Search for any inline data in divs with specific patterns
    log("\n=== Searching for inline stats data ===")
    
    # Look for text patterns like "52.24" followed by "%"
    stats_pattern = re.compile(r'(\d+\.\d+)%')
    matches = stats_pattern.findall(html)
    log(f"Found {len(matches)} percentage values in entire HTML")
    log(f"First 20: {matches[:20]}")
    
    # 7. Look for the specific counter section by text content
    log("\n=== Searching by text content ===")
    counter_text = soup.find(string=re.compile(r'Counter', re.I))
    if counter_text:
        parent = counter_text.find_parent('div')
        if parent:
            log(f"Found 'Counter' text in div with classes: {parent.get('class', [])}")
            # Get sibling divs
            siblings = parent.find_next_siblings()
            log(f"  Has {len(siblings)} sibling divs")
    
    # 8. Check for any template or hidden elements
    log("\n=== Searching for template/hidden elements ===")
    templates = soup.find_all(['template', 'q:template'])
    log(f"Found {len(templates)} template elements")
    
    hidden_divs = soup.find_all('div', style=re.compile(r'display:\s*none', re.I))
    log(f"Found {len(hidden_divs)} hidden divs")
    
    # Save detailed output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, f'investigation_{TIMESTAMP}.txt')
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("LOLALYTICS INVESTIGATION RESULTS\n")
        f.write("=" * 80 + "\n\n")
        
        if counter_container:
            f.write("COUNTER CONTAINER HTML:\n")
            f.write("-" * 80 + "\n")
            f.write(str(counter_container)[:10000])
            f.write("\n\n")
        
        f.write("ALL /vs/ LINKS AND THEIR PARENTS:\n")
        f.write("-" * 80 + "\n")
        for i, link in enumerate(vs_links[:20]):
            f.write(f"\n{i+1}. URL: {link.get('href', 'N/A')}\n")
            f.write(f"   HTML: {str(link)}\n")
    
    log(f"\n✓ Detailed output saved to: {output_file}")
    log("=" * 80)

if __name__ == "__main__":
    investigate_page()
