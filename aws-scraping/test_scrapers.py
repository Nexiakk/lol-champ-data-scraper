#!/usr/bin/env python3
"""
Local testing script for the League of Legends data scrapers.
Tests scrapers without Firebase integration and with limited champions.
"""

import json
import time
from scraper.lolalytics_wrapper import LolalyticsWrapper
from scraper.wiki_scraper import scrape_champion_abilities

def get_champion_list_local():
    """Fetch champion list from Riot Data Dragon API (local version without Firebase)"""
    import requests

    try:
        # Get latest version
        versions_url = "https://ddragon.leagueoflegends.com/api/versions.json"
        versions_response = requests.get(versions_url, timeout=10)
        versions_response.raise_for_status()
        versions = versions_response.json()
        latest_version = versions[0]

        # Get champion data
        champions_url = f"https://ddragon.leagueoflegends.com/cdn/{latest_version}/data/en_US/champion.json"
        champions_response = requests.get(champions_url, timeout=10)
        champions_response.raise_for_status()
        champions_data = champions_response.json()

        # Return sorted list of champion names
        champion_names = list(champions_data['data'].keys())
        champion_names.sort()
        return champion_names

    except Exception as e:
        print(f"Error fetching champion list from Riot API: {e}")
        # Fallback to a smaller static list for testing
        return [
            'Ahri', 'Akali', 'Ashe', 'Jinx', 'Lux', 'Miss Fortune', 'Vayne', 'Yuumi'
        ]

def test_champion_list():
    """Test fetching champion list from Riot API"""
    print("Testing champion list fetch...")

    try:
        champions = get_champion_list_local()
        print(f"✓ Successfully fetched {len(champions)} champions")
        print(f"First 10 champions: {champions[:10]}")
        return champions
    except Exception as e:
        print(f"✗ Error fetching champion list: {e}")
        return []

def test_lolalytics_scraper():
    """Test Lolalytics scraper with a few champions"""
    print("\nTesting Lolalytics scraper...")

    scraper = LolalyticsWrapper()
    try:
        data = scraper.get_champion_stats()
        print(f"✓ Successfully scraped data for {len(data)} champions")
        if data:
            # Show sample data
            sample_champion = list(data.keys())[0]
            sample_stats = data[sample_champion]
            print(f"Sample data for {sample_champion}: {sample_stats}")
        return data
    except Exception as e:
        print(f"✗ Error in Lolalytics scraper: {e}")
        return {}

def test_wiki_scraper(champions_to_test=None):
    """Test League Wiki scraper with specific champions"""
    print("\nTesting League Wiki scraper...")

    if champions_to_test is None:
        champions_to_test = ['Ahri', 'Akali', 'Ashe']

    results = {}
    for champion in champions_to_test:
        print(f"Testing {champion}...")
        try:
            abilities = scrape_champion_abilities(champion)
            if abilities:
                print(f"✓ Found {len(abilities)} abilities for {champion}")
                print(f"Sample abilities: {abilities[:2]}")
                results[champion] = abilities
            else:
                print(f"✗ No abilities found for {champion}")
                results[champion] = []

            # Rate limiting for testing
            time.sleep(1)

        except Exception as e:
            print(f"✗ Error scraping {champion}: {e}")
            results[champion] = []

    return results

def save_test_results(results, filename="test_results.json"):
    """Save test results to JSON file"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Test results saved to {filename}")

def test_lolalytics_detailed():
    """Detailed testing of Lolalytics API with different approaches"""
    print("\n🔍 Detailed Lolalytics API Testing")

    import lolalytics_api

    # Test 1: Check available lanes and ranks
    try:
        print("Available lanes:", lolalytics_api.display_lanes())
        print("Available ranks:", lolalytics_api.display_ranks())
    except Exception as e:
        print(f"Error getting lanes/ranks: {e}")

    # Test 2: Try get_tierlist with different parameters
    test_cases = [
        {"n": 5, "desc": "Basic tierlist"},
        {"n": 1, "desc": "Single champion"},
        {"n": 5, "lane": "top", "desc": "Top lane only"},
        {"n": 5, "rank": "platinum", "desc": "Platinum rank"}
    ]

    for test_case in test_cases:
        try:
            print(f"\nTesting: {test_case['desc']}")
            result = lolalytics_api.get_tierlist(**{k: v for k, v in test_case.items() if k != 'desc'})
            print(f"Success: Got {len(result)} champions")
            if result:
                first_champ = list(result.values())[0]
                print(f"Sample: {first_champ}")
        except Exception as e:
            print(f"Failed: {e}")

    # Test 3: Try get_champion_data with different formats
    champion_tests = [
        {"champion": "Aatrox", "desc": "Champion name"},
        {"champion": "266", "desc": "Champion ID (Aatrox)"},
        {"champion": "aatrox", "desc": "Lowercase name"},
        {"champion": "Aatrox", "lane": "top", "desc": "With lane"},
        {"champion": "Aatrox", "rank": "gold", "desc": "With rank"}
    ]

    for test_case in champion_tests:
        try:
            print(f"\nTesting get_champion_data: {test_case['desc']}")
            result = lolalytics_api.get_champion_data(**{k: v for k, v in test_case.items() if k != 'desc'})
            print(f"Success: Got data for {test_case['champion']}")
            print(f"Data keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
        except Exception as e:
            print(f"Failed: {e}")

def main():
    """Run all tests"""
    print("🧪 Starting League of Legends Data Scraper Tests\n")

    # Test 1: Champion list
    champions = test_champion_list()

    # Test 2: Lolalytics scraper
    lolalytics_data = test_lolalytics_scraper()

    # Test 3: Detailed Lolalytics testing
    test_lolalytics_detailed()

    # Test 4: Wiki scraper (limited champions)
    test_champions = champions[:5] if len(champions) >= 5 else ['Ahri', 'Akali', 'Ashe', 'Jinx', 'Lux']
    wiki_data = test_wiki_scraper(test_champions)

    # Compile results
    results = {
        "champion_list": {
            "count": len(champions),
            "sample": champions[:10] if champions else []
        },
        "lolalytics_data": {
            "count": len(lolalytics_data),
            "sample": dict(list(lolalytics_data.items())[:3]) if lolalytics_data else {}
        },
        "wiki_data": wiki_data
    }

    # Save results
    save_test_results(results)

    # Summary
    print("\n📊 Test Summary:")
    print(f"- Champion list: {'✓' if champions else '✗'} ({len(champions)} champions)")
    print(f"- Lolalytics scraper: {'✓' if lolalytics_data else '✗'} ({len(lolalytics_data)} champions)")
    print(f"- Wiki scraper: {'✓' if any(wiki_data.values()) else '✗'} ({sum(len(v) for v in wiki_data.values())} total abilities)")

    print("\n🎉 Testing completed!")

if __name__ == "__main__":
    main()