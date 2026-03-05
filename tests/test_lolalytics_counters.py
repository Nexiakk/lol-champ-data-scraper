"""
Test script for scraping lolalytics counter matchup data.
Fetches Diana build page and extracts counter matchup information.
"""

import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime

# Configuration
TEST_URL = "https://lolalytics.com/pl/lol/diana/build/?tier=d2_plus"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

class LolalyticsCounterTest:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.logs = []
        self.html_content = ""
        self.extracted_data = {}

    def log(self, message):
        """Log a message with timestamp"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        print(log_entry)

    def fetch_page(self):
        """Fetch the Diana build page"""
        self.log(f"Fetching URL: {TEST_URL}")
        try:
            response = self.session.get(TEST_URL, timeout=15)
            response.raise_for_status()
            self.html_content = response.text
            self.log(f"Successfully fetched page. Status: {response.status_code}")
            self.log(f"Content length: {len(self.html_content)} characters")
            return True
        except Exception as e:
            self.log(f"ERROR fetching page: {e}")
            return False

    def find_counter_container(self, soup):
        """Find the counter matchups container"""
        self.log("\n=== Searching for counter matchups container ===")

        # Try to find by the specific class pattern from the HTML element provided
        # The container has class: flex h-[146px] mb-2 border border-[#333333] bg-gradient-to-r...
        counter_container = soup.find('div', class_=re.compile(r'flex h-\[146px\] mb-2 border'))

        if counter_container:
            self.log("✓ Found counter container by class pattern (flex h-[146px] mb-2 border)")
            return counter_container

        # Fallback: Look for any div with bg-gradient-to-r and border-[#333333]
        counter_container = soup.find('div', class_=re.compile(r'bg-gradient-to-r.*border-\[#333333\]'))
        if counter_container:
            self.log("✓ Found counter container by gradient/border pattern")
            return counter_container

        # Another fallback: Look for containers with counter-related content
        self.log("⚠ Primary patterns not found, trying alternative selectors...")

        # Look for containers containing "Counter" text
        counter_divs = soup.find_all('div', string=re.compile(r'Counter', re.I))
        for div in counter_divs:
            parent = div.find_parent('div', class_=re.compile(r'flex.*border'))
            if parent:
                self.log(f"✓ Found counter container via 'Counter' text (parent of: {div.get_text(strip=True)[:50]})")
                return parent

        # Look for the specific structure with "Win Rate" and "Delta" labels
        win_rate_divs = soup.find_all('div', string=re.compile(r'Win Rate', re.I))
        for div in win_rate_divs:
            parent = div.find_parent('div', class_=re.compile(r'flex'))
            if parent:
                # Check if it also contains Delta
                if parent.find(string=re.compile(r'Delta', re.I)):
                    self.log("✓ Found counter container via Win Rate + Delta pattern")
                    return parent

        self.log("✗ Could not find counter container with any pattern")
        return None

    def extract_counter_data(self, container):
        """Extract counter matchup data from the container"""
        self.log("\n=== Extracting counter matchup data ===")

        data = {
            'headers': [],
            'matchups': []
        }

        if not container:
            self.log("No container provided for extraction")
            return data

        # Extract header labels (Win Rate, Delta 1, Delta 2, Pick Rate, Games)
        header_divs = container.find_all('div', class_=re.compile(r'text-(green-500|\[#[a-f0-9]+\])'))
        for header in header_divs:
            text = header.get_text(strip=True)
            if text and text not in data['headers']:
                data['headers'].append(text)
                self.log(f"  Found header: {text}")

        # Also look for headers in the left sidebar
        sidebar = container.find('div', class_=re.compile(r'w-\[80px\]'))
        if sidebar:
            sidebar_texts = [t.strip() for t in sidebar.stripped_strings]
            self.log(f"  Sidebar labels: {sidebar_texts}")

        # Extract matchup entries - look for the scrollable section
        scrollable_div = container.find('div', class_=re.compile(r'cursor-grab|overflow-x-scroll'))
        if scrollable_div:
            self.log("✓ Found scrollable matchups container")

            # Find all matchup divs (each champion entry)
            # Each matchup is typically in a <div> containing an <a> tag with /vs/ in href
            matchup_links = scrollable_div.find_all('a', href=re.compile(r'/vs/'))
            self.log(f"  Found {len(matchup_links)} matchup links")

            for link in matchup_links:
                matchup = self.parse_matchup_entry(link)
                if matchup:
                    data['matchups'].append(matchup)
        else:
            # Fallback: search entire container for matchup links
            matchup_links = container.find_all('a', href=re.compile(r'/vs/'))
            self.log(f"  Found {len(matchup_links)} matchup links (container-wide search)")

            for link in matchup_links:
                matchup = self.parse_matchup_entry(link)
                if matchup:
                    data['matchups'].append(matchup)

        self.log(f"\n✓ Extracted {len(data['matchups'])} matchups from container")
        return data

    def parse_matchup_entry(self, link):
        """Parse a single matchup entry from an anchor tag"""
        matchup = {}

        # Extract champion name from URL
        href = link.get('href', '')
        match = re.search(r'/vs/([^/]+)/', href)
        if match:
            champ_name = match.group(1).replace('-', ' ').title()
            matchup['champion'] = champ_name
        else:
            # Try to get from alt text of image
            img = link.find('img')
            if img:
                matchup['champion'] = img.get('alt', 'Unknown')
            else:
                return None

        # Get all text content from the link's parent or siblings
        parent = link.find_parent('div')
        if parent:
            # Find all divs with numeric values
            value_divs = parent.find_all('div', class_=re.compile(r'my-1'))

            values = []
            for div in value_divs:
                text = div.get_text(strip=True)
                if text:
                    values.append(text)

            # Assign values based on position (Win Rate, Delta 1, Delta 2, Pick Rate, Games)
            if len(values) >= 1:
                matchup['win_rate'] = values[0]
            if len(values) >= 2:
                matchup['delta_1'] = values[1]
            if len(values) >= 3:
                matchup['delta_2'] = values[2]
            if len(values) >= 4:
                matchup['pick_rate'] = values[3]
            if len(values) >= 5:
                matchup['games'] = values[4]

        return matchup if matchup.get('champion') else None

    def extract_all_page_counters(self, soup):
        """Extract all counter matchups from the entire page"""
        matchups = []
        
        # Find all links with /vs/ pattern
        vs_links = soup.find_all('a', href=re.compile(r'/vs/'))
        self.log(f"Searching entire page - Found {len(vs_links)} /vs/ links")
        
        # Process each unique champion matchup
        seen_champions = set()
        for link in vs_links:
            href = link.get('href', '')
            match = re.search(r'/vs/([^/]+)/', href)
            if match:
                champ_name = match.group(1)
                if champ_name not in seen_champions:
                    seen_champions.add(champ_name)
                    matchup = self.parse_matchup_from_page(link, href)
                    if matchup:
                        matchups.append(matchup)
        
        self.log(f"Extracted {len(matchups)} unique matchups from page")
        return matchups

    def parse_matchup_from_page(self, link, href):
        """Parse a matchup entry from a link found anywhere on the page"""
        matchup = {}
        
        # Extract champion name from URL
        match = re.search(r'/vs/([^/]+)/', href)
        if match:
            champ_name = match.group(1).replace('-', ' ').title()
            matchup['champion'] = champ_name
        else:
            return None
        
        # Find the parent container that holds all the matchup data
        # Look for a parent div that contains this link and has sibling divs with stats
        parent_div = link.find_parent('div')
        grandparent_div = parent_div.find_parent('div') if parent_div else None
        
        # Try to find stats in the same container as the link
        if grandparent_div:
            # Look for divs that contain numeric values
            all_divs = grandparent_div.find_all('div', recursive=True)
            
            values = []
            for div in all_divs:
                text = div.get_text(strip=True)
                # Match patterns like "52.24", "-2.49", "1,386", "8.32%"
                if re.match(r'^-?\d+\.?\d*%?$', text) or re.match(r'^\d{1,3},\d{3}$', text):
                    if text not in values and len(values) < 10:  # Limit to avoid duplicates
                        values.append(text)
            
            # The expected order from the HTML is: Win Rate, Delta 1, Delta 2, Pick Rate, Games
            if len(values) >= 5:
                matchup['win_rate'] = values[0]
                matchup['delta_1'] = values[1]
                matchup['delta_2'] = values[2]
                matchup['pick_rate'] = values[3]
                matchup['games'] = values[4]
            elif len(values) >= 1:
                matchup['win_rate'] = values[0]
        
        return matchup

    def analyze_html_structure(self, soup):
        """Analyze and log the HTML structure for debugging"""
        self.log("\n=== HTML Structure Analysis ===")

        # Find all flex containers with border
        flex_containers = soup.find_all('div', class_=re.compile(r'flex.*border'))
        self.log(f"Total flex containers with border: {len(flex_containers)}")

        # Find all containers with bg-gradient
        gradient_containers = soup.find_all('div', class_=re.compile(r'bg-gradient'))
        self.log(f"Total gradient containers: {len(gradient_containers)}")

        # Find all matchup links
        vs_links = soup.find_all('a', href=re.compile(r'/vs/'))
        self.log(f"Total /vs/ links: {len(vs_links)}")

        # Sample some class names for debugging
        if flex_containers:
            sample = flex_containers[0]
            self.log(f"\nSample flex container classes: {sample.get('class', [])}")

    def save_output(self):
        """Save logs and HTML content to file"""
        # Create output directory if it doesn't exist
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Generate filename
        filename = f"lolalytics_diana_test_{TIMESTAMP}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)

        self.log(f"\n=== Saving output to {filepath} ===")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("LOLALYTICS DIANA COUNTER SCRAPER TEST\n")
            f.write(f"URL: {TEST_URL}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")

            # Write logs
            f.write("LOGS:\n")
            f.write("-" * 80 + "\n")
            for log in self.logs:
                f.write(log + "\n")

            # Write extracted data
            f.write("\n" + "=" * 80 + "\n")
            f.write("EXTRACTED DATA:\n")
            f.write("-" * 80 + "\n")

            if self.extracted_data.get('headers'):
                f.write(f"\nHeaders found: {self.extracted_data['headers']}\n")

            if self.extracted_data.get('matchups'):
                f.write(f"\nMatchups ({len(self.extracted_data['matchups'])} found):\n")
                for i, matchup in enumerate(self.extracted_data['matchups'], 1):
                    f.write(f"\n{i}. {matchup.get('champion', 'Unknown')}\n")
                    f.write(f"   Win Rate: {matchup.get('win_rate', 'N/A')}\n")
                    f.write(f"   Delta 1: {matchup.get('delta_1', 'N/A')}\n")
                    f.write(f"   Delta 2: {matchup.get('delta_2', 'N/A')}\n")
                    f.write(f"   Pick Rate: {matchup.get('pick_rate', 'N/A')}\n")
                    f.write(f"   Games: {matchup.get('games', 'N/A')}\n")
            else:
                f.write("\nNo matchups extracted.\n")

            # Write HTML content (truncated if too large)
            f.write("\n" + "=" * 80 + "\n")
            f.write("HTML CONTENT (first 50000 chars):\n")
            f.write("-" * 80 + "\n")
            f.write(self.html_content[:50000])
            if len(self.html_content) > 50000:
                f.write(f"\n\n... [truncated, total length: {len(self.html_content)} chars] ...\n")

        self.log(f"✓ Output saved to: {filepath}")
        return filepath

    def run(self):
        """Run the full test"""
        self.log("=" * 80)
        self.log("STARTING LOLALYTICS COUNTER SCRAPER TEST")
        self.log("=" * 80)

        # Step 1: Fetch the page
        if not self.fetch_page():
            self.log("Failed to fetch page. Aborting.")
            self.save_output()
            return

        # Step 2: Parse HTML
        soup = BeautifulSoup(self.html_content, 'html.parser')
        self.log("✓ HTML parsed with BeautifulSoup")

        # Step 3: Analyze structure
        self.analyze_html_structure(soup)

        # Step 4: Find counter container
        counter_container = self.find_counter_container(soup)

        # Step 5: Extract data
        if counter_container:
            self.extracted_data = self.extract_counter_data(counter_container)
        
        # If no matchups found in container, search entire page
        if not self.extracted_data.get('matchups'):
            self.log("\n⚠ No matchups in container. Searching entire page for counter matchups...")
            self.extracted_data['matchups'] = self.extract_all_page_counters(soup)

        # Step 6: Save output
        output_path = self.save_output()

        self.log("\n" + "=" * 80)
        self.log("TEST COMPLETED")
        self.log(f"Output file: {output_path}")
        self.log("=" * 80)

        return self.extracted_data


def main():
    """Main entry point"""
    tester = LolalyticsCounterTest()
    return tester.run()


if __name__ == "__main__":
    main()
