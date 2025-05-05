import binascii
import os
import sys
import struct
import zipfile
import lzma
import tempfile
import shutil
from collections import defaultdict

BSP_SIGNATURE = 0x50534256
BSP_LUMP_PAKFILE = 40
LZMA_ID = (ord('A') << 24) | (ord('M') << 16) | (ord('Z') << 8) | ord('L')


def extract_pakfile(bsp_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    try:
        with open(bsp_path, 'rb') as f:
            # Read header
            signature = struct.unpack('<I', f.read(4))[0]
            if signature != BSP_SIGNATURE:
                print(f"Error: Invalid BSP signature: {signature:X}")
                return False

            version = struct.unpack('<I', f.read(4))[0]

            # Navigate to the pakfile lump entry
            f.seek(4 + 4 + BSP_LUMP_PAKFILE * 16)

            # Read lump info
            offset = struct.unpack('<I', f.read(4))[0]
            length = struct.unpack('<I', f.read(4))[0]
            version = struct.unpack('<I', f.read(4))[0]
            uncompressed_length = struct.unpack('<I', f.read(4))[0]

            if offset == 0 or length == 0:
                print("Error: BSP has no pakfile lump")
                return False

            # Read pakfile data
            f.seek(offset)
            pak_data = f.read(length)

            # Save the raw pakfile for later
            with open(os.path.join(output_dir, "_pakfile.raw"), 'wb') as p:
                p.write(pak_data)

            # Write to temp file and extract
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
                temp_zip.write(pak_data)
                temp_zip_path = temp_zip.name

            file_count = 0
            try:
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    for file_info in zip_ref.infolist():
                        if file_info.filename.endswith('/'):
                            continue

                        target_path = os.path.join(output_dir, file_info.filename)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)

                        with zip_ref.open(file_info) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                        file_count += 1
            except zipfile.BadZipFile:
                print("Error: Pakfile is not a valid ZIP file")
                os.unlink(temp_zip_path)
                return False

            os.unlink(temp_zip_path)
            print(f"Extracted {file_count} files from pakfile to {output_dir}")
            return True

    except Exception as e:
        print(f"Error extracting pakfile: {e}")
        import traceback
        traceback.print_exc()
        return False


def add_files_to_pakfile(bsp_path, input_dir, output_bsp_path=None):
    if not os.path.exists(input_dir):
        print(f"Error: Input directory does not exist: {input_dir}")
        return False

    if output_bsp_path is None:
        output_bsp_path = bsp_path

    # Check if we have the raw pakfile
    raw_pakfile_path = os.path.join(input_dir, "_pakfile.raw")
    if not os.path.exists(raw_pakfile_path):
        print("Error: Raw pakfile not found. Please extract the pakfile first.")
        return False

    try:
        # For this approach, we'll use the original pakfile and replace individual files
        with open(raw_pakfile_path, 'rb') as f:
            original_pak_data = f.read()

        # Create a temporary extract directory
        temp_extract_dir = tempfile.mkdtemp()

        try:
            # Copy the raw pakfile to a temporary location
            temp_zip_path = os.path.join(temp_extract_dir, "temp.zip")
            with open(temp_zip_path, 'wb') as f:
                f.write(original_pak_data)

            # Now extract all files from the original pakfile
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)

            # Copy new files over the extracted ones
            file_count = 0
            for root, _, files in os.walk(input_dir):
                for file in files:
                    if file == "_pakfile.raw":
                        continue  # Skip our raw pakfile

                    source_path = os.path.join(root, file)
                    relative_path = os.path.relpath(source_path, input_dir)
                    target_path = os.path.join(temp_extract_dir, relative_path)

                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    shutil.copy2(source_path, target_path)
                    file_count += 1

            # Now the simplest approach - directly use the original BSP
            # and just update the files we need to change
            with open(bsp_path, 'rb') as f:
                bsp_data = bytearray(f.read())

            # Get the pakfile lump entry
            lump_entry_offset = 8 + BSP_LUMP_PAKFILE * 16
            offset = struct.unpack('<I', bsp_data[lump_entry_offset:lump_entry_offset + 4])[0]
            length = struct.unpack('<I', bsp_data[lump_entry_offset + 4:lump_entry_offset + 8])[0]

            # Create a new output file
            with open(output_bsp_path, 'wb') as f:
                # Write everything up to the pakfile
                f.write(bsp_data[:offset])

                # Inject our raw pakfile
                f.write(original_pak_data)

                # If there's data after the pakfile, append it
                if offset + length < len(bsp_data):
                    f.write(bsp_data[offset + length:])

            print(f"Updated/preserved {file_count} files in the pakfile")
            print(f"Successfully saved modified BSP to {output_bsp_path}")
            return True

        finally:
            shutil.rmtree(temp_extract_dir)

    except Exception as e:
        print(f"Error adding files to pakfile: {e}")
        import traceback
        traceback.print_exc()
        return False


def compare_bsp_files(original_bsp, modified_bsp):
    try:
        # Read BSP files
        with open(original_bsp, 'rb') as f1:
            original_data = f1.read()

        with open(modified_bsp, 'rb') as f2:
            modified_data = f2.read()

        # Get pakfile lump info from original
        lump_entry_offset = 8 + BSP_LUMP_PAKFILE * 16
        offset = struct.unpack('<I', original_data[lump_entry_offset:lump_entry_offset + 4])[0]
        offset += 32
        # Compare data up to pakfile start
        if len(original_data) < offset or len(modified_data) < offset:
            print("Error: One of the files is too small")
            return False

        # Find all differences up to pakfile
        diff_count = 0
        all_diffs = []
        lump_diffs = defaultdict(list)  # Group differences by lump

        for i in range(min(offset, len(original_data), len(modified_data))):
            if original_data[i] != modified_data[i]:
                diff_count += 1
                all_diffs.append(i)

                # Check if difference is in lump directory
                if i >= 8 and i < 8 + 64 * 16:
                    lump_index = (i - 8) // 16
                    lump_field = (i - 8) % 16 // 4
                    lump_diffs[lump_index].append((lump_field, i))

        if diff_count > 0:
            print(f"Found {diff_count} differences up to pakfile at offset 0x{offset:08X}")

            # Analyze differences in the lump directory
            if lump_diffs:
                print("\n=== LUMP DIRECTORY DIFFERENCES ===")
                field_names = ["Offset", "Length", "Version", "Uncompressed Length"]

                for lump_index, fields in sorted(lump_diffs.items()):
                    lump_start = 8 + lump_index * 16
                    original_lump = original_data[lump_start:lump_start + 16]
                    modified_lump = modified_data[lump_start:lump_start + 16]

                    orig_vals = struct.unpack('<IIII', original_lump)
                    mod_vals = struct.unpack('<IIII', modified_lump)

                    print(f"\nLump #{lump_index} has {len(fields)} field differences:")

                    for i, (orig, mod) in enumerate(zip(orig_vals, mod_vals)):
                        if orig != mod:
                            print(f"  {field_names[i]}: 0x{orig:08X} ({orig}) -> 0x{mod:08X} ({mod})")

            # Show all raw differences in sequential blocks
            print("\n=== ALL BINARY DIFFERENCES ===")

            block_start = None
            for i in range(len(all_diffs)):
                if block_start is None:
                    block_start = all_diffs[i]

                # Check if this is the last diff or if there's a gap to the next diff
                if i == len(all_diffs) - 1 or all_diffs[i + 1] > all_diffs[i] + 16:
                    block_end = all_diffs[i] + 1

                    # Print the block of differences
                    print(
                        f"\nDifferences at offsets 0x{block_start:08X}-0x{block_end - 1:08X} ({block_end - block_start} bytes):")

                    # Show binary view
                    width = 16  # bytes per line
                    for line_start in range(block_start - (block_start % width), block_end + width, width):
                        if line_start + width <= block_start and line_start + width <= block_end:
                            continue  # Skip lines before differences

                        if line_start >= block_end:
                            break  # Skip lines after differences

                        # Print address
                        print(f"0x{line_start:08X}: ", end="")

                        # Print bytes
                        for j in range(width):
                            pos = line_start + j

                            if pos < len(original_data) and pos < len(modified_data):
                                orig_byte = original_data[pos]
                                mod_byte = modified_data[pos]

                                if orig_byte != mod_byte and block_start <= pos < block_end:
                                    # Highlight differences
                                    print(f"[{orig_byte:02X}->{mod_byte:02X}]", end=" ")
                                else:
                                    print(f"{orig_byte:02X}", end=" ")
                            else:
                                print("  ", end=" ")

                        # Print ASCII representation
                        print(" | ", end="")
                        for j in range(width):
                            pos = line_start + j
                            if pos < len(original_data):
                                c = original_data[pos]
                                if 32 <= c <= 126:  # Printable ASCII
                                    print(chr(c), end="")
                                else:
                                    print(".", end="")
                            else:
                                print(" ", end="")
                        print()

                    # Start new block
                    block_start = None

            # If there are a lot of differences, provide summary statistics
            if diff_count > 100:
                # Count differences by region
                region_diffs = {
                    "Header (0-8)": sum(1 for x in all_diffs if x < 8),
                    "Lump Directory (8-1032)": sum(1 for x in all_diffs if 8 <= x < 8 + 64 * 16),
                    "Data Section": sum(1 for x in all_diffs if x >= 8 + 64 * 16)
                }

                print("\n=== DIFFERENCE SUMMARY ===")
                for region, count in region_diffs.items():
                    print(f"{region}: {count} differences")

                # Show difference density (how many bytes differ in each 1KB block)
                print("\nDifference density (changes per 1KB):")
                block_size = 1024
                for i in range(0, offset, block_size):
                    end = min(i + block_size, offset)
                    count = sum(1 for x in all_diffs if i <= x < end)
                    if count > 0:
                        print(f"0x{i:08X}-0x{end - 1:08X}: {count} differences")

            return False
        else:
            print(f"Files are identical up to pakfile at offset 0x{offset:08X} ({offset} bytes)")

            # Also check if pakfile entry in the lump directory is identical
            pakfile_entry_start = 8 + BSP_LUMP_PAKFILE * 16
            pakfile_entry_end = pakfile_entry_start + 16

            if original_data[pakfile_entry_start:pakfile_entry_end] != modified_data[
                                                                       pakfile_entry_start:pakfile_entry_end]:
                print("\nWARNING: Pakfile lump directory entries differ, even though data before pakfile is identical")

                original_entry = struct.unpack('<IIII', original_data[pakfile_entry_start:pakfile_entry_end])
                modified_entry = struct.unpack('<IIII', modified_data[pakfile_entry_start:pakfile_entry_end])

                field_names = ["Offset", "Length", "Version", "Uncompressed Length"]
                print("\nOriginal pakfile entry:")
                for i, name in enumerate(field_names):
                    print(f"  {name}: 0x{original_entry[i]:08X} ({original_entry[i]})")

                print("\nModified pakfile entry:")
                for i, name in enumerate(field_names):
                    print(f"  {name}: 0x{modified_entry[i]:08X} ({modified_entry[i]})")

            return True

    except Exception as e:
        print(f"Error comparing BSP files: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    bsp_path = "pl_borneo.bsp"
    input_dir = "pl_borneo"
    output_bsp = "pl_borneo_new.bsp"
    extract_pakfile(bsp_path, input_dir)
    add_files_to_pakfile(bsp_path, input_dir, output_bsp)
    compare_bsp_files(bsp_path, output_bsp)

if __name__ == "__main__":
    sys.exit(main())