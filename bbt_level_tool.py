import argparse
import json
import os
import sys


HEADER_SIZE = 16


def detect_dimensions(header, total_size):
    candidates = [
        (0, 1),
        (1, 2),
    ]

    matches = []
    for width_index, height_index in candidates:
        width = header[width_index]
        height = header[height_index]
        expected_size = HEADER_SIZE + (width * height)
        if expected_size == total_size:
            matches.append((width, height, width_index, height_index))

    if not matches:
        raise ValueError(
            f"File size does not match known width/height header layouts: "
            f"got {total_size} bytes"
        )

    return matches[0]


def parse_level_bytes(data):
    if len(data) < HEADER_SIZE:
        raise ValueError("File is too small to contain a valid level header")

    header = list(data[:HEADER_SIZE])
    width, height, width_index, height_index = detect_dimensions(header, len(data))
    expected_size = HEADER_SIZE + (width * height)

    if len(data) != expected_size:
        raise ValueError(
            f"File size does not match width/height from header: "
            f"got {len(data)} bytes, expected {expected_size} for {width}x{height}"
        )

    tile_bytes = list(data[HEADER_SIZE:])
    rows = []
    for row_index in range(height):
        start = row_index * width
        end = start + width
        rows.append(tile_bytes[start:end])

    return {
        "width": width,
        "height": height,
        "width_index": width_index,
        "height_index": height_index,
        "header_bytes": header,
        "header_hex": [f"{value:02X}" for value in header],
        "tiles": rows,
    }


def build_level_bytes(level_data):
    width = int(level_data["width"])
    height = int(level_data["height"])
    header_bytes = list(level_data["header_bytes"])
    tiles = level_data["tiles"]
    width_index = int(level_data.get("width_index", 0))
    height_index = int(level_data.get("height_index", 1))

    if len(header_bytes) != HEADER_SIZE:
        raise ValueError(f"header_bytes must contain exactly {HEADER_SIZE} values")

    if header_bytes[width_index] != width or header_bytes[height_index] != height:
        raise ValueError("header_bytes width/height positions must match width and height")

    if len(tiles) != height:
        raise ValueError(f"tiles must contain exactly {height} rows")

    flat_tiles = []
    for row in tiles:
        if len(row) != width:
            raise ValueError(f"Each tile row must contain exactly {width} values")
        flat_tiles.extend(int(value) & 0xFF for value in row)

    return bytes((int(value) & 0xFF) for value in header_bytes + flat_tiles)


def export_level(input_path, output_path):
    with open(input_path, "rb") as file_obj:
        data = file_obj.read()

    parsed = parse_level_bytes(data)

    with open(output_path, "w", encoding="utf-8") as file_obj:
        json.dump(parsed, file_obj, indent=2)
        file_obj.write("\n")

    print(f"Exported {input_path} -> {output_path}")
    print(f"  width: {parsed['width']}")
    print(f"  height: {parsed['height']}")


def import_level(input_path, output_path):
    with open(input_path, "r", encoding="utf-8") as file_obj:
        level_data = json.load(file_obj)

    built = build_level_bytes(level_data)

    with open(output_path, "wb") as file_obj:
        file_obj.write(built)

    print(f"Imported {input_path} -> {output_path}")
    print(f"  size: {len(built)} bytes")


def main():
    parser = argparse.ArgumentParser(
        description="Export/import BattleBlock Theater plain level files to a JSON format."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a plain level file to JSON")
    export_parser.add_argument("input_file", help="Input plain level file")
    export_parser.add_argument("output_json", nargs="?", help="Output JSON path")

    import_parser = subparsers.add_parser("import", help="Build a plain level file from JSON")
    import_parser.add_argument("input_json", help="Input JSON file")
    import_parser.add_argument("output_file", nargs="?", help="Output plain level file")

    args = parser.parse_args()

    if args.command == "export":
        input_path = os.path.abspath(args.input_file)
        output_path = os.path.abspath(args.output_json or (args.input_file + ".json"))
        export_level(input_path, output_path)
        return

    if args.command == "import":
        input_path = os.path.abspath(args.input_json)
        default_output = os.path.splitext(args.input_json)[0] + ".bin"
        output_path = os.path.abspath(args.output_file or default_output)
        import_level(input_path, output_path)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
