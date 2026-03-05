"""
Analyze saved HTML fixture to understand form structure.
"""
import sys
import re
from bs4 import BeautifulSoup

def analyze_fixture(champion_name):
    """Analyze HTML structure for form detection."""
    with open(f'fixtures/{champion_name.lower()}.html', 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    print(f"\n{'='*60}")
    print(f"ANALYZING: {champion_name}")
    print('='*60)
    
    # 1. Find form tabs
    print("\n--- FORM TABS ---")
    tab_images = soup.find_all('img', src=re.compile(rf'{champion_name.lower()}_(\w+)_tab', re.I))
    print(f"Tab images found: {len(tab_images)}")
    
    for img in tab_images:
        print(f"\n  Image src: {img.get('src')}")
        parent = img.find_parent(['span', 'a', 'button'])
        if parent:
            print(f"    Title: {parent.get('title')}")
            print(f"    ID: {parent.get('id')}")
            print(f"    Class: {parent.get('class')}")
    
    # 2. Find skill divs
    print("\n--- SKILL DIVS ---")
    skill_divs = soup.find_all('div', class_=re.compile(r'skill_\w+'))
    print(f"Total skill divs: {len(skill_divs)}")
    
    for i, div in enumerate(skill_divs[:15]):  # Show first 15
        classes = div.get('class', [])
        skill_type = [c for c in classes if c.startswith('skill_')]
        
        # Try to get ability name
        name = None
        name_div = div.find('div', class_='ability-info-stats__ability')
        if name_div:
            name = name_div.get_text(strip=True)
        else:
            name_tag = div.find(['h3', 'strong', 'b'])
            if name_tag:
                name = name_tag.get_text(strip=True)
        
        print(f"  {i}: {skill_type} - {name or 'Unknown'}")
    
    # 3. Look for passive sections
    print("\n--- PASSIVE SECTIONS ---")
    innate_divs = soup.find_all('div', class_='skill_innate')
    print(f"Innate (passive) divs: {len(innate_divs)}")
    
    # 4. Check for form-related classes or IDs
    print("\n--- FORM CONTAINERS ---")
    form_containers = soup.find_all(['div', 'section'], class_=re.compile(r'form|stance', re.I))
    print(f"Containers with 'form' or 'stance' in class: {len(form_containers)}")
    
    # 5. Count abilities per type
    print("\n--- ABILITY COUNTS ---")
    type_counts = {}
    for div in skill_divs:
        classes = div.get('class', [])
        for c in classes:
            if c.startswith('skill_'):
                type_counts[c] = type_counts.get(c, 0) + 1
    
    for skill_type, count in sorted(type_counts.items()):
        print(f"  {skill_type}: {count}")
    
    # 6. Determine if multi-form
    total_abilities = len(skill_divs)
    q_count = type_counts.get('skill_q', 0)
    has_multiple_forms = q_count > 1 or total_abilities > 6
    
    print(f"\n--- CONCLUSION ---")
    print(f"  Total abilities: {total_abilities}")
    print(f"  Q abilities: {q_count}")
    print(f"  Multi-form: {has_multiple_forms}")

if __name__ == '__main__':
    champions = ['Jayce', 'Elise', 'Nidalee', 'Aatrox', 'Yasuo']
    
    for champ in champions:
        try:
            analyze_fixture(champ)
        except Exception as e:
            print(f"Error analyzing {champ}: {e}")
