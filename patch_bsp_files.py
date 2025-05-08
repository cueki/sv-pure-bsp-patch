import os
import struct
import tempfile
import zipfile
import time
import argparse

# constants
BSP_SIGNATURE = 0x50534256
BSP_LUMP_PAKFILE = 40

# compression methods
ZIP_STORED = 0
ZIP_DEFLATED = 8
ZIP_BZIP2 = 12
ZIP_LZMA = 14


def extract_pakfile_info(bsp_path):
    try:
        with open(bsp_path, 'rb') as f:
            # header
            signature = struct.unpack('<I', f.read(4))[0]
            if signature != BSP_SIGNATURE:
                print(f"Error: Invalid BSP signature: {signature:X}")
                return None, None, None

            version = struct.unpack('<I', f.read(4))[0]

            # pakfile lump entry
            f.seek(8 + BSP_LUMP_PAKFILE * 16)
            offset = struct.unpack('<I', f.read(4))[0]
            length = struct.unpack('<I', f.read(4))[0]
            version = struct.unpack('<I', f.read(4))[0]
            uncompressed_length = struct.unpack('<I', f.read(4))[0]

            if offset == 0 or length == 0:
                print(f"Info: BSP has no pakfile lump - will create one")
                return None, offset, length

            # read pakfile data
            f.seek(offset)
            pak_data = f.read(length)

            return pak_data, offset, length

    except Exception as e:
        print(f"Error reading pakfile: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None


def list_pakfile_contents(pak_data):
    if not pak_data:
        return set()

    try:
        # create a temp file to hold the pakfile data
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_zip:
            temp_zip_path = temp_zip.name
            temp_zip.write(pak_data)

        file_list = set()

        try:
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                # first pass: compression methods
                compression_stats = {}

                for file_info in zip_ref.infolist():
                    method = file_info.compress_type
                    if method not in compression_stats:
                        compression_stats[method] = 0
                    compression_stats[method] += 1
                    file_list.add(file_info.filename)

                print("Compression methods used in this pakfile:")
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

                print(f"Found {len(file_list)} files in pakfile")

        except zipfile.BadZipFile:
            print("Error: Pakfile is not a valid ZIP file")
            return set()

        os.unlink(temp_zip_path)
        return file_list

    except Exception as e:
        print(f"Error examining pakfile: {e}")
        import traceback
        traceback.print_exc()
        return set()


def preprocess_assets(assets_dir, existing_files=None, output_dir=None):
    # pre-process assets to create a compressed version ready for addition to map files
    if existing_files is None:
        existing_files = set()

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="assets_")
    else:
        os.makedirs(output_dir, exist_ok=True)

    print(f"Pre-processing assets from {assets_dir}")

    all_files = []
    all_dirs = []
    skipped_files = []

    for root, dirs, files in os.walk(assets_dir):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            rel_dir = os.path.relpath(dir_path, assets_dir)
            if rel_dir != '.':
                rel_dir_path = rel_dir.replace('\\', '/') + '/'
                if rel_dir_path not in existing_files:
                    all_dirs.append(rel_dir_path)

        for file_name in files:
            file_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(file_path, assets_dir).replace('\\', '/')

            if rel_path in existing_files:
                skipped_files.append(rel_path)
            else:
                all_files.append((file_path, rel_path))

    if skipped_files:
        print(f"Skipping {len(skipped_files)} files that already exist in pakfile:")
        for i, file in enumerate(sorted(skipped_files)[:10]):
            print(f"  {file}")
        if len(skipped_files) > 10:
            print(f"  ...and {len(skipped_files) - 10} more")

    # temp zip for pre-processing
    temp_zip_path = os.path.join(output_dir, "_assets.zip")

    with zipfile.ZipFile(temp_zip_path, 'w') as zip_ref:
        # add dirs
        for dir_path in sorted(all_dirs):
            dir_info = zipfile.ZipInfo(dir_path)
            dir_info.date_time = time.localtime(time.time())[:6]
            dir_info.external_attr = 0o40755 << 16
            zip_ref.writestr(dir_info, '')

        # add all files with appropriate compression (lzma or none really)
        for file_path, rel_path in sorted(all_files):
            file_info = zipfile.ZipInfo(rel_path)
            file_info.date_time = time.localtime(os.path.getmtime(file_path))[:6]
            file_info.external_attr = 0o644 << 16

            file_info.compress_type = zipfile.ZIP_LZMA

            with open(file_path, 'rb') as f:
                file_data = f.read()

            # write to zip with the selected compression method
            try:
                zip_ref.writestr(file_info, file_data)
            except Exception as e:
                print(f"Error compressing {rel_path}: {e}")
                # fall back to no compression
                file_info.compress_type = zipfile.ZIP_STORED
                zip_ref.writestr(file_info, file_data)

    return temp_zip_path, len(all_files), len(all_dirs)


def merge_pakfiles(original_pak_data, new_assets_zip_path):
    if not original_pak_data and not os.path.exists(new_assets_zip_path):
        print("Error: Both original pakfile and new assets are missing")
        return None

    # if there's no original pakfile, just return the new assets
    if not original_pak_data:
        with open(new_assets_zip_path, 'rb') as f:
            return f.read()

    # if there are no new assets, just return the original pakfile
    if not os.path.exists(new_assets_zip_path):
        return original_pak_data

    # create a temp zip for the merged result
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_merged:
        temp_merged_path = temp_merged.name

    try:
        # create a temporary file for the original pakfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_original:
            temp_original_path = temp_original.name
            temp_original.write(original_pak_data)

        # open both zip files
        with zipfile.ZipFile(temp_original_path, 'r') as original_zip, \
                zipfile.ZipFile(new_assets_zip_path, 'r') as new_zip, \
                zipfile.ZipFile(temp_merged_path, 'w') as merged_zip:

            # first we do the pakfile
            for file_info in original_zip.infolist():
                # read the file from the original pakfile
                file_data = original_zip.read(file_info.filename)

                # copy the file to the merged pakfile with the same compression
                copied_info = zipfile.ZipInfo(file_info.filename)
                copied_info.date_time = file_info.date_time
                copied_info.external_attr = file_info.external_attr
                copied_info.compress_type = file_info.compress_type

                if file_info.compress_type == 0:
                    copied_info.file_size = file_info.file_size
                    copied_info.CRC = file_info.CRC

                # write to the merged zip
                merged_zip.writestr(copied_info, file_data)

            # these are the new files
            existing_files = {f.filename for f in original_zip.infolist()}
            for file_info in new_zip.infolist():
                if file_info.filename not in existing_files:
                    # read the file from the new assets
                    file_data = new_zip.read(file_info.filename)

                    # Copy the file to the merged pakfile with the same compression
                    copied_info = zipfile.ZipInfo(file_info.filename)
                    copied_info.date_time = file_info.date_time
                    copied_info.external_attr = file_info.external_attr
                    copied_info.compress_type = file_info.compress_type

                    if file_info.compress_type == 0:
                        copied_info.file_size = file_info.file_size
                        copied_info.CRC = file_info.CRC

                    # write to the merged zip
                    merged_zip.writestr(copied_info, file_data)

        # read the merged zip data
        with open(temp_merged_path, 'rb') as f:
            merged_data = f.read()

        # clean up
        os.unlink(temp_original_path)
        os.unlink(temp_merged_path)

        return merged_data

    except Exception as e:
        print(f"Error merging pakfiles: {e}")
        import traceback
        traceback.print_exc()

        if os.path.exists(temp_original_path):
            os.unlink(temp_original_path)
        if os.path.exists(temp_merged_path):
            os.unlink(temp_merged_path)

        return None


def rebuild_bsp(bsp_path, new_pakfile_data, output_bsp_path=None):
    # rebuild a BSP file with a new pakfile
    if output_bsp_path is None:
        output_bsp_path = f"{bsp_path}.new"

    print(f"Rebuilding BSP with new pakfile...")
    print(f"Input:  {bsp_path}")
    print(f"Output: {output_bsp_path}")

    try:
        # read the original BSP
        with open(bsp_path, 'rb') as f:
            bsp_data = bytearray(f.read())

        # get the pakfile lump
        lump_entry_offset = 8 + BSP_LUMP_PAKFILE * 16
        offset = struct.unpack('<I', bsp_data[lump_entry_offset:lump_entry_offset + 4])[0]
        length = struct.unpack('<I', bsp_data[lump_entry_offset + 4:lump_entry_offset + 8])[0]

        # special case for maps without a pakfile
        if offset == 0 or length == 0:
            # need to create a new pakfile
            offset = len(bsp_data)
            length = 0

        # create the new map file
        with open(output_bsp_path, 'wb') as f:
            # write everything up to the pakfile
            f.write(bsp_data[:offset])
            f.write(new_pakfile_data)

            # if there's data after the pakfile, append it
            if offset + length < len(bsp_data):
                f.write(bsp_data[offset + length:])

        # update lump length and offset in header
        new_length = len(new_pakfile_data)
        with open(output_bsp_path, 'r+b') as f:
            f.seek(lump_entry_offset)
            f.write(struct.pack('<I', offset))
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


def batch_process(bsp_dir, assets_dir, output_dir=None, overwrite=False):
    if not os.path.isdir(bsp_dir):
        print(f"Error: BSP directory {bsp_dir} is not a valid directory")
        return False

    if not os.path.isdir(assets_dir):
        print(f"Error: Assets directory {assets_dir} is not a valid directory")
        return False

    if output_dir is None:
        output_dir = os.path.join(bsp_dir, "output")

    os.makedirs(output_dir, exist_ok=True)

    print(f"Batch processing BSP files from {bsp_dir}")
    print(f"Adding assets from {assets_dir}")
    print(f"Output will be saved to {output_dir}")

    bsp_files = []
    for root, _, files in os.walk(bsp_dir):
        for file in files:
            if file.lower().endswith('.bsp'):
                bsp_files.append(os.path.join(root, file))

    if not bsp_files:
        print(f"No BSP files found in {bsp_dir}")
        return False

    print(f"\nFound {len(bsp_files)} BSP files to process")

    success_count = 0
    failure_count = 0

    for bsp_path in bsp_files:
        bsp_name = os.path.basename(bsp_path)
        print(f"\nProcessing {bsp_name}...")

        # get the pakfile info without extracting
        pak_data, offset, length = extract_pakfile_info(bsp_path)

        # list existing files to avoid duplication
        existing_files = list_pakfile_contents(pak_data)

        # pre-process assets that don't already exist in the pakfile
        assets_zip_path, new_files_count, new_dirs_count = preprocess_assets(
            assets_dir, existing_files, os.path.join(output_dir, "_preprocessed_assets"))

        if new_files_count == 0 and new_dirs_count == 0:
            print(f"No new files to add to {bsp_name}, skipping...")
            continue

        print(f"Adding {new_files_count} files and {new_dirs_count} directories to {bsp_name}")

        # merge the pakfile
        merged_pak_data = merge_pakfiles(pak_data, assets_zip_path)
        if not merged_pak_data:
            print(f"Error merging pakfiles for {bsp_name}, skipping...")
            failure_count += 1
            continue

        # rebuild the bsp
        output_bsp_path = os.path.join(output_dir, bsp_name)
        if overwrite:
            output_bsp_path = bsp_path

        if rebuild_bsp(bsp_path, merged_pak_data, output_bsp_path):
            success_count += 1
        else:
            failure_count += 1

    print(f"\nBatch processing complete!")
    print(f"Successfully processed {success_count} BSP files")
    if failure_count > 0:
        print(f"Failed to process {failure_count} BSP files")

    return success_count > 0


def main():
    parser = argparse.ArgumentParser(description="Batch process BSP files to add assets")
    parser.add_argument("bsp_dir", help="Directory containing BSP files to process")
    parser.add_argument("assets_dir", help="Directory containing assets to add to BSP files")
    parser.add_argument("-o", "--output", help="Output directory for processed BSP files")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite original BSP files")

    args = parser.parse_args()

    batch_process(args.bsp_dir, args.assets_dir, args.output, args.overwrite)


if __name__ == "__main__":
    main()