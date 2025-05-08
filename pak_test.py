import os
import sys
import struct
import tempfile
import zipfile
import shutil
import json
import time
from pathlib import Path

# Constants
BSP_SIGNATURE = 0x50534256
BSP_LUMP_PAKFILE = 40

# Define compression methods (including method 14 for LZMA)
ZIP_STORED = 0
ZIP_DEFLATED = 8
ZIP_BZIP2 = 12
ZIP_LZMA = 14


def extract_pakfile(bsp_path, output_dir=None):
    """Extract the pakfile from a BSP file to a directory."""
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="pakfile_")
    else:
        os.makedirs(output_dir, exist_ok=True)

    print(f"Extracting pakfile from {bsp_path} to {output_dir}")

    try:
        with open(bsp_path, 'rb') as f:
            # Read header
            signature = struct.unpack('<I', f.read(4))[0]
            if signature != BSP_SIGNATURE:
                print(f"Error: Invalid BSP signature: {signature:X}")
                return None

            version = struct.unpack('<I', f.read(4))[0]

            # Navigate to the pakfile lump entry
            f.seek(8 + BSP_LUMP_PAKFILE * 16)

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

            # Save the raw pakfile for later reference
            with open(os.path.join(output_dir, "_pakfile.raw"), 'wb') as p:
                p.write(pak_data)

            # Extract ZIP contents
            temp_zip_path = os.path.join(output_dir, "_pakfile.zip")
            with open(temp_zip_path, 'wb') as z:
                z.write(pak_data)

            try:
                file_count = 0
                dir_count = 0

                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    # Create metadata storage
                    metadata = {
                        'compression_methods': {},
                        'timestamps': {},
                        'external_attrs': {},
                        'comments': {}
                    }

                    # First pass: count compression methods
                    compression_stats = {}

                    for file_info in zip_ref.infolist():
                        method = file_info.compress_type
                        if method not in compression_stats:
                            compression_stats[method] = 0
                        compression_stats[method] += 1

                    # Print compression method statistics
                    print("\nCompression methods used in this pakfile:")
                    for method, count in compression_stats.items():
                        method_name = "Unknown"
                        if method == ZIP_STORED:
                            method_name = "STORED (no compression)"
                        elif method == ZIP_DEFLATED:
                            method_name = "DEFLATED"
                        elif method == ZIP_BZIP2:
                            method_name = "BZIP2"
                        elif method == ZIP_LZMA:
                            method_name = "LZMA"
                        print(f"  Method {method} ({method_name}): {count} files")

                    # Extract all files
                    for file_info in zip_ref.infolist():
                        if file_info.filename.endswith('/'):
                            # It's a directory
                            dir_path = os.path.join(output_dir, file_info.filename)
                            os.makedirs(dir_path, exist_ok=True)

                            # Record directory metadata
                            metadata['timestamps'][file_info.filename] = file_info.date_time
                            metadata['external_attrs'][file_info.filename] = file_info.external_attr
                            if file_info.comment:
                                metadata['comments'][file_info.filename] = file_info.comment.decode('utf-8',
                                                                                                    errors='ignore')

                            dir_count += 1
                            continue

                        # It's a file
                        target_path = os.path.join(output_dir, file_info.filename)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)

                        with zip_ref.open(file_info) as source, open(target_path, 'wb') as target:
                            shutil.copyfileobj(source, target)

                        # Record file metadata
                        metadata['compression_methods'][file_info.filename] = file_info.compress_type
                        metadata['timestamps'][file_info.filename] = file_info.date_time
                        metadata['external_attrs'][file_info.filename] = file_info.external_attr
                        if file_info.comment:
                            metadata['comments'][file_info.filename] = file_info.comment.decode('utf-8',
                                                                                                errors='ignore')

                        file_count += 1

                    # Save metadata for recompression
                    with open(os.path.join(output_dir, "_pakfile_metadata.json"), 'w') as meta_file:
                        json.dump(metadata, meta_file, indent=2)

                print(f"Extracted {file_count} files and {dir_count} directories from pakfile")

            except zipfile.BadZipFile:
                print("Error: Pakfile is not a valid ZIP file")
                return None

            # Clean up temp zip
            os.remove(temp_zip_path)

            return output_dir

    except Exception as e:
        print(f"Error extracting pakfile: {e}")
        import traceback
        traceback.print_exc()
        return None


def has_lzma_support():
    """Check if the current Python installation supports LZMA compression in zipfile."""
    try:
        # Try to access the ZIP_LZMA attribute
        return hasattr(zipfile, 'ZIP_LZMA')
    except AttributeError:
        return False


def create_pakfile(input_dir):
    """Create a ZIP file from a directory, preserving original compression methods."""
    print(f"Creating new pakfile from {input_dir}")

    # Check if we have LZMA support
    lzma_supported = has_lzma_support()
    if not lzma_supported:
        print("WARNING: LZMA compression is not supported in this Python installation.")
        print("Files that originally used LZMA compression will use DEFLATED instead.")

    # Check for metadata from original pakfile
    metadata = None
    metadata_path = os.path.join(input_dir, "_pakfile_metadata.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            print("Found original pakfile metadata, will use it for recompression")
        except Exception as e:
            print(f"Warning: Could not read pakfile metadata: {e}")
            metadata = None

    # Create a temporary ZIP file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
        temp_zip_path = temp_zip.name

    # Collect all files and directories
    all_files = []
    all_dirs = []

    for root, dirs, files in os.walk(input_dir):
        for dir_name in dirs:
            if dir_name.startswith('_pakfile'):
                continue  # Skip metadata directories

            dir_path = os.path.join(root, dir_name)
            rel_dir = os.path.relpath(dir_path, input_dir)
            if rel_dir != '.':  # Skip root directory
                all_dirs.append(rel_dir.replace('\\', '/') + '/')

        for file_name in files:
            if file_name.startswith('_pakfile'):
                continue  # Skip metadata files

            file_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(file_path, input_dir)
            all_files.append((file_path, rel_path.replace('\\', '/')))

    # Create a new ZIP
    with zipfile.ZipFile(temp_zip_path, 'w') as zip_ref:
        # First add all directories to preserve structure
        for dir_path in sorted(all_dirs):  # Sort for consistent ordering
            # Create directory entry - use original timestamp if available
            dir_info = zipfile.ZipInfo(dir_path)

            # Apply directory metadata if available
            if metadata and dir_path in metadata['timestamps']:
                dir_info.date_time = tuple(metadata['timestamps'][dir_path])
            else:
                dir_info.date_time = time.localtime(time.time())[:6]

            if metadata and dir_path in metadata['external_attrs']:
                dir_info.external_attr = metadata['external_attrs'][dir_path]
            else:
                dir_info.external_attr = 0o40755 << 16  # Default directory permissions

            if metadata and dir_path in metadata.get('comments', {}):
                dir_info.comment = metadata['comments'][dir_path].encode('utf-8')

            zip_ref.writestr(dir_info, '')

        # Then add all files with their original compression methods
        compression_used = {'kept_original': 0, 'changed': 0}

        for file_path, rel_path in sorted(all_files):  # Sort for consistent ordering
            file_info = zipfile.ZipInfo(rel_path)

            # Apply file metadata if available
            if metadata and rel_path in metadata['timestamps']:
                file_info.date_time = tuple(metadata['timestamps'][rel_path])
            else:
                file_info.date_time = time.localtime(os.path.getmtime(file_path))[:6]

            if metadata and rel_path in metadata['external_attrs']:
                file_info.external_attr = metadata['external_attrs'][rel_path]
            else:
                file_info.external_attr = 0o644 << 16  # Default file permissions

            if metadata and rel_path in metadata.get('comments', {}):
                file_info.comment = metadata['comments'][rel_path].encode('utf-8')

            # Determine compression method
            original_method = None
            if metadata and rel_path in metadata['compression_methods']:
                original_method = metadata['compression_methods'][rel_path]

            # For new files or existing files, use LZMA if supported, otherwise DEFLATED
            if original_method is None:
                # This is a newly added file
                if lzma_supported:
                    compression_method = zipfile.ZIP_LZMA
                    print(f"New file {rel_path} will use LZMA compression")
                else:
                    compression_method = zipfile.ZIP_DEFLATED
                    print(f"New file {rel_path} will use DEFLATED compression (LZMA not supported)")
            else:
                # Use original compression method
                if original_method == ZIP_STORED:
                    compression_method = ZIP_STORED
                elif original_method == ZIP_DEFLATED:
                    compression_method = ZIP_DEFLATED
                elif original_method == ZIP_BZIP2 and hasattr(zipfile, 'ZIP_BZIP2'):
                    compression_method = zipfile.ZIP_BZIP2
                elif original_method == ZIP_LZMA and lzma_supported:
                    compression_method = zipfile.ZIP_LZMA
                elif original_method == ZIP_LZMA and not lzma_supported:
                    # Fall back to DEFLATED for LZMA if not supported
                    compression_method = ZIP_DEFLATED
                    print(f"Warning: File {rel_path} originally used LZMA compression, falling back to DEFLATED")
                else:
                    # For unknown or unsupported methods, default to STORED
                    print(f"Warning: File {rel_path} had unknown compression method {original_method}, using STORED")
                    compression_method = ZIP_STORED

            # Read file data
            with open(file_path, 'rb') as f:
                file_data = f.read()

            # Set compression method and store file
            try:
                file_info.compress_type = compression_method
                zip_ref.writestr(file_info, file_data)

                if original_method == compression_method:
                    compression_used['kept_original'] += 1
                else:
                    compression_used['changed'] += 1

            except Exception as e:
                print(f"Error compressing {rel_path} with method {compression_method}: {e}")
                # Fall back to stored
                file_info.compress_type = ZIP_STORED
                zip_ref.writestr(file_info, file_data)

    # Read the compressed data
    with open(temp_zip_path, 'rb') as f:
        zip_data = f.read()

    # Clean up
    os.unlink(temp_zip_path)

    print(f"Created new pakfile ({len(zip_data)} bytes)")
    print(
        f"Compression stats: {compression_used['kept_original']} files kept original method, {compression_used['changed']} files used different method")
    return zip_data


def rebuild_bsp(bsp_path, new_pakfile_data, output_bsp_path=None):
    """Rebuild a BSP file with a new pakfile."""
    if output_bsp_path is None:
        output_bsp_path = f"{bsp_path}.new"

    print(f"Rebuilding BSP with new pakfile...")
    print(f"Input:  {bsp_path}")
    print(f"Output: {output_bsp_path}")

    try:
        # Read the original BSP
        with open(bsp_path, 'rb') as f:
            bsp_data = bytearray(f.read())

        # Get the pakfile lump entry
        lump_entry_offset = 8 + BSP_LUMP_PAKFILE * 16
        offset = struct.unpack('<I', bsp_data[lump_entry_offset:lump_entry_offset + 4])[0]
        length = struct.unpack('<I', bsp_data[lump_entry_offset + 4:lump_entry_offset + 8])[0]

        # Create the new BSP file
        with open(output_bsp_path, 'wb') as f:
            # Write everything up to the pakfile
            f.write(bsp_data[:offset])

            # Write our new pakfile
            f.write(new_pakfile_data)

            # If there's data after the pakfile, append it
            if offset + length < len(bsp_data):
                f.write(bsp_data[offset + length:])

        # Update lump length in header
        new_length = len(new_pakfile_data)
        with open(output_bsp_path, 'r+b') as f:
            f.seek(lump_entry_offset + 4)
            f.write(struct.pack('<I', new_length))

        print(f"Successfully rebuilt BSP with new pakfile")
        print(f"Original pakfile size: {length} bytes")
        print(f"New pakfile size: {new_length} bytes")
        if length > 0:
            print(f"Size change: {new_length - length} bytes ({((new_length / length) - 1) * 100:.2f}%)")

        return True

    except Exception as e:
        print(f"Error rebuilding BSP: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python pakfile_with_lzma.py <bsp_path> [output_bsp_path]")
        print("  If no output path is provided, <bsp_path>.new will be used")
        return

    bsp_path = sys.argv[1]
    output_bsp_path = sys.argv[2] if len(sys.argv) > 2 else f"{bsp_path}.new"

    # Extract name without extension for the extraction directory
    bsp_name = Path(bsp_path).stem
    extract_dir = bsp_name

    # Check if LZMA is supported
    if has_lzma_support():
        print("LZMA compression is supported in this Python installation")
    else:
        print("WARNING: LZMA compression is not supported in this Python installation")
        print("Files that originally used LZMA compression will use DEFLATED instead")
        print("To use LZMA compression, install Python 3.3+ with the lzma module")

    # Step 1: Extract the pakfile
    pakfile_dir = extract_pakfile(bsp_path, extract_dir)
    if not pakfile_dir:
        return

    print(f"\nPakfile extracted to {pakfile_dir}")
    print("You can now add or modify files in this directory.")
    input("Press Enter to continue and rebuild the BSP with any changes made...")

    # Step 2: Create a new pakfile matching original compression
    new_pakfile_data = create_pakfile(pakfile_dir)

    # Step 3: Rebuild the BSP
    rebuild_bsp(bsp_path, new_pakfile_data, output_bsp_path)


if __name__ == "__main__":
    main()