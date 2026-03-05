"""
Refactored main scraper module.
Uses shared utilities and modern Python practices.
"""

import os
from typing import Dict, List, Optional
from datetime import datetime

# Import refactored utilities
from .utils import (
    RiotAPIClient, ChampionNameMapper, PatchManager,
    get_display_name, get_champion_id, get_champion_image_name,
    get_champion_list, normalize_patch_for_lolalytics,
    encode_champion_name_for_wiki, encode_champion_name_for_lolalytics
)
from .firebase_utils import FirebaseManager, FirebaseConfig
from .logging_utils import get_logger, log_scraping_start, log_scraping_success, log_scraping_error
from .config import get_config
from .models import ChampionData, ScrapingResult
from .lolalytics_build_scraper import LolalyticsBuildScraper
from .wiki_scraper import scrape_champion_abilities

# Legacy import for backward compatibility
from .main_legacy import check_patch_viability

# Global instances
_firebase_manager: Optional[FirebaseManager] = None
_logger = get_logger(__name__)

def normalize_patch_for_lolalytics(patch_version):
    """Convert Riot API patch format (x.y.z) to Lolalytics format (x.y)"""
    # Split by dots and take only first two components
    parts = patch_version.split('.')
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return patch_version

def parse_wiki_date(date_text):
    """Parse wiki date format from various possible formats"""
    try:
        import re

        # Remove link references like [1], [2], etc.
        date_text = re.sub(r'\s*\[\d+\]\s*$', '', date_text).strip()

        # Handle the <br> tag creating newlines (if present)
        date_text = date_text.replace('\n', ' ').strip()

        # Handle cases where day and year are concatenated (e.g., "January 82026" -> "January 8 2026")
        # Look for pattern: Month DayYear
        date_match = re.search(r'^([A-Za-z]+)\s+(\d+)(20\d{2})$', date_text)
        if date_match:
            month, day, year = date_match.groups()
            date_text = f"{month} {day} {year}"

        # Parse format like "January 8 2026"
        return datetime.strptime(date_text, '%B %d %Y')
    except ValueError:
        print(f"Could not parse date: {date_text}")
        return None

def wiki_to_riot_patch(wiki_version):
    """Convert Wiki patch format V26.01 to Riot format 16.1"""
    if not wiki_version.startswith('V'):
        return None

    try:
        version = wiki_version[1:]  # Remove 'V' -> "26.01"
        year_digit, patch_num = version.split('.')

        # Convert year: 26 -> 16 (1 + last digit of year)
        riot_major = f"1{year_digit[-1]}"  # 6 -> "16"

        # Keep patch number as is
        return f"{riot_major}.{int(patch_num)}"  # "16.1"

    except (ValueError, IndexError):
        print(f"Could not convert wiki version: {wiki_version}")
        return None

def scrape_wiki_patches(current_year):
    """Scrape League Wiki annual cycle page for patches with release dates"""
    url = f"https://wiki.leagueoflegends.com/en-us/Patch/{current_year}_Annual_Cycle"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        patches = []

        # Find the patch table
        table = soup.find('table')
        if not table:
            return []

        rows = table.find_all('tr')[1:]  # Skip header row

        for row in rows:
            cells = row.find_all(['th', 'td'])
            if len(cells) < 2:
                continue

            # Extract date from first cell (th)
            date_cell = cells[0]
            date_text = date_cell.get_text().strip()

            # Parse date format: "January 8\n2026" -> datetime
            release_date = parse_wiki_date(date_text)
            if not release_date:
                continue

            # Extract patch from second cell (td)
            patch_cell = cells[1]
            patch_link = patch_cell.find('a')
            if patch_link:
                patch_title = patch_link.get('title') or patch_link.get_text().strip()
                patches.append({
                    'title': patch_title,  # e.g., "V26.01"
                    'release_date': release_date
                })

        return patches

    except Exception as e:
        print(f"Error scraping wiki patches: {e}")
        return []

def check_patch_viability(current_patch_full):
    """
    Check if current patch has been released long enough using Wiki data.
    Returns tuple: (use_current_patch, target_patch, metrics)
    """
    try:
        print(f"🔍 Checking patch {current_patch_full} viability using Wiki data...")

        # Normalize patch format (16.1.1 -> 16.1)
        current_patch_short = normalize_patch_for_lolalytics(current_patch_full)
        current_year = datetime.now().year

        # Scrape wiki patches
        wiki_patches = scrape_wiki_patches(current_year)

        if not wiki_patches:
            print("⚠️ No wiki patches found, falling back to previous patch")
            return False, get_previous_patch(current_patch_full), {}

        # Find matching patch
        for wiki_patch in wiki_patches:
            riot_version = wiki_to_riot_patch(wiki_patch['title'])

            if riot_version == current_patch_short:
                days_since_release = (datetime.now() - wiki_patch['release_date']).days

                print(f"✅ Found matching patch {wiki_patch['title']} -> {riot_version}")
                print(f"   Released: {wiki_patch['release_date'].strftime('%Y-%m-%d')}")
                print(f"   Days since release: {days_since_release}")

                # Use current patch if released more than 4 days ago
                if days_since_release >= 4:
                    print("✅ Patch is viable for scraping")
                    return True, current_patch_full, {
                        'days_since_release': days_since_release,
                        'release_date': wiki_patch['release_date'],
                        'wiki_title': wiki_patch['title']
                    }
                else:
                    print(f"⚠️ Patch too new ({days_since_release} days), falling back")
                    return False, get_previous_patch(current_patch_full), {
                        'days_since_release': days_since_release,
                        'release_date': wiki_patch['release_date'],
                        'reason': 'patch_too_new'
                    }

        # Patch not found on wiki
        print(f"⚠️ Patch {current_patch_short} not found on Wiki, falling back")
        return False, get_previous_patch(current_patch_full), {'reason': 'patch_not_on_wiki'}

    except Exception as e:
        print(f"❌ Error checking patch viability: {e}")
        import traceback
        traceback.print_exc()
        return False, get_previous_patch(current_patch_full), {'error': str(e)}

def scrape_and_store_data():
    """Main function to scrape data and store in Firebase"""
    print("Starting data scraping...")

    # Get current patch and check viability
    current_patch = get_current_patch()
    print(f"Current patch: {current_patch}")

    # Check if current patch has sufficient sample size
    use_current, target_patch, viability_metrics = check_patch_viability(current_patch)

    if use_current:
        print(f"✅ Using current patch {current_patch} for scraping")
    else:
        print(f"⚠️ Current patch {current_patch} has insufficient data")
        print(f"🔄 Falling back to patch {target_patch}")

    champions = get_champion_list()

    # Process each champion
    for champion_internal in champions:
        try:
            # Get all champion data
            champion_id = get_champion_id(champion_internal)
            champion_display = get_display_name(champion_internal)
            champion_image_name = get_champion_image_name(champion_internal)
            simplified_key = get_simplified_key(champion_internal)

            print(f"\n=== Processing {champion_internal} (display: {champion_display}, key: {simplified_key}) ===")

            # Scrape League Wiki abilities data
            print(f"Scraping wiki abilities for {champion_display}...")
            abilities_data = scrape_champion_abilities(champion_display)
            print(f"Found {len(abilities_data)} abilities")

            # Scrape Lolalytics build data with target patch
            print(f"Scraping lolalytics data for {champion_display} (patch {target_patch})...")
            lolalytics_scraper = LolalyticsBuildScraper()
            normalized_patch = normalize_patch_for_lolalytics(target_patch)
            build_data = lolalytics_scraper.scrape_champion_build(champion_display, patch=normalized_patch)

            # Combine the data with new structure
            combined_data = {
                'id': champion_id,              # Numeric champion ID (136 for Aurelion Sol)
                'imageName': champion_image_name, # Internal key for images (AurelionSol)
                'name': champion_display,       # Display name (Aurelion Sol)
                'abilities': abilities_data,
                'lastUpdated': datetime.utcnow()
            }

            # Add lolalytics data if available (flattened structure, remove tier field)
            if build_data:
                # Copy build data but exclude the 'tier' field since it's always diamond_plus
                for key, value in build_data.items():
                    if key != 'tier':  # Skip the tier field
                        combined_data[key] = value
                print(f"Combined data: {len(build_data.get('roles', {}))} roles")
            else:
                print("No build data available")

            # Store combined data using internal key (remove /data subdocument)
            store_combined_champion_data(champion_internal, combined_data)
            print(f"✅ Successfully stored data for {champion_display} (key: {champion_internal})")

        except Exception as e:
            print(f"❌ Error processing {champion_internal}: {e}")
            import traceback
            traceback.print_exc()

    # Update role containers for optimized queries
    print("\n🔄 Updating role containers...")
    update_role_containers()

    # Clean up old patch data to save space
    print("\n🧹 Cleaning up old patch data...")
    cleanup_old_patch_data()

    print("\n🎉 Data scraping, optimization, and cleanup completed!")

class SmartUpdateEngine:
    """Intelligent update system for champion data"""

    def __init__(self):
        self.tier_thresholds = {
            'S': {'min_percent': 0.4, 'min_absolute': 15000},  # 40% of old or 15K
            'A': {'min_percent': 0.5, 'min_absolute': 10000},  # 50% of old or 10K
            'B': {'min_percent': 0.6, 'min_absolute': 7500},   # 60% of old or 7.5K
            'C': {'min_percent': 0.7, 'min_absolute': 5000},   # 70% of old or 5K
        }

    def calculate_champion_tier(self, total_games):
        """Categorize champion by historical play rate"""
        if total_games >= 150000:
            return 'S'
        elif total_games >= 75000:
            return 'A'
        elif total_games >= 25000:
            return 'B'
        else:
            return 'C'

    def calculate_adaptive_threshold(self, old_total_games):
        """Calculate switching threshold based on champion's tier"""
        tier = self.calculate_champion_tier(old_total_games)
        config = self.tier_thresholds[tier]

        return max(
            old_total_games * config['min_percent'],
            config['min_absolute']
        )

    def should_update_champion(self, current_data, new_data):
        """Simplified: Patch viability already checked globally"""

        # Always update on patch changes (patch already validated globally as ready)
        if new_data.get('patch') != current_data.get('patch'):
            return {
                'update': True,
                'abilities': True,
                'lolalytics': True,
                'reason': f"Patch changed to {new_data['patch']} (validated globally)"
            }

        # Same patch: Only update if abilities changed
        else:
            abilities_changed = self._abilities_changed(
                current_data.get('abilities', []),
                new_data.get('abilities', [])
            )
            return {
                'update': abilities_changed,  # Only if abilities changed
                'abilities': abilities_changed,
                'lolalytics': True,  # Always update (growing sample)
                'reason': f"Same patch: abilities={abilities_changed}, lolalytics=True"
            }

    def _calculate_total_games(self, data):
        """Sum games across all roles"""
        return sum(
            role_data.get('stats', {}).get('games', 0)
            for role_data in data.get('roles', {}).values()
        )

    def _abilities_changed(self, old_abilities, new_abilities):
        """Check if abilities actually changed"""
        if len(old_abilities) != len(new_abilities):
            return True

        # Compare each ability
        for old, new in zip(old_abilities, new_abilities):
            if (old.get('name') != new.get('name') or
                old.get('cooldown') != new.get('cooldown') or
                old.get('type') != new.get('type')):
                return True

        return False

    def get_viable_roles(self, scraped_data, historical_roles=None):
        """Get all roles that should be stored - simplified since we only scrape ≥9% roles"""
        viable_roles = set()

        # All scraped roles are already ≥9% pickrate, so just return them
        viable_roles.update(scraped_data.get('roles', {}).keys())

        # Add historically viable roles (if any exist from before the optimization)
        if historical_roles:
            viable_roles.update(historical_roles)

        return list(viable_roles)

def test_data_integration():
    """Test the data integration with smart updates"""
    print("🧪 Testing data integration with smart updates...")

    champion = "Aatrox"
    update_engine = SmartUpdateEngine()

    try:
        print(f"\n=== Testing {champion} Integration ===")

        # Scrape League Wiki abilities data
        print("Scraping wiki abilities...")
        abilities_data = scrape_champion_abilities(champion)
        print(f"✅ Found {len(abilities_data)} abilities")

        # Scrape Lolalytics build data
        print("Scraping lolalytics data...")
        lolalytics_scraper = LolalyticsBuildScraper()
        build_data = lolalytics_scraper.scrape_champion_build(champion.lower())

        # Simulate current data (what would be in database)
        current_data = {
            'name': champion,
            'abilities': abilities_data,  # Same abilities for testing
            'patch': '15.23',  # Simulate old patch
            'tier': 'diamond_plus',
            'roles': {
                'top': {'stats': {'games': 95000, 'pick_rate': 45.0}},
                'jungle': {'stats': {'games': 75000, 'pick_rate': 38.0}}
            }
        }

        # Decide what to update
        update_decision = update_engine.should_update_champion(current_data, build_data)

        print(f"\n📊 Update Decision: {update_decision}")

        # Apply selective updates
        final_data = current_data.copy()  # Start with current

        if update_decision['abilities']:
            final_data['abilities'] = abilities_data

        if update_decision['lolalytics']:
            # Update with new build data
            final_data.update(build_data)
            # Filter to viable roles only
            viable_roles = update_engine.get_viable_roles(build_data)
            final_data['roles'] = {
                role: final_data['roles'][role]
                for role in viable_roles
                if role in final_data['roles']
            }

        # Show results
        print("\n📈 Final Data Summary:")
        print(f"  - Abilities: {len(final_data.get('abilities', []))} abilities")
        print(f"  - Patch: {final_data.get('patch')} (was {current_data.get('patch')})")
        print(f"  - Roles: {list(final_data.get('roles', {}).keys())}")
        print(f"  - Total Games: {update_engine._calculate_total_games(final_data)}")

        champion_tier = update_engine.calculate_champion_tier(
            update_engine._calculate_total_games(current_data)
        )
        threshold = update_engine.calculate_adaptive_threshold(
            update_engine._calculate_total_games(current_data)
        )
        print(f"  - Champion Tier: {champion_tier} (threshold: {threshold})")

        print("\n✅ Smart integration test successful!")
        return final_data, update_decision

    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def store_combined_champion_data(champion_key: str, data: dict):
    """Store combined champion data and update role containers incrementally"""
    if not init_firebase():
        raise Exception("Firebase not available")

    # Store champion data
    doc_ref = db.collection('champions').document(f'all/{champion_key}')
    doc_ref.set(data)

    # Update role containers for this champion
    update_role_containers_for_champion(champion_key, data)

def update_role_containers_for_champion(champion_key: str, champion_data: dict):
    """Update role containers for a single champion"""
    roles = champion_data.get('roles', {})

    for role_name, role_stats in roles.items():
        if role_name and role_stats.get('stats', {}).get('games', 0) > 0:
            # Normalize role name for storage
            normalized_role = normalize_role_name(role_name)
            role_ref = get_role_container_ref(normalized_role)

            # Update role container atomically
            update_role_container_incremental(role_ref, champion_key, role_stats)

def update_role_container_incremental(role_ref, champion_key: str, role_stats: dict):
    """Atomically update a single role container"""
    @firestore.transactional
    def update_in_transaction(transaction):
        role_doc = role_ref.get(transaction=transaction)

        if role_doc.exists:
            current_data = role_doc.to_dict()
            champions_list = current_data.get('champions', [])
        else:
            champions_list = []

        # Add champion if not already present
        if champion_key not in champions_list:
            champions_list.append(champion_key)

        # Update role document
        transaction.set(role_ref, {
            'champions': champions_list,
            'count': len(champions_list),
            'lastUpdated': datetime.utcnow()
        }, merge=True)

    update_in_transaction(db)

def get_role_container_ref(role_name: str):
    """Get reference to role container document at champions/roles/{roleName}"""
    return db.collection('champions').document(f'roles/{role_name}')

def normalize_role_name(role_name: str) -> str:
    """Normalize role names for storage"""
    mapping = {
        'top': 'top',
        'jungle': 'jungle',
        'mid': 'middle',
        'bot': 'bottom',
        'adc': 'bottom',
        'support': 'support'
    }
    return mapping.get(role_name.lower(), role_name.lower())

def update_role_containers():
    """Create optimized role container indexes for Firebase free tier"""
    if not init_firebase():
        print("Firebase not available, skipping role container update")
        return

    print("Updating role containers for optimized Firebase queries...")

    try:
        # Get all champions
        champions_ref = db.collection('champions')
        champions = champions_ref.stream()

        role_champions = {
            'top': [],
            'jungle': [],
            'middle': [],
            'bottom': [],
            'support': []
        }

        for champ_doc in champions:
            champ_data = champ_doc.to_dict()

            # Check which roles this champion plays
            roles = champ_data.get('roles', {})
            for role in roles:
                if role in role_champions:
                    role_champions[role].append({
                        'id': champ_doc.id,
                        'name': champ_data.get('name', ''),
                        'pickRate': roles[role].get('stats', {}).get('pick_rate', 0)
                    })

        # Sort champions by pick rate (highest first) and limit if needed
        for role in role_champions:
            role_champions[role].sort(key=lambda x: x['pickRate'], reverse=True)
            # Keep all champions for now - Firebase can handle it
            # Could limit to top N if storage becomes an issue

        # Store role containers
        roles_ref = db.collection('roles')
        current_patch = None

        for role, champions_list in role_champions.items():
            # Extract just champion IDs for lightweight queries
            champion_ids = [champ['id'] for champ in champions_list]

            # Get current patch from first champion if available
            if not current_patch and champions_list:
                first_champ_data = db.collection('champions').document(f'all/{champions_list[0]["id"]}').get()
                if first_champ_data.exists:
                    current_patch = first_champ_data.to_dict().get('patch')

            role_doc = {
                'champions': champion_ids,  # Lightweight: just IDs
                'count': len(champion_ids),
                'lastUpdated': datetime.utcnow()
            }

            if current_patch:
                role_doc['patch'] = current_patch

            roles_ref.document(role).set(role_doc)
            print(f"✅ Updated {role}: {len(champion_ids)} champions")

        print(f"🎉 Role containers updated successfully!")

    except Exception as e:
        print(f"❌ Error updating role containers: {e}")
        import traceback
        traceback.print_exc()

def get_riot_versions():
    """Fetch and cache Riot API versions for automatic patch detection"""
    cache_key = "riot_versions"
    cached = riot_cache.get(cache_key)

    if cached and time.time() - cached['timestamp'] < 3600:  # 1 hour cache
        return cached['versions']

    try:
        print("Fetching Riot API versions...")
        response = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10)
        response.raise_for_status()
        versions = response.json()

        # Cache the result
        riot_cache[cache_key] = {
            'versions': versions,
            'timestamp': time.time()
        }

        print(f"✅ Fetched {len(versions)} patch versions from Riot API")
        return versions

    except Exception as e:
        print(f"❌ Failed to fetch Riot versions: {e}")
        # Return cached version if available, otherwise empty list
        return cached['versions'] if cached else []

def get_previous_patch(current_patch):
    """Automatically find the previous patch using Riot API data"""
    versions = get_riot_versions()

    try:
        current_index = versions.index(current_patch)
        if current_index + 1 < len(versions):
            previous_patch = versions[current_index + 1]  # Next item is previous (list is newest first)
            print(f"✅ Detected previous patch: {current_patch} → {previous_patch}")
            return previous_patch
        else:
            print(f"⚠️ No previous patch found for {current_patch}")
    except ValueError:
        print(f"⚠️ Current patch {current_patch} not found in Riot versions")

    return None

def get_champion_fallback_data(champion_id, current_patch):
    """Get fallback data from automatically detected previous patch"""
    if not init_firebase():
        return None

    previous_patch = get_previous_patch(current_patch)
    if not previous_patch:
        return None

    try:
        # Look for archived data from previous patch
        fallback_doc = db.collection('champions') \
                        .document(f'all/{champion_id}') \
                        .collection('patch_history') \
                        .document(previous_patch) \
                        .get()

        if fallback_doc.exists:
            data = fallback_doc.to_dict()
            data['_fallback'] = True
            data['_fallback_patch'] = previous_patch
            data['_current_patch'] = current_patch
            print(f"✅ Found fallback data for {champion_id} from patch {previous_patch}")
            return data
        else:
            print(f"⚠️ No archived data found for {champion_id} in patch {previous_patch}")

    except Exception as e:
        print(f"❌ Error retrieving fallback data: {e}")

    return None

def cleanup_old_patch_data():
    """Clean up old patch data, keeping only current + 1 previous patch"""
    if not init_firebase():
        print("Firebase not available, skipping cleanup")
        return

    print("🧹 Cleaning up old patch data...")

    try:
        # Get current patch from a sample champion
        current_patch = None
        champions_ref = db.collection('champions')
        sample_champions = champions_ref.limit(1).get()

        for doc in sample_champions:
            current_patch = doc.to_dict().get('patch')
            break

        if not current_patch:
            print("⚠️ Could not determine current patch, skipping cleanup")
            return

        print(f"Current active patch: {current_patch}")

        # Collect all patch history data
        old_patches = []
        champions_stream = champions_ref.stream()

        for champ_doc in champions_stream:
            patch_history_ref = champ_doc.collection('patch_history')
            patches = patch_history_ref.list_documents()

            for patch_doc in patches:
                patch_version = patch_doc.id
                if patch_version != current_patch:
                    old_patches.append((champ_doc.id, patch_version, patch_doc))

        # Group by patch version
        patches_by_version = {}
        for champ_id, patch_version, doc_ref in old_patches:
            if patch_version not in patches_by_version:
                patches_by_version[patch_version] = []
            patches_by_version[patch_version].append(doc_ref)

        # Sort patches by version (newest first)
        sorted_patches = sorted(patches_by_version.keys(), reverse=True)

        # Keep only the most recent previous patch
        if len(sorted_patches) > 1:
            patches_to_delete = sorted_patches[1:]  # Everything except the newest

            total_deleted = 0
            for old_patch in patches_to_delete:
                print(f"🗑️ Deleting old patch data: {old_patch}")
                for doc_ref in patches_by_version[old_patch]:
                    doc_ref.delete()
                    total_deleted += 1

            print(f"✅ Cleanup complete: deleted {total_deleted} old patch documents")
        else:
            print("ℹ️ No old patch data to clean up")

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        import traceback
        traceback.print_exc()

def get_current_patch():
    """Get the current League of Legends patch version from Riot API"""
    try:
        versions_url = "https://ddragon.leagueoflegends.com/api/versions.json"
        versions_response = requests.get(versions_url, timeout=10)
        versions_response.raise_for_status()
        versions = versions_response.json()
        return versions[0]  # Latest version is first in the list
    except Exception as e:
        print(f"Error fetching current patch from Riot API: {e}")
        return "15.24"  # Fallback to known recent patch

def get_champion_list():
    """Get list of all champions from Riot Data Dragon API"""
    try:
        # Get latest version
        current_patch = get_current_patch()

        # Get champion data
        champions_url = f"https://ddragon.leagueoflegends.com/cdn/{current_patch}/data/en_US/champion.json"
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
            'Aatrox', 'Ahri', 'Akali', 'Ashe', 'Jinx', 'Lux', 'Miss Fortune', 'Vayne', 'Yuumi',
            'Yasuo', 'Zed', 'Kaisa', 'Caitlyn', 'Ezreal', 'Varus'
        ]

def test_name_mapping():
    """Test the champion name mapping and encoding functions"""
    print("🧪 Testing champion name mapping and encoding...")

    test_cases = [
        ('MonkeyKing', 'Wukong'),
        ('KSante', "K'Sante"),
        ('JarvanIV', 'Jarvan IV'),
        ('Aatrox', 'Aatrox'),
        ('MissFortune', 'Miss Fortune')
    ]

    print("\n📋 Testing name mapping:")
    for internal, expected_display in test_cases:
        actual_display = get_display_name(internal)
        status = "✅" if actual_display == expected_display else "❌"
        print(f"  {status} {internal} → {actual_display} (expected: {expected_display})")

    print("\n🔗 Testing URL encoding:")

    encoding_tests = [
        ("K'Sante", "K%27Sante", "ksante"),
        ("Jarvan IV", "Jarvan_IV", "jarvaniv"),
        ("Wukong", "Wukong", "wukong"),
        ("Miss Fortune", "Miss_Fortune", "missfortune")
    ]

    for display_name, expected_wiki, expected_lolalytics in encoding_tests:
        actual_wiki = encode_champion_name_for_wiki(display_name)
        actual_lolalytics = encode_champion_name_for_lolalytics(display_name)

        wiki_status = "✅" if actual_wiki == expected_wiki else "❌"
        lolalytics_status = "✅" if actual_lolalytics == expected_lolalytics else "❌"

        print(f"  {display_name}:")
        print(f"    Wiki: {wiki_status} {actual_wiki} (expected: {expected_wiki})")
        print(f"    Lolalytics: {lolalytics_status} {actual_lolalytics} (expected: {expected_lolalytics})")

    print("\n✅ Name mapping tests completed!")

if __name__ == "__main__":
    # Test the name mapping first
    test_name_mapping()

    # Test the integration
    test_result = test_data_integration()

    # Uncomment to run full scraping with Firebase
    # scrape_and_store_data()
