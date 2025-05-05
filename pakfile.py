import os
import sys
import struct
import tempfile
import zipfile
import difflib
import hashlib
from collections import defaultdict

BSP_SIGNATURE = 0x50534256
BSP_LUMP_PAKFILE = 40


def extract_pakfile(bsp_path):
    """Extract the pakfile from a BSP file and return it as bytes."""
    try:
        with open(bsp_path, 'rb') as f:
            # Read header
            signature = struct.unpack('<I', f.read(4))[0]
            if signature != BSP_SIGNATURE:
                print(f"Error: Invalid BSP signature: {signature:X}")
                return None

            # Navigate to the pakfile lump entry
            f.seek(4 + 4 + BSP_LUMP_PAKFILE * 16)

            # Read lump info
            offset = struct.unpack('<I', f.read(4))[0]
            length = struct.unpack('<I', f.read(4))[0]
            version = struct.unpack('<I', f.read(4))[0]
            uncompressed_length = struct.unpack('<I', f.read(4))[0]

            if offset == 0 or length == 0:
                print("Error: BSP has no pakfile lump")
                return None

            # Read pakfile data
            f.seek(offset)
            pak_data = f.read(length)

            return pak_data

    except Exception as e:
        print(f"Error extracting pakfile: {e}")
        return None


def analyze_zip_structure(zip_data):
    """Analyze the structure of a ZIP file without extracting it."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
        temp_zip.write(zip_data)
        temp_zip_path = temp_zip.name

    try:
        result = {
            'files': [],
            'directories': [],
            'file_count': 0,
            'total_size': 0,
            'compressed_size': 0,
            'file_hashes': {}
        }

        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            for info in zip_ref.infolist():
                if info.filename.endswith('/'):
                    result['directories'].append(info.filename)
                else:
                    result['files'].append(info.filename)
                    result['file_count'] += 1
                    result['total_size'] += info.file_size
                    result['compressed_size'] += info.compress_size

                    # Calculate hash of file content
                    with zip_ref.open(info) as f:
                        content = f.read()
                        result['file_hashes'][info.filename] = hashlib.md5(content).hexdigest()

        return result

    except Exception as e:
        print(f"Error analyzing ZIP structure: {e}")
        return None

    finally:
        os.unlink(temp_zip_path)


def compare_pakfiles(bsp1_path, bsp2_path):
    """Compare pakfiles from two BSP files."""
    pak1_data = extract_pakfile(bsp1_path)
    pak2_data = extract_pakfile(bsp2_path)

    if pak1_data is None or pak2_data is None:
        return False

    print(f"\nPakfile comparison: {os.path.basename(bsp1_path)} vs {os.path.basename(bsp2_path)}")
    print(f"Pakfile 1 size: {len(pak1_data)} bytes")
    print(f"Pakfile 2 size: {len(pak2_data)} bytes")

    # Quick binary comparison
    if pak1_data == pak2_data:
        print("Binary comparison: Pakfiles are identical!")
        return True

    print("Binary comparison: Pakfiles differ")

    # Analyze ZIP structure
    pak1_structure = analyze_zip_structure(pak1_data)
    pak2_structure = analyze_zip_structure(pak2_data)

    if pak1_structure is None or pak2_structure is None:
        return False

    # Compare ZIP structure
    print(f"\nZIP structure comparison:")
    print(f"Pakfile 1: {pak1_structure['file_count']} files, {len(pak1_structure['directories'])} directories")
    print(f"Pakfile 2: {pak2_structure['file_count']} files, {len(pak2_structure['directories'])} directories")

    # Calculate differences in file list
    files1_set = set(pak1_structure['files'])
    files2_set = set(pak2_structure['files'])

    only_in_1 = files1_set - files2_set
    only_in_2 = files2_set - files1_set
    common_files = files1_set.intersection(files2_set)

    # Check for different file contents
    different_content = []
    for file in common_files:
        if pak1_structure['file_hashes'][file] != pak2_structure['file_hashes'][file]:
            different_content.append(file)

    print(f"\nFile comparison:")
    print(f"Files only in {os.path.basename(bsp1_path)}: {len(only_in_1)}")
    if only_in_1:
        for i, file in enumerate(sorted(only_in_1)):
            if i < 20:  # Limit output to 20 files
                print(f"  - {file}")
            else:
                print(f"  ... and {len(only_in_1) - 20} more")
                break

    print(f"Files only in {os.path.basename(bsp2_path)}: {len(only_in_2)}")
    if only_in_2:
        for i, file in enumerate(sorted(only_in_2)):
            if i < 20:  # Limit output to 20 files
                print(f"  - {file}")
            else:
                print(f"  ... and {len(only_in_2) - 20} more")
                break

    print(f"Files with different content: {len(different_content)}")
    if different_content:
        for i, file in enumerate(sorted(different_content)):
            if i < 20:  # Limit output to 20 files
                print(f"  - {file}")
            else:
                print(f"  ... and {len(different_content) - 20} more")
                break

    # Check for ZIP metadata differences (compression method, timestamps, etc.)
    print("\nChecking for ZIP metadata differences...")
    temp1 = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    temp2 = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    try:
        temp1.write(pak1_data)
        temp2.write(pak2_data)
        temp1.close()
        temp2.close()

        meta_differences = defaultdict(list)

        with zipfile.ZipFile(temp1.name, 'r') as zip1, zipfile.ZipFile(temp2.name, 'r') as zip2:
            # Check files that exist in both
            for file in common_files:
                info1 = zip1.getinfo(file)
                info2 = zip2.getinfo(file)

                if info1.compress_type != info2.compress_type:
                    meta_differences['compression_method'].append(file)

                if info1.date_time != info2.date_time:
                    meta_differences['timestamp'].append(file)

                if info1.external_attr != info2.external_attr:
                    meta_differences['attributes'].append(file)

                if info1.comment != info2.comment:
                    meta_differences['comment'].append(file)

        if meta_differences:
            print("Found metadata differences:")
            for diff_type, files in meta_differences.items():
                print(f"  {diff_type}: {len(files)} files differ")
        else:
            print("No ZIP metadata differences found for common files.")

    finally:
        os.unlink(temp1.name)
        os.unlink(temp2.name)

    # Check for ZIP structure differences (central directory, etc.)
    print("\nZIP structure binary comparison:")
    if len(pak1_data) > 1000 and len(pak2_data) > 1000:
        # Check first 100 bytes (local file header)
        if pak1_data[:100] != pak2_data[:100]:
            print("  First 100 bytes (headers) differ")
            print(f"  Pak1 header: {pak1_data[:20].hex()}")
            print(f"  Pak2 header: {pak2_data[:20].hex()}")
        else:
            print("  First 100 bytes (headers) are identical")

        # Check last 1000 bytes (central directory)
        if pak1_data[-1000:] != pak2_data[-1000:]:
            print("  Last 1000 bytes (central directory) differ")
        else:
            print("  Last 1000 bytes (central directory) are identical")

    return True


compare_pakfiles("pl_borneo.bsp", "pl_borneo_new.bsp")
