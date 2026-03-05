"""
Investigation script to examine template elements where counter data might be stored.
"""

import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime

TEST_URL = "https://lolalytics.com/pl/lol/diana/build/?tier=d2_plus"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

def log(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")

def investigate_templates():
    log("=" * 80)
    log("INVESTIGATING TEMPLATE ELEMENTS")
    log("=" * 80)
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    log(f"Fetching {TEST_URL}")
    response = session.get(TEST_URL, timeout=15)
    html = response.text
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find all template elements
    templates = soup.find_all(['template', 'q:template'])
    log(f"Found {len(templates)} template elements\n")
    
    # Analyze each template
    for i, template in enumerate(templates[:20]):  # Check first 20
        log(f"--- Template {i+1} ---")
        log(f"  Tag: {template.name}")
        log(f"  Attributes: {template.attrs}")
        
        # Get template content
        content = template.string or template.get_text()
        if content:
            content_preview = content[:200].replace('\n', ' ')
            log(f"  Content preview: {content_preview}...")
            
            # Check if it contains counter-related data
            if any(word in content.lower() for word in ['win', 'delta', 'pick', 'viego', 'khazix', 'leesin']):
                log(f"  ✓✓✓ POTENTIAL COUNTER DATA FOUND ✓✓✓")
                log(f"  Full content:\n{content[:2000]}")
        else:
            # Check nested elements
            nested = template.find_all()
            log(f"  Has {len(nested)} nested elements")
            if nested:
                for j, elem in enumerate(nested[:3]):
                    log(f"    Nested {j+1}: <{elem.name}> classes={elem.get('class', [])}")
        
        log("")
    
    # Also check script tags more thoroughly
    log("\n=== Checking script tags for data ===")
    scripts = soup.find_all('script')
    
    for i, script in enumerate(scripts):
        if script.string:
            # Look for patterns that might contain counter data
            if any(pattern in script.string for pattern in ['viego', 'khazix', 'leesin', 'winRate', 'delta']):
                log(f"\nScript {i} contains potential counter data:")
                log(f"{script.string[:500]}...")
    
    # Save all template contents to file
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(OUTPUT_DIR, f'templates_{TIMESTAMP}.txt')
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("ALL TEMPLATE ELEMENTS:\n")
        f.write("=" * 80 + "\n\n")
        
        for i, template in enumerate(templates):
            f.write(f"\n--- Template {i+1} ---\n")
            f.write(f"Tag: {template.name}\n")
            f.write(f"Attributes: {template.attrs}\n")
            f.write(f"Content:\n{template}\n")
            f.write("-" * 80 + "\n")
    
    log(f"\n✓ All templates saved to: {output_file}")
    log("=" * 80)

if __name__ == "__main__":
    investigate_templates()
