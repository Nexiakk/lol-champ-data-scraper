"""
League Wiki scraper with multi-form champion support.
Detects forms (like Jayce's Hammer/Cannon) and groups abilities accordingly.
"""
import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Optional, Any
from urllib.parse import quote


def encode_champion_name_for_wiki(champion_name: str) -> str:
    """Encode champion name for League Wiki URL format."""
    encoded = champion_name.replace(' ', '_')
    encoded = quote(encoded, safe='_')
    return encoded


def detect_forms(soup: BeautifulSoup, champion_name: str) -> List[Dict[str, Any]]:
    """
    Detect multiple forms by looking for tab images.
    Returns list of form metadata: [{name, key, tab_image_src}]
    """
    forms = []
    champion_lower = champion_name.lower()

    # Find tab images (e.g., Jayce_hammer_tab.png, Jayce_cannon_tab.png)
    tab_images = soup.find_all('img', src=re.compile(rf'{champion_lower}_(\w+)_tab\.png', re.I))

    # Use a set to avoid duplicates (tabs often appear twice in HTML)
    seen_keys = set()

    for img in tab_images:
        src = img.get('src', '')
        match = re.search(rf'{champion_lower}_(\w+)_tab\.png', src, re.I)
        if match:
            form_key = match.group(1).lower()

            # Skip duplicates
            if form_key in seen_keys:
                continue
            seen_keys.add(form_key)

            # Try to get human-readable name from surrounding context
            form_name = form_key.capitalize()

            # Look for parent with title attribute (e.g., "Mercury Cannon abilities")
            parent = img.find_parent(['span', 'a', 'button', 'center'])
            if parent:
                title = parent.get('title', '')
                if title and 'abilities' in title.lower():
                    # "Mercury Cannon abilities" -> "Mercury Cannon"
                    form_name = title.replace('abilities', '').strip()

            # Special case mappings for known champions
            form_name_map = {
                'hammer': 'Mercury Hammer',
                'cannon': 'Mercury Cannon',
                'human': 'Human Form',
                'spider': 'Spider Form',
                'cougar': 'Cougar Form',
                'mini': 'Mini Gnar',
                'mega': 'Mega Gnar',
            }

            if form_key in form_name_map:
                form_name = form_name_map[form_key]

            forms.append({
                'key': form_key,
                'name': form_name,
                'tab_image_src': src
            })

    return forms


def extract_skill_type(skill_div) -> Optional[str]:
    """Extract skill type (Passive, Q, W, E, R) from CSS classes."""
    classes = skill_div.get('class', [])

    # Map CSS classes to skill types
    class_to_type = {
        'skill_innate': 'Passive',
        'skill_q': 'Q',
        'skill_w': 'W',
        'skill_e': 'E',
        'skill_r': 'R'
    }

    for class_name in classes:
        if class_name in class_to_type:
            return class_to_type[class_name]

    return None


def extract_ability_name(skill_div) -> Optional[str]:
    """Extract ability name from skill div."""
    # Look for the specific ability name element
    name_div = skill_div.find('div', class_='ability-info-stats__ability')
    if name_div:
        name = name_div.get_text(strip=True)
        # Filter out generic labels
        if name not in ['Edit', 'Active:', 'Passive:', 'Innate:']:
            return name

    # Fallback: Look for h3 or strong tags
    name_tag = skill_div.find(['h3', 'strong', 'b'])
    if name_tag:
        name = name_tag.get_text(strip=True)
        if name not in ['Edit', 'Active:', 'Passive:', 'Innate:']:
            return name

    return None


def extract_cooldown(skill_div) -> Optional[str]:
    """Extract cooldown from ability container."""
    # Look for ability-info-stats__stat elements
    stat_elements = skill_div.find_all('div', class_='ability-info-stats__stat')

    for stat in stat_elements:
        label_elem = stat.find('div', class_='ability-info-stats__stat-label')
        value_elem = stat.find('div', class_='ability-info-stats__stat-value')

        if label_elem and value_elem:
            label_text = label_elem.get_text(strip=True).upper()
            if 'COOLDOWN' in label_text or label_text == 'CD:':
                cooldown = value_elem.get_text(strip=True)
                # Clean up cooldown string
                cooldown = re.sub(r'\s*seconds?\s*$', '', cooldown, flags=re.I)
                if cooldown and cooldown not in ['.', '']:
                    return cooldown

    # Fallback: Search text for cooldown patterns
    text = skill_div.get_text()
    cooldown_match = re.search(r'cooldown[:\s]*([\d./\s]+)', text, re.IGNORECASE)
    if cooldown_match:
        cooldown = cooldown_match.group(1).strip()
        if cooldown and cooldown not in ['.', '']:
            return cooldown

    return None


def extract_cost(skill_div) -> Optional[Dict[str, str]]:
    """Extract cost information from ability container."""
    stat_elements = skill_div.find_all('div', class_='ability-info-stats__stat')

    for stat in stat_elements:
        label_elem = stat.find('div', class_='ability-info-stats__stat-label')
        value_elem = stat.find('div', class_='ability-info-stats__stat-value')

        if label_elem and value_elem:
            label_text = label_elem.get_text(strip=True).upper()

            if label_text == 'COST:':
                value_text = value_elem.get_text(strip=True)

                # Parse value and resource type
                # Example: "55 / 65 / 75 / 85 / 95 mana" or "40 Energy"
                parts = value_text.split()

                if len(parts) >= 2:
                    # Last part is the resource type
                    resource = parts[-1].lower()
                    value = ' '.join(parts[:-1])

                    # Validate resource type
                    valid_resources = ['mana', 'energy', 'fury', 'health', 'flow']
                    if resource in valid_resources:
                        return {'value': value, 'resource': resource}

                    # If not a known resource, treat the whole thing as value
                    return {'value': value_text, 'resource': resource}

                elif len(parts) == 1:
                    value = parts[0]
                    if value.isdigit() or '/' in value:
                        return {'value': value, 'resource': 'mana'}

    return None


def extract_ability_data(skill_div, champion_name: str) -> Optional[Dict[str, Any]]:
    """Extract all data from a single skill div."""
    skill_type = extract_skill_type(skill_div)
    if not skill_type:
        return None

    name = extract_ability_name(skill_div)
    if not name or name == champion_name:
        return None

    # Skip generic entries
    if name in ['Edit', 'Active:', 'Passive:', 'Innate:', '']:
        return None

    cooldown = extract_cooldown(skill_div)
    cost = extract_cost(skill_div)

    ability = {
        'name': name,
        'type': skill_type,
    }

    # Only include cooldown if it exists (passives may not have cooldown)
    if cooldown:
        ability['cooldown'] = cooldown

    # Only include cost if it exists
    if cost:
        ability['cost'] = cost

    return ability


def extract_all_abilities(soup: BeautifulSoup, champion_name: str) -> List[Dict[str, Any]]:
    """Extract all abilities from the page (excluding wrappers)."""
    abilities = []

    # Find only actual skill divs (not skill_header or skill_wrapper)
    skill_divs = soup.find_all('div', class_=re.compile(r'^skill_(innate|q|w|e|r)$'))

    for skill_div in skill_divs:
        ability = extract_ability_data(skill_div, champion_name)
        if ability:
            # Check for duplicates (same name and type)
            if not any(a['name'] == ability['name'] and a['type'] == ability['type'] for a in abilities):
                abilities.append(ability)

    return abilities


def find_transform_ability_indices(abilities: List[Dict[str, Any]]) -> List[int]:
    """
    Find indices of R abilities that are likely transform abilities.
    These usually indicate form boundaries.
    """
    transform_indices = []
    for i, ability in enumerate(abilities):
        if ability['type'] == 'R':
            name_lower = ability['name'].lower()
            # R abilities with "transform" in the name are form switches
            if 'transform' in name_lower:
                transform_indices.append(i)
    return transform_indices


def group_abilities_by_form(abilities: List[Dict[str, Any]], forms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group abilities by form.
    For multi-form champions, abilities appear in order of forms.
    """
    if len(forms) <= 1:
        # Single form - all abilities in one group
        return [{
            'name': forms[0]['name'] if forms else 'Skills',
            'abilities': abilities
        }]

    # Multi-form: Try to detect form boundaries
    # Strategy 1: Look for transform R abilities as boundaries
    transform_indices = find_transform_ability_indices(abilities)

    if len(transform_indices) >= len(forms):
        # Use transform abilities as boundaries
        form_abilities = []
        for i, form in enumerate(forms):
            if i == 0:
                start_idx = 0
                end_idx = transform_indices[i] + 1  # Include the transform R
            elif i < len(forms) - 1:
                start_idx = transform_indices[i - 1] + 1
                end_idx = transform_indices[i] + 1
            else:
                start_idx = transform_indices[i - 1] + 1 if len(transform_indices) >= len(forms) else transform_indices[-1] + 1
                end_idx = len(abilities)

            form_abilities.append({
                'name': form['name'],
                'abilities': abilities[start_idx:end_idx]
            })

        return form_abilities

    # Strategy 2: Even split by ability count
    form_abilities = []
    abilities_per_form = max(1, len(abilities) // len(forms))

    for i, form in enumerate(forms):
        start_idx = i * abilities_per_form
        if i == len(forms) - 1:
            end_idx = len(abilities)
        else:
            end_idx = start_idx + abilities_per_form

        form_abilities.append({
            'name': form['name'],
            'abilities': abilities[start_idx:end_idx]
        })

    return form_abilities


def clean_form_abilities(form_abilities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Clean up form abilities:
    - Remove duplicate passives
    - Filter out generic/invalid abilities
    """
    cleaned_forms = []

    for form in form_abilities:
        cleaned_abilities = []
        seen_names = set()

        for ability in form['abilities']:
            name = ability['name']

            # Skip generic entries
            if name in ['Edit', 'Active:', 'Passive:', 'Innate:', '']:
                continue

            # Skip "Innate - X" duplicates (they're just passive descriptions)
            if name.lower().startswith('innate -'):
                continue

            # Skip duplicates within the same form
            key = f"{ability['type']}:{name}"
            if key in seen_names:
                continue
            seen_names.add(key)

            cleaned_abilities.append(ability)

        if cleaned_abilities:
            cleaned_forms.append({
                'name': form['name'],
                'abilities': cleaned_abilities
            })

    return cleaned_forms


def scrape_champion_abilities_from_html(html: str, champion_display_name: str) -> Dict[str, Any]:
    """
    Scrape abilities from saved HTML (for testing).
    Returns structured data with forms.
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Detect forms
    forms = detect_forms(soup, champion_display_name)

    # Extract all abilities
    abilities = extract_all_abilities(soup, champion_display_name)

    # Group by form
    form_data = group_abilities_by_form(abilities, forms)

    # Clean up the form data
    form_data = clean_form_abilities(form_data)

    return {
        'forms': form_data,
        'hasMultipleForms': len(forms) > 1,
        'totalAbilities': sum(len(form['abilities']) for form in form_data)
    }


def scrape_champion_abilities(champion_display_name: str) -> List[Dict[str, Any]]:
    """
    Scrape ability data from League Wiki.
    Returns list of forms with abilities (backward compatible format).
    """
    encoded_name = encode_champion_name_for_wiki(champion_display_name)
    url = f"https://wiki.leagueoflegends.com/en-us/{encoded_name}"

    try:
        response = requests.get(url, timeout=10, allow_redirects=True)
        response.raise_for_status()

        result = scrape_champion_abilities_from_html(response.text, champion_display_name)

        # For backward compatibility, return flat abilities array
        # But include form information in ability names if multi-form
        flat_abilities = []
        for form in result['forms']:
            for ability in form['abilities']:
                # Add form context for multi-form champions
                if result['hasMultipleForms']:
                    ability['formName'] = form['name']
                flat_abilities.append(ability)

        return flat_abilities

    except Exception as e:
        print(f"Error scraping {champion_display_name}: {e}")
        return []


def scrape_champion_abilities_with_forms(champion_display_name: str) -> Dict[str, Any]:
    """
    Scrape ability data with full form structure.
    Returns {forms: [...], hasMultipleForms: bool, totalAbilities: int}
    """
    encoded_name = encode_champion_name_for_wiki(champion_display_name)
    url = f"https://wiki.leagueoflegends.com/en-us/{encoded_name}"

    try:
        response = requests.get(url, timeout=10, allow_redirects=True)
        response.raise_for_status()

        return scrape_champion_abilities_from_html(response.text, champion_display_name)

    except Exception as e:
        print(f"Error scraping {champion_display_name}: {e}")
        return {'forms': [], 'hasMultipleForms': False, 'totalAbilities': 0}


if __name__ == '__main__':
    # Test with fixtures
    import os

    test_champions = ['Jayce', 'Elise', 'Nidalee', 'Aatrox', 'Yasuo']

    for champ in test_champions:
        fixture_path = os.path.join('tests', 'fixtures', f'{champ.lower()}.html')
        if os.path.exists(fixture_path):
            with open(fixture_path, 'r', encoding='utf-8') as f:
                html = f.read()

            result = scrape_champion_abilities_from_html(html, champ)

            print(f"\n{'='*60}")
            print(f"{champ}")
            print('='*60)
            print(f"Forms: {len(result['forms'])}")
            print(f"Has multiple forms: {result['hasMultipleForms']}")
            print(f"Total abilities: {result['totalAbilities']}")

            for i, form in enumerate(result['forms']):
                print(f"\n  Form {i+1}: {form['name']}")
                for ability in form['abilities']:
                    cooldown_str = f" (CD: {ability.get('cooldown', 'N/A')})" if ability.get('cooldown') else ""
                    cost_str = ""
                    if ability.get('cost'):
                        cost_str = f" [{ability['cost']['value']} {ability['cost']['resource']}]"
                    print(f"    - {ability['type']}: {ability['name']}{cooldown_str}{cost_str}")
