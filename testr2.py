import sys
import struct
import re
import lzma


def decompress_source_lzma(data):
    if data[:4] != b'LZMA':
        raise ValueError("Not Source LZMA format (missing LZMA signature)")

    # Extract header information
    actual_size = struct.unpack("<I", data[4:8])[0]
    lzma_size = struct.unpack("<I", data[8:12])[0]
    properties = data[12:17]

    print(f"LZMA Header Info:")
    print(f"  Uncompressed size: {actual_size} bytes")
    print(f"  Compressed size: {lzma_size} bytes")
    print(f"  Properties: {properties.hex()}")

    # Extract compressed data (skip header)
    compressed_data = data[17:]

    # Create LZMA decompressor with properties
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                                         filters=[{'id': lzma.FILTER_LZMA1,
                                                  'dict_size': 1 << 24,
                                                  'lc': 3}])

    # Decompress
    decompressed = decompressor.decompress(compressed_data)
    print(decompressed)
    return decompressed


def read_entities_lump(bsp_path):
    with open(bsp_path, 'rb') as f:
        bsp_data = f.read()

    print(f"BSP file size: {len(bsp_data)} bytes")

    # Read BSP header
    signature = struct.unpack("<I", bsp_data[0:4])[0]
    version = struct.unpack("<I", bsp_data[4:8])[0]

    # Convert signature to ASCII for display
    signature_bytes = struct.pack("<I", signature)
    signature_ascii = signature_bytes.decode('ascii', errors='replace')

    print(f"Signature: 0x{signature:08X} ('{signature_ascii}')")
    print(f"Version: {version}")

    # Find entities lump (lump 0)
    entities_offset = struct.unpack("<I", bsp_data[8:12])[0]
    entities_size = struct.unpack("<I", bsp_data[12:16])[0]

    print(f"Entities lump offset: {entities_offset}")
    print(f"Entities lump size: {entities_size} bytes")

    # Read entities data
    entities_data = bsp_data[entities_offset:entities_offset + entities_size]

    # Check if compressed
    is_compressed = entities_data.startswith(b'LZMA')
    print(f"Entities lump is" + (" LZMA compressed" if is_compressed else " not compressed"))

    # Get entities text
    if is_compressed:
        try:
            entities_text = decompress_source_lzma(entities_data).decode('ascii', errors='replace')
        except Exception as e:
            print(f"Error decompressing entities: {e}")
            return False

    # Count entities
    entity_count = entities_text.count('{')
    print(f"Total entities found: {entity_count}")
    print(entities_text)
    skyname_match = re.search(r'"skyname"\s+"([^"]+)"', entities_text)
    if skyname_match:
        print(f"Current skyname: '{skyname_match.group(1)}'")
    else:
        print("No skyname found in entities")

    # Print first 1000 characters of entities text
    print("\nFirst 1000 characters of entities text:")
    print("----------------------------------------")
    print(entities_text[:1000])
    print("----------------------------------------")

    # Also display as hex for debugging
    print("\nFirst 100 bytes of entities lump as hex:")
    print(entities_data[:100].hex(' ', 16))

    # Find all classnames
    classnames = {}
    for match in re.finditer(r'"classname"\s+"([^"]+)"', entities_text):
        classname = match.group(1)
        classnames[classname] = classnames.get(classname, 0) + 1

    print("\nEntity classnames found:")
    for classname, count in classnames.items():
        print(f"  {classname}: {count} instances")

    return True


def compress_source_lzma(data, original_header=None):
    properties = original_header[12:17]
    lc = properties[0] % 9
    lp = properties[0] // 9
    pb = properties[1]
    dict_size = 1 << 24

    lzma_filter = [{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}]

    compressed = lzma.compress(data=data,
                               format=lzma.FORMAT_RAW,
                               filters=lzma_filter)
    # First 5 bytes are properties
    properties = compressed[:5]
    compressed_data = compressed[5:]

    # Create Source LZMA header
    header = (
            b'LZMA' +
            struct.pack("<I", len(data)) +
            struct.pack("<I", len(compressed_data)) +
            properties
    )

    # Combine header with compressed data
    result = header + compressed_data
    return result


def patch_skyname_safely(bsp_path, new_skyname, output_path=None):
    if output_path is None:
        output_path = bsp_path

    # Read BSP file
    with open(bsp_path, 'rb') as f:
        bsp_data = f.read()

    # Read BSP header
    signature = struct.unpack("<I", bsp_data[0:4])[0]
    if signature != 0x50534256:  # "VBSP"
        print("Error: Not a valid BSP file (missing VBSP signature)")
        return False

    # Find entities lump (lump 0)
    entities_offset = struct.unpack("<I", bsp_data[8:12])[0]
    entities_size = struct.unpack("<I", bsp_data[12:16])[0]

    # Read entities data
    entities_data = bsp_data[entities_offset:entities_offset + entities_size]
    with open("fuckyou", 'wb') as f:
        f.write(entities_data)
    # Check if compressed
    is_compressed = entities_data.startswith(b'LZMA')

    if is_compressed:
        print("Entities lump is LZMA compressed")
        try:
            entities_text = decompress_source_lzma(entities_data).decode('ascii')
        except Exception as e:
            print(f"Error decompressing entities: {e}")
            return False
    else:
        entities_text = entities_data.decode('ascii')

    # Find skyname in entities
    skyname_match = re.search(r'"skyname"\s+"([^"]+)"', entities_text)
    if not skyname_match:
        print("Error: No skyname found in entities")
        return False

    current_skyname = skyname_match.group(1)
    print(f"Current skyname: '{current_skyname}'")
    print(f"Using skyname: '{new_skyname}'")

    # Replace skyname
    new_entities_text = entities_text.replace(current_skyname, new_skyname)
    new_entities_data = new_entities_text.encode('ascii')
    new_entities_data = compress_source_lzma(new_entities_data, original_header=entities_data)
    with open("fuckit", 'wb') as f:
        f.write(new_entities_data)

    # Write modified BSP
    with open(output_path, 'wb') as f:
        # Write everything up to entities lump
        f.write(bsp_data[:entities_offset])

        # Write new entities data (same size as original)
        f.write(new_entities_data)

        # Write remaining data
        f.write(bsp_data[entities_offset + entities_size:])

    print(f"BSP patched successfully. Place your skybox files in:")
    print(f"  custom/materials/skybox/{new_skyname}*.vtf")
    print(f"  custom/materials/skybox/{new_skyname}*.vmt")
    return True


def main():

    bsp_path = "pl_borneo.bsp"
    new_skyname = "sky_jungle_01"
    output_path = "yeet.bsp"
    # read_entities_lump("pl_borneo.bsp")
    # read_entities_lump("yeet.bsp")
    patch_skyname_safely(bsp_path, new_skyname, output_path)


if __name__ == "__main__":
    sys.exit(main())