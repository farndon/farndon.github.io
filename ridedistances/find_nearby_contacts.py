#!/usr/bin/env python3
"""
find_nearby_contacts.py

Reads a CSV file with columns: name, address, phone
Prompts the user for a reference street address (number, street, city, state)
and a search radius in miles (0.1 mile resolution), then lists every contact
whose address geocodes to within that radius.

Usage:
    python find_nearby_contacts.py contacts.csv

Requires:
    pip install geopy

Notes:
    - Geocoding is done with the free Nominatim (OpenStreetMap) service.
      It is rate-limited to about 1 request/second, so large CSV files will
      take a while (the script sleeps between requests to be a good citizen
      of that free service).
    - Addresses that can't be geocoded are skipped with a warning, not
      treated as fatal errors.
"""

import csv
import sys
import time
import argparse
from pathlib import Path

try:
    from geopy.geocoders import Nominatim
    from geopy.distance import geodesic
    from geopy.exc import GeocoderServiceError, GeocoderTimedOut
except ImportError:
    sys.exit("This script requires geopy. Install it with:\n    pip install geopy")


GEOCODE_USER_AGENT = "csv_proximity_finder_script"
REQUEST_DELAY_SECONDS = 1.0  # be polite to Nominatim's free tier


def prompt_reference_address():
    print("Enter the reference street address to compare against:")
    street = input("  Street address (number and street name): ").strip()
    city = input("  City: ").strip()
    state = input("  State: ").strip()
    return f"{street}, {city}, {state}"


def prompt_radius():
    while True:
        raw = input("Enter search radius in miles (e.g. 5.0, resolution 0.1): ").strip()
        try:
            radius = round(float(raw), 1)
            if radius <= 0:
                print("Please enter a positive number.")
                continue
            return radius
        except ValueError:
            print("Please enter a valid number.")


def geocode_with_retry(geolocator, address, retries=3):
    for attempt in range(retries):
        try:
            return geolocator.geocode(address, timeout=10)
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            if attempt == retries - 1:
                print(f"  Warning: could not geocode '{address}': {e}")
                return None
            time.sleep(1.0)
    return None


def load_contacts(csv_path):
    contacts = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldmap = {name.lower().strip(): name for name in (reader.fieldnames or [])}
        required = ['name', 'address', 'phone']
        missing = [r for r in required if r not in fieldmap]
        if missing:
            sys.exit(
                f"CSV is missing required column(s): {', '.join(missing)}. "
                f"Found columns: {reader.fieldnames}"
            )
        for row in reader:
            contacts.append({
                'name': row[fieldmap['name']].strip(),
                'address': row[fieldmap['address']].strip(),
                'phone': row[fieldmap['phone']].strip(),
            })
    return contacts


def main():
    parser = argparse.ArgumentParser(
        description="Find contacts within a given radius of a reference address."
    )
    parser.add_argument("csv_file", help="Path to CSV file with name, address, phone columns")
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.is_file():
        sys.exit(f"File not found: {csv_path}")

    contacts = load_contacts(csv_path)
    if not contacts:
        sys.exit("No contacts found in CSV file.")

    ref_address = prompt_reference_address()
    radius_miles = prompt_radius()

    geolocator = Nominatim(user_agent=GEOCODE_USER_AGENT)

    print(f"\nGeocoding reference address: {ref_address}")
    ref_location = geocode_with_retry(geolocator, ref_address)
    if ref_location is None:
        sys.exit("Could not geocode the reference address. Please check it and try again.")
    ref_coords = (ref_location.latitude, ref_location.longitude)
    print(f"  -> {ref_location.latitude:.6f}, {ref_location.longitude:.6f}")

    print(
        f"\nGeocoding {len(contacts)} contact address(es)... this may take a while "
        f"(~{REQUEST_DELAY_SECONDS:.0f}s per address, to respect the free geocoding service)."
    )

    matches = []
    for i, contact in enumerate(contacts, 1):
        print(f"[{i}/{len(contacts)}] {contact['name']}: {contact['address']}")
        location = geocode_with_retry(geolocator, contact['address'])
        time.sleep(REQUEST_DELAY_SECONDS)

        if location is None:
            continue

        contact_coords = (location.latitude, location.longitude)
        distance_miles = geodesic(ref_coords, contact_coords).miles

        if distance_miles <= radius_miles:
            matches.append({**contact, 'distance_miles': round(distance_miles, 2)})

    matches.sort(key=lambda c: c['distance_miles'])

    print(f"\n{'=' * 60}")
    print(f"Contacts within {radius_miles} miles of {ref_address}:")
    print(f"{'=' * 60}")
    if not matches:
        print("No matches found.")
    else:
        for m in matches:
            print(
                f"{m['name']:30s} {m['distance_miles']:>6.2f} mi   "
                f"{m['address']:40s} {m['phone']}"
            )

    if matches:
        out_path = csv_path.with_name(csv_path.stem + "_matches.csv")
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['name', 'address', 'phone', 'distance_miles'])
            writer.writeheader()
            writer.writerows(matches)
        print(f"\nResults also saved to: {out_path}")


if __name__ == "__main__":
    main()