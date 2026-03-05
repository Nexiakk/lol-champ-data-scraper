import requests
from bs4 import BeautifulSoup
import json
import re
import time
from typing import Dict, List, Optional

from .utils import get_internal_key_from_lolalytics

def encode_champion_name_for_lolalytics(display_name):
    """Encode champion name for Lolalytics URL format (simplified, no special chars/spaces)"""
    # Convert to lowercase
    encoded = display_name.lower()

    # Remove apostrophes, quotes, and other special characters
    encoded = re.sub(r"['\"]", '', encoded)

    # Replace spaces with nothing (remove spaces)
    encoded = encoded.replace(' ', '')

    # Handle roman numerals (IV -> iv, etc.)
    # But keep them as is since they're already lowercase
    
    # Hard-coded edge case: Monkey King is "wukong" on lolalytics
    if encoded == 'monkeyking':
        return 'wukong'

    return encoded

class LolalyticsBuildScraper:
    def __init__(self):
        self.base_url = "https://lolalytics.com"
        self.session = requests.Session()
        # Add headers to look more like a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def get_champion_roles(self, champion: str, tier: str = "d2_plus", patch: str = None) -> List[str]:
        """Get roles with playrate >= 9% from main champion page"""
        base_url = f"{self.base_url}/pl/lol/{champion}/build/"
        params = []
        params.append(f"tier={tier}")
        if patch:
            params.append(f"patch={patch}")
        url = base_url + "?" + "&".join(params)
        print(f"Fetching roles from: {url}")

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find the roles container
            roles_container = soup.find('div', class_='flex h-[51px] w-[197px] gap-[3px] pt-[3px]')
            if not roles_container:
                print("Could not find roles container")
                return []

            valid_roles = []
            role_links = roles_container.find_all('a', href=True)

            for link in role_links:
                # Extract percentage
                percentage_div = link.find('div', class_='mt-[8px] text-center text-[9px]')
                if percentage_div:
                    percentage_text = percentage_div.get_text().strip()
                    # Remove % and convert to float
                    try:
                        percentage = float(percentage_text.rstrip('%'))
                        if percentage >= 9.0:  # Only collect roles with ≥9% pickrate
                            # Extract role from href
                            href = link['href']
                            role_match = re.search(r'/build/\?lane=([^&]+)', href)
                            if role_match:
                                role = role_match.group(1)
                            else:
                                # No lane parameter = main role, determine what role it actually is
                                role = self.determine_main_role_from_url(champion, href, tier, patch)
                            valid_roles.append((role, href))  # Store both role and URL
                    except ValueError:
                        continue

            return valid_roles

        except Exception as e:
            print(f"Error getting roles for {champion}: {e}")
            return []

    def get_role_stats(self, champion: str, role: str, tier: str = "d2_plus", patch: str = None) -> Dict:
        """Get win rate, pick rate, tier, rank, ban rate, games for a specific role"""
        base_url = f"{self.base_url}/pl/lol/{champion}/build/"
        params = []
        if patch:
            params.append(f"lane={role}")
            params.append(f"tier={tier}")
            params.append(f"patch={patch}")
        else:
            params.append(f"lane={role}")
            params.append(f"tier={tier}")
        url = base_url + "?" + "&".join(params)
        print(f"Fetching stats for {champion} {role}: {url}")

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            stats = {}

            # First stats section: Win Rate and Pick Rate
            first_stats = soup.find('div', class_='flex justify-around border border-[#333333] p-2 text-center')
            if first_stats:
                stat_divs = first_stats.find_all('div', recursive=False)
                if len(stat_divs) >= 2:
                    # Win Rate (first div, index 0)
                    win_rate_div = stat_divs[0]
                    win_rate_text = win_rate_div.find('div', class_='mb-1 font-bold')
                    if win_rate_text:
                        stats['win_rate'] = float(win_rate_text.get_text().strip().rstrip('%'))

                    # Pick Rate (second div, index 1)
                    pick_rate_div = stat_divs[1]
                    pick_rate_text = pick_rate_div.find('div', class_='mb-1 font-bold')
                    if pick_rate_text:
                        stats['pick_rate'] = float(pick_rate_text.get_text().strip().rstrip('%'))

            # Second stats section: Tier, Rank, Ban Rate, Games
            second_stats = soup.find('div', class_='mt-2 flex justify-around border border-[#333333] p-2 text-center')
            if second_stats:
                stat_divs = second_stats.find_all('div', recursive=False)
                if len(stat_divs) >= 4:
                    # Tier
                    tier_div = stat_divs[0]
                    tier_text = tier_div.find('div', class_='mb-1 font-bold')
                    if tier_text:
                        stats['tier'] = tier_text.get_text().strip()

                    # Rank
                    rank_div = stat_divs[1]
                    rank_text = rank_div.find('div', class_='mb-1 font-bold')
                    if rank_text:
                        stats['rank'] = rank_text.get_text().strip()

                    # Ban Rate
                    ban_rate_div = stat_divs[2]
                    ban_rate_text = ban_rate_div.find('div', class_='mb-1 font-bold')
                    if ban_rate_text:
                        stats['ban_rate'] = float(ban_rate_text.get_text().strip().rstrip('%'))

                    # Games
                    games_div = stat_divs[3]
                    games_text = games_div.find('div', class_='mb-1 font-bold')
                    if games_text:
                        games_str = games_text.get_text().strip().replace(',', '')
                        stats['games'] = int(games_str)

            return stats

        except Exception as e:
            print(f"Error getting stats for {champion} {role}: {e}")
            return {}

    def get_role_stats_from_url(self, champion: str, role_url: str, tier: str = "d2_plus", patch: str = None) -> Dict:
        """Get stats from a specific URL (for main role detection)"""
        # Ensure we have a full URL
        if role_url.startswith('/'):
            role_url = self.base_url + role_url
        print(f"Fetching stats from URL: {role_url}")

        try:
            response = self.session.get(role_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            stats = {}

            # First stats section: Win Rate and Pick Rate
            first_stats = soup.find('div', class_='flex justify-around border border-[#333333] p-2 text-center')
            if first_stats:
                stat_divs = first_stats.find_all('div', recursive=False)
                if len(stat_divs) >= 2:
                    # Win Rate (first div, index 0)
                    win_rate_div = stat_divs[0]
                    win_rate_text = win_rate_div.find('div', class_='mb-1 font-bold')
                    if win_rate_text:
                        stats['win_rate'] = float(win_rate_text.get_text().strip().rstrip('%'))

                    # Pick Rate (second div, index 1)
                    pick_rate_div = stat_divs[1]
                    pick_rate_text = pick_rate_div.find('div', class_='mb-1 font-bold')
                    if pick_rate_text:
                        stats['pick_rate'] = float(pick_rate_text.get_text().strip().rstrip('%'))

            # Second stats section: Tier, Rank, Ban Rate, Games
            second_stats = soup.find('div', class_='mt-2 flex justify-around border border-[#333333] p-2 text-center')
            if second_stats:
                stat_divs = second_stats.find_all('div', recursive=False)
                if len(stat_divs) >= 4:
                    # Tier
                    tier_div = stat_divs[0]
                    tier_text = tier_div.find('div', class_='mb-1 font-bold')
                    if tier_text:
                        stats['tier'] = tier_text.get_text().strip()

                    # Rank
                    rank_div = stat_divs[1]
                    rank_text = rank_div.find('div', class_='mb-1 font-bold')
                    if rank_text:
                        stats['rank'] = rank_text.get_text().strip()

                    # Ban Rate
                    ban_rate_div = stat_divs[2]
                    ban_rate_text = ban_rate_div.find('div', class_='mb-1 font-bold')
                    if ban_rate_text:
                        stats['ban_rate'] = float(ban_rate_text.get_text().strip().rstrip('%'))

                    # Games
                    games_div = stat_divs[3]
                    games_text = games_div.find('div', class_='mb-1 font-bold')
                    if games_text:
                        games_str = games_text.get_text().strip().replace(',', '')
                        stats['games'] = int(games_str)

            return stats

        except Exception as e:
            print(f"Error getting stats from URL {role_url}: {e}")
            return {}

    def determine_main_role_from_url(self, champion: str, role_url: str, tier: str = "d2_plus", patch: str = None) -> str:
        """Determine what role the main URL actually represents"""
        # Ensure we have a full URL
        if role_url.startswith('/'):
            full_url = self.base_url + role_url
        else:
            full_url = role_url

        try:
            response = self.session.get(full_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for the active/selected role indicator
            # Try to find the currently active role tab or button
            active_role_elements = soup.find_all(['a', 'button', 'div'], class_=re.compile(r'active|selected|current'))

            for element in active_role_elements:
                # Check if this element contains role information
                text = element.get_text().strip().lower()
                if any(role in text for role in ['top', 'jungle', 'mid', 'middle', 'adc', 'bottom', 'support']):
                    if 'top' in text:
                        return 'top'
                    elif 'jungle' in text:
                        return 'jungle'
                    elif 'mid' in text or 'middle' in text:
                        return 'middle'
                    elif 'adc' in text or 'bottom' in text:
                        return 'bottom'
                    elif 'support' in text:
                        return 'support'

            # Fallback: Check the page title for role information
            title = soup.title.get_text() if soup.title else ""
            title_lower = title.lower()

            if 'top' in title_lower:
                return 'top'
            elif 'jungle' in title_lower:
                return 'jungle'
            elif 'mid' in title_lower or 'middle' in title_lower:
                return 'middle'
            elif 'adc' in title_lower or 'bottom' in title_lower:
                return 'bottom'
            elif 'support' in title_lower:
                return 'support'

            # Last resort: check URL parameters that might indicate the role
            if 'lane=' in full_url:
                lane_match = re.search(r'lane=([^&]+)', full_url)
                if lane_match:
                    return lane_match.group(1)

            # If all else fails, assume top (most common default)
            print(f"Could not determine main role for {champion}, defaulting to 'top'")
            return 'top'

        except Exception as e:
            print(f"Error determining main role from URL {full_url}: {e}")
            return 'top'  # Safe default

    def get_counter_matchups(self, champion: str, role: str, tier: str = "d2_plus", patch: str = None) -> List[Dict]:
        """Get counter matchups for a specific role - optimized HTML parsing only"""
        base_url = f"{self.base_url}/pl/lol/{champion}/counters/"
        params = []
        params.append(f"lane={role}")
        params.append(f"tier={tier}")
        if patch:
            params.append(f"patch={patch}")
        url = base_url + "?" + "&".join(params)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            counters = []

            # Direct HTML parsing - skip JSON attempts that always fail
            # Look for matchup links that contain the counter data
            matchup_links = soup.find_all('a', href=lambda x: x and '/lol/' in x and '/vs/' in x)

            if matchup_links:
                for link in matchup_links:  # Process all available counters
                    try:
                        counter_data = {}

                        # Get champion name from URL
                        href = link['href']
                        match = re.search(r'/vs/([^/]+)/', href)
                        if match:
                            lolalytics_name = match.group(1)
                            # Convert to internal champion key using proper mapping
                            internal_key = get_internal_key_from_lolalytics(lolalytics_name)
                            if internal_key:
                                counter_data['champion'] = internal_key
                            else:
                                # Fallback to the old behavior if mapping fails
                                counter_data['champion'] = lolalytics_name.replace('-', ' ').title()

                        # Extract win rate - look for percentage in the link content
                        link_text = link.get_text()
                        winrate_match = re.search(r'(\d+\.?\d*)%', link_text)
                        if winrate_match:
                            try:
                                counter_data['win_rate'] = float(winrate_match.group(1))
                            except:
                                pass

                        # Extract games count - look for number followed by Games
                        games_match = re.search(r'(\d+(?:,\d+)*)\s*Games', link_text)
                        if games_match:
                            try:
                                games_text = games_match.group(1).replace(',', '')
                                counter_data['games'] = int(games_text)
                            except:
                                pass

                        if counter_data.get('champion') and counter_data.get('win_rate') is not None:
                            counters.append(counter_data)

                    except Exception as e:
                        continue

            return counters

        except Exception as e:
            print(f"Error getting counters for {champion} {role}: {e}")
            return []

    def scrape_champion_build(self, champion_display_name: str, tier: str = "d2_plus", patch: str = None) -> Dict:
        """Main method to scrape all champion build data - returns flattened structure"""
        print(f"\n=== Scraping {champion_display_name} build data ===")

        # Encode champion name for Lolalytics URL
        encoded_champion = encode_champion_name_for_lolalytics(champion_display_name)

        # Get valid roles
        roles = self.get_champion_roles(encoded_champion, tier, patch)
        if not roles:
            print(f"No valid roles found for {champion_display_name}")
            return {}

        result = {
            'tier': tier,
            'patch': patch,
            'roles': {}
        }

        # Get data for each role
        for role_info in roles:
            if isinstance(role_info, tuple):
                role_name, role_url = role_info
            else:
                role_name = role_info
                role_url = None

            print(f"\n--- Processing role: {role_name} ---")

            # Get stats for this role
            if role_url and 'lane=' not in role_url:
                # Main role without lane parameter - use the URL directly
                stats = self.get_role_stats_from_url(encoded_champion, role_url, tier, patch)
            else:
                # Normal role with lane parameter
                stats = self.get_role_stats(encoded_champion, role_name, tier, patch)

            # Note: Individual role filtering happens at the patch level in the update engine
            # We collect all roles with ≥9% pickrate here, regardless of individual game counts

            # Get counters only for valid roles
            counters = self.get_counter_matchups(encoded_champion, role_name, tier, patch)

            result['roles'][role_name] = {
                'stats': stats,
                'counters': counters
            }

            # Rate limiting
            time.sleep(1)

        return result

def test_aatrox():
    """Test the scraper with Aatrox"""
    scraper = LolalyticsBuildScraper()
    result = scraper.scrape_champion_build("aatrox")

    print("\n=== Test Results ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result

if __name__ == "__main__":
    test_aatrox()
