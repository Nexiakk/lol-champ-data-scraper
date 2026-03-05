"""
Legacy functions from main.py that are being phased out.
These are kept for backward compatibility during the refactoring.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

# Import utilities that are still needed
from .utils import get_previous_patch, get_current_patch


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

                # Use current patch if released more than 7 days ago
                if days_since_release >= 7:
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
