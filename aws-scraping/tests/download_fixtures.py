"""
Download HTML fixtures from League Wiki for testing scraper.
Run this once to save test data locally.
"""
import requests
import os
import time

# Champions to download for testing
# - Multi-form: Jayce, Elise, Nidalee, Gnar, Kayn, Samira
# - Single-form: Aatrox, Yasuo, Diana
TEST_CHAMPIONS = [
    'Jayce',      # Multi-form: Mercury Hammer / Mercury Cannon
    'Elise',      # Multi-form: Human / Spider
    'Nidalee',    # Multi-form: Human / Cougar
    'Gnar',       # Multi-form: Mini / Mega
    'Kayn',       # Multi-form: Base / Shadow Assassin / Rhaast
    'Samira',     # Passive style ratings
    'Aatrox',     # Single form
    'Yasuo',      # Single form
    'Diana',      # Single form
]

def download_fixture(champion_name):
    """Download HTML from League Wiki for a champion."""
    # Encode champion name for URL
    encoded_name = champion_name.replace(' ', '_')
    url = f"https://wiki.leagueoflegends.com/en-us/{encoded_name}"
    
    print(f"Downloading {champion_name}...")
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Save to fixtures directory
        fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', f'{champion_name.lower()}.html')
        with open(fixture_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        print(f"  ✓ Saved to fixtures/{champion_name.lower()}.html ({len(response.text)} bytes)")
        return True
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures')
    os.makedirs(fixtures_dir, exist_ok=True)
    
    print("Downloading test fixtures from League Wiki...\n")
    
    success_count = 0
    for champion in TEST_CHAMPIONS:
        if download_fixture(champion):
            success_count += 1
        time.sleep(1)  # Be nice to the server
    
    print(f"\n✓ Downloaded {success_count}/{len(TEST_CHAMPIONS)} fixtures")
    print(f"Fixtures saved to: {fixtures_dir}")

if __name__ == '__main__':
    main()
