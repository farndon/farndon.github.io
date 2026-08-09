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
import json
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
CACHE_FILENAME = "geocode_cache.json"

# The geocoding service sometimes fails to resolve addresses in
# unincorporated communities, so we substitute the enclosing county name when
# querying the geocoder. The original text is preserved everywhere else
# (display, CSV output, cache key) so results still show "Granite Bay", for example
# add more such places in the list below
GEOCODE_SUBSTITUTIONS = {
    "granite bay": "Placer County",
    "antelope": "Sacramento County",
}


def prepare_geocode_query(address):
    """
    Returns the address string to send to the geocoder, substituting any
    known problem place names (e.g. "Granite Bay" -> "Placer County") while
    leaving the original `address` untouched for display purposes.
    """
    query = address
    lower = address.lower()
    for needle, replacement in GEOCODE_SUBSTITUTIONS.items():
        if needle in lower:
            idx = lower.find(needle)
            query = query[:idx] + replacement + query[idx + len(needle):]
            lower = query.lower()
    return query

#==================================================
# load_cache
# If the .json cache file exists, load it and use it
# If the file is missing we will rebuild it by
# resubmitting all addresses to the geo server
#==================================================
def load_cache(cache_path):
    if cache_path.is_file():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not read cache file ({e}); starting with an empty cache.")
    return {}

#=========================================
# save_cache
# Saves the json geo location cache file
#=========================================
def save_cache(cache_path, cache):
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except OSError as e:
        print(f"Warning: could not write cache file: {e}")

#==========================================================
# prompt_reference_address
# Prompt user for the refrence address to include
# number and street, city and state
# Elected to leave zip code off since we might not know it
#==========================================================
def prompt_reference_address():
    print("Enter the reference street address to compare against:")
    street = input("  Street address (number and street name): ").strip()
    city = input("  City: ").strip()
    state = input("  State: ").strip()
    return f"{street}, {city}, {state}"

#===================================================
# prompt_radius
# Prompt user for the radius in miles .1 LSB
#===================================================
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

#===========================================================================
def geocode_cached(geolocator, address, cache, retries=3):
    """
    Returns (latitude, longitude, was_cached) for the given address, or
    (None, None, False) if it could not be geocoded. Results are stored in
    and served from the `cache` dict (address string -> {"lat":.., "lon":..}
    or None for a known-bad address). The `address` passed in and used as
    the cache key is the original display address; a substituted version
    (see GEOCODE_SUBSTITUTIONS) is sent to the geocoding service itself.
    """
    if address in cache:
        cached = cache[address]
        if cached is None:
            return None, None, True
        return cached['lat'], cached['lon'], True

    query = prepare_geocode_query(address)

    for attempt in range(retries):
        try:
            location = geolocator.geocode(query, timeout=10)
            if location is None:
                cache[address] = None
                return None, None, False
            cache[address] = {'lat': location.latitude, 'lon': location.longitude}
            return location.latitude, location.longitude, False
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            if attempt == retries - 1:
                print(f"  Warning: could not geocode '{address}': {e}")
                cache[address] = None
                return None, None, False
            time.sleep(1.0)
    return None, None, False

#==============================================================
# load_contacts
# Loads the contacts from the contacts csv file
# This would contain everybody in the set of people to search on
#==============================================================
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

#=======================
# main
#=======================
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

    cache_path = csv_path.with_name(CACHE_FILENAME)
    cache = load_cache(cache_path)
    print(f"Loaded {len(cache)} cached geocode result(s) from {cache_path}")

    ref_address = prompt_reference_address()
    radius_miles = prompt_radius()

    geolocator = Nominatim(user_agent=GEOCODE_USER_AGENT)

    print(f"\nGeocoding reference address: {ref_address}")
    try:
        ref_lat, ref_lon, was_cached = geocode_cached(geolocator, ref_address, cache)
        if not was_cached:
            time.sleep(REQUEST_DELAY_SECONDS)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl-C). Saving progress before exiting...")
        save_cache(cache_path, cache)
        print(f"Cache saved to {cache_path} ({len(cache)} entries)")
        sys.exit(130)
    if ref_lat is None:
        save_cache(cache_path, cache)
        sys.exit("Could not geocode the reference address. Please check it and try again.")
    ref_coords = (ref_lat, ref_lon)
    print(f"  -> {ref_lat:.6f}, {ref_lon:.6f}" + (" (from cache)" if was_cached else ""))

    print(
        f"\nGeocoding {len(contacts)} contact address(es)... this may take a while "
        f"(~{REQUEST_DELAY_SECONDS:.0f}s per new address; cached addresses are instant)."
    )

    matches = []
    failed = []
    try:
        for i, contact in enumerate(contacts, 1):
            print(f"[{i}/{len(contacts)}] {contact['name']}: {contact['address']}")
            lat, lon, was_cached = geocode_cached(geolocator, contact['address'], cache)
            if not was_cached:
                time.sleep(REQUEST_DELAY_SECONDS)
                if i % 10 == 0:
                    save_cache(cache_path, cache)  # periodic save so progress isn't lost

            if lat is None:
                print(f"  ERROR: could not geocode address for '{contact['name']}': "
                      f"{contact['address']}")
                failed.append(contact)
                continue

            contact_coords = (lat, lon)
            distance_miles = geodesic(ref_coords, contact_coords).miles

            if distance_miles <= radius_miles:
                matches.append({**contact, 'distance_miles': round(distance_miles, 2)})
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl-C). Saving progress before exiting...")
        save_cache(cache_path, cache)
        print(f"Cache saved to {cache_path} ({len(cache)} entries)")
        if matches:
            partial_path = csv_path.with_name(csv_path.stem + "_matches_partial.csv")
            with open(partial_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f, fieldnames=['name', 'address', 'phone', 'distance_miles']
                )
                writer.writeheader()
                writer.writerows(sorted(matches, key=lambda c: c['distance_miles']))
            print(f"Partial results ({len(matches)} match(es) found so far) saved to: "
                  f"{partial_path}")
        else:
            print("No matches had been found yet.")
        sys.exit(130)

    save_cache(cache_path, cache)
    print(f"Cache saved to {cache_path} ({len(cache)} entries)")

    if failed:
        print(f"\n{'=' * 60}")
        print(f"WARNING: {len(failed)} address(es) could not be geocoded and were "
              f"excluded from results:")
        print(f"{'=' * 60}")
        for c in failed:
            print(f"  {c['name']:30s} {c['address']}")

    matches.sort(key=lambda c: c['distance_miles'])

    print(f"\n{'=' * 70}")
    print(f"Contacts within {radius_miles} miles of {ref_address}:")
    print(f"{'=' * 70}")
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

    if failed:
        failed_path = csv_path.with_name(csv_path.stem + "_geocode_failures.csv")
        with open(failed_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['name', 'address', 'phone'])
            writer.writeheader()
            writer.writerows(failed)
        print(f"Addresses that failed to geocode saved to: {failed_path}")

#================================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl-C). Exiting.")
        sys.exit(130)
