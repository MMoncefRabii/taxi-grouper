#!/usr/bin/env python3
"""Test sequential color assignment for taxi groups (no hash collisions)."""

import sys

# Simulating the _apply_row_colors logic for sequential color assignment
def test_sequential_coloring():
    # Default palette from _load_color_palette()
    palette = [
        "#F6D55C",
        "#ED553B",
        "#3CAEA3",
        "#20639B",
        "#173F5F",
        "#F66B9B",
        "#9B59B6",
        "#2ECC71",
        "#E67E22",
        "#95A5A6",
    ]
    
    # Simulate group_to_rows from the actual data
    # This represents what happens when we have 5 consecutive taxi groups
    group_to_rows = {
        "1": [1, 4],  # Rows 1 and 4 have Groupe Taxi = "1"
        "2": [2, 5],  # Rows 2 and 5 have Groupe Taxi = "2"
        "3": [3, 6],  # Rows 3 and 6 have Groupe Taxi = "3"
        "4": [7],     # Row 7 has Groupe Taxi = "4"
        "5": [8],     # Row 8 has Groupe Taxi = "5"
    }
    
    # Sequential color assignment logic (from the fix)
    def sort_key(k: str):
        try:
            return (0, int(k))  # Numeric keys sort first
        except ValueError:
            return (1, k)  # Then lexicographic

    sorted_keys = sorted(group_to_rows.keys(), key=sort_key)
    key_to_color_index = {key: i % len(palette) for i, key in enumerate(sorted_keys)}
    
    # Print results
    print("=" * 60)
    print("Sequential Color Assignment Test")
    print("=" * 60)
    print(f"\nPalette ({len(palette)} colors):")
    for i, color in enumerate(palette):
        print(f"  {i}: {color}")
    
    print(f"\nTaxi Groups (sorted): {sorted_keys}")
    print("\nColor Mapping (no hash collisions):")
    for key in sorted_keys:
        color_index = key_to_color_index[key]
        color = palette[color_index]
        print(f"  Taxi {key} → Color {color_index} ({color})")
    
    # Verify no collisions for consecutive groups
    print("\nVerification:")
    colors_assigned = [key_to_color_index[key] for key in sorted_keys]
    consecutive_groups = list(range(1, 6))
    
    # Check if any consecutive taxi numbers got the same color
    collision_found = False
    for i in range(len(consecutive_groups) - 1):
        taxi_a = str(consecutive_groups[i])
        taxi_b = str(consecutive_groups[i + 1])
        if taxi_a in key_to_color_index and taxi_b in key_to_color_index:
            color_a = key_to_color_index[taxi_a]
            color_b = key_to_color_index[taxi_b]
            if color_a == color_b:
                print(f"  ✗ COLLISION: Taxi {taxi_a} and Taxi {taxi_b} both got color {color_a}")
                collision_found = True
            else:
                print(f"  ✓ Taxi {taxi_a}: {palette[color_a]} | Taxi {taxi_b}: {palette[color_b]} (different)")
    
    if not collision_found:
        print("\n✓ SUCCESS: No hash collisions for consecutive taxi groups!")
        print("  Sequential assignment ensures each consecutive group gets a unique color.")
        return 0
    else:
        print("\n✗ FAILED: Collisions still exist!")
        return 1

if __name__ == "__main__":
    sys.exit(test_sequential_coloring())
