import argparse
import json
import os

from hexdump_playlist_tool import export_playlist_bytes, import_playlist_bytes, load_template_bytes, parse_name_table
from rebuild_ebt import CipherState, HEADER_SIZE, load_key, resolve_local_path


def get_default_basename(path):
    basename = os.path.basename(path).upper()
    stem, _, _ = basename.rpartition(".")
    return stem or basename


def decrypt_ebt_payload(ebt_bytes, basename):
    if len(ebt_bytes) < HEADER_SIZE:
        raise ValueError("Input .ebt is too small")

    encrypted = ebt_bytes[HEADER_SIZE:]
    if len(encrypted) % 8 != 0:
        raise ValueError("Encrypted .ebt payload is not 8-byte aligned")

    state = CipherState(
        load_key(resolve_local_path("key1")),
        load_key(resolve_local_path("key2")),
        basename.upper(),
    )
    state.descramble()

    out = bytearray()
    for offset in range(0, len(encrypted), 8):
        out.extend(state.decrypt_block(encrypted[offset:offset + 8]))
    return bytes(out)


def encrypt_ebt_payload(raw_bytes, template_ebt, basename):
    if len(template_ebt) < HEADER_SIZE:
        raise ValueError("Template .ebt is too small")

    padded_raw = raw_bytes
    if len(padded_raw) % 8 != 0:
        padded_raw += b"\x00" * (8 - (len(padded_raw) % 8))

    encrypted_region_end = HEADER_SIZE + len(padded_raw)
    if encrypted_region_end > len(template_ebt):
        raise ValueError(
            f"Encrypted payload would exceed template size: need {encrypted_region_end}, have {len(template_ebt)}"
        )

    state = CipherState(
        load_key(resolve_local_path("key1")),
        load_key(resolve_local_path("key2")),
        basename.upper(),
    )
    state.descramble()

    out = bytearray(template_ebt)
    for offset in range(0, len(padded_raw), 8):
        block = padded_raw[offset:offset + 8]
        out[HEADER_SIZE + offset:HEADER_SIZE + offset + 8] = state.encrypt_block(block)
    return bytes(out), len(padded_raw)


def extract_raw_playlist_bytes(decrypted_payload):
    names, records_offset = parse_name_table(decrypted_payload)
    if len(names) < 2:
        raise ValueError("Could not parse playlist names from decrypted .ebt payload")

    # Keep the full decrypted payload. The embedded level records are not laid
    # out as one simple contiguous list, so trimming to the first sequential
    # parse can drop most of the playlist data.
    return decrypted_payload, names[0], len(decrypted_payload)


def export_ebt(input_ebt, output_dir, basename_override=None):
    basename = basename_override or get_default_basename(input_ebt)
    with open(input_ebt, "rb") as file_obj:
        ebt_bytes = file_obj.read()

    decrypted = decrypt_ebt_payload(ebt_bytes, basename)
    raw_bytes, playlist_name, raw_size = extract_raw_playlist_bytes(decrypted)

    export_playlist_bytes(
        raw_bytes,
        output_dir,
        source_label=None,
        extra_manifest={
            "source_ebt_file": input_ebt,
            "basename": basename,
            "playlist_name": playlist_name,
            "source_raw_hex": raw_bytes.hex().upper(),
            "template_ebt_size": len(ebt_bytes),
            "raw_plaintext_size": raw_size,
            "header_size": HEADER_SIZE,
        },
    )

    print(f"Source ebt: {input_ebt}")
    print(f"Basename: {basename}")


def import_ebt(input_dir, output_ebt, template_ebt=None, basename_override=None):
    manifest_path = os.path.join(input_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as file_obj:
        manifest = json.load(file_obj)

    template_path = template_ebt or manifest.get("source_ebt_file")
    if not template_path:
        raise ValueError("No template .ebt path available. Pass --template or export from an .ebt first.")

    basename = basename_override or manifest.get("basename") or get_default_basename(template_path)

    raw_template = load_template_bytes(manifest, template_path=None)
    rebuilt_raw = import_playlist_bytes(input_dir, raw_template)

    with open(template_path, "rb") as file_obj:
        template_bytes = file_obj.read()

    rebuilt_ebt, padded_size = encrypt_ebt_payload(rebuilt_raw, template_bytes, basename)

    with open(output_ebt, "wb") as file_obj:
        file_obj.write(rebuilt_ebt)

    print(f"Template ebt: {template_path}")
    print(f"Basename: {basename}")
    print(f"Raw bytes: {len(rebuilt_raw)}")
    print(f"Padded raw bytes: {padded_size}")
    print(f"Wrote rebuilt ebt: {output_ebt}")


def verify_ebt(input_dir):
    manifest_path = os.path.join(input_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as file_obj:
        manifest = json.load(file_obj)

    raw_template = load_template_bytes(manifest, template_path=None)
    checked = 0

    for entry in manifest["entries"]:
        if entry.get("kind") != "level":
            continue

        json_path = os.path.join(input_dir, entry["json_file"])
        with open(json_path, "r", encoding="utf-8") as file_obj:
            level_data = json.load(file_obj)

        from bbt_level_tool import build_level_bytes

        rebuilt = build_level_bytes(level_data)
        expected_size = int(entry["record_size"])
        offset = int(entry["record_offset"])
        actual = raw_template[offset + 5:offset + 5 + expected_size]

        if len(rebuilt) != expected_size:
            raise ValueError(
                f"{entry['name']}: rebuilt size {len(rebuilt)} does not match expected record size {expected_size}"
            )

        if rebuilt != actual:
            raise ValueError(f"{entry['name']}: JSON does not match source .ebt payload bytes at offset {offset}")

        checked += 1

    print(f"Verified {checked} level records against embedded source bytes")


def main():
    parser = argparse.ArgumentParser(
        description="Direct BattleBlock Theater .ebt exporter/importer for per-level JSON editing."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export an .ebt file directly to per-level JSON")
    export_parser.add_argument("input_ebt", help="Input .ebt file")
    export_parser.add_argument("output_dir", help="Output directory for JSON files")
    export_parser.add_argument("--basename", help="Override the basename used for the playlist key schedule")

    import_parser = subparsers.add_parser("import", help="Rebuild an .ebt directly from per-level JSON")
    import_parser.add_argument("input_dir", help="Directory created by the export command")
    import_parser.add_argument("output_ebt", help="Output rebuilt .ebt file")
    import_parser.add_argument("--template", help="Original .ebt file to use as a template")
    import_parser.add_argument("--basename", help="Override the basename used for the playlist key schedule")

    verify_parser = subparsers.add_parser("verify", help="Verify exported JSON still matches the source .ebt payload")
    verify_parser.add_argument("input_dir", help="Directory created by the export command")

    args = parser.parse_args()

    if args.command == "export":
        export_ebt(os.path.abspath(args.input_ebt), os.path.abspath(args.output_dir), args.basename)
        return

    if args.command == "import":
        import_ebt(
            os.path.abspath(args.input_dir),
            os.path.abspath(args.output_ebt),
            os.path.abspath(args.template) if args.template else None,
            args.basename,
        )
        return

    if args.command == "verify":
        verify_ebt(os.path.abspath(args.input_dir))
        return


if __name__ == "__main__":
    main()
