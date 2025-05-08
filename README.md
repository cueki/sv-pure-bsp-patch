Files provided generated with:
```
python patch_bsp_files.py input_bsp/ default_stuff/ --output output_bsp/
```
Prevents any sv_pure bypass by patching whatever files you want (default_stuff in the example) to whatever bsp files you want. It will match the type of compression used by the map file in order to keep sizes relative, most likely LZMA or no compression at all.

This works because all lumps (besides the entities lump) are md5 verified upon joining a server. There is no way around this. This is how sv_pure is intended to work.